"""Slack slash command handlers - aligned with API v0.99.5.

This module handles all Slack slash commands through a consolidated /ggp interface.
User-specific commands use per-user authentication via stored tokens obtained 
during the /ggp connect flow.

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
# Levenshtein Distance Helper for "Did You Mean?" Suggestions
# ============================================================================

def _levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate the Levenshtein distance between two strings.
    
    This is a simple, efficient implementation for short strings (command names).
    """
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # Cost is 0 if characters match, 1 if they don't
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (0 if c1 == c2 else 1)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def _suggest_command(input_cmd: str, available_commands: list[str]) -> str | None:
    """Suggest the closest matching command for unknown input.
    
    Only suggests if Levenshtein distance is ≤ 2 (close matches only).
    
    Args:
        input_cmd: The command the user typed
        available_commands: List of valid command names
        
    Returns:
        The closest matching command name, or None if no close match
    """
    input_lower = input_cmd.lower()
    
    # First try exact substring match
    for cmd in available_commands:
        if input_lower in cmd.lower() or cmd.lower() in input_lower:
            return cmd
    
    # Then try Levenshtein distance
    best_match = None
    best_distance = float('inf')
    
    for cmd in available_commands:
        distance = _levenshtein_distance(input_lower, cmd.lower())
        if distance < best_distance:
            best_distance = distance
            best_match = cmd
    
    # Only suggest if distance is ≤ 2 (close match)
    if best_distance <= 2:
        return best_match
    
    return None


# ============================================================================
# Command Registry and Help System
# ============================================================================

# Define command metadata for help and routing
PUBLIC_COMMANDS = {
    "ping": {
        "description": "Test bot responsiveness",
        "requires_auth": False,
        "params": "",
    },
    "status": {
        "description": "Check intranet API status",
        "requires_auth": False,
        "params": "",
    },
    "bank-holiday": {
        "description": "Show next UK bank holiday",
        "requires_auth": False,
        "params": "",
    },
    "connect": {
        "description": "Link your Slack account to the intranet",
        "requires_auth": False,
        "params": "<email> <password>",
    },
    "help": {
        "description": "Show this help or details about a command",
        "requires_auth": False,
        "params": "[command]",
    },
}

AUTH_COMMANDS = {
    "whoami": {
        "description": "Show your linked intranet profile",
        "requires_auth": True,
        "params": "",
    },
}

HOLIDAY_SUBCOMMANDS = {
    "balance": {
        "description": "Check holiday entitlement",
        "requires_auth": True,
        "params": "",
    },
    "list": {
        "description": "View your holiday bookings",
        "requires_auth": True,
        "params": "",
    },
    "new": {
        "description": "Request time off",
        "requires_auth": True,
        "params": "<dates> [note]",
    },
    "cancel": {
        "description": "Cancel a holiday booking",
        "requires_auth": True,
        "params": "<id>",
    },
}


def _get_all_command_names() -> list[str]:
    """Get list of all valid command names for suggestion matching."""
    names = list(PUBLIC_COMMANDS.keys()) + list(AUTH_COMMANDS.keys())
    # Add holiday subcommands as 'holiday <subcmd>'
    for subcmd in HOLIDAY_SUBCOMMANDS.keys():
        names.append(f"holiday {subcmd}")
    return names


def _format_command_help(name: str, meta: dict) -> str:
    """Format a single command for help display."""
    params = f" {meta['params']}" if meta['params'] else ""
    return f"• /ggp {name}{params} - {meta['description']}"


