"""Slack Bolt app setup with Socket Mode and graceful shutdown support."""

import asyncio
import logging

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from ggp_bot.config import settings
from ggp_bot.slack.handlers.commands import handle_ggp_command


logger = logging.getLogger(__name__)

# Create the Bolt app
app = AsyncApp(
    token=settings.slack_bot_token,
    signing_secret=settings.slack_signing_secret,
)

# Register the consolidated slash command handler
app.command("/ggp")(handle_ggp_command)

# Global handler reference for shutdown
_handler: AsyncSocketModeHandler | None = None


async def start_app(shutdown_event: asyncio.Event | None = None) -> None:
    """Start the Slack app with Socket Mode handler.
    
    Args:
        shutdown_event: Optional event to signal graceful shutdown
    """
    global _handler
    
    logger.debug("Initializing Socket Mode handler...")
    _handler = AsyncSocketModeHandler(
        app=app,
        app_token=settings.slack_app_token
    )
    
    # Start the handler
    logger.info("Starting Slack Socket Mode handler...")
    
    if shutdown_event:
        # Run handler and wait for shutdown event
        handler_task = asyncio.create_task(
            _handler.start_async(),
            name="socket_mode_handler"
        )
        
        # Wait for either handler to complete or shutdown event
        shutdown_task = asyncio.create_task(
            shutdown_event.wait(),
            name="shutdown_waiter"
        )
        
        done, pending = await asyncio.wait(
            [handler_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Cancel remaining tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # Check for exceptions
        for task in done:
            if task.exception() and not isinstance(task.exception(), asyncio.CancelledError):
                raise task.exception()
    else:
        # Original behavior - block until interrupted
        await _handler.start_async()


async def shutdown_app() -> None:
    """Shutdown the Slack app gracefully."""
    global _handler
    
    if _handler:
        logger.debug("Closing Slack Socket Mode handler...")
        try:
            await _handler.close()
            logger.debug("Slack handler closed successfully")
        except Exception as e:
            logger.warning(f"Error closing Slack handler: {e}")
        finally:
            _handler = None
    else:
        logger.debug("No Slack handler to close")
