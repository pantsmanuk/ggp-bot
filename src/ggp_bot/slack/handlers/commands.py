"""Slack slash command handlers - aligned with API v0.99.5."""

from slack_bolt.async_app import AsyncAck, AsyncRespond
from slack_sdk.web.async_client import AsyncWebClient

from ggp_bot.config import settings
from ggp_bot.intranet.client import IntranetClient
from ggp_bot.intranet.errors import IntranetError, IntranetInsufficientDaysError


async def handle_ping_command(ack: AsyncAck, respond: AsyncRespond) -> None:
    """Handle the /ggp-ping command."""
    await ack()
    await respond("Pong! :table_tennis_paddle_and_ball: Bot is alive and responding.")


async def handle_intranet_status_command(
    ack: AsyncAck, 
    respond: AsyncRespond,
    client: AsyncWebClient
) -> None:
    """Handle the /intranet-status command."""
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
                f"• Last checked: {health.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC') if health.timestamp else 'N/A'}"
            )
        except IntranetError as e:
            await respond(f":x: Intranet connection failed: {e}")
        except Exception as e:
            await respond(f":x: Unexpected error: {e}")


async def handle_next_bank_holiday_command(
    ack: AsyncAck, 
    respond: AsyncRespond
) -> None:
    """Handle the /next-bank-holiday command."""
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


async def handle_holiday_entitlement_command(
    ack: AsyncAck, 
    respond: AsyncRespond
) -> None:
    """Handle the /holiday-entitlement command."""
    await ack()
    
    if not settings.intranet_api_token:
        await respond(":x: Authentication required. Please contact an administrator.")
        return
    
    async with IntranetClient(
        base_url=settings.intranet_base_url,
        token=settings.intranet_api_token
    ) as intranet:
        try:
            entitlement = await intranet.get_holiday_entitlement()
            
            year_start = entitlement.company_year.get("start", "N/A")
            year_end = entitlement.company_year.get("end", "N/A")
            
            await respond(
                f"*Your Holiday Entitlement* :palm_tree:\n"
                f"• Total: {entitlement.total} days\n"
                f"• Used: {entitlement.used} days\n"
                f"• Remaining: {entitlement.remaining} days\n"
                f"• Pending: {entitlement.pending} days\n"
                f"• Company Year: {year_start} to {year_end}"
            )
        except IntranetError as e:
            await respond(f":x: Failed to fetch entitlement: {e}")
        except Exception as e:
            await respond(f":x: Unexpected error: {e}")


async def handle_my_holidays_command(
    ack: AsyncAck, 
    respond: AsyncRespond
) -> None:
    """Handle the /my-holidays command."""
    await ack()
    
    if not settings.intranet_api_token:
        await respond(":x: Authentication required. Please contact an administrator.")
        return
    
    async with IntranetClient(
        base_url=settings.intranet_base_url,
        token=settings.intranet_api_token
    ) as intranet:
        try:
            holidays = await intranet.get_my_holidays()
            
            if not holidays:
                await respond("No holiday requests found. Time to book some time off! :palm_tree:")
                return
            
            lines = ["*Your Holiday Requests* :calendar:"]
            
            for h in holidays:
                status_emoji = ":white_check_mark:" if h.approved else ":hourglass_flowing_sand:"
                half_day_text = ""
                if h.half_day:
                    half_day_text = f" ({h.half_day})"
                
                lines.append(
                    f"• {status_emoji} #{h.id}: {h.start_date} to {h.end_date}"
                    f"{half_day_text} - {h.working_days} day(s) - {h.status}"
                )
                if h.note:
                    lines.append(f"  _Note: {h.note}_")
            
            await respond("\n".join(lines))
            
        except IntranetError as e:
            await respond(f":x: Failed to fetch holidays: {e}")
        except Exception as e:
            await respond(f":x: Unexpected error: {e}")


