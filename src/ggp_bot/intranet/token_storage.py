"""Secure token storage using SQLite with Fernet encryption.

Tokens are stored in a local SQLite database with the token values encrypted
using Fernet symmetric encryption. The encryption key should be provided via
the TOKEN_ENCRYPTION_KEY environment variable (base64-encoded 32-byte key).

If no key is provided, a key is derived from the machine's hostname and
SLACK_SIGNING_SECRET as a fallback (suitable for single-machine deployments
but not recommended for production multi-instance setups).

Example:
    To generate a new Fernet key:
    >>> from cryptography.fernet import Fernet
    >>> key = Fernet.generate_key()
    >>> print(key.decode())  # Add this to .env as TOKEN_ENCRYPTION_KEY
"""

import json
import logging
import os
import sqlite3
import hashlib
import base64
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from ggp_bot.config import settings

logger = logging.getLogger(__name__)


@dataclass
class UserToken:
    """Represents a stored user API token with metadata."""
    
    slack_user_id: str
    token: str  # Decrypted plain token
    scopes: list[str]
    created_at: str
    expires_at: str | None = None
    
    @property
    def is_expired(self) -> bool:
        """Check if the token has expired."""
        if not self.expires_at:
            return False
        try:
            expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            return datetime.now(expiry.tzinfo) > expiry
        except ValueError:
            return False
    
    def has_scope(self, scope: str) -> bool:
        """Check if token has a specific scope."""
        return scope in self.scopes


