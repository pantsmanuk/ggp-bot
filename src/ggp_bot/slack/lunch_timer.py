"""Lunch timer management for background reminders.

This module provides background task management for lunch break timers,
including DM warnings at 55, 59, and 60 minutes.
"""

import asyncio
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from slack_sdk.web.async_client import AsyncWebClient

from ggp_bot.config import settings
from ggp_bot.intranet.token_storage import token_storage


logger = logging.getLogger(__name__)


class LunchTimer:
    """Represents an active lunch timer."""
    
    def __init__(
        self,
        slack_user_id: str,
        channel_id: str,
        start_time: datetime,
        warning_55_sent: bool = False,
        warning_59_sent: bool = False,
        warning_60_sent: bool = False
    ):
        self.slack_user_id = slack_user_id
        self.channel_id = channel_id
        self.start_time = start_time
        self.warning_55_sent = warning_55_sent
        self.warning_59_sent = warning_59_sent
        self.warning_60_sent = warning_60_sent
    
    @property
    def elapsed_minutes(self) -> float:
        """Calculate elapsed time since timer started."""
        return (datetime.now() - self.start_time).total_seconds() / 60
    
    @property
    def remaining_minutes(self) -> float:
        """Calculate remaining time until 60 minutes."""
        return max(0, 60 - self.elapsed_minutes)


