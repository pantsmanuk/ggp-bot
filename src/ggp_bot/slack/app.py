"""Slack Bolt app setup with Socket Mode."""

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from ggp_bot.config import settings
from ggp_bot.slack.handlers.commands import handle_ping_command


# Create the Bolt app
# Socket Mode doesn't need request signing in the traditional sense,
# but we still provide the signing secret for completeness
app = AsyncApp(
    token=settings.slack_bot_token,
    signing_secret=settings.slack_signing_secret,
)

# Register slash command handlers
app.command("/ggp-ping")(handle_ping_command)


async def start_app() -> None:
    """Start the Slack app with Socket Mode handler."""
    handler = AsyncSocketModeHandler(
        app=app,
        app_token=settings.slack_app_token
    )
    await handler.start_async()
