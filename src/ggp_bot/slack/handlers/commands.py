"""Slack slash command handlers - aligned with API v0.99.5.

This module handles all Slack slash commands. User-specific commands now use
per-user authentication via stored tokens obtained during the /connect flow.

Public endpoints (health check, public holidays) use the bot token, while
user-specific endpoints (holiday requests, profile) use the user's personal token.
"""

from slack_bolt.async_app import AsyncAck, AsyncRespond
from slack_sdk.web.async_client import AsyncWebClient

from ggp_bot.config import settings
from ggp_bot.intranet.client import IntranetClient
from ggp_bot.intranet.errors import (
    IntranetError,
    IntranetAuthError,
    IntranetScopeError,
    IntranetNotFoundError,
    IntranetInsufficientDaysError,
    IntranetSlackNotLinkedError,
)
from ggp_bot.intranet.token_storage import token_storage
from ggp_bot.utils.date_parser import parse_holiday_request


# ============================================================================
# Helper Functions
# ============================================================================

def _format_holiday_dates(holiday) -> str:
    """Format holiday dates based on type (half-day, single-day, or multi-day).
    
    Args:
        holiday: HolidayRequest object
        
    Returns:
        Formatted date string
        
    Formats:
    - Half-day (same date, AM or PM): "23/04/2026 (AM)"
    - Single day (same date, full): "23/04/2026"
    - Multi-day: "23/04/2026 to 25/04/2026" or with half-day markers
    """
    from ggp_bot.utils.date_parser import format_date_uk
    
    start_date_uk = format_date_uk(holiday.start_date)
    end_date_uk = format_date_uk(holiday.end_date)
    
    # Check if it's a single-day holiday (same start and end date)
    if holiday.start_date == holiday.end_date:
        # Single date - check for half-day
        if holiday.start_half_day:
            return f"{start_date_uk} ({holiday.start_half_day})"
        elif holiday.end_half_day:
            return f"{start_date_uk} ({holiday.end_half_day})"
        elif holiday.half_day:
            # Legacy support
            return f"{start_date_uk} ({holiday.half_day})"
        else:
            # Full single day
            return start_date_uk
    else:
        # Multi-day holiday
        parts = []
        parts.append(start_date_uk)
        if holiday.start_half_day:
            parts.append(f"({holiday.start_half_day})")
        parts.append("to")
        parts.append(end_date_uk)
        if holiday.end_half_day:
            parts.append(f"({holiday.end_half_day})")
        return " ".join(parts)


# ============================================================================
# Public Commands (No Authentication Required)
# ============================================================================

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
    
    # Health check uses bot token or no auth
    async with IntranetClient.with_bot_token() as intranet:
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
    
    # Public holidays endpoint doesn't need auth
    async with IntranetClient.with_bot_token() as intranet:
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


# ============================================================================
# User-Specific Commands (Require Per-User Authentication)
# ============================================================================

def _check_user_linked(slack_user_id: str) -> bool:
    """Check if a user has linked their account.
    
    Args:
        slack_user_id: The Slack user ID
        
    Returns:
        True if the user has a stored token
    """
    # DEBUG: Temporary diagnostic logging
    has_token = token_storage.has_token(slack_user_id)
    all_users = token_storage.get_all_users()
    print(f"[DEBUG] _check_user_linked: user={slack_user_id}, has_token={has_token}, all_users={all_users}")
    return has_token


async def _handle_not_linked(respond: AsyncRespond) -> None:
    """Send a standard response for users who haven't linked their account."""
    await respond(
        ":x: *Your Slack account is not linked to the intranet.*\n"
        "Please run `/connect <intranet-email> <password>` to link your accounts."
    )


async def handle_holiday_entitlement_command(
    ack: AsyncAck, 
    respond: AsyncRespond,
    command: dict
) -> None:
    """Handle the /holiday-entitlement command."""
    await ack()
    
    slack_user_id = command.get("user_id")
    
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond)
        return
    
    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
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
    except IntranetScopeError:
        await respond(
            ":x: *Permission Denied*\n"
            "Your account doesn't have permission to view holiday entitlement. "
            "Please contact an administrator."
        )
    except IntranetAuthError:
        await respond(
            ":x: *Authentication Failed*\n"
            "Your session may have expired. Please run `/connect` again to re-link your account."
        )
    except IntranetError as e:
        await respond(f":x: Failed to fetch entitlement: {e}")
    except Exception as e:
        await respond(f":x: Unexpected error: {e}")


