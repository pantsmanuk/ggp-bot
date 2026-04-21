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
    
    DEFAULT_DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "tokens.db"
    
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
        
        # Initialize encryption
        self._fernet = self._init_encryption(encryption_key)
        
        # Initialize database
        self._init_database()
    
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
        print(f"[DEBUG] get_token: Looking for user {slack_user_id} in {self.db_path}")
        
        # Check if DB file exists
        if not self.db_path.exists():
            print(f"[DEBUG] DB file does not exist: {self.db_path}")
            return None
        
        print(f"[DEBUG] DB file exists, querying...")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM user_tokens WHERE slack_user_id = ?",
                (slack_user_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                print(f"[DEBUG] No row found for user {slack_user_id}")
                return None
            
            print(f"[DEBUG] Found row for user {slack_user_id}, attempting decryption...")
            
            # Decrypt token value
            try:
                decrypted_token = self._decrypt(row["encrypted_token"])
                print(f"[DEBUG] Decryption successful")
            except Exception as e:
                print(f"[DEBUG] Decryption failed: {e}")
                # If decryption fails, token is corrupted or key changed
                return None
            
            # Parse scopes from JSON
            import json
            scopes = json.loads(row["scopes"])
            
            user_token = UserToken(
                slack_user_id=row["slack_user_id"],
                token=decrypted_token,
                scopes=scopes,
                created_at=row["created_at"],
                expires_at=row["expires_at"]
            )
            
            # Check expiry and clean up if expired
            if user_token.is_expired:
                self.remove_token(slack_user_id)
                return None
            
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
        import json
        
        print(f"[DEBUG] TokenStorage.save_token called for {slack_user_id}")
        print(f"[DEBUG] DB path: {self.db_path}")
        
        created_at = datetime.now().isoformat()
        print(f"[DEBUG] Encrypting token...")
        encrypted_token = self._encrypt(token)
        print(f"[DEBUG] Token encrypted, length: {len(encrypted_token)}")
        scopes_json = json.dumps(scopes)
        
        print(f"[DEBUG] Writing to database...")
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
            print(f"[DEBUG] Database write committed successfully")
        
        return UserToken(
            slack_user_id=slack_user_id,
            token=token,
            scopes=scopes,
            created_at=created_at,
            expires_at=expires_at
        )
    
    def remove_token(self, slack_user_id: str) -> bool:
        """Remove a user's token.
        
        Args:
            slack_user_id: The Slack user ID
            
        Returns:
            True if token was removed, False if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM user_tokens WHERE slack_user_id = ?",
                (slack_user_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def has_token(self, slack_user_id: str) -> bool:
        """Check if a user has a valid (non-expired) token.
        
        Args:
            slack_user_id: The Slack user ID
            
        Returns:
            True if user has a valid token, False otherwise
        """
        print(f"[DEBUG] has_token called for {slack_user_id}")
        result = self.get_token(slack_user_id)
        print(f"[DEBUG] get_token returned: {result is not None}")
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


# Global token storage instance
token_storage = TokenStorage()
