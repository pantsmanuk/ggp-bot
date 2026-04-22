"""Time clock state tracking for idempotent #Attendance posting.

This module tracks the last notified time clock state per user to ensure
we only post to #Attendance when the state actually changes (in -> out or out -> in),
not on every clock command (which may be idempotent).
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path

from ggp_bot.config import settings


logger = logging.getLogger(__name__)


class TimeClockStateTracker:
    """Track last notified time clock state per user.
    
    Uses SQLite to persist state across bot restarts.
    """
    
    def __init__(self, db_path: str | None = None):
        """Initialize the state tracker.
        
        Args:
            db_path: Path to SQLite database. Defaults to data directory.
        """
        if db_path:
            self.db_path = Path(db_path)
        else:
            # Default to data directory
            data_dir = Path(settings.data_dir) if hasattr(settings, 'data_dir') else Path("data")
            data_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = data_dir / "timeclock_state.db"
        
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize the SQLite database with required table."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS timeclock_notifications (
                        slack_user_id TEXT PRIMARY KEY,
                        last_state TEXT,  -- "in" or "out"
                        last_event_id INTEGER,
                        last_notified_at TIMESTAMP
                    )
                """)
                conn.commit()
                logger.debug(f"TimeClockStateTracker initialized at {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize timeclock state DB: {e}")
            raise
    
    def get_last_state(self, slack_user_id: str) -> str | None:
        """Get the last notified state for a user.
        
        Args:
            slack_user_id: The Slack user ID
            
        Returns:
            The last state ("in" or "out") or None if no record exists
        """
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT last_state FROM timeclock_notifications WHERE slack_user_id = ?",
                    (slack_user_id,)
                )
                row = cursor.fetchone()
                if row:
                    return row[0]
                return None
        except sqlite3.Error as e:
            logger.error(f"Failed to get last state for {slack_user_id}: {e}")
            return None
    
    def should_notify(self, slack_user_id: str, new_state: str) -> bool:
        """Check if we should notify #Attendance for this state change.
        
        Only returns True if:
        - No previous state recorded (first time)
        - Previous state is different from new_state (actual change)
        
        Args:
            slack_user_id: The Slack user ID
            new_state: The new state ("in" or "out")
            
        Returns:
            True if #Attendance should be notified
        """
        last_state = self.get_last_state(slack_user_id)
        
        if last_state is None:
            logger.debug(f"No previous state for {slack_user_id}, should notify")
            return True
        
        if last_state != new_state:
            logger.debug(f"State change for {slack_user_id}: {last_state} -> {new_state}, should notify")
            return True
        
        logger.debug(f"No state change for {slack_user_id}, already {new_state}")
        return False
    
    def update_state(self, slack_user_id: str, state: str, event_id: int) -> None:
        """Update the last notified state for a user.
        
        Args:
            slack_user_id: The Slack user ID
            state: The new state ("in" or "out")
            event_id: The time clock event ID for reference
        """
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO timeclock_notifications 
                    (slack_user_id, last_state, last_event_id, last_notified_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(slack_user_id) DO UPDATE SET
                    last_state = excluded.last_state,
                    last_event_id = excluded.last_event_id,
                    last_notified_at = excluded.last_notified_at
                    """,
                    (slack_user_id, state, event_id, datetime.now().isoformat())
                )
                conn.commit()
                logger.debug(f"Updated state for {slack_user_id}: {state} (event {event_id})")
        except sqlite3.Error as e:
            logger.error(f"Failed to update state for {slack_user_id}: {e}")
    
    def clear_state(self, slack_user_id: str) -> None:
        """Clear the state record for a user (useful for testing).
        
        Args:
            slack_user_id: The Slack user ID
        """
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM timeclock_notifications WHERE slack_user_id = ?",
                    (slack_user_id,)
                )
                conn.commit()
                logger.debug(f"Cleared state for {slack_user_id}")
        except sqlite3.Error as e:
            logger.error(f"Failed to clear state for {slack_user_id}: {e}")


# Global instance for use across the application
timeclock_tracker = TimeClockStateTracker()