class LunchTimerManager:
    """Manages lunch timers with database persistence and background checking."""
    
    def __init__(self, db_path: Optional[Path] = None):
        """Initialize the lunch timer manager.
        
        Args:
            db_path: Path to SQLite database. Defaults to data directory.
        """
        if db_path:
            self.db_path = Path(db_path)
        else:
            # Default to data directory
            data_dir = Path(settings.data_dir) if hasattr(settings, 'data_dir') else Path("data")
            data_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = data_dir / "lunch_timers.db"
        
        # Check if database is new or existing for logging
        db_exists = self.db_path.exists()
        db_status = "opened" if db_exists else "created"
        
        self._init_database()
        self._active_timers: dict[str, LunchTimer] = {}
        self._check_task: Optional[asyncio.Task] = None
        self._client: Optional[AsyncWebClient] = None
        
        # Log database initialization at INFO level
        logger.info(f"Lunch timer database {db_status}: {self.db_path}")
    
    def _init_database(self) -> None:
        """Initialize the SQLite database with required table."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS lunch_timers (
                        slack_user_id TEXT PRIMARY KEY,
                        channel_id TEXT NOT NULL,
                        start_time TIMESTAMP NOT NULL,
                        warning_55_sent BOOLEAN DEFAULT 0,
                        warning_59_sent BOOLEAN DEFAULT 0,
                        warning_60_sent BOOLEAN DEFAULT 0
                    )
                """)
                conn.commit()
                logger.debug(f"LunchTimerManager database initialized at {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize lunch timer database: {e}")
            raise
    
    def set_client(self, client: AsyncWebClient) -> None:
        """Set the Slack client for sending messages."""
        self._client = client
    
    def start_timer(self, slack_user_id: str, channel_id: str) -> bool:
        """Start a new lunch timer for a user.
        
        Idempotent - returns False if timer already exists.
        
        Args:
            slack_user_id: The Slack user ID
            channel_id: The channel/DM to send reminders to
            
        Returns:
            True if new timer started, False if already exists
        """
        # Check if already exists in memory or DB
        if slack_user_id in self._active_timers:
            logger.debug(f"Lunch timer already active for {slack_user_id}")
            return False
        
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                
                # Check if already in DB
                cursor.execute(
                    "SELECT 1 FROM lunch_timers WHERE slack_user_id = ?",
                    (slack_user_id,)
                )
                if cursor.fetchone():
                    logger.debug(f"Lunch timer already in DB for {slack_user_id}")
                    # Load it into memory
                    self._load_timer_from_db(slack_user_id)
                    return False
                
                # Insert new timer
                start_time = datetime.now()
                cursor.execute(
                    """
                    INSERT INTO lunch_timers 
                    (slack_user_id, channel_id, start_time, warning_55_sent, warning_59_sent, warning_60_sent)
                    VALUES (?, ?, ?, 0, 0, 0)
                    """,
                    (slack_user_id, channel_id, start_time.isoformat())
                )
                conn.commit()
                
                # Add to active timers
                timer = LunchTimer(
                    slack_user_id=slack_user_id,
                    channel_id=channel_id,
                    start_time=start_time
                )
                self._active_timers[slack_user_id] = timer
                
                logger.info(f"Started lunch timer for {slack_user_id}")
                return True
                
        except sqlite3.Error as e:
            logger.error(f"Failed to start lunch timer for {slack_user_id}: {e}")
            return False
    
    def cancel_timer(self, slack_user_id: str) -> bool:
        """Cancel an active lunch timer.
        
        Args:
            slack_user_id: The Slack user ID
            
        Returns:
            True if timer was cancelled, False if not found
        """
        # Remove from memory
        if slack_user_id in self._active_timers:
            del self._active_timers[slack_user_id]
        
        # Remove from DB
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM lunch_timers WHERE slack_user_id = ?",
                    (slack_user_id,)
                )
                conn.commit()
                
                if cursor.rowcount > 0:
                    logger.info(f"Cancelled lunch timer for {slack_user_id}")
                    return True
                return False
                
        except sqlite3.Error as e:
            logger.error(f"Failed to cancel lunch timer for {slack_user_id}: {e}")
            return False
    
    def has_active_timer(self, slack_user_id: str) -> bool:
        """Check if user has an active lunch timer."""
        if slack_user_id in self._active_timers:
            return True
        
        # Check DB
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT 1 FROM lunch_timers WHERE slack_user_id = ?",
                    (slack_user_id,)
                )
                return cursor.fetchone() is not None
        except sqlite3.Error:
            return False
    
    def _load_timer_from_db(self, slack_user_id: str) -> Optional[LunchTimer]:
        """Load a timer from the database into memory."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT slack_user_id, channel_id, start_time, 
                           warning_55_sent, warning_59_sent, warning_60_sent
                    FROM lunch_timers WHERE slack_user_id = ?
                    """,
                    (slack_user_id,)
                )
                row = cursor.fetchone()
                
                if row:
                    timer = LunchTimer(
                        slack_user_id=row[0],
                        channel_id=row[1],
                        start_time=datetime.fromisoformat(row[2]),
                        warning_55_sent=bool(row[3]),
                        warning_59_sent=bool(row[4]),
                        warning_60_sent=bool(row[5])
                    )
                    self._active_timers[slack_user_id] = timer
                    return timer
                return None
                
        except sqlite3.Error as e:
            logger.error(f"Failed to load timer from DB for {slack_user_id}: {e}")
            return None
    
    def _update_warning_flag(self, slack_user_id: str, flag_name: str) -> None:
        """Update a warning flag in the database."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"UPDATE lunch_timers SET {flag_name} = 1 WHERE slack_user_id = ?",
                    (slack_user_id,)
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to update warning flag for {slack_user_id}: {e}")
    
    async def check_timers(self) -> None:
        """Background task to check all active timers and send warnings.
        
        Runs every 30 seconds.
        """
        while True:
            try:
                await self._process_timers()
                await asyncio.sleep(30)  # Check every 30 seconds
            except asyncio.CancelledError:
                logger.info("Lunch timer check task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in lunch timer check loop: {e}")
                await asyncio.sleep(30)  # Continue even on error
    
    async def _process_timers(self) -> None:
        """Process all active timers and send warnings as needed."""
        if not self._client:
            return
        
        # Ensure all DB timers are loaded into memory
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT slack_user_id FROM lunch_timers")
                rows = cursor.fetchall()
                
                for (slack_user_id,) in rows:
                    if slack_user_id not in self._active_timers:
                        self._load_timer_from_db(slack_user_id)
        except sqlite3.Error as e:
            logger.error(f"Failed to load timers from DB: {e}")
            return
        
        # Check each active timer
        for slack_user_id, timer in list(self._active_timers.items()):
            elapsed = timer.elapsed_minutes
            
            # 55 minute warning
            if elapsed >= 55 and not timer.warning_55_sent:
                await self._send_warning(slack_user_id, "5 minutes left on lunch break")
                timer.warning_55_sent = True
                self._update_warning_flag(slack_user_id, "warning_55_sent")
            
            # 59 minute warning
            elif elapsed >= 59 and not timer.warning_59_sent:
                await self._send_warning(slack_user_id, "1 minute left on lunch break")
                timer.warning_59_sent = True
                self._update_warning_flag(slack_user_id, "warning_59_sent")
            
            # 60 minute warning
            elif elapsed >= 60 and not timer.warning_60_sent:
                await self._send_warning(slack_user_id, "Lunch break over - please clock in")
                timer.warning_60_sent = True
                self._update_warning_flag(slack_user_id, "warning_60_sent")
                
                # Optionally remove from active timers after final warning
                # or keep to prevent duplicate final warnings
    
    async def _send_warning(self, slack_user_id: str, message: str) -> None:
        """Send a DM warning to a user."""
        if not self._client:
            return
        
        try:
            # Open DM channel
            dm_response = await self._client.conversations_open(users=[slack_user_id])
            dm_channel = dm_response["channel"]["id"]
            
            # Send message
            await self._client.chat_postMessage(
                channel=dm_channel,
                text=message
            )
            logger.debug(f"Sent lunch warning to {slack_user_id}: {message}")
            
        except Exception as e:
            logger.error(f"Failed to send lunch warning to {slack_user_id}: {e}")
    
    def start_background_task(self, client: AsyncWebClient) -> None:
        """Start the background timer checking task.
        
        Args:
            client: The Slack WebClient for sending messages
        """
        self.set_client(client)
        if self._check_task is None or self._check_task.done():
            self._check_task = asyncio.create_task(self.check_timers())
            logger.info("Started lunch timer background task")
    
    def stop_background_task(self) -> None:
        """Stop the background timer checking task."""
        if self._check_task and not self._check_task.done():
            self._check_task.cancel()
            logger.info("Stopped lunch timer background task")


# Global instance for use across the application
lunch_timer_manager = LunchTimerManager()