async def handle_request_holiday_command(
    ack: AsyncAck,
    respond: AsyncRespond,
    command: dict
) -> None:
    """Handle the /request-holiday command.
    
    Usage: /request-holiday <start-date> <end-date> [note]
    Dates in YYYY-MM-DD format
    """
    await ack()
    
    if not settings.intranet_api_token:
        await respond(":x: Authentication required. Please contact an administrator.")
        return
    
    # Parse command arguments
    text = command.get("text", "").strip()
    parts = text.split(None, 2)  # Split into max 3 parts
    
    if len(parts) < 2:
        await respond(
            ":warning: *Usage:* `/request-holiday <start-date> <end-date> [note]`\n"
            "Dates should be in YYYY-MM-DD format (e.g., 2026-05-01)\n"
            "Example: `/request-holiday 2026-05-01 2026-05-05 Family vacation`"
        )
        return
    
    start_date, end_date = parts[0], parts[1]
    note = parts[2] if len(parts) > 2 else None
    
    async with IntranetClient(
        base_url=settings.intranet_base_url,
        token=settings.intranet_api_token
    ) as intranet:
        try:
            result = await intranet.request_holiday(
                start=start_date,
                end=end_date,
                note=note
            )
            
            await respond(
                f":white_check_mark: *Holiday Requested*\n"
                f"• Request ID: #{result.id}\n"
                f"• Dates: {result.start_date} to {result.end_date}\n"
                f"• Working days: {result.working_days}\n"
                f"• Status: Pending approval"
            )
            
        except IntranetInsufficientDaysError as e:
            details = e.details or {}
            shortfall = details.get("shortfall", "unknown")
            remaining = details.get("remaining_days", "unknown")
            await respond(
                f":x: *Insufficient Holiday Days*\n"
                f"You don't have enough days remaining.\n"
                f"• Remaining: {remaining} days\n"
                f"• Shortfall: {shortfall} days"
            )
        except IntranetError as e:
            await respond(f":x: Failed to request holiday: {e}")
        except Exception as e:
            await respond(f":x: Unexpected error: {e}")


async def handle_whoami_command(
    ack: AsyncAck, 
    respond: AsyncRespond
) -> None:
    """Handle the /whoami command."""
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
            
            slack_status = ":white_check_mark: Linked" if user.slack_linked else ":x: Not linked"
            lines.append(f"• Slack: {slack_status}")
            
            await respond("\n".join(lines))
        except IntranetError as e:
            if e.error_code == "UNAUTHENTICATED":
                await respond(
                    f":x: Your Slack account is not linked to the intranet.\n"
                    f"Please run `/connect` to link your accounts."
                )
            else:
                await respond(f":x: Failed to fetch profile: {e}")
        except Exception as e:
            await respond(f":x: Unexpected error: {e}")


async def handle_connect_command(
    ack: AsyncAck,
    respond: AsyncRespond,
    command: dict,
    client: AsyncWebClient
) -> None:
    """Handle the /connect command for Slack account linking.
    
    Usage: /connect <intranet-email> <intranet-password>
    """
    await ack()
    
    # Parse command arguments
    text = command.get("text", "").strip()
    parts = text.split()
    
    if len(parts) != 2:
        await respond(
            ":warning: *Usage:* `/connect <intranet-email> <intranet-password>`\n"
            "Example: `/connect john.doe@ggpsystems.co.uk mypassword`"
        )
        return
    
    intranet_email, intranet_password = parts[0], parts[1]
    slack_user_id = command.get("user_id")
    
    # Get Slack user info for the linking request
    try:
        slack_info = await client.users_info(user=slack_user_id)
        slack_user = slack_info.get("user", {})
        slack_email = slack_user.get("profile", {}).get("email", "")
        slack_username = slack_user.get("name", "")
    except Exception:
        slack_email = ""
        slack_username = ""
    
    if not settings.intranet_api_token:
        await respond(":x: Bot is not configured for intranet authentication.")
        return
    
    async with IntranetClient(
        base_url=settings.intranet_base_url,
        token=settings.intranet_api_token
    ) as intranet:
        try:
            result = await intranet.link_slack_account(
                slack_user_id=slack_user_id,
                slack_email=slack_email,
                slack_username=slack_username,
                intranet_email=intranet_email,
                intranet_password=intranet_password
            )
            
            if result.get("success"):
                user_data = result.get("data", {}).get("user", {})
                user_name = user_data.get("name", "your account")
                
                await respond(
                    f":white_check_mark: *Account linked successfully!*\n"
                    f"Your Slack account is now connected to: {user_name}\n\n"
                    f"You can now use commands like `/whoami` and `/my-holidays`."
                )
            else:
                message = result.get("message", "Unknown error")
                await respond(f":x: Linking failed: {message}")
                
        except IntranetError as e:
            await respond(f":x: Failed to link account: {e}")
        except Exception as e:
            await respond(f":x: Unexpected error: {e}")