class TokenStorage:
    """SQLite-based encrypted token storage using Fernet.
    
    Token values are encrypted at rest using Fernet symmetric encryption.
    The database schema stores:
    - slack_user_id (PRIMARY KEY)
    - encrypted_token (Fernet-encrypted Bearer token)
    - scopes (JSON array as text)
    - created_at (ISO timestamp)
    - expires_at (ISO timestamp or NULL)
    
    Args:
        db_path: Path to SQLite database file
        encryption_key: Optional Fernet key (base64-encoded). If not provided,
                       uses TOKEN_ENCRYPTION_KEY env var or derives from
                       machine-specific data.
    """
    
    @property
    def DEFAULT_DB_PATH(self) -> Path:
        """Get default database path from settings."""
        return Path(settings.data_dir) / "tokens.db"
    
    def __init__(
        self,
        db_path: Path | str | None = None,
        encryption_key: str | None = None
    ):
        """Initialize encrypted token storage.
        
        Args:
            db_path: Path to SQLite database. Defaults to data/tokens.db
            encryption_key: Fernet key for encryption. If not provided,
                          reads from TOKEN_ENCRYPTION_KEY env var.
        """
        self.db_path = Path(db_path or self.DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Check if database is new or existing for logging
        db_exists = self.db_path.exists()
        db_status = "opened" if db_exists else "created"
        
        # Initialize encryption
        self._fernet = self._init_encryption(encryption_key)
        
        # Initialize database
        self._init_database()
        
        # Log database initialization at INFO level
        logger.info(f"Token storage database {db_status}: {self.db_path}")
    
    def _init_encryption(self, key: str | None = None) -> Fernet:
        """Initialize Fernet encryption.
        
        Priority for key:
        1. Provided key argument
        2. TOKEN_ENCRYPTION_KEY env var
        3. Derived from machine-specific data (fallback)
        
        Args:
            key: Optional base64-encoded Fernet key
            
        Returns:
            Configured Fernet instance
        """
        if key:
            return Fernet(key.encode() if isinstance(key, str) else key)
        
        # Try environment variable
        env_key = os.getenv("TOKEN_ENCRYPTION_KEY")
        if env_key:
            return Fernet(env_key.encode())
        
        # Fallback: derive key from machine-specific data
        # This allows the bot to work without explicit key configuration
        # but is not suitable for multi-instance deployments
        return self._derive_key_from_machine()
    
    def _derive_key_from_machine(self) -> Fernet:
        """Derive encryption key from machine-specific data.
        
        Uses hostname and Slack signing secret to create a deterministic
        key. This allows single-machine deployments to work without
        explicit key configuration, but tokens won't be portable across
        machines and re-installing the OS will invalidate stored tokens.
        
        Returns:
            Fernet instance with derived key
        """
        import socket
        
        # Combine machine-specific factors
        hostname = socket.gethostname()
        slack_secret = os.getenv("SLACK_SIGNING_SECRET", "default-secret")
        
        # Create a salt from the hostname hash
        salt = hashlib.sha256(hostname.encode()).digest()[:16]
        
        # Use PBKDF2 to derive a 32-byte key
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(slack_secret.encode()))
        
        return Fernet(key)
    
    def _init_database(self) -> None:
        """Create SQLite schema if not exists."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_tokens (
                    slack_user_id TEXT PRIMARY KEY,
                    encrypted_token BLOB NOT NULL,
                    scopes TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT
                )
            """)
            
            # Create index for faster lookup
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_tokens_slack_id 
                ON user_tokens(slack_user_id)
            """)
            
            conn.commit()
    
    def _encrypt(self, plaintext: str) -> bytes:
        """Encrypt a string value."""
        return self._fernet.encrypt(plaintext.encode())
    
    def _decrypt(self, ciphertext: bytes) -> str:
        """Decrypt an encrypted value."""
        return self._fernet.decrypt(ciphertext).decode()
    
    def get_token(self, slack_user_id: str) -> UserToken | None:
        """Retrieve a user's decrypted token.
        
        Args:
            slack_user_id: The Slack user ID (e.g., U1234567890)
            
        Returns:
            UserToken with decrypted values, or None if not found/expired
        """
        logger.debug(f"get_token: Looking for user {slack_user_id}")
        
        # Check if DB file exists
        if not self.db_path.exists():
            logger.debug(f"DB file does not exist: {self.db_path}")
            return None
        
        logger.debug(f"DB file exists, querying...")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM user_tokens WHERE slack_user_id = ?",
                (slack_user_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                logger.debug(f"No row found for user {slack_user_id}")
                return None
            
            # Get metadata for logging before attempting decryption
            created_at = row["created_at"]
            expires_at = row["expires_at"]
            scopes_json = row["scopes"]
            
            # Calculate token age
            try:
                created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                token_age_hours = (datetime.now(created_dt.tzinfo) - created_dt).total_seconds() / 3600
            except:
                token_age_hours = None
            
            logger.debug(f"Found row for user {slack_user_id}, created_at={created_at}, expires_at={expires_at}, attempting decryption...")
            
            # Decrypt token value
            try:
                decrypted_token = self._decrypt(row["encrypted_token"])
                logger.debug(f"Decryption successful")
            except Exception as e:
                # Log detailed metadata on decryption failure for audit purposes
                logger.error(
                    f"TOKEN AUDIT: Decryption failed for user {slack_user_id}. "
                    f"Created: {created_at}, Age: {token_age_hours:.1f}h if token_age_hours else 'unknown', "
                    f"Scopes (raw): {scopes_json[:100] if scopes_json else 'empty'}, "
                    f"Error: {type(e).__name__}: {str(e)[:100]}"
                )
                # If decryption fails, token is corrupted or key changed
                return None
            
            # Parse scopes from JSON
            try:
                scopes = json.loads(scopes_json)
            except json.JSONDecodeError as e:
                logger.error(f"TOKEN AUDIT: Failed to parse scopes JSON for user {slack_user_id}: {e}")
                scopes = []
            
            user_token = UserToken(
                slack_user_id=row["slack_user_id"],
                token=decrypted_token,
                scopes=scopes,
                created_at=created_at,
                expires_at=expires_at
            )
            
            # Integrity check: warn on empty scopes (don't delete - let API refresh)
            if not scopes:
                logger.warning(
                    f"TOKEN AUDIT: User {slack_user_id} token has empty scopes. "
                    f"Created: {created_at}, Age: {token_age_hours:.1f}h. "
                    f"Token will be used but API may reject due to insufficient permissions."
                )
            
            # Log token age for all successful retrievals (INFO level for audit trail)
            age_str = f"{token_age_hours:.1f}h" if token_age_hours is not None else "unknown"
            logger.debug(
                f"TOKEN AUDIT: Token retrieved for user {slack_user_id}. "
                f"Age: {age_str}, Scopes: {len(scopes)} scope(s)"
            )
            
            # Check expiry and clean up if expired
            if user_token.is_expired:
                logger.info(
                    f"TOKEN AUDIT: Token expired for user {slack_user_id}. "
                    f"Created: {created_at}, Expires: {expires_at}, Age: {token_age_hours:.1f}h. Removing from storage."
                )
                self.remove_token(slack_user_id, reason="token_expired")
                return None
            
            logger.debug(f"Token retrieved successfully for {slack_user_id}, scopes: {scopes}")
            return user_token
    
    def save_token(
        self,
        slack_user_id: str,
        token: str,
        scopes: list[str],
        expires_at: str | None = None
    ) -> UserToken:
        """Store a user's token (encrypted).
        
        Args:
            slack_user_id: The Slack user ID
            token: The Bearer token string (will be encrypted)
            scopes: List of scopes granted to this token
            expires_at: Optional ISO 8601 expiry timestamp
            
        Returns:
            The stored UserToken (with decrypted token value)
        """
        # Check if this is a new token or an update
        is_update = self.has_token(slack_user_id)
        action = "UPDATED" if is_update else "CREATED"
        
        logger.info(
            f"TOKEN AUDIT: Token {action} for user {slack_user_id}. "
            f"Scopes: {scopes}, Expires: {expires_at if expires_at else 'never'}"
        )
        
        logger.debug(f"TokenStorage.save_token called for {slack_user_id}")
        
        created_at = datetime.now().isoformat()
        logger.debug(f"Encrypting token...")
        encrypted_token = self._encrypt(token)
        logger.debug(f"Token encrypted, length: {len(encrypted_token)}")
        scopes_json = json.dumps(scopes)
        
        logger.debug(f"Writing to database...")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO user_tokens (slack_user_id, encrypted_token, scopes, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(slack_user_id) DO UPDATE SET
                    encrypted_token=excluded.encrypted_token,
                    scopes=excluded.scopes,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at
                """,
                (slack_user_id, encrypted_token, scopes_json, created_at, expires_at)
            )
            conn.commit()
            logger.info(f"TOKEN AUDIT: Token {action.lower()} successfully for user {slack_user_id} at {created_at}")
        
        return UserToken(
            slack_user_id=slack_user_id,
            token=token,
            scopes=scopes,
            created_at=created_at,
            expires_at=expires_at
        )
    
    def remove_token(self, slack_user_id: str, reason: str = "unknown") -> bool:
        """Remove a user's token.
        
        Args:
            slack_user_id: The Slack user ID
            reason: Reason for removal (for audit logging)
            
        Returns:
            True if token was removed, False if not found
        """
        logger.info(f"TOKEN AUDIT: Removing token for user {slack_user_id}. Reason: {reason}")
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM user_tokens WHERE slack_user_id = ?",
                (slack_user_id,)
            )
            conn.commit()
            removed = cursor.rowcount > 0
            if removed:
                logger.info(f"TOKEN AUDIT: Token removed successfully for user {slack_user_id}")
            else:
                logger.warning(f"TOKEN AUDIT: No token found to remove for user {slack_user_id}")
            return removed
    
    def has_token(self, slack_user_id: str) -> bool:
        """Check if a user has a valid (non-expired) token.
        
        Args:
            slack_user_id: The Slack user ID
            
        Returns:
            True if user has a valid token, False otherwise
        """
        logger.debug(f"has_token called for {slack_user_id}")
        result = self.get_token(slack_user_id)
        logger.debug(f"get_token returned: {result is not None}")
        return result is not None
    
    def get_all_users(self) -> list[str]:
        """Get list of all Slack user IDs with stored tokens.
        
        Returns:
            List of Slack user IDs
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT slack_user_id FROM user_tokens"
            )
            return [row[0] for row in cursor.fetchall()]
    
    def clear_all(self) -> int:
        """Remove all stored tokens. Use with caution.
        
        Returns:
            Number of tokens removed
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM user_tokens")
            conn.commit()
            return cursor.rowcount
    
    def get_stats(self) -> dict[str, Any]:
        """Get storage statistics.
        
        Returns:
            Dict with count of stored tokens
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM user_tokens")
            count = cursor.fetchone()[0]
            
        return {
            "total_tokens": count,
            "db_path": str(self.db_path),
            "encrypted": True,
        }
    
    def log_token_audit_summary(self) -> None:
        """Log audit summary of all stored tokens (without exposing sensitive data).
        
        This is useful for debugging token issues in production without
        compromising security by logging actual token values.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT slack_user_id, scopes, created_at, expires_at FROM user_tokens"
                )
                rows = cursor.fetchall()
                
            if not rows:
                logger.info("TOKEN AUDIT SUMMARY: No tokens stored in database")
                return
            
            logger.info(f"TOKEN AUDIT SUMMARY: {len(rows)} token(s) in storage")
            
            for row in rows:
                slack_id = row["slack_user_id"]
                created_at = row["created_at"]
                expires_at = row["expires_at"]
                scopes_json = row["scopes"]
                
                # Parse scopes
                try:
                    scopes = json.loads(scopes_json) if scopes_json else []
                    scope_count = len(scopes)
                    scope_summary = f"{scope_count} scope(s)"
                except:
                    scope_summary = "ERROR parsing scopes"
                
                # Calculate age
                try:
                    created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    age_hours = (datetime.now(created_dt.tzinfo) - created_dt).total_seconds() / 3600
                    age_str = f"{age_hours:.1f}h old"
                except:
                    age_str = "unknown age"
                
                # Check if expired
                expired_str = ""
                if expires_at:
                    try:
                        expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                        is_expired = datetime.now(expires_dt.tzinfo) > expires_dt
                        expired_str = " [EXPIRED]" if is_expired else f" [expires in {(expires_dt - datetime.now(expires_dt.tzinfo)).total_seconds() / 3600:.1f}h]"
                    except:
                        expired_str = " [expiry parse error]"
                
                logger.info(
                    f"TOKEN AUDIT: User {slack_id} - {scope_summary}, {age_str}, "
                    f"created {created_at}{expired_str}"
                )
                
        except Exception as e:
            logger.error(f"TOKEN AUDIT: Failed to generate audit summary: {e}")
    
    def validate_all_tokens(self) -> dict[str, Any]:
        """Validate all stored tokens for integrity issues.
        
        Performs validation without modifying the database:
        - Checks if tokens can be decrypted
        - Verifies scopes are present and valid JSON
        - Reports expiry status
        
        Returns:
            Dict with validation results:
            {
                'total': int,
                'valid': int,
                'warnings': int,
                'errors': int,
                'details': list[dict]  # Per-token details with issues
            }
        """
        results = {
            'total': 0,
            'valid': 0,
            'warnings': 0,
            'errors': 0,
            'details': []
        }
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT slack_user_id, encrypted_token, scopes, created_at, expires_at FROM user_tokens"
                )
                rows = cursor.fetchall()
            
            results['total'] = len(rows)
            
            if not rows:
                logger.info("TOKEN AUDIT: No tokens to validate")
                return results
            
            for row in rows:
                slack_id = row["slack_user_id"]
                scopes_json = row["scopes"]
                expires_at = row["expires_at"]
                created_at = row["created_at"]
                encrypted_token = row["encrypted_token"]
                
                issues = []
                token_age_hours = None
                
                # Calculate token age
                try:
                    created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    token_age_hours = (datetime.now(created_dt.tzinfo) - created_dt).total_seconds() / 3600
                except (ValueError, TypeError):
                    issues.append("invalid_created_at")
                
                # Check decryption
                try:
                    self._decrypt(encrypted_token)
                except Exception as e:
                    issues.append(f"decryption_failed: {type(e).__name__}")
                    logger.error(
                        f"TOKEN AUDIT: Token validation failed for user {slack_id}. "
                        f"Decryption error: {type(e).__name__}, Created: {created_at}"
                    )
                
                # Check scopes
                try:
                    scopes = json.loads(scopes_json) if scopes_json else []
                    if not scopes:
                        issues.append("empty_scopes")
                        logger.warning(
                            f"TOKEN AUDIT: User {slack_id} has empty scopes. "
                            f"Created: {created_at}, Age: {token_age_hours:.1f}h if token_age_hours else 'unknown'"
                        )
                except json.JSONDecodeError:
                    issues.append("invalid_scopes_json")
                    logger.warning(
                        f"TOKEN AUDIT: User {slack_id} has invalid scopes JSON. "
                        f"Created: {created_at}"
                    )
                
                # Check expiry
                if expires_at:
                    try:
                        expiry_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                        if datetime.now(expiry_dt.tzinfo) > expiry_dt:
                            issues.append("expired")
                            # Note: get_token would remove this, but we're just validating
                    except (ValueError, TypeError):
                        issues.append("invalid_expiry_format")
                
                # Categorize result
                if not issues:
                    results['valid'] += 1
                elif any(i.startswith('decryption_failed') or i == 'invalid_scopes_json' 
                        for i in issues):
                    results['errors'] += 1
                else:
                    results['warnings'] += 1
                
                if issues:
                    results['details'].append({
                        'user_id': slack_id,
                        'issues': issues,
                        'created_at': created_at,
                        'age_hours': token_age_hours
                    })
            
            # Log summary
            logger.info(
                f"TOKEN AUDIT: Validation complete. "
                f"Total: {results['total']}, Valid: {results['valid']}, "
                f"Warnings: {results['warnings']}, Errors: {results['errors']}"
            )
            
            return results
            
        except sqlite3.Error as e:
            logger.error(f"TOKEN AUDIT: Database error during validation: {e}")
            results['errors'] += 1
            return results
        except Exception as e:
            logger.error(f"TOKEN AUDIT: Validation failed with error: {e}")
            results['errors'] += 1
            return results


# Global token storage instance
token_storage = TokenStorage()