async def handle_my_holidays_command(
    ack: AsyncAck, 
    respond: AsyncRespond,
    command: dict
) -> None:
    """Handle the /my-holidays command."""
    await ack()
    
    slack_user_id = command.get("user_id")
    
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond)
        return
    
    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            holidays = await intranet.get_my_holidays()
            
            if not holidays:
                await respond("No holiday requests found. Time to book some time off! :palm_tree:")
                return
            
            lines = ["*Your Holiday Requests* :calendar:"]
            
            for h in holidays:
                status_emoji = ":white_check_mark:" if h.approved else ":hourglass_flowing_sand:"
                
                # Format display based on holiday type
                date_display = _format_holiday_dates(h)
                
                lines.append(
                    f"• {status_emoji} #{h.id}: {date_display}"
                    f" - {h.working_days} day(s) - {h.status}"
                )
                if h.note:
                    lines.append(f"  _Note: {h.note}_")
            
            await respond("\n".join(lines))
            
    except IntranetScopeError:
        await respond(
            ":x: *Permission Denied*\n"
            "Your account doesn't have permission to view holidays. "
            "Please contact an administrator."
        )
    except IntranetAuthError:
        await respond(
            ":x: *Authentication Failed*\n"
            "Your session may have expired. Please run `/connect` again to re-link your account."
        )
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
    
    Supports multiple date formats and half-day requests:
    - /request-holiday <start> [end] [note]  (end defaults to start for single-day)
    - /request-holiday 23/04/2026 Family vacation (single day)
    - /request-holiday 23/04/2026 25/04/2026 Family vacation (multi-day)
    - /request-holiday 23/04/2026 AM Doctor appointment (half day)
    - /request-holiday 23/04/2026 AM 25/04/2026 PM Working half days
    
    Date formats: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, or 'DD Mon YYYY'
    Half-day markers: AM or PM (optional, can be specified for start and/or end)
    """
    await ack()
    
    slack_user_id = command.get("user_id")
    
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond)
        return
    
    # Parse command arguments
    text = command.get("text", "").strip()
    
    if not text:
        await respond(
            ":warning: *Usage:* `/request-holiday <start> [end] [note]`\n"
            "*Single day:* Omit end date to book one day\n"
            "*Date formats:* YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, or 'DD Mon YYYY'\n"
            "*Half days:* Add AM or PM after a date\n"
            "*Examples:*\n"
            "• `/request-holiday 23/04/2026 Family vacation` (single day)\n"
            "• `/request-holiday 23/04/2026 25/04/2026 Family vacation` (multi-day)\n"
            "• `/request-holiday 23/04/2026 AM Doctor appointment` (half day)\n"
            "• `/request-holiday 23/04/2026 AM 25/04/2026 PM Working half days`"
        )
        return
    
    try:
        # Parse dates and half-day markers
        start_date, end_date, start_half_day, end_half_day, note = parse_holiday_request(text)
    except ValueError as e:
        await respond(
            f":warning: *Invalid date format:* {e}\n\n"
            "*Supported formats:*\n"
            "• ISO: 2026-04-23\n"
            "• UK: 23/04/2026 or 23-04-2026\n"
            "• Verbose: 23 Apr 2026\n\n"
            "Example: `/request-holiday 23/04/2026 25/04/2026 Vacation`"
        )
        return
    
    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            # DEBUG: Log available scopes
            print(f"[DEBUG] User {slack_user_id} scopes: {intranet.scopes}")
            print(f"[DEBUG] Has bot:holiday:write? {intranet.has_scope('bot:holiday:write')}")
            
            # Check if user has write permission
            if not intranet.has_scope("bot:holiday:write"):
                await respond(
                    ":x: *Permission Denied*\n"
                    f"Your token has these scopes: {', '.join(intranet.scopes) or 'none'}\n"
                    "Missing required scope: bot:holiday:write\n"
                    "Please contact an administrator to update your permissions."
                )
                return
            
            print(f"[DEBUG] Requesting holiday: {start_date} to {end_date}, start_half={start_half_day}, end_half={end_half_day}")
            
            result = await intranet.request_holiday(
                start=start_date,
                end=end_date,
                start_half_day=start_half_day,
                end_half_day=end_half_day,
                note=note
            )
            
            # Build response message with better formatting
            if result.start_date == result.end_date:
                # Single day - show just one date
                if result.start_half_day:
                    date_display = f"{result.start_date} {result.start_half_day}"
                elif result.end_half_day:
                    date_display = f"{result.start_date} {result.end_half_day}"
                elif result.half_day:
                    date_display = f"{result.start_date} {result.half_day}"
                else:
                    date_display = result.start_date
            else:
                # Multi-day - show range with optional half-day markers
                date_parts = [result.start_date]
                if result.start_half_day:
                    date_parts.append(result.start_half_day)
                date_parts.append("to")
                date_parts.append(result.end_date)
                if result.end_half_day:
                    date_parts.append(result.end_half_day)
                date_display = " ".join(date_parts)
            
            await respond(
                f":white_check_mark: *Holiday Requested*\n"
                f"• Request ID: #{result.id}\n"
                f"• Date(s): {date_display}\n"
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
    except IntranetScopeError:
        await respond(
            ":x: *Permission Denied*\n"
            "Your account doesn't have permission to request holidays. "
            "Please contact an administrator."
        )
    except IntranetAuthError:
        await respond(
            ":x: *Authentication Failed*\n"
            "Your session may have expired. Please run `/connect` again to re-link your account."
        )
    except IntranetError as e:
        await respond(f":x: Failed to request holiday: {e}")
    except Exception as e:
        await respond(f":x: Unexpected error: {e}")


async def handle_cancel_holiday_command(
    ack: AsyncAck,
    respond: AsyncRespond,
    command: dict
) -> None:
    """Handle the /cancel-holiday command.
    
    Usage: /cancel-holiday <holiday-id>
    Cancels a pending holiday request by its ID.
    """
    await ack()
    
    slack_user_id = command.get("user_id")
    
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond)
        return
    
    # Parse command arguments
    text = command.get("text", "").strip()
    
    if not text:
        await respond(
            ":warning: *Usage:* `/cancel-holiday <holiday-id>`\n"
            "Example: `/cancel-holiday 123`\n\n"
            "Use `/my-holidays` to see your holiday IDs."
        )
        return
    
    # Parse holiday ID
    try:
        holiday_id = int(text.split()[0])
    except ValueError:
        await respond(
            ":warning: *Invalid holiday ID*\n"
            "Please provide a valid number.\n"
            "Example: `/cancel-holiday 123`"
        )
        return
    
    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            # Check if user has write permission
            if not intranet.has_scope("bot:holiday:write"):
                await respond(
                    ":x: *Permission Denied*\n"
                    "Your account doesn't have permission to cancel holidays. "
                    "Please contact an administrator."
                )
                return
            
            result = await intranet.cancel_holiday(holiday_id)
            
            print(f"[DEBUG] cancel_holiday result: {result}")
            
            # Build response - API returns working_days_returned
            days_text = ""
            if 'working_days_returned' in result:
                days_text = f"\n• Days returned: {result['working_days_returned']}"
            elif 'days_returned' in result:
                days_text = f"\n• Days returned: {result['days_returned']}"
            
            await respond(
                f":white_check_mark: *Holiday Cancelled*\n"
                f"• Request ID: #{holiday_id}\n"
                f"• Status: {result.get('status', 'Cancelled')}"
                f"{days_text}"
            )
            
    except IntranetNotFoundError:
        await respond(
            f":x: *Holiday not found*\n"
            f"Could not find holiday request #{holiday_id}.\n"
            "Use `/my-holidays` to see your current holiday requests."
        )
    except IntranetScopeError:
        await respond(
            ":x: *Permission Denied*\n"
            "Your account doesn't have permission to cancel holidays. "
            "Please contact an administrator."
        )
    except IntranetAuthError:
        await respond(
            ":x: *Authentication Failed*\n"
            "Your session may have expired. Please run `/connect` again to re-link your account."
        )
    except IntranetError as e:
        await respond(f":x: Failed to cancel holiday: {e}")
    except Exception as e:
        await respond(f":x: Unexpected error: {e}")


async def handle_whoami_command(
    ack: AsyncAck, 
    respond: AsyncRespond,
    command: dict
) -> None:
    """Handle the /whoami command.
    
    Uses the /users/by-slack-id/{slackId} endpoint to find which intranet
    user is linked to the calling Slack user.
    """
    await ack()
    
    slack_user_id = command.get("user_id")
    
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond)
        return
    
    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            # Use the new by-slack-id endpoint (API v0.99.6)
            user = await intranet.get_user_by_slack_id(slack_user_id)
            
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
            
            # Show token scopes for debugging (optional)
            if intranet.scopes:
                lines.append(f"• Permissions: {', '.join(intranet.scopes[:3])}{'...' if len(intranet.scopes) > 3 else ''}")
            
            await respond("\n".join(lines))
            
    except IntranetSlackNotLinkedError:
        await respond(
            f":x: *Your Slack account is not linked to the intranet.*\n"
            f"Please run `/connect <intranet-email> <password>` to link your accounts."
        )
    except IntranetAuthError:
        await respond(
            f":x: *Authentication Failed*\n"
            f"Your session may have expired. Please run `/connect` again to re-link your account."
        )
    except IntranetError as e:
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
    
    After successful linking, the API returns a personal Bearer token which
    is stored and used for subsequent authenticated requests by this user.
    """
    await ack()
    
    # Parse command arguments
    # Split only on first whitespace - password can contain spaces
    text = command.get("text", "").strip()
    parts = text.split(None, 1)  # Split into max 2 parts: email and password
    
    if len(parts) != 2:
        await respond(
            ":warning: *Usage:* `/connect <intranet-email> <intranet-password>`\n"
            "Example: `/connect john.doe@ggpsystems.co.uk mypassword`\n"
            "Note: Passwords with spaces are supported (e.g., `/connect email my password with spaces`)"
        )
        return
    
    intranet_email, intranet_password = parts[0], parts[1]
    slack_user_id = command.get("user_id")
    
    # Get Slack user info for the linking request
    # First try to get email from command context
    slack_email = command.get("user_email", "")
    slack_username = ""
    
    # If not available, try to fetch from Slack API
    if not slack_email:
        try:
            slack_info = await client.users_info(user=slack_user_id)
            slack_user = slack_info.get("user", {})
            slack_email = slack_user.get("profile", {}).get("email", "")
            slack_username = slack_user.get("name", "")
        except Exception:
            slack_email = ""
            slack_username = ""
    
    # If still no email, try to use intranet_email as fallback
    # (they should match for the same person)
    if not slack_email:
        slack_email = intranet_email
    
    # Use bot token for the linking request (requires bot:write scope)
    async with IntranetClient.with_bot_token() as intranet:
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
                token_data = result.get("data", {}).get("token", {})
                scopes = token_data.get("scopes", [])
                
                scope_text = ""
                if scopes:
                    scope_text = f"\n• Permissions granted: {', '.join(scopes[:5])}"
                    if len(scopes) > 5:
                        scope_text += f" and {len(scopes) - 5} more"
                
                await respond(
                    f":white_check_mark: *Account linked successfully!*\n"
                    f"Your Slack account is now connected to: {user_name}\n"
                    f"{scope_text}\n\n"
                    f"You can now use commands like `/whoami`, `/my-holidays`, and `/request-holiday`."
                )
            else:
                message = result.get("message", "Unknown error")
                await respond(f":x: Linking failed: {message}")
                
        except IntranetScopeError:
            await respond(
                ":x: *Bot Configuration Error*\n"
                "The bot doesn't have permission to link accounts. "
                "Please contact an administrator."
            )
        except IntranetAuthError:
            await respond(
                ":x: *Bot Authentication Error*\n"
                "The bot is not properly configured. Please contact an administrator."
            )
        except IntranetError as e:
            await respond(f":x: Failed to link account: {e}")
        except Exception as e:
            await respond(f":x: Unexpected error: {e}")
