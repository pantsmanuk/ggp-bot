"""Slack slash command handlers."""

from slack_bolt.async_app import AsyncAck, AsyncRespond


async def handle_ping_command(ack: AsyncAck, respond: AsyncRespond) -> None:
    """Handle the /ggp-ping command.
    
    Simple health check command to verify bot is responsive.
    """
    await ack()  # Acknowledge the command immediately
    await respond("Pong! :table_tennis_paddle_and_ball: Bot is alive and responding.")
