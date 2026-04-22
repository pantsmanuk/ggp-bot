"""Logging configuration for ggp-bot.

Supports both console and file output with configurable log levels.
"""

import logging
import sys
from pathlib import Path
from typing import TextIO

from ggp_bot.config import settings


def setup_logging() -> None:
    """Configure logging based on environment settings.
    
    Supports:
    - Console output (default)
    - File output (if LOG_FILE is set)
    - Configurable log level via LOG_LEVEL
    """
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    # Create formatter
    formatter = logging.Formatter(log_format, date_format)
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Always add console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Add file handler if configured
    if settings.log_file:
        log_path = Path(settings.log_file)
        # Create parent directories if needed
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        
        # Log that we're using file output
        logging.info(f"Logging to file: {log_path.absolute()}")
    
    # Reduce noise from third-party libraries
    logging.getLogger("slack_bolt").setLevel(logging.WARNING)
    logging.getLogger("slack_sdk").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
