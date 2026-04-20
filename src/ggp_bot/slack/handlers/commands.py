"""Slack slash command handlers."""

from slack_bolt.async_app import AsyncAck, AsyncRespond
from slack_sdk.web.async_client import AsyncWebClient

from ggp_bot.config import settings
from ggp_bot.intranet.client import IntranetClient
from ggp_bot.intranet.errors import IntranetError


async def handle_ping_command(ack: AsyncAck, respond: AsyncRespond) -> None:
    """Handle the /ggp-ping command."""
    await ack()
    await respond("Pong! :table_tennis_paddle_and_ball: Bot is alive and responding.")


async def handle_intranet_status_command(
    ack: AsyncAck, 
    respond: AsyncRespond,
    client: AsyncWebClient
) -> None:
    """Handle the /intranet status command.
    
    Shows API connectivity and version information.
    """
    await ack()
    
    async with IntranetClient(
        base_url=settings.intranet_base_url,
        token=settings.intranet_api_token
    ) as intranet:
        try:
            health = await intranet.health_check()
            
            status_emoji = ":white_check_mark:" if health.status == "healthy" else ":warning:"
            
            await respond(
                f"{status_emoji} *Intranet API Status*\n"
                f"• Status: {health.status}\n"
                f"• Version: {health.version}\n"
                f"• Last checked: {health.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )
        except IntranetError as e:
            await respond(f":x: Intranet connection failed: {e}")
        except Exception as e:
            await respond(f":x: Unexpected error: {e}")


async def handle_next_bank_holiday_command(
    ack: AsyncAck, 
    respond: AsyncRespond
) -> None:
    """Handle the /next-bank-holiday command.
    
    Shows the next upcoming UK bank holiday.
    """
    await ack()
    
    async with IntranetClient(
        base_url=settings.intranet_base_url,
        token=settings.intranet_api_token
    ) as intranet:
        try:
            holiday = await intranet.get_next_public_holiday()
            
            days_text = "tomorrow!" if holiday.is_tomorrow else f"in {holiday.days_until} days"
            if holiday.is_today:
                days_text = "today! :tada:"
            
            await respond(
                f"*Next UK Bank Holiday* :flag-gb:\n"
                f"• {holiday.name}\n"
                f"• Date: {holiday.date} ({holiday.day_of_week})\n"
                f"• Coming up: {days_text}"
            )
        except IntranetError as e:
            await respond(f":x: Failed to fetch public holiday: {e}")
        except Exception as e:
            await respond(f":x: Unexpected error: {e}")


async def handle_whoami_command(
    ack: AsyncAck, 
    respond: AsyncRespond
) -> None:
    """Handle the /whoami command.
    
    Shows current user's intranet profile.
    """
    await ack()
    
    if not settings.intranet_api_token:
        await respond(":x: Authentication required. Please contact an administrator.")
        return
    
    async with IntranetClient(
        base_url=settings.intranet_base_url,
        token=settings.intranet_api_token
    ) as intranet:
        try:
            user = await intranet.get_current_user()
            
            lines = [f"*Your Profile* :bust_in_silhouette:"]
            lines.append(f"• Name: {user.name}")
            lines.append(f"• Email: {user.email}")
            if user.department:
                lines.append(f"• Department: {user.department}")
            if user.job_title:
                lines.append(f"• Job Title: {user.job_title}")
            if user.phone:
                lines.append(f"• Phone: {user.phone}")
            if user.location:
                lines.append(f"• Location: {user.location}")
            
            await respond("\n".join(lines))
        except IntranetError as e:
            await respond(f":x: Failed to fetch profile: {e}")
        except Exception as e:
            await respond(f":x: Unexpected error: {e}")