async def _handle_help_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    topic: str | None = None
) -> None:
    """Display context-aware help.
    
    Args:
        respond: Slack respond function
        slack_user_id: The Slack user ID (for checking connection status)
        topic: Optional specific command to get detailed help for
    """
    is_connected = token_storage.has_token(slack_user_id)
    
    # If user asked for help on a specific topic
    if topic:
        topic_lower = topic.lower()
        
        # Check for holiday subcommand help
        if topic_lower.startswith("holiday "):
            subcmd = topic_lower.split(" ", 1)[1]
            if subcmd in HOLIDAY_SUBCOMMANDS:
                meta = HOLIDAY_SUBCOMMANDS[subcmd]
                params = f" {meta['params']}" if meta['params'] else ""
                
                help_text = (
                    f"*/ggp holiday {subcmd}{params}*\n"
                    f"{meta['description']}\n\n"
                )
                
                if subcmd == "new":
                    help_text += (
                        "*Examples:*\n"
                        "• /ggp holiday new 23/04/2026 Vacation (single day)\n"
                        "• /ggp holiday new 23/04/2026 25/04/2026 Family trip (multi-day)\n"
                        "• /ggp holiday new 23/04/2026 AM Doctor (half day)\n\n"
                        "*Date formats:* YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, or 'DD Mon YYYY'\n"
                        "*Half-day markers:* AM or PM after a date"
                    )
                elif subcmd == "cancel":
                    help_text += "Use `/ggp holiday list` to find holiday IDs."
                
                await respond(help_text)
                return
        
        # Check for top-level command help
        all_commands = {**PUBLIC_COMMANDS, **AUTH_COMMANDS}
        if topic_lower in all_commands:
            meta = all_commands[topic_lower]
            params = f" {meta['params']}" if meta['params'] else ""
            
            help_text = f"*/ggp {topic_lower}{params}*\n{meta['description']}"
            
            if topic_lower == "connect":
                help_text += (
                    "\n\n*Example:*\n"
                    "• /ggp connect john.doe@ggpsystems.co.uk mypassword\n\n"
                    "This links your Slack account to your intranet profile, "
                    "allowing you to use personalized commands."
                )
            
            await respond(help_text)
            return
        
        # Unknown topic
        await respond(
            f":warning: Unknown command '{topic}'.\n"
            f"Run `/ggp help` to see all available commands."
        )
        return
    
    # General help - show based on connection status
    lines = ["*GGP Bot Commands*\n"]
    
    if is_connected:
        lines.append(":white_check_mark: Your account is linked\n")
    
    lines.append("*Public commands:*")
    for name, meta in PUBLIC_COMMANDS.items():
        lines.append(_format_command_help(name, meta))
    
    if is_connected:
        lines.append("\n*Your commands:*")
        for name, meta in AUTH_COMMANDS.items():
            lines.append(_format_command_help(name, meta))
        
        lines.append("\n*Holiday commands:*")
        for name, meta in HOLIDAY_SUBCOMMANDS.items():
            lines.append(_format_command_help(f"holiday {name}", meta))
        
        lines.append(
            "\n*Examples:*\n"
            "• /ggp holiday new 23/04/2026 Vacation\n"
            "• /ggp holiday new 23/04/2026 AM Doctor"
        )
    else:
        lines.append(
            "\n_Run `/ggp connect <email> <password>` to link your account "
            "and access holiday and profile commands._"
        )
        lines.append("\n*Available after connecting:*")
        for name, meta in AUTH_COMMANDS.items():
            lines.append(f"• /ggp {name} - {meta['description']}")
        for name, meta in HOLIDAY_SUBCOMMANDS.items():
            lines.append(f"• /ggp holiday {name} - {meta['description']}")
    
    await respond("\n".join(lines))


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
        "Please run `/ggp connect <intranet-email> <password>` to link your accounts."
    )


# ============================================================================
# Public Subcommand Handlers (No Authentication Required)
# ============================================================================

async def _handle_ping_subcommand(
    respond: AsyncRespond,
    client: AsyncWebClient | None = None
) -> None:
    """Handle the ping subcommand."""
    await respond("Pong! :table_tennis_paddle_and_ball: Bot is alive and responding.")


async def _handle_status_subcommand(
    respond: AsyncRespond,
    client: AsyncWebClient | None = None
) -> None:
    """Handle the status subcommand (was /intranet-status)."""
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


async def _handle_bank_holiday_subcommand(
    respond: AsyncRespond,
    client: AsyncWebClient | None = None
) -> None:
    """Handle the bank-holiday subcommand (was /next-bank-holiday)."""
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


