"""Main entry point for ggp-bot with graceful shutdown support."""

import asyncio
import logging
import signal

# Configure logging FIRST, before any imports that might instantiate
# token_storage or other components that log during initialization
from ggp_bot.logging_config import setup_logging
setup_logging()

from ggp_bot.slack.app import start_app, shutdown_app
from ggp_bot.intranet.client import IntranetClient


logger = logging.getLogger(__name__)

# Global shutdown event for coordinating graceful shutdown
_shutdown_event = asyncio.Event()


def _signal_handler(signum: int, frame) -> None:
    """Handle SIGINT and SIGTERM signals.
    
    Sets the shutdown event to trigger graceful shutdown.
    """
    sig_name = signal.Signals(signum).name
    logger.info(f"Received {sig_name}, initiating graceful shutdown...")
    _shutdown_event.set()


async def main() -> None:
    """Run the GGP Slack bot with graceful shutdown support."""
    logger.info("Starting GGP Bot...")
    
    # Install signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    logger.debug("Signal handlers installed for SIGINT and SIGTERM")
    
    # Start the app in a background task
    app_task = asyncio.create_task(
        start_app(shutdown_event=_shutdown_event),
        name="slack_app"
    )
    
    try:
        # Wait for either the app to complete or shutdown to be triggered
        done, pending = await asyncio.wait(
            [app_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Check if app_task raised an exception
        for task in done:
            if task.exception():
                raise task.exception()
                
    except asyncio.CancelledError:
        logger.debug("Main task cancelled")
    finally:
        # Ensure graceful shutdown
        if not _shutdown_event.is_set():
            logger.debug("Setting shutdown event...")
            _shutdown_event.set()
        
        # Cancel any pending tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # Perform cleanup
        await _perform_cleanup()
        
    logger.info("GGP Bot shut down successfully")


async def _perform_cleanup() -> None:
    """Perform cleanup operations during shutdown."""
    logger.debug("Starting cleanup operations...")
    
    # Close all active IntranetClient connections
    await IntranetClient.close_all()
    
    # Shutdown Slack app
    await shutdown_app()
    
    logger.debug("Cleanup completed")


def main_sync() -> None:
    """Synchronous entry point for CLI."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # This should not happen due to signal handling, but just in case
        logger.info("KeyboardInterrupt caught in main_sync")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        raise


if __name__ == "__main__":
    main_sync()
