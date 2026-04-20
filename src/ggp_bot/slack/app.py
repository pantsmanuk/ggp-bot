"""Slack Bolt app setup with Socket Mode."""

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from ggp_bot.config import settings
from ggp_bot.slack.handlers.commands import (
    handle_ping_command,
    handle_intranet_status_command,
    handle_next_bank_holiday_command,
    handle_holiday_entitlement_command,
    handle_my_holidays_command,
    handle_request_holiday_command,
    handle_whoami_command,
    handle_connect_command,
)


# Create the Bolt app
app = AsyncApp(
    token=settings.slack_bot_token,
    signing_secret=settings.slack_signing_secret,
)

# Register slash command handlers
app.command("/ggp-ping")(handle_ping_command)
app.command("/intranet-status")(handle_intranet_status_command)
app.command("/next-bank-holiday")(handle_next_bank_holiday_command)
app.command("/holiday-entitlement")(handle_holiday_entitlement_command)
app.command("/my-holidays")(handle_my_holidays_command)
app.command("/request-holiday")(handle_request_holiday_command)
app.command("/whoami")(handle_whoami_command)
app.command("/connect")(handle_connect_command)


async def start_app() -> None:
    """Start the Slack app with Socket Mode handler."""
    handler = AsyncSocketModeHandler(
        app=app,
        app_token=settings.slack_app_token
    )
    await handler.start_async()
