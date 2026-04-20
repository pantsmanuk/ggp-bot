"""Main entry point for ggp-bot."""

import asyncio
import logging
import sys

from ggp_bot.slack.app import start_app


# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Run the GGP Slack bot."""
    logger.info("Starting GGP Bot...")
    
    try:
        await start_app()
    except KeyboardInterrupt:
        logger.info("Shutting down GGP Bot...")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        raise


def main_sync() -> None:
    """Synchronous entry point for CLI."""
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