async def _handle_connect_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    args: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle the connect subcommand (account linking).
    
    Usage: /ggp connect <intranet-email> <intranet-password>
    
    After successful linking, the API returns a personal Bearer token which
    is stored and used for subsequent authenticated requests by this user.
    """
    # Parse command arguments
    # Split only on first whitespace - password can contain spaces
    parts = args.strip().split(None, 1)  # Split into max 2 parts: email and password
    
    if len(parts) != 2:
        await respond(
            ":warning: *Usage:* `/ggp connect <intranet-email> <intranet-password>`\n"
            "Example: `/ggp connect john.doe@ggpsystems.co.uk mypassword`\n"
            "Note: Passwords with spaces are supported (e.g., `/ggp connect email my password with spaces`)"
        )
        return
    
    intranet_email, intranet_password = parts[0], parts[1]
    
    # Get Slack user info for the linking request
    # First try to get email from command context
    slack_email = ""
    slack_username = ""
    
    # If client available, try to fetch from Slack API
    if client:
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
                    f"You can now use commands like `/ggp whoami`, `/ggp holiday list`, and `/ggp holiday new`."
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


# ============================================================================
# User-Specific Subcommand Handlers (Require Per-User Authentication)
# ============================================================================

async def _handle_whoami_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle the whoami subcommand.
    
    Uses the /users/by-slack-id/{slackId} endpoint to find which intranet
    user is linked to the calling Slack user.
    """
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
            f"Please run `/ggp connect <intranet-email> <password>` to link your accounts."
        )
    except IntranetAuthError:
        await respond(
            f":x: *Authentication Failed*\n"
            f"Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        await respond(f":x: Failed to fetch profile: {e}")
    except Exception as e:
        await respond(f":x: Unexpected error: {e}")


async def _handle_holiday_balance_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle the holiday balance subcommand (was /holiday-entitlement)."""
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
            "Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        await respond(f":x: Failed to fetch entitlement: {e}")
    except Exception as e:
        await respond(f":x: Unexpected error: {e}")


async def _handle_holiday_list_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle the holiday list subcommand (was /my-holidays)."""
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
            "Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        await respond(f":x: Failed to fetch holidays: {e}")
    except Exception as e:
        await respond(f":x: Unexpected error: {e}")


async def _handle_holiday_new_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    args: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle the holiday new subcommand (was /request-holiday).
    
    Supports multiple date formats and half-day requests:
    - /ggp holiday new <start> [end] [note]  (end defaults to start for single-day)
    - /ggp holiday new 23/04/2026 Family vacation (single day)
    - /ggp holiday new 23/04/2026 25/04/2026 Family vacation (multi-day)
    - /ggp holiday new 23/04/2026 AM Doctor appointment (half day)
    - /ggp holiday new 23/04/2026 AM 25/04/2026 PM Working half days
    
    Date formats: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, or 'DD Mon YYYY'
    Half-day markers: AM or PM (optional, can be specified for start and/or end)
    """
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond)
        return
    
    # Parse command arguments
    text = args.strip()
    
    if not text:
        await respond(
            ":warning: *Usage:* `/ggp holiday new <start> [end] [note]`\n"
            "*Single day:* Omit end date to book one day\n"
            "*Date formats:* YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, or 'DD Mon YYYY'\n"
            "*Half days:* Add AM or PM after a date\n"
            "*Examples:*\n"
            "• `/ggp holiday new 23/04/2026 Family vacation` (single day)\n"
            "• `/ggp holiday new 23/04/2026 25/04/2026 Family vacation` (multi-day)\n"
            "• `/ggp holiday new 23/04/2026 AM Doctor appointment` (half day)\n"
            "• `/ggp holiday new 23/04/2026 AM 25/04/2026 PM Working half days`"
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
            "Example: `/ggp holiday new 23/04/2026 25/04/2026 Vacation`"
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
            
            print(f"[DEBUG] API result: id={result.id}, working_days={result.working_days}, start={result.start_date}, end={result.end_date}")
            
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
            "Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        await respond(f":x: Failed to request holiday: {e}")
    except Exception as e:
        await respond(f":x: Unexpected error: {e}")


async def _handle_holiday_cancel_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    args: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle the holiday cancel subcommand (was /cancel-holiday).
    
    Usage: /ggp holiday cancel <holiday-id>
    Cancels a pending holiday request by its ID.
    """
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond)
        return
    
    # Parse command arguments
    text = args.strip()
    
    if not text:
        await respond(
            ":warning: *Usage:* `/ggp holiday cancel <holiday-id>`\n"
            "Example: `/ggp holiday cancel 123`\n\n"
            "Use `/ggp holiday list` to see your holiday IDs."
        )
        return
    
    # Parse holiday ID
    try:
        holiday_id = int(text.split()[0])
    except ValueError:
        await respond(
            ":warning: *Invalid holiday ID*\n"
            "Please provide a valid number.\n"
            "Example: `/ggp holiday cancel 123`"
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
            "Use `/ggp holiday list` to see your current holiday requests."
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
            "Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        await respond(f":x: Failed to cancel holiday: {e}")
    except Exception as e:
        await respond(f":x: Unexpected error: {e}")


# ============================================================================
# Holiday Subcommand Dispatcher
# ============================================================================

async def _handle_holiday_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    args: str,
    client: AsyncWebClient | None = None
) -> None:
    """Dispatch holiday subcommands to their handlers.
    
    Args:
        respond: Slack respond function
        slack_user_id: The Slack user ID
        args: Subcommand and arguments (e.g., "new 23/04/2026 Vacation")
        client: Optional Slack WebClient
    """
    # Parse the holiday subcommand
    parts = args.strip().split(None, 1)
    subcommand = parts[0].lower() if parts else ""
    sub_args = parts[1] if len(parts) > 1 else ""
    
    if subcommand == "balance":
        await _handle_holiday_balance_subcommand(respond, slack_user_id, client)
    elif subcommand == "list":
        await _handle_holiday_list_subcommand(respond, slack_user_id, client)
    elif subcommand == "new":
        await _handle_holiday_new_subcommand(respond, slack_user_id, sub_args, client)
    elif subcommand == "cancel":
        await _handle_holiday_cancel_subcommand(respond, slack_user_id, sub_args, client)
    else:
        # Unknown holiday subcommand - suggest valid ones
        valid_subcommands = list(HOLIDAY_SUBCOMMANDS.keys())
        suggestion = _suggest_command(subcommand, [f"holiday {cmd}" for cmd in valid_subcommands])
        
        if suggestion:
            suggestion_clean = suggestion.replace("holiday ", "")
            await respond(
                f":warning: Unknown holiday subcommand '{subcommand}'.\n"
                f"Did you mean: `holiday {suggestion_clean}`?\n\n"
                f"*Available holiday commands:*\n"
                f"• /ggp holiday balance - Check holiday entitlement\n"
                f"• /ggp holiday list - View your bookings\n"
                f"• /ggp holiday new <dates> - Request time off\n"
                f"• /ggp holiday cancel <id> - Cancel a booking\n\n"
                f"Run `/ggp help holiday` for more details."
            )
        else:
            await respond(
                f":warning: Unknown holiday subcommand '{subcommand}'.\n\n"
                f"*Available holiday commands:*\n"
                f"• /ggp holiday balance - Check holiday entitlement\n"
                f"• /ggp holiday list - View your bookings\n"
                f"• /ggp holiday new <dates> - Request time off\n"
                f"• /ggp holiday cancel <id> - Cancel a booking\n\n"
                f"Run `/ggp help holiday` for more details."
            )


