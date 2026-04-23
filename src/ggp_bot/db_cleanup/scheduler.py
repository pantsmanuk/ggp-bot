"""Database cleanup scheduler for daily garbage collection.

This module manages daily cleanup tasks for all SQLite databases:
- Lunch timers: Cleared entirely at 06:00 daily
- Time clock state: Cleared entirely at 06:00 daily
- Token cache: Audited only (no deletion except API-reported expiry)

Follows the LunchTimerManager pattern with background asyncio tasks.
"""

import asyncio
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from ggp_bot.config import settings
from ggp_bot.intranet.token_storage import token_storage
from ggp_bot.slack.lunch_timer import lunch_timer_manager
from ggp_bot.intranet.state_tracking import timeclock_tracker


logger = logging.getLogger(__name__)


class DatabaseCleanupScheduler:
    """Manages daily cleanup tasks for all SQLite databases.
    
    Runs at 06:00 local time daily to clear transient data:
    - Lunch timers (users don't work overnight)
    - Time clock state (#Attendance shows "today's" status)
    
    Token cache is audited but never auto-deleted (only removed on API-reported expiry).
    """
    
    def __init__(self):
        """Initialize the cleanup scheduler."""
        self._cleanup_task: Optional[asyncio.Task] = None
        self._last_run: Optional[datetime] = None
        self._last_run_status: Optional[str] = None
    
    def start(self) -> None:
        """Start the daily cleanup background task.
        
        Idempotent - safe to call multiple times.
        """
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("Database cleanup scheduler started")
    
    def stop(self) -> None:
        """Stop the cleanup background task gracefully."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            logger.info("Database cleanup scheduler stopped")
    
    async def _cleanup_loop(self) -> None:
        """Main loop - runs daily at 06:00.
        
        Calculates seconds until next 06:00, sleeps, then performs cleanup.
        Handles graceful shutdown via CancelledError.
        """
        try:
            while True:
                # Calculate seconds until next 06:00
                now = datetime.now()
                next_run = now.replace(hour=6, minute=0, second=0, microsecond=0)
                
                # If 06:00 has passed today, schedule for tomorrow
                if next_run <= now:
                    next_run += timedelta(days=1)
                
                wait_seconds = (next_run - now).total_seconds()
                hours_until = wait_seconds / 3600
                
                logger.info(
                    f"Next database cleanup scheduled for {next_run.isoformat()} "
                    f"(in {hours_until:.1f} hours)"
                )
                
                await asyncio.sleep(wait_seconds)
                await self._perform_cleanup()
                
        except asyncio.CancelledError:
            logger.info("Database cleanup loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in cleanup loop: {e}", exc_info=True)
            # Don't re-raise - keep the loop running
    
    async def _perform_cleanup(self) -> None:
        """Execute cleanup tasks for all databases.
        
        Performs three operations:
        1. Clear all lunch timers (daily reset)
        2. Clear all time clock state (daily reset)
        3. Audit token cache (reporting only)
        
        All errors are logged but don't stop the cleanup process.
        """
        start_time = datetime.now()
        logger.info("Starting daily database cleanup (06:00)...")
        
        try:
            # 1. Lunch timers - clear ALL (daily reset)
            await self._cleanup_lunch_timers()
            
            # 2. Timeclock state - clear ALL (daily reset)
            await self._cleanup_timeclock_state()
            
            # 3. Token cache - audit only, no cleanup
            await self._audit_token_cache()
            
            self._last_run = datetime.now()
            self._last_status = "success"
            duration = (self._last_run - start_time).total_seconds()
            logger.info(f"Daily database cleanup completed in {duration:.2f}s")
            
        except Exception as e:
            self._last_run = datetime.now()
            self._last_status = f"error: {e}"
            logger.error(f"Database cleanup failed: {e}", exc_info=True)
    
    async def _cleanup_lunch_timers(self) -> int:
        """Clear all lunch timers from database.
        
        Returns:
            Number of records removed
        """
        try:
            # Get the database path from the lunch timer manager
            db_path = lunch_timer_manager.db_path
            
            with sqlite3.connect(str(db_path)) as conn:
                cursor = conn.cursor()
                
                # Count before deletion for logging
                cursor.execute("SELECT COUNT(*) FROM lunch_timers")
                count = cursor.fetchone()[0]
                
                # Delete all records
                cursor.execute("DELETE FROM lunch_timers")
                conn.commit()
                
                # Clear in-memory cache
                lunch_timer_manager._active_timers.clear()
                
                logger.info(f"GC: Removed {count} lunch timers from database")
                return count
                
        except sqlite3.Error as e:
            logger.error(f"GC: Failed to cleanup lunch timers: {e}")
            return 0
        except Exception as e:
            logger.error(f"GC: Unexpected error cleaning lunch timers: {e}")
            return 0
    
    async def _cleanup_timeclock_state(self) -> int:
        """Clear all time clock state from database.
        
        Returns:
            Number of records removed
        """
        try:
            # Get the database path from the state tracker
            db_path = timeclock_tracker.db_path
            
            with sqlite3.connect(str(db_path)) as conn:
                cursor = conn.cursor()
                
                # Count before deletion for logging
                cursor.execute("SELECT COUNT(*) FROM timeclock_notifications")
                count = cursor.fetchone()[0]
                
                # Delete all records
                cursor.execute("DELETE FROM timeclock_notifications")
                conn.commit()
                
                logger.info(f"GC: Removed {count} timeclock state records")
                return count
                
        except sqlite3.Error as e:
            logger.error(f"GC: Failed to cleanup timeclock state: {e}")
            return 0
        except Exception as e:
            logger.error(f"GC: Unexpected error cleaning timeclock state: {e}")
            return 0
    
    async def _audit_token_cache(self) -> dict[str, Any]:
        """Audit the token cache for integrity issues.
        
        Performs validation checks on all stored tokens without removing them:
        - Can decrypt
        - Has scopes
        - Not expired (this would trigger removal via get_token)
        
        Returns:
            Dict with audit results: {'valid': int, 'warnings': int, 'errors': int}
        """
        try:
            # Use the token storage's built-in audit function
            token_storage.log_token_audit_summary()
            
            # Also perform proactive integrity check
            validation_results = self._validate_all_tokens()
            
            valid = validation_results.get('valid', 0)
            warnings = validation_results.get('warnings', 0)
            errors = validation_results.get('errors', 0)
            
            logger.info(f"GC: Token audit - {valid} valid, {warnings} with warnings, {errors} with errors")
            
            return validation_results
            
        except Exception as e:
            logger.error(f"GC: Failed to audit token cache: {e}")
            return {'valid': 0, 'warnings': 0, 'errors': 1, 'error': str(e)}
    
    def _validate_all_tokens(self) -> dict[str, Any]:
        """Validate all stored tokens without modifying database.
        
        Performs integrity checks on each token:
        - Decryption succeeds
        - Has non-empty scopes
        - Not expired
        
        Returns:
            Dict with validation summary
        """
        results = {
            'valid': 0,
            'warnings': 0,
            'errors': 0,
            'details': []
        }
        
        try:
            # Get all user IDs with stored tokens
            user_ids = token_storage.get_all_users()
            
            if not user_ids:
                return results
            
            import json
            
            # Check each token without triggering get_token's expiry removal
            with sqlite3.connect(str(token_storage.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT slack_user_id, scopes, created_at, expires_at FROM user_tokens"
                )
                rows = cursor.fetchall()
            
            for row in rows:
                slack_id = row["slack_user_id"]
                scopes_json = row["scopes"]
                expires_at = row["expires_at"]
                created_at = row["created_at"]
                
                issues = []
                
                # Check scopes
                try:
                    scopes = json.loads(scopes_json) if scopes_json else []
                    if not scopes:
                        issues.append("empty_scopes")
                        logger.warning(
                            f"GC: Token audit - User {slack_id} has empty scopes. "
                            f"Created: {created_at}"
                        )
                except json.JSONDecodeError:
                    issues.append("invalid_scopes_json")
                    logger.warning(
                        f"GC: Token audit - User {slack_id} has invalid scopes JSON. "
                        f"Created: {created_at}"
                    )
                
                # Check expiry
                if expires_at:
                    try:
                        expiry_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                        if datetime.now(expiry_dt.tzinfo) > expiry_dt:
                            issues.append("expired")
                            # Note: get_token would remove this, but we're just auditing
                    except ValueError:
                        issues.append("invalid_expiry_format")
                
                # Check decryptability (this validates encryption integrity)
                try:
                    with sqlite3.connect(str(token_storage.db_path)) as conn:
                        cursor = conn.execute(
                            "SELECT encrypted_token FROM user_tokens WHERE slack_user_id = ?",
                            (slack_id,)
                        )
                        token_row = cursor.fetchone()
                        if token_row:
                            # Try to decrypt - if this fails, token is corrupted
                            token_storage._decrypt(token_row[0])
                except Exception as e:
                    issues.append(f"decryption_failed: {type(e).__name__}")
                    logger.error(
                        f"GC: Token audit - User {slack_id} token decryption failed. "
                        f"Error: {e}, Created: {created_at}"
                    )
                
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
                        'created_at': created_at
                    })
            
            return results
            
        except Exception as e:
            logger.error(f"GC: Token validation failed: {e}")
            results['errors'] += 1
            return results
    
    def get_status(self) -> dict[str, Any]:
        """Get current scheduler status.
        
        Returns:
            Dict with scheduler state information
        """
        # Calculate next run time
        now = datetime.now()
        next_run = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        
        return {
            'running': self._cleanup_task is not None and not self._cleanup_task.done(),
            'last_run': self._last_run.isoformat() if self._last_run else None,
            'last_status': getattr(self, '_last_status', None),
            'next_run': next_run.isoformat(),
            'next_run_in_seconds': (next_run - now).total_seconds(),
        }
    
    async def run_now(self) -> dict[str, Any]:
        """Manually trigger cleanup immediately.
        
        Returns:
            Dict with cleanup results
        """
        logger.info("ADMIN: Manual database cleanup triggered")
        
        start_time = datetime.now()
        
        lunch_count = await self._cleanup_lunch_timers()
        timeclock_count = await self._cleanup_timeclock_state()
        token_audit = await self._audit_token_cache()
        
        duration = (datetime.now() - start_time).total_seconds()
        
        self._last_run = datetime.now()
        self._last_status = "manual_run"
        
        return {
            'lunch_timers_removed': lunch_count,
            'timeclock_records_removed': timeclock_count,
            'token_audit': token_audit,
            'duration_seconds': duration,
        }


# Global instance for use across the application
cleanup_scheduler = DatabaseCleanupScheduler()