# ============================================================================
# Main Command Router
# ============================================================================

async def handle_ggp_command(
    ack: AsyncAck,
    respond: AsyncRespond,
    command: dict,
    client: AsyncWebClient
) -> None:
    """Main entry point for the /ggp command.
    
    Routes to appropriate subcommand handlers based on the command text.
    
    Args:
        ack: Slack Bolt ack function
        respond: Slack Bolt respond function
        command: Command dictionary containing user_id, text, etc.
        client: Slack WebClient for API calls
    """
    await ack()
    
    # Parse the command
    slack_user_id = command.get("user_id")
    full_text = command.get("text", "").strip()
    
    # Split into command and arguments
    parts = full_text.split(None, 1)
    subcommand = parts[0].lower() if parts else "help"
    args = parts[1] if len(parts) > 1 else ""
    
    # Route to appropriate handler
    if subcommand == "ping":
        await _handle_ping_subcommand(respond, client)
    elif subcommand == "status":
        await _handle_status_subcommand(respond, client)
    elif subcommand == "bank-holiday":
        await _handle_bank_holiday_subcommand(respond, client)
    elif subcommand == "connect":
        await _handle_connect_subcommand(respond, slack_user_id, args, client)
    elif subcommand == "whoami":
        await _handle_whoami_subcommand(respond, slack_user_id, client)
    elif subcommand == "holiday":
        await _handle_holiday_subcommand(respond, slack_user_id, args, client)
    elif subcommand == "help":
        await _handle_help_subcommand(respond, slack_user_id, args)
    else:
        # Unknown command - provide suggestion if close match
        all_commands = _get_all_command_names()
        suggestion = _suggest_command(subcommand, all_commands)
        
        if suggestion:
            await respond(
                f":warning: Unknown command '{subcommand}'.\n"
                f"Did you mean: `{suggestion}`?\n\n"
                f"Run `/ggp help` to see all available commands."
            )
        else:
            await respond(
                f":warning: Unknown command '{subcommand}'.\n\n"
                f"Run `/ggp help` to see all available commands."
            )
