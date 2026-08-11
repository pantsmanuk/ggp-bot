"""Slack slash command handlers - aligned with API v1.0.0.

This module handles all Slack slash commands through a consolidated /ggp interface.
User-specific commands use per-user authentication via stored tokens obtained 
during the /ggp connect flow.

Public endpoints (health check, public holidays) use the bot token, while
user-specific endpoints (holiday requests, profile) use the user's personal token.
"""

import logging
import re
import socket

from slack_bolt.async_app import AsyncAck, AsyncRespond
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from ggp_bot.config import settings

logger = logging.getLogger(__name__)
from ggp_bot.intranet.client import IntranetClient
from ggp_bot.intranet.errors import (
    IntranetError,
    IntranetAuthError,
    IntranetInvalidCredentialsError,
    IntranetScopeError,
    IntranetNotFoundError,
    IntranetInsufficientDaysError,
    IntranetSlackNotLinkedError,
)
from ggp_bot.intranet.token_storage import token_storage
from ggp_bot.db_cleanup.scheduler import cleanup_scheduler
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
    "whois": {
        "description": "Show a user's profile and status by @mention",
        "requires_auth": True,
        "params": "<@user>",
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
        "description": "Cancel holiday booking(s)",
        "requires_auth": True,
        "params": "<id(s)>",
    },
}

DIRECTORY_SUBCOMMANDS = {
    "search": {
        "description": "Search directory by name, email, or department",
        "requires_auth": True,
        "params": "<query>",
    },
    "list": {
        "description": "List all users in directory",
        "requires_auth": True,
        "params": "",
    },
}

CLOCK_SUBCOMMANDS = {
    "in": {
        "description": "Clock in",
        "requires_auth": True,
        "params": "[force] [note]",
    },
    "out": {
        "description": "Clock out",
        "requires_auth": True,
        "params": "[note]",
    },
    "today": {
        "description": "Show today's time card",
        "requires_auth": True,
        "params": "",
    },
    "week": {
        "description": "Show this week's time card",
        "requires_auth": True,
        "params": "",
    },
    "lunch": {
        "description": "Start 1-hour lunch break with reminders",
        "requires_auth": True,
        "params": "",
    },
}

ADMIN_SUBCOMMANDS = {
    "cache": {
        "description": "Token cache management",
        "requires_auth": True,
        "params": "<clear|status>",
    },
    "gc": {
        "description": "Garbage collection control",
        "requires_auth": True,
        "params": "<status|run>",
    },
    "integrity": {
        "description": "Database integrity checking",
        "requires_auth": True,
        "params": "<check>",
    },
    "holiday": {
        "description": "Admin holiday management (approve/deny)",
        "requires_auth": True,
        "params": "<pending|approve|approve-all|deny|deny-all>",
    },
    "refresh": {
        "description": "Refresh a user's API token",
        "requires_auth": True,
        "params": "<@user>",
    },
}


def _get_all_command_names() -> list[str]:
    """Get list of all valid command names for suggestion matching.
    
    Note: Admin commands are excluded from suggestions as they should
    only be discoverable by admin users via /ggp help output.
    """
    names = list(PUBLIC_COMMANDS.keys()) + list(AUTH_COMMANDS.keys())
    # Add holiday subcommands as 'holiday <subcmd>'
    for subcmd in HOLIDAY_SUBCOMMANDS.keys():
        names.append(f"holiday {subcmd}")
    # Add directory subcommands as 'directory <subcmd>'
    for subcmd in DIRECTORY_SUBCOMMANDS.keys():
        names.append(f"directory {subcmd}")
    # Add clock subcommands as 'clock <subcmd>'
    for subcmd in CLOCK_SUBCOMMANDS.keys():
        names.append(f"clock {subcmd}")
    # Add clock aliases
    names.extend(["in", "out", "lunch"])
    # Admin commands intentionally excluded - only discoverable by admins
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
                    help_text += (
                        "*Examples:*\n"
                        "• /ggp holiday cancel 123 (single holiday)\n"
                        "• /ggp holiday cancel 123, 125, 127 (multiple)\n"
                        "• /ggp holiday cancel 150-155 (range)\n"
                        "• /ggp holiday cancel 150, 152-155, 158 (mixed)\n\n"
                        "Use `/ggp holiday list` to find holiday IDs."
                    )
                elif subcmd == "search":
                    help_text += (
                        "*Examples:*\n"
                        "• /ggp directory search john (search by name)\n"
                        "• /ggp directory search engineering (search by department)\n"
                        "• /ggp directory search john@company.com (search by email)"
                    )
                elif subcmd == "list":
                    help_text += (
                        "Shows all users in the company directory.\n\n"
                        "Use `/ggp whois @user` to see detailed profile and status."
                    )
                
                await respond(help_text)
                return
        
        # Check for directory subcommand help
        if topic_lower.startswith("directory "):
            subcmd = topic_lower.split(" ", 1)[1]
            if subcmd in DIRECTORY_SUBCOMMANDS:
                meta = DIRECTORY_SUBCOMMANDS[subcmd]
                params = f" {meta['params']}" if meta['params'] else ""
                
                help_text = (
                    f"*/ggp directory {subcmd}{params}*\n"
                    f"{meta['description']}\n\n"
                )
                
                if subcmd == "search":
                    help_text += (
                        "*Examples:*\n"
                        "• /ggp directory search john (search by name)\n"
                        "• /ggp directory search engineering (search by department)\n"
                        "• /ggp directory search john@company.com (search by email)"
                    )
                elif subcmd == "list":
                    help_text += (
                        "Shows all users in the company directory with their departments.\n\n"
                        "Use `/ggp directory search <name>` to find specific users."
                    )
                
                await respond(help_text)
                return
        
        # Check for clock subcommand help
        if topic_lower.startswith("clock "):
            subcmd = topic_lower.split(" ", 1)[1]
            if subcmd in CLOCK_SUBCOMMANDS:
                meta = CLOCK_SUBCOMMANDS[subcmd]
                params = f" {meta['params']}" if meta['params'] else ""
                
                help_text = (
                    f"*/ggp clock {subcmd}{params}*\n"
                    f"{meta['description']}\n\n"
                )
                
                if subcmd == "in":
                    help_text += (
                        "*Examples:*\n"
                        "• /ggp clock in\n"
                        "• /ggp clock in Working on project X\n"
                        "• /ggp clock in force Working on project X\n\n"
                        "*Public holiday warning:* If today is a public holiday, you must add `force` to clock in.\n"
                        "Posts to #Attendance channel (only on state change)."
                    )
                elif subcmd == "out":
                    help_text += (
                        "*Examples:*\n"
                        "• /ggp clock out\n"
                        "• /ggp clock out Lunch break\n\n"
                        "Posts to #Attendance channel (only on state change)."
                    )
                elif subcmd == "today":
                    help_text += (
                        "Shows all clock events for today with in/out times and durations."
                    )
                elif subcmd == "week":
                    help_text += (
                        "Shows all clock events for the current week, grouped by day."
                    )
                elif subcmd == "lunch":
                    help_text += (
                        "Starts a 1-hour lunch timer with DM reminders.\n\n"
                        "*Reminders:*\n"
                        "• 5 minutes left on lunch break\n"
                        "• 1 minute left on lunch break\n"
                        "• Lunch break over - please clock in\n\n"
                        "*Idempotent:* Additional calls while timer is running do nothing.\n"
                        "*Early return:* Clock in normally to cancel remaining reminders."
                    )
                
                await respond(help_text)
                return
        
        # Check for clock alias help
        if topic_lower in ("in", "out", "lunch"):
            subcmd = topic_lower
            meta = CLOCK_SUBCOMMANDS[subcmd]
            params = f" {meta['params']}" if meta['params'] else ""
            
            help_text = (
                f"*/ggp {subcmd}{params}*\n"
                f"Alias for `/ggp clock {subcmd}{params}`\n"
                f"{meta['description']}\n\n"
            )
            
            if subcmd == "in":
                help_text += (
                    "*Examples:*\n"
                    "• /ggp in\n"
                    "• /ggp in Working on project X\n"
                    "• /ggp in force Working on project X\n\n"
                    "*Public holiday warning:* If today is a public holiday, you must add `force` to clock in.\n"
                    "Posts to #Attendance channel (only on state change)."
                )
            elif subcmd == "out":
                help_text += (
                    "*Examples:*\n"
                    "• /ggp out\n"
                    "• /ggp out Lunch break\n\n"
                    "Posts to #Attendance channel (only on state change)."
                )
            elif subcmd == "lunch":
                help_text += (
                    "Starts a 1-hour lunch timer with DM reminders.\n\n"
                    "*Reminders:*\n"
                    "• 5 minutes left on lunch break\n"
                    "• 1 minute left on lunch break\n"
                    "• Lunch break over - please clock in\n\n"
                    "*Idempotent:* Additional calls while timer is running do nothing.\n"
                    "*Early return:* Clock in normally to cancel remaining reminders."
                )
            
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
            elif topic_lower == "whois":
                help_text += (
                    "\n\n*Example:*\n"
                    "• /ggp whois @john.doe\n\n"
                    "Shows the user's profile, department, phone number, and current status."
                )
            
            await respond(help_text)
            return
        
        # Check for clock as a top-level help topic
        if topic_lower == "clock":
            help_text = (
                "*/ggp clock [subcommand]*\n"
                "Time clock management for tracking work hours.\n\n"
                "*Subcommands:*\n"
                "• in [force] [note] - Clock in (posts to #Attendance)\n"
                "• out [note] - Clock out (posts to #Attendance)\n"
                "• lunch - Start 1-hour lunch timer with DM reminders\n"
                "• today - Show today's time card\n"
                "• week - Show this week's time card\n"
                "• (no subcommand) - Show current clock status\n\n"
                "*Aliases:*\n"
                "• /ggp in - Alias for `/ggp clock in`\n"
                "• /ggp out - Alias for `/ggp clock out`\n"
                "• /ggp lunch - Alias for `/ggp clock lunch`\n\n"
                "*Examples:*\n"
                "• /ggp clock in\n"
                "• /ggp clock in Starting work on Project X\n"
                "• /ggp clock in force Starting work on Project X\n"
                "• /ggp clock out Lunch\n"
                "• /ggp clock lunch\n"
                "• /ggp clock\n"
                "• /ggp clock today\n\n"
                "Run `/ggp help clock <subcommand>` for more details."
            )
            await respond(help_text)
            return
        
        # Examples topic
        if topic_lower == "examples":
            await respond(
                "*Command Examples*\n\n"
                "• /ggp holiday new 23/04/2026 Vacation\n"
                "• /ggp holiday new 23/04/2026 AM Doctor\n"
                "• /ggp holiday cancel 123\n"
                "• /ggp holiday cancel 150-155\n"
                "• /ggp directory search john\n"
                "• /ggp whois @john.doe\n"
                "• /ggp clock in\n"
                "• /ggp clock in force Working late\n"
                "• /ggp clock out Working late\n"
                "• /ggp clock lunch\n"
                "• /ggp clock today\n"
                "• /ggp in\n"
                "• /ggp in force\n"
                "• /ggp out\n"
                "• /ggp lunch"
            )
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
        
        lines.append("\n*Directory commands:*")
        for name, meta in DIRECTORY_SUBCOMMANDS.items():
            lines.append(_format_command_help(f"directory {name}", meta))
        
        lines.append("\n*Clock commands:*")
        for name, meta in CLOCK_SUBCOMMANDS.items():
            lines.append(_format_command_help(f"clock {name}", meta))
        
        lines.append("\n*Clock aliases:*")
        lines.append("• /ggp in - Alias for `/ggp clock in`")
        lines.append("• /ggp out - Alias for `/ggp clock out`")
        lines.append("• /ggp lunch - Alias for `/ggp clock lunch`")
        
        lines.append("\n_Run `/ggp help examples` for command examples._")
        
        # Only show admin hint to admin users
        is_admin = await _check_is_admin_silent(slack_user_id)
        if is_admin:
            lines.append("\n_Run `/ggp admin help` for admin commands._")
    else:
        lines.append(
            "\n_Run `/ggp connect <email> <password>` to link your account "
            "and access holiday, directory, clock, and profile commands._"
        )
        lines.append("\n*Available after connecting:*")
        for name, meta in AUTH_COMMANDS.items():
            lines.append(f"• /ggp {name} - {meta['description']}")
        for name, meta in HOLIDAY_SUBCOMMANDS.items():
            lines.append(f"• /ggp holiday {name} - {meta['description']}")
        for name, meta in DIRECTORY_SUBCOMMANDS.items():
            lines.append(f"• /ggp directory {name} - {meta['description']}")
        for name, meta in CLOCK_SUBCOMMANDS.items():
            lines.append(f"• /ggp clock {name} - {meta['description']}")
        lines.append("• /ggp in - Alias for `/ggp clock in`")
        lines.append("• /ggp out - Alias for `/ggp clock out`")
        lines.append("• /ggp lunch - Alias for `/ggp clock lunch`")
    
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
    logger.debug(f"_check_user_linked: user={slack_user_id}, has_token={has_token}, all_users={all_users}")
    return has_token


async def _handle_not_linked(respond: AsyncRespond, slack_user_id: str | None = None) -> None:
    """Send a standard response for users who haven't linked their account."""
    error_msg = (
        ":x: *Your Slack account is not linked to the intranet.*\n"
        "Please run `/ggp connect <intranet-email> <password>` to link your accounts."
    )
    await respond(error_msg)
    # Log this user-facing error so admins can diagnose issues
    user_info = f" (user: {slack_user_id})" if slack_user_id else ""
    logger.error(f"User attempted command but account not linked{user_info}")


async def _resolve_slack_id(identifier: str, client: AsyncWebClient) -> str | None:
    """Resolve a Slack user ID from mention, @username, or display name.

    Supports:
    • <@U12345678> mention format
    • @username (with email and users_list fallback)
    • bare display name (e.g. "john")

    Args:
        identifier: Raw user identifier from command args
        client: Slack WebClient for API calls

    Returns:
        Slack user ID if exactly one match, None for zero or ambiguous
    """
    # Method 1: Extract from mention format <@U12345678> or <@U12345678|Name>
    mention_match = re.search(r'<@([A-Z0-9]+)(?:\|[^>]*)?>', identifier)
    if mention_match:
        return mention_match.group(1)

    if not client or not identifier.strip():
        return None

    # Normalise: strip optional @ prefix
    username = identifier.lstrip('@').strip()
    if not username:
        return None

    # 2a: Email lookup
    email_variations = [
        f"{username}@ggpsystems.co.uk",
        f"{username.replace('.', ' ').replace(' ', '.')}@ggpsystems.co.uk",
    ]
    for email in email_variations:
        try:
            info = await client.users_lookupByEmail(email=email)
            if info and info.get('ok'):
                return info['user']['id']
        except SlackApiError as e:
            if e.response.get('error') == 'users_not_found':
                continue
            logger.debug(f"_resolve_slack_id: Slack API error during email lookup: {e}", exc_info=True)
        except Exception:
            logger.debug("_resolve_slack_id: unexpected error during email lookup", exc_info=True)

    # 2b: Fuzzy name search in workspace
    try:
        users_list = await client.users_list()
        if not (users_list and users_list.get('ok')):
            return None

        search_lower = username.lower()
        matches: list[str] = []

        for user in users_list.get('members', []):
            if user.get('is_bot') or user.get('deleted'):
                continue
            profile = user.get('profile', {})
            display_name = (profile.get('display_name', '') or '').lower()
            real_name = (profile.get('real_name', '') or '').lower()
            name = (profile.get('name', '') or '').lower()
            if (search_lower in display_name or
                search_lower in real_name or
                search_lower in name or
                display_name in search_lower or
                real_name in search_lower or
                name in search_lower):
                matches.append(user['id'])

        if len(matches) == 1:
            return matches[0]
    except SlackApiError as e:
        logger.debug(f"_resolve_slack_id: Slack API error during users_list: {e}", exc_info=True)
    except Exception:
        logger.debug("_resolve_slack_id: unexpected error during users_list", exc_info=True)

    return None


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
                f"• API Version: {health.version}\n"
                f"• Bot Version: v{IntranetClient.BOT_VERSION}\n"
                f"• Last checked: {health.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC') if health.timestamp else 'N/A'}"
            )
        except IntranetError as e:
            logger.error(f"Intranet connection failed in status command: {e}")
            await respond(f":x: Intranet connection failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in status command: {e}", exc_info=True)
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
            logger.error(f"Failed to fetch public holiday: {e}")
            await respond(f":x: Failed to fetch public holiday: {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching public holiday: {e}", exc_info=True)
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
                
                # IMPORTANT: Verify the token to get the actual scopes from API
                # The initial link response may have incomplete/incorrect scopes
                try:
                    async with await IntranetClient.for_user(slack_user_id) as verify_client:
                        # for_user() automatically verifies and updates stored scopes
                        actual_scopes = verify_client.scopes
                        logger.info(f"Token verified after connect for {slack_user_id}, actual scopes: {actual_scopes}")
                        # Use actual scopes for display
                        scopes = actual_scopes
                except Exception as e:
                    logger.warning(f"Could not verify token immediately after connect for {slack_user_id}: {e}")
                    # Continue with scopes from link response - they'll be corrected on first whoami use
                
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
                logger.error(f"Account linking failed for user: {message}")
                await respond(f":x: Linking failed: {message}")
                
        except IntranetInvalidCredentialsError as e:
            logger.error(f"Invalid intranet credentials for {slack_user_id} (email={intranet_email!r}): {e}")
            await respond(
                ":x: *Invalid intranet credentials*\n"
                "Please check your email and password.\n"
                "Note: Email is case-sensitive. If copying from a password manager, check for extra spaces."
            )
        except IntranetScopeError as e:
            logger.error(f"Bot lacks permission to link accounts: {e}")
            await respond(
                ":x: *Bot Configuration Error*\n"
                "The bot doesn't have permission to link accounts. "
                "Please contact an administrator."
            )
        except IntranetAuthError as e:
            logger.error(f"Bot authentication error during linking: {e}")
            await respond(
                ":x: *Bot Authentication Error*\n"
                "The bot is not properly configured. Please contact an administrator."
            )
        except IntranetError as e:
            logger.error(f"Failed to link account: {e}")
            await respond(f":x: Failed to link account: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during account linking: {e}", exc_info=True)
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
            # Use the new by-slack-id endpoint (API v1.0.0)
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
        logger.error(f"User {slack_user_id} attempted whoami but account not linked to intranet")
        await respond(
            f":x: *Your Slack account is not linked to the intranet.*\n"
            f"Please run `/ggp connect <intranet-email> <password>` to link your accounts."
        )
    except IntranetAuthError as e:
        logger.error(f"Authentication failed for user {slack_user_id} during whoami: {e}")
        await respond(
            f":x: *Authentication Failed*\n"
            f"Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        logger.error(f"Failed to fetch profile for user {slack_user_id}: {e}")
        await respond(f":x: Failed to fetch profile: {e}")
    except Exception as e:
        logger.error(f"Unexpected error fetching profile for user {slack_user_id}: {e}", exc_info=True)
        await respond(f":x: Unexpected error: {e}")


async def _handle_whois_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    args: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle the whois subcommand.
    
    Shows a user's profile and current status by Slack @mention.
    Usage: /ggp whois @username
    """
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond)
        return
    
    # Parse the @mention from args
    target_user = args.strip()
    
    logger.debug(f"whois: raw args = '{args}'")
    logger.debug(f"whois: target_user = '{target_user}'")
    
    if not target_user:
        await respond(
            ":warning: *Usage:* `/ggp whois <@user>`\n"
            "Example: `/ggp whois @john.doe`\n\n"
            "Tip: Type @ and select the user from Slack's autocomplete."
        )
        return
    
    target_slack_id = await _resolve_slack_id(target_user, client)
    
    if not target_slack_id:
        await respond(
            ":warning: *Could not identify user*\n"
            f"Received: `{target_user}`\n\n"
            "Please use @mention to specify the user.\n"
            "Example: `/ggp whois @john.doe`\n\n"
            "**Important:** Make sure to:\n"
            "1. Type @ and wait for Slack's autocomplete dropdown\n"
            "2. Select the user from the dropdown (don't just type the name)\n"
            "3. This ensures the user is properly linked\n\n"
            "Alternatively, you can search by name:\n"
            "• `/ggp directory search elliott` - then use the exact name from results"
        )
        return
    
    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            # Get the target user's profile by their Slack ID
            user = await intranet.get_user_by_slack_id(target_slack_id)
            
            # Also fetch their status
            status_data = await intranet.get_user_status(user.id)
            status = status_data.get('status', {})
            
            lines = [f"*{user.name}* :bust_in_silhouette:"]
            lines.append(f"• Email: {user.email}")
            if user.department:
                lines.append(f"• Department: {user.department}")
            if user.job_title:
                lines.append(f"• Job Title: {user.job_title}")
            if user.phone:
                lines.append(f"• Phone: {user.phone}")
            if user.location:
                lines.append(f"• Location: {user.location}")
            
            # Status information
            if status:
                is_working = status.get('is_working', False)
                clocked_in = status.get('clocked_in', False)
                current_absence = status.get('current_absence')
                
                status_parts = []
                if current_absence:
                    status_parts.append(f"📅 {current_absence}")
                elif is_working:
                    status_parts.append("💼 Working")
                else:
                    status_parts.append("⭕ Not working")
                
                if clocked_in:
                    status_parts.append("⏰ Clocked in")
                
                lines.append(f"• Status: {' | '.join(status_parts)}")
            
            slack_status = ":white_check_mark: Linked" if user.slack_linked else ":x: Not linked"
            lines.append(f"• Slack: {slack_status}")
            
            await respond("\n".join(lines))
            
    except IntranetSlackNotLinkedError:
        logger.error(f"Target Slack user not linked to intranet during whois lookup by {slack_user_id}")
        await respond(
            f":x: *That Slack user is not linked to the intranet.*\n"
            f"The user may need to run `/ggp connect` to link their account."
        )
    except IntranetNotFoundError:
        logger.error(f"User not found during whois lookup by {slack_user_id}")
        await respond(
            f":x: *User not found*\n"
            f"Could not find a user with that Slack ID in the intranet."
        )
    except IntranetAuthError as e:
        logger.error(f"Authentication failed for user {slack_user_id} during whois: {e}")
        await respond(
            f":x: *Authentication Failed*\n"
            f"Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        logger.error(f"Failed to fetch user info during whois by {slack_user_id}: {e}")
        await respond(f":x: Failed to fetch user info: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during whois by {slack_user_id}: {e}", exc_info=True)
        await respond(f":x: Unexpected error: {e}")


async def _handle_holiday_balance_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle the holiday balance subcommand (was /holiday-entitlement)."""
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond, slack_user_id)
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
    except IntranetScopeError as e:
        logger.error(f"User {slack_user_id} lacks permission to view holiday entitlement: {e}")
        await respond(
            ":x: *Permission Denied*\n"
            "Your account doesn't have permission to view holiday entitlement. "
            "Please contact an administrator."
        )
    except IntranetAuthError as e:
        logger.error(f"Authentication failed for user {slack_user_id} viewing holiday entitlement: {e}")
        await respond(
            ":x: *Authentication Failed*\n"
            "Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        logger.error(f"Failed to fetch holiday entitlement for user {slack_user_id}: {e}")
        await respond(f":x: Failed to fetch entitlement: {e}")
    except Exception as e:
        logger.error(f"Unexpected error fetching holiday entitlement for user {slack_user_id}: {e}", exc_info=True)
        await respond(f":x: Unexpected error: {e}")


async def _handle_holiday_list_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle the holiday list subcommand (was /my-holidays)."""
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond, slack_user_id)
        return
    
    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            holidays = await intranet.get_my_holidays()
            
            if not holidays:
                await respond("No holiday requests found. Time to book some time off! :palm_tree:")
                return
            
            lines = ["*Your Holiday Requests* :calendar:"]
            
            for h in holidays:
                from datetime import date
                
                # Determine holiday timing relative to today
                end_date = date.fromisoformat(h.end_date) if isinstance(h.end_date, str) else h.end_date
                today = date.today()
                is_future_or_current = end_date >= today  # Future or currently being taken
                
                # Select emoji: pending -> hourglass, approved+future/current -> palm_tree, approved+past -> checkmark
                if not h.approved:
                    status_emoji = ":hourglass_flowing_sand:"
                elif is_future_or_current:
                    status_emoji = ":palm_tree:"
                else:
                    status_emoji = ":white_check_mark:"
                
                # Format display based on holiday type
                date_display = _format_holiday_dates(h)
                
                lines.append(
                    f"• {status_emoji} #{h.id}: {date_display}"
                    f" - {h.working_days} day(s) - {h.status}"
                )
                if h.note:
                    lines.append(f"  _Note: {h.note}_")
            
            await respond("\n".join(lines))
            
    except IntranetScopeError as e:
        logger.error(f"User {slack_user_id} lacks permission to view holidays: {e}")
        await respond(
            ":x: *Permission Denied*\n"
            "Your account doesn't have permission to view holidays. "
            "Please contact an administrator."
        )
    except IntranetAuthError as e:
        logger.error(f"Authentication failed for user {slack_user_id} viewing holidays: {e}")
        await respond(
            ":x: *Authentication Failed*\n"
            "Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        logger.error(f"Failed to fetch holidays for user {slack_user_id}: {e}")
        await respond(f":x: Failed to fetch holidays: {e}")
    except Exception as e:
        logger.error(f"Unexpected error fetching holidays for user {slack_user_id}: {e}", exc_info=True)
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
        await _handle_not_linked(respond, slack_user_id)
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
        logger.warning(f"User {slack_user_id} provided invalid date format: {e}")
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
            logger.debug(f"User {slack_user_id} scopes: {intranet.scopes}")
            logger.debug(f"Has bot:holiday:write? {intranet.has_scope('bot:holiday:write')}")
            
            # Check if user has write permission
            if not intranet.has_scope("bot:holiday:write"):
                logger.error(
                    f"User {slack_user_id} denied holiday write permission. "
                    f"Has scopes: {intranet.scopes}, missing: bot:holiday:write"
                )
                await respond(
                    ":x: *Permission Denied*\n"
                    f"Your token has these scopes: {', '.join(intranet.scopes) or 'none'}\n"
                    "Missing required scope: bot:holiday:write\n"
                    "Please contact an administrator to update your permissions."
                )
                return
            
            logger.debug(f"Requesting holiday: {start_date} to {end_date}, start_half={start_half_day}, end_half={end_half_day}")
            
            result = await intranet.request_holiday(
                start=start_date,
                end=end_date,
                start_half_day=start_half_day,
                end_half_day=end_half_day,
                note=note
            )
            
            logger.debug(f"API result: id={result.id}, working_days={result.working_days}, start={result.start_date}, end={result.end_date}")
            
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
        logger.error(
            f"User {slack_user_id} has insufficient holiday days. "
            f"Remaining: {remaining}, Shortfall: {shortfall}"
        )
        await respond(
            f":x: *Insufficient Holiday Days*\n"
            f"You don't have enough days remaining.\n"
            f"• Remaining: {remaining} days\n"
            f"• Shortfall: {shortfall} days"
        )
    except IntranetScopeError as e:
        logger.error(f"User {slack_user_id} lacks permission to request holidays: {e}")
        await respond(
            ":x: *Permission Denied*\n"
            "Your account doesn't have permission to request holidays. "
            "Please contact an administrator."
        )
    except IntranetAuthError as e:
        logger.error(f"Authentication failed for user {slack_user_id} requesting holiday: {e}")
        await respond(
            ":x: *Authentication Failed*\n"
            "Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        logger.error(f"Failed to request holiday for user {slack_user_id}: {e}")
        await respond(f":x: Failed to request holiday: {e}")
    except Exception as e:
        logger.error(f"Unexpected error requesting holiday for user {slack_user_id}: {e}", exc_info=True)
        await respond(f":x: Unexpected error: {e}")


async def _handle_holiday_cancel_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    args: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle the holiday cancel subcommand (was /cancel-holiday).
    
    Supports single ID, multiple IDs, or ranges:
    - /ggp holiday cancel 123 (single)
    - /ggp holiday cancel 123, 125, 127 (multiple)
    - /ggp holiday cancel 150-155 (range)
    - /ggp holiday cancel 150, 152-155, 158 (mixed)
    """
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond, slack_user_id)
        return
    
    # Parse command arguments
    text = args.strip()
    
    if not text:
        logger.warning(f"User {slack_user_id} attempted holiday cancel without providing IDs")
        await respond(
            ":warning: *Usage:* `/ggp holiday cancel <ids>`\n"
            "*Single:* `/ggp holiday cancel 123`\n"
            "*Multiple:* `/ggp holiday cancel 123, 125, 127`\n"
            "*Range:* `/ggp holiday cancel 150-155`\n"
            "*Mixed:* `/ggp holiday cancel 150, 152-155, 158`\n\n"
            "Use `/ggp holiday list` to see your holiday IDs."
        )
        return
    
    # Validate the ID format (allow: numbers, commas, hyphens, spaces)
    import re
    if not re.match(r'^[\d\s,\-]+$', text):
        logger.warning(f"User {slack_user_id} provided invalid holiday ID format: {text}")
        await respond(
            ":warning: *Invalid holiday ID format*\n"
            "Please provide valid holiday IDs.\n"
            "Examples:\n"
            "• `/ggp holiday cancel 123`\n"
            "• `/ggp holiday cancel 123, 125, 127`\n"
            "• `/ggp holiday cancel 150-155`"
        )
        return
    
    # Determine if this is a batch cancellation (contains comma or hyphen)
    is_batch = ',' in text or '-' in text
    
    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            # Check if user has write permission
            if not intranet.has_scope("bot:holiday:write"):
                logger.error(
                    f"User {slack_user_id} denied permission to cancel holidays. "
                    f"Has scopes: {intranet.scopes}"
                )
                await respond(
                    ":x: *Permission Denied*\n"
                    "Your account doesn't have permission to cancel holidays. "
                    "Please contact an administrator."
                )
                return
            
            if is_batch:
                # Use batch cancellation endpoint
                result = await intranet.cancel_holidays_batch(text)
                
                logger.debug(f"cancel_holidays_batch result: {result}")
                
                # Build response for batch operation
                # API returns: {'cancelled': [{'id': 160, 'working_days_returned': 0.5}, ...], 'failed': [], 'total_working_days_returned': 1}
                cancelled = result.get('cancelled', [])
                failed = result.get('failed', [])
                total_days = result.get('total_working_days_returned', 0)
                
                lines = [f":white_check_mark: *Holidays Cancelled*"]
                lines.append(f"• Cancelled: {len(cancelled)} request(s)")
                
                if cancelled:
                    # cancelled is now a list of dicts with 'id' and 'working_days_returned'
                    cancelled_ids = [str(c.get('id', '?')) for c in cancelled]
                    id_list = ', '.join(cancelled_ids[:10])
                    if len(cancelled_ids) > 10:
                        id_list += f" and {len(cancelled_ids) - 10} more"
                    lines.append(f"• IDs: {id_list}")
                
                if total_days:
                    lines.append(f"• Total days returned: {total_days}")
                
                if failed:
                    lines.append(f"\n:warning: *Failed to cancel {len(failed)} request(s):*")
                    for fail in failed[:5]:
                        fail_id = fail.get('id', '?') if isinstance(fail, dict) else fail
                        fail_reason = fail.get('reason', 'Unknown error') if isinstance(fail, dict) else 'Unknown error'
                        lines.append(f"• #{fail_id}: {fail_reason}")
                    if len(failed) > 5:
                        lines.append(f"• ... and {len(failed) - 5} more")
                
                await respond('\n'.join(lines))
            else:
                # Single cancellation - use legacy endpoint
                try:
                    holiday_id = int(text.split()[0])
                except ValueError:
                    logger.warning(f"User {slack_user_id} provided invalid holiday ID: {text}")
                    await respond(
                        ":warning: *Invalid holiday ID*\n"
                        "Please provide a valid number.\n"
                        "Example: `/ggp holiday cancel 123`"
                    )
                    return
                
                result = await intranet.cancel_holiday(holiday_id)
                
                logger.debug(f"cancel_holiday result: {result}")
                
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
            
    except IntranetNotFoundError as e:
        logger.error(f"User {slack_user_id} attempted to cancel non-existent holiday: {e}")
        await respond(
            f":x: *Holiday not found*\n"
            f"Could not find one or more holiday requests.\n"
            "Use `/ggp holiday list` to see your current holiday requests."
        )
    except IntranetScopeError as e:
        logger.error(f"User {slack_user_id} lacks permission to cancel holidays: {e}")
        await respond(
            ":x: *Permission Denied*\n"
            "Your account doesn't have permission to cancel holidays. "
            "Please contact an administrator."
        )
    except IntranetAuthError as e:
        logger.error(f"Authentication failed for user {slack_user_id} canceling holiday: {e}")
        await respond(
            ":x: *Authentication Failed*\n"
            "Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        logger.error(f"Failed to cancel holiday for user {slack_user_id}: {e}")
        await respond(f":x: Failed to cancel holiday: {e}")
    except Exception as e:
        logger.error(f"Unexpected error canceling holiday for user {slack_user_id}: {e}", exc_info=True)
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
# Directory Subcommand Handlers
# ============================================================================

async def _handle_directory_search_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    args: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle the directory search subcommand.
    
    Searches for users by name, email, or department.
    Usage: /ggp directory search <query>
    """
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond, slack_user_id)
        return
    
    query = args.strip()
    
    if not query:
        logger.warning(f"User {slack_user_id} attempted directory search without query")
        await respond(
            ":warning: *Usage:* `/ggp directory search <query>`\n"
            "Examples:\n"
            "• `/ggp directory search john` (search by name)\n"
            "• `/ggp directory search engineering` (search by department)\n"
            "• `/ggp directory search john@company.com` (search by email)"
        )
        return
    
    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            users = await intranet.search_users(query)
            
            if not users:
                await respond(f"No users found matching '*{query}*'.")
                return
            
            lines = [f"*Directory Search Results* :mag_right: ({len(users)} found)", ""]
            
            for user in users[:20]:  # Limit to 20 results
                lines.append(f"*{user.name}*")
                if user.email:
                    lines.append(f"  📧 {user.email}")
                if user.department:
                    lines.append(f"  🏢 {user.department}")
                if user.title:
                    lines.append(f"  💼 {user.title}")
                lines.append("")  # Blank line between users
            
            if len(users) > 20:
                lines.append(f"_... and {len(users) - 20} more results. Refine your search._")
            
            await respond("\n".join(lines))
            
    except IntranetAuthError as e:
        logger.error(f"Authentication failed for user {slack_user_id} during directory search: {e}")
        await respond(
            ":x: *Authentication Failed*\n"
            "Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        logger.error(f"Failed to search directory for user {slack_user_id}: {e}")
        await respond(f":x: Failed to search directory: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during directory search for user {slack_user_id}: {e}", exc_info=True)
        await respond(f":x: Unexpected error: {e}")


async def _handle_directory_list_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle the directory list subcommand.
    
    Shows all users in the company directory.
    Usage: /ggp directory list
    """
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond, slack_user_id)
        return
    
    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            users = await intranet.get_directory()
            
            if not users:
                await respond("No users found in directory.")
                return
            
            lines = [f"*Company Directory* :building_construction: ({len(users)} users)", ""]
            
            # Show first 30 users with name and department
            for user in users[:30]:
                dept = f" - {user.department}" if user.department else ""
                lines.append(f"• {user.name}{dept}")
            
            if len(users) > 30:
                lines.append(f"\n_... and {len(users) - 30} more users. Use `/ggp directory search` to find specific users._")
            
            lines.append(f"\n_Tip: Use `/ggp whois @user` to see detailed profile and status._")
            
            await respond("\n".join(lines))
            
    except IntranetAuthError as e:
        logger.error(f"Authentication failed for user {slack_user_id} fetching directory: {e}")
        await respond(
            ":x: *Authentication Failed*\n"
            "Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        logger.error(f"Failed to fetch directory for user {slack_user_id}: {e}")
        await respond(f":x: Failed to fetch directory: {e}")
    except Exception as e:
        logger.error(f"Unexpected error fetching directory for user {slack_user_id}: {e}", exc_info=True)
        await respond(f":x: Unexpected error: {e}")


# ============================================================================
# Directory Subcommand Dispatcher
# ============================================================================

async def _handle_directory_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    args: str,
    client: AsyncWebClient | None = None
) -> None:
    """Dispatch directory subcommands to their handlers.
    
    Args:
        respond: Slack respond function
        slack_user_id: The Slack user ID
        args: Subcommand and arguments (e.g., "search john")
        client: Optional Slack WebClient
    """
    # Parse the directory subcommand
    parts = args.strip().split(None, 1)
    subcommand = parts[0].lower() if parts else ""
    sub_args = parts[1] if len(parts) > 1 else ""
    
    if subcommand == "search":
        await _handle_directory_search_subcommand(respond, slack_user_id, sub_args, client)
    elif subcommand == "list":
        await _handle_directory_list_subcommand(respond, slack_user_id, client)
    else:
        # Unknown directory subcommand - suggest valid ones
        valid_subcommands = list(DIRECTORY_SUBCOMMANDS.keys())
        suggestion = _suggest_command(subcommand, [f"directory {cmd}" for cmd in valid_subcommands])
        
        if suggestion:
            suggestion_clean = suggestion.replace("directory ", "")
            await respond(
                f":warning: Unknown directory subcommand '{subcommand}'.\n"
                f"Did you mean: `directory {suggestion_clean}`?\n\n"
                f"*Available directory commands:*\n"
                f"• /ggp directory search <query> - Search by name/email/dept\n"
                f"• /ggp directory list - Show all users\n\n"
                f"Run `/ggp help directory` for more details."
            )
        else:
            await respond(
                f":warning: Unknown directory subcommand '{subcommand}'.\n\n"
                f"*Available directory commands:*\n"
                f"• /ggp directory search <query> - Search by name/email/dept\n"
                f"• /ggp directory list - Show all users\n\n"
                f"Run `/ggp help directory` for more details."
            )


# ============================================================================
# Clock Subcommand Handlers
# ============================================================================

async def _handle_clock_in_out_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    event_type: str,
    args: str,
    client: AsyncWebClient,
) -> None:
    """Handle clock in/out with #Attendance posting.
    
    Args:
        respond: Slack respond function
        slack_user_id: The Slack user ID
        event_type: "in" or "out"
        args: Optional note
        client: Slack WebClient for #Attendance posting
    """
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond, slack_user_id)
        return
    
    # Check for timeclock:write scope
    from ggp_bot.intranet.token_storage import token_storage
    user_token = token_storage.get_token(slack_user_id)
    if user_token and not user_token.has_scope("bot:timeclock:write"):
        logger.error(
            f"User {slack_user_id} denied time clock write permission. "
            f"Has scopes: {user_token.scopes}, missing: bot:timeclock:write"
        )
        await respond(
            ":x: *Permission Denied*\n"
            "Your token doesn't have time clock write permission.\n"
            "Please run `/ggp connect` again to refresh your permissions."
        )
        return
    
    note = args.strip() if args else None
    force = False

    # For clock-in: check if today is a public holiday unless forced
    if event_type == "in":
        # Parse force flag from first token
        if note:
            parts = note.split(None, 1)
            if parts[0].lower() == "force":
                force = True
                note = parts[1] if len(parts) > 1 else None

        if not force:
            try:
                async with IntranetClient.with_bot_token() as holiday_client:
                    holiday = await holiday_client.get_next_public_holiday()
                    if holiday.is_today:
                        await respond(
                            f":calendar: *Public Holiday Today*\n"
                            f"Today is {holiday.name}.\n\n"
                            f"If you really want to work, use `/ggp clock in force` or `/ggp in force`."
                        )
                        return
            except Exception as e:
                logger.warning(f"Failed to check public holiday for clock-in guard: {e}")
                # Fail open: allow clock-in if holiday API fails

    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            # Get user profile for name
            user = await intranet.get_user_by_slack_id(slack_user_id)
            
            # Perform clock event
            result = await intranet.clock_event(event_type, note)
            event_id = result.get('id', 0)
            
            logger.debug(f"clock_event result: {result}")
            
            # Check if we should notify #Attendance (idempotent)
            from ggp_bot.intranet.state_tracking import timeclock_tracker
            should_post = timeclock_tracker.should_notify(slack_user_id, event_type)
            
            if should_post:
                # Post to #Attendance channel
                from ggp_bot.slack.formatters import format_attendance_message
                # Get timestamp from result for clock emoji (API uses 'event' field)
                event_timestamp = result.get('event')
                attendance_msg = format_attendance_message(
                    user.name, event_type, note, timestamp=event_timestamp
                )
                
                try:
                    await client.chat_postMessage(
                        channel="#Attendance",
                        text=attendance_msg
                    )
                    logger.debug(f"Posted to #Attendance: {attendance_msg}")
                except Exception as e:
                    # Log error but don't fail the command
                    logger.error(f"Failed to post to #Attendance for user {slack_user_id}: {e}")
                
                # Update tracking state
                timeclock_tracker.update_state(slack_user_id, event_type, event_id)
            
            # If clocking in, cancel any active lunch timer (early return)
            if event_type == "in":
                from ggp_bot.slack.lunch_timer import lunch_timer_manager
                if lunch_timer_manager.has_active_timer(slack_user_id):
                    lunch_timer_manager.cancel_timer(slack_user_id)
                    logger.debug(f"Cancelled lunch timer for {slack_user_id} (early return)")
            
            # Reply to user
            from ggp_bot.slack.formatters import format_clock_confirmation
            confirmation = format_clock_confirmation(event_type, note)
            await respond(confirmation)
            
    except IntranetAuthError as e:
        logger.error(f"Authentication failed for user {slack_user_id} during clock {event_type}: {e}")
        await respond(
            ":x: *Authentication Failed*\n"
            "Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        logger.error(f"Failed to clock {event_type} for user {slack_user_id}: {e}")
        await respond(f":x: Failed to clock {event_type}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during clock {event_type} for user {slack_user_id}: {e}", exc_info=True)
        await respond(f":x: Unexpected error: {e}")


async def _handle_clock_status_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle clock status command (shows current clocked in/out state)."""
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond, slack_user_id)
        return
    
    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            status_data = await intranet.get_timeclock_status()
            
            logger.debug(f"timeclock_status: {status_data}")
            
            # Convert to model for formatting
            # The model aliases handle field name mapping:
            # API 'clocked_in' -> model 'is_clocked_in'
            # API 'event' -> model 'time'
            # API 'duration_minutes' -> model 'current_duration'
            from ggp_bot.intranet.models import TimeClockStatus
            status = TimeClockStatus.model_validate(status_data)
            
            from ggp_bot.slack.formatters import format_timeclock_status_block
            blocks = format_timeclock_status_block(status)
            await respond(blocks=blocks)
            
    except IntranetAuthError:
        await respond(
            ":x: *Authentication Failed*\n"
            "Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        logger.error(f"Failed to get clock status for user {slack_user_id}: {e}")
        await respond(f":x: Failed to get clock status: {e}")
    except Exception as e:
        logger.error(f"Unexpected error getting clock status for user {slack_user_id}: {e}", exc_info=True)
        await respond(f":x: Unexpected error: {e}")


async def _handle_clock_today_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle clock today command (shows today's time card)."""
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond, slack_user_id)
        return
    
    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            events_data = await intranet.get_timeclock_history("today")
            
            logger.debug(f"timeclock_today: {len(events_data)} events")
            
            # Convert to models
            from ggp_bot.intranet.models import TimeClockEvent
            events = [TimeClockEvent(**e) for e in events_data]
            
            from ggp_bot.slack.formatters import format_timecard_block
            blocks = format_timecard_block("Time Card - Today", events)
            await respond(blocks=blocks)
            
    except IntranetAuthError as e:
        logger.error(f"Authentication failed for user {slack_user_id} getting today's time card: {e}")
        await respond(
            ":x: *Authentication Failed*\n"
            "Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        logger.error(f"Failed to get today's time card for user {slack_user_id}: {e}")
        await respond(f":x: Failed to get today's time card: {e}")
    except Exception as e:
        logger.error(f"Unexpected error getting today's time card for user {slack_user_id}: {e}", exc_info=True)
        await respond(f":x: Unexpected error: {e}")


async def _handle_clock_week_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle clock week command (shows this week's time card)."""
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond, slack_user_id)
        return
    
    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            events_data = await intranet.get_timeclock_history("week")
            
            logger.debug(f"timeclock_week: {len(events_data)} events")
            
            # Convert to models
            from ggp_bot.intranet.models import TimeClockEvent
            events = [TimeClockEvent(**e) for e in events_data]
            
            from ggp_bot.slack.formatters import format_timecard_block
            blocks = format_timecard_block("Time Card - This Week", events)
            await respond(blocks=blocks)
            
    except IntranetAuthError as e:
        logger.error(f"Authentication failed for user {slack_user_id} getting week's time card: {e}")
        await respond(
            ":x: *Authentication Failed*\n"
            "Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        logger.error(f"Failed to get week's time card for user {slack_user_id}: {e}")
        await respond(f":x: Failed to get week's time card: {e}")
    except Exception as e:
        logger.error(f"Unexpected error getting week's time card for user {slack_user_id}: {e}", exc_info=True)
        await respond(f":x: Unexpected error: {e}")


async def _handle_clock_lunch_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    client: AsyncWebClient,
) -> None:
    """Handle clock lunch command - starts 1-hour timer with reminders.
    
    Idempotent - silently swallows duplicate calls.
    """
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond, slack_user_id)
        return
    
    # Check for timeclock:write scope
    from ggp_bot.intranet.token_storage import token_storage
    user_token = token_storage.get_token(slack_user_id)
    if user_token and not user_token.has_scope("bot:timeclock:write"):
        logger.error(
            f"User {slack_user_id} denied time clock write permission for lunch timer. "
            f"Has scopes: {user_token.scopes}"
        )
        await respond(
            ":x: *Permission Denied*\n"
            "Your token doesn't have time clock write permission.\n"
            "Please run `/ggp connect` again to refresh your permissions."
        )
        return
    
    # Check if timer already exists (idempotent)
    from ggp_bot.slack.lunch_timer import lunch_timer_manager
    if lunch_timer_manager.has_active_timer(slack_user_id):
        # Silently swallow - timer already running
        return
    
    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            # Get user profile for name
            user = await intranet.get_user_by_slack_id(slack_user_id)
            
            # Clock out via API
            result = await intranet.clock_event("out", "Lunch break")
            
            # Update local state tracker for idempotent #Attendance posting
            from ggp_bot.intranet.state_tracking import timeclock_tracker
            timeclock_tracker.update_state(slack_user_id, "out", result.get('id', 0))
            
            # Start lunch timer
            # Get the DM channel ID for sending reminders
            dm_response = await client.conversations_open(users=[slack_user_id])
            dm_channel_id = dm_response["channel"]["id"]
            
            timer_started = lunch_timer_manager.start_timer(slack_user_id, dm_channel_id)
            
            if not timer_started:
                # Shouldn't happen due to check above, but handle gracefully
                return
            
            # Send confirmation via respond (same as other clock commands)
            await respond(":pizza: You started *lunch*")
            
            # Post to #Attendance
            try:
                from ggp_bot.slack.formatters import format_attendance_message
                event_timestamp = result.get('event')
                attendance_msg = format_attendance_message(
                    user.name, "lunch", timestamp=event_timestamp
                )
                await client.chat_postMessage(
                    channel="#Attendance",
                    text=attendance_msg
                )
            except Exception as e:
                # Log but don't fail
                logger.error(f"Failed to post lunch to #Attendance for user {slack_user_id}: {e}")
            
    except IntranetAuthError as e:
        logger.error(f"Authentication failed for user {slack_user_id} starting lunch timer: {e}")
        await respond(
            ":x: *Authentication Failed*\n"
            "Your session may have expired. Please run `/ggp connect` again to re-link your account."
        )
    except IntranetError as e:
        logger.error(f"Failed to start lunch timer for user {slack_user_id}: {e}")
        await respond(f":x: Failed to start lunch timer: {e}")
    except Exception as e:
        logger.error(f"Unexpected error starting lunch timer for user {slack_user_id}: {e}", exc_info=True)
        await respond(f":x: Unexpected error: {e}")


async def _handle_clock_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    args: str,
    client: AsyncWebClient,
) -> None:
    """Dispatch clock subcommands to their handlers.
    
    Args:
        respond: Slack respond function
        slack_user_id: The Slack user ID
        args: Subcommand and arguments (e.g., "in Working late")
        client: Slack WebClient for #Attendance posting
    """
    # Parse the clock subcommand
    parts = args.strip().split(None, 1)
    subcommand = parts[0].lower() if parts else ""
    sub_args = parts[1] if len(parts) > 1 else ""
    
    if subcommand == "in":
        await _handle_clock_in_out_subcommand(respond, slack_user_id, "in", sub_args, client)
    elif subcommand == "out":
        await _handle_clock_in_out_subcommand(respond, slack_user_id, "out", sub_args, client)
    elif subcommand == "today":
        await _handle_clock_today_subcommand(respond, slack_user_id, client)
    elif subcommand == "week":
        await _handle_clock_week_subcommand(respond, slack_user_id, client)
    elif subcommand == "lunch":
        await _handle_clock_lunch_subcommand(respond, slack_user_id, client)
    elif subcommand == "":
        # No subcommand - show current status
        await _handle_clock_status_subcommand(respond, slack_user_id, client)
    else:
        # Unknown clock subcommand - suggest valid ones
        valid_subcommands = list(CLOCK_SUBCOMMANDS.keys())
        suggestion = _suggest_command(subcommand, [f"clock {cmd}" for cmd in valid_subcommands])
        
        if suggestion:
            suggestion_clean = suggestion.replace("clock ", "")
            await respond(
                f":warning: Unknown clock command '{subcommand}'.\n"
                f"Did you mean: `clock {suggestion_clean}`?\n\n"
                f"*Available clock commands:*\n"
                f"• /ggp clock in [note] - Clock in\n"
                f"• /ggp clock out [note] - Clock out\n"
                f"• /ggp clock lunch - Start 1-hour lunch timer\n"
                f"• /ggp clock - Show current status\n"
                f"• /ggp clock today - Today's time card\n"
                f"• /ggp clock week - This week's time card\n\n"
                f"Run `/ggp help clock` for more details."
            )
        else:
            await respond(
                f":warning: Unknown clock command '{subcommand}'.\n\n"
                f"*Available clock commands:*\n"
                f"• /ggp clock in [note] - Clock in\n"
                f"• /ggp clock out [note] - Clock out\n"
                f"• /ggp clock lunch - Start 1-hour lunch timer\n"
                f"• /ggp clock - Show current status\n"
                f"• /ggp clock today - Today's time card\n"
                f"• /ggp clock week - This week's time card\n\n"
                f"Run `/ggp help clock` for more details."
            )


# ============================================================================
# Admin Subcommand Handlers
# ============================================================================

async def _require_admin(
    respond: AsyncRespond,
    slack_user_id: str
) -> bool:
    """Check if the user has admin role.
    
    Fetches the user's profile from the API and checks if role == "admin".
    
    Args:
        respond: Slack respond function
        slack_user_id: The Slack user ID to check
        
    Returns:
        True if user is admin, False otherwise
    """
    if not _check_user_linked(slack_user_id):
        await _handle_not_linked(respond, slack_user_id)
        return False
    
    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            user = await intranet.get_user_by_slack_id(slack_user_id)
            
            if user.role != "admin":
                logger.warning(
                    f"ADMIN: User {slack_user_id} attempted admin command "
                    f"but has role='{user.role}'"
                )
                await respond(
                    ":x: *Admin Access Denied*\n"
                    "This command requires admin privileges. "
                    "Your role: " + (user.role or "user")
                )
                return False
            
            return True
            
    except Exception as e:
        logger.error(f"ADMIN: Failed to check admin status for {slack_user_id}: {e}")
        await respond(
            ":x: *Failed to verify admin status*\n"
            "Could not retrieve your user profile. Please try again."
        )
        return False


async def _check_is_admin_silent(slack_user_id: str) -> bool:
    """Silently check if a user has admin role.
    
    This is used for conditional help display - it checks admin status
    without sending any responses to the user.
    
    Args:
        slack_user_id: The Slack user ID to check
        
    Returns:
        True if user is admin, False otherwise (including on error)
    """
    if not token_storage.has_token(slack_user_id):
        return False
    
    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            user = await intranet.get_user_by_slack_id(slack_user_id)
            return user.role == "admin"
    except Exception:
        # On any error (API failure, etc.), default to False (not admin)
        return False


# ============================================================================
# Admin Holiday Helpers
# ============================================================================

import re as _re

def _parse_ids_and_text(args: str) -> tuple[str, str | None]:
    """Split 'ids [optional text]' where ids may contain digits, commas, hyphens, spaces.
    
    Args:
        args: Raw command text after subcommand (e.g., "123, 125, 127 Approved for project")
    
    Returns:
        (ids, text) — ids is stripped, text is stripped or None
    """
    text = args.strip()
    if not text:
        return "", None
    # Match longest leading sequence ending in a digit, then whitespace, then the rest
    m = _re.match(r'^([\d,\-\s]*\d)\s+(\S.*)$', text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # Entire string is just IDs (no trailing text)
    return text, None


async def _require_admin_holiday_scope(
    respond: AsyncRespond,
    slack_user_id: str
) -> bool:
    """Check if the user has bot:admin:holiday scope.
    
    Args:
        respond: Slack respond function
        slack_user_id: The Slack user ID to check
    
    Returns:
        True if user has the scope, False otherwise (response already sent)
    """
    user_token = token_storage.get_token(slack_user_id)
    if not user_token or not user_token.has_scope("bot:admin:holiday"):
        logger.warning(
            f"ADMIN: User {slack_user_id} attempted admin holiday command "
            f"but lacks bot:admin:holiday scope."
        )
        await respond(
            ":x: *Permission Denied*\n"
            "Missing required scope: `bot:admin:holiday`\n"
            "Please run `/ggp connect` again to refresh your permissions."
        )
        return False
    return True


async def _handle_admin_cache_clear_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    args: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle admin cache clear - remove specific user from token cache."""
    if not await _require_admin(respond, slack_user_id):
        return
    
    target_user = args.strip()
    
    if not target_user:
        await respond(
            ":warning: *Usage:* `/ggp admin cache clear <@user>`\n"
            "Example: `/ggp admin cache clear @john.doe`"
        )
        return
    
    target_slack_id = await _resolve_slack_id(target_user, client)

    if not target_slack_id:
        await respond(
            ":x: *Could not identify user*\n"
            f"Received: `{target_user}`\n\n"
            "Please use @mention to specify the user.\n"
            "Example: `/ggp admin cache clear @john.doe`"
        )
        return

    try:
        removed = token_storage.remove_token(target_slack_id, reason="admin_manual_clear")
        
        if removed:
            logger.info(f"ADMIN: User {slack_user_id} cleared token cache for user {target_slack_id}")
            await respond(
                f":white_check_mark: *Token cache cleared*\n"
                f"Removed token for user <@{target_slack_id}> from cache."
            )
        else:
            await respond(
                f":warning: *No token found*\n"
                f"User <@{target_slack_id}> was not in the token cache."
            )
            
    except Exception as e:
        logger.error(f"ADMIN: Failed to clear token cache for {target_slack_id}: {e}")
        await respond(f":x: Failed to clear token cache: {e}")


async def _handle_admin_cache_status_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle admin cache status - show token cache statistics."""
    if not await _require_admin(respond, slack_user_id):
        return
    
    try:
        stats = token_storage.get_stats()
        
        lines = ["*Token Cache Status* :key:"]
        lines.append(f"• Host: {socket.gethostname()}")
        lines.append(f"• Total tokens: {stats.get('total_tokens', 0)}")
        lines.append(f"• Database: {stats.get('db_path', 'N/A')}")
        lines.append(f"• Encrypted: {'Yes' if stats.get('encrypted') else 'No'}")
        
        await respond("\n".join(lines))
        
    except Exception as e:
        logger.error(f"ADMIN: Failed to get cache status: {e}")
        await respond(f":x: Failed to get cache status: {e}")


async def _handle_admin_gc_status_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle admin gc status - show GC schedule and last run."""
    if not await _require_admin(respond, slack_user_id):
        return
    
    try:
        status = cleanup_scheduler.get_status()
        
        running = "Yes" if status.get('running') else "No"
        last_run = status.get('last_run', 'Never')
        last_status = status.get('last_status', 'N/A')
        next_run = status.get('next_run', 'Unknown')
        next_in = status.get('next_run_in_seconds', 0)
        
        lines = ["*Garbage Collection Status* :broom:"]
        lines.append(f"• Running: {running}")
        lines.append(f"• Last run: {last_run}")
        lines.append(f"• Last status: {last_status}")
        lines.append(f"• Next run: {next_run}")
        
        if next_in > 0:
            hours = next_in / 3600
            lines.append(f"• Next run in: {hours:.1f} hours")
        
        await respond("\n".join(lines))
        
    except Exception as e:
        logger.error(f"ADMIN: Failed to get GC status: {e}")
        await respond(f":x: Failed to get GC status: {e}")


async def _handle_admin_gc_run_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle admin gc run - manually trigger garbage collection."""
    if not await _require_admin(respond, slack_user_id):
        return
    
    logger.info(f"ADMIN: User {slack_user_id} triggered manual GC run")
    
    # Respond immediately to avoid timeout, then run the cleanup
    await respond("🧹 *Running garbage collection...* (this may take a moment)")
    
    try:
        results = await cleanup_scheduler.run_now()
        
        lines = ["*Garbage Collection Complete* :white_check_mark:"]
        lines.append(f"• Lunch timers removed: {results.get('lunch_timers_removed', 0)}")
        lines.append(f"• Timeclock records removed: {results.get('timeclock_records_removed', 0)}")
        
        token_audit = results.get('token_audit', {})
        valid = token_audit.get('valid', 0)
        warnings = token_audit.get('warnings', 0)
        errors = token_audit.get('errors', 0)
        lines.append(f"• Token audit: {valid} valid, {warnings} warnings, {errors} errors")
        
        duration = results.get('duration_seconds', 0)
        lines.append(f"• Duration: {duration:.2f}s")
        
        await respond("\n".join(lines))
        
    except Exception as e:
        logger.error(f"ADMIN: Manual GC run failed: {e}")
        await respond(f":x: Garbage collection failed: {e}")


async def _handle_admin_integrity_check_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    client: AsyncWebClient | None = None
) -> None:
    """Handle admin integrity check - validate all databases."""
    if not await _require_admin(respond, slack_user_id):
        return
    
    logger.info(f"ADMIN: User {slack_user_id} triggered integrity check")
    
    await respond("🔍 *Running database integrity check...* (this may take a moment)")
    
    try:
        # Validate token cache
        token_results = token_storage.validate_all_tokens()
        
        lines = ["*Database Integrity Check* :mag:"]
        lines.append("\n*Token Cache:*")
        lines.append(f"• Total tokens: {token_results.get('total', 0)}")
        lines.append(f"• Valid: {token_results.get('valid', 0)} :white_check_mark:")
        lines.append(f"• Warnings: {token_results.get('warnings', 0)} :warning:")
        lines.append(f"• Errors: {token_results.get('errors', 0)} :x:")
        
        # Show details if there are issues
        details = token_results.get('details', [])
        if details:
            lines.append("\n*Issues Found:*")
            for detail in details[:5]:  # Show first 5
                user_id = detail.get('user_id', 'unknown')
                issues = detail.get('issues', [])
                lines.append(f"• <@{user_id}>: {', '.join(issues)}")
            if len(details) > 5:
                lines.append(f"• ... and {len(details) - 5} more")
        
        await respond("\n".join(lines))
        
    except Exception as e:
        logger.error(f"ADMIN: Integrity check failed: {e}")
        await respond(f":x: Integrity check failed: {e}")


async def _handle_admin_refresh_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    args: str,
    client: AsyncWebClient | None = None,
) -> None:
    """Handle admin refresh — force token refresh for a linked user."""
    if not await _require_admin(respond, slack_user_id):
        return

    target_user = args.strip()
    if not target_user:
        await respond(
            ":warning: *Usage:* `/ggp admin refresh <@user>`\n"
            "Example: `/ggp admin refresh @john.doe`\n\n"
            "Refreshes the user's API token with their current role-based scopes."
        )
        return

    target_slack_id = await _resolve_slack_id(target_user, client)
    if not target_slack_id:
        await respond(
            ":x: *Could not identify user*\n"
            f"Received: `{target_user}`\n\n"
            "Please use @mention to specify the user.\n"
            "Example: `/ggp admin refresh @john.doe`"
        )
        return

    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            result = await intranet.refresh_token(target_slack_id)

            api_token = result.get("api_token")
            scopes = result.get("token_scopes", [])
            name = result.get("name", "Unknown")

            if not api_token:
                await respond(":x: *Token refresh failed:* No token returned by API.")
                return

            token_storage.save_token(
                slack_user_id=target_slack_id,
                token=api_token,
                scopes=scopes,
            )

            scope_text = ", ".join(scopes[:5])
            if len(scopes) > 5:
                scope_text += f" and {len(scopes) - 5} more"

            await respond(
                f":white_check_mark: *Token refreshed for {name}*\n"
                f"• Slack ID: {target_slack_id}\n"
                f"• Scopes: {scope_text}"
            )

    except IntranetScopeError as e:
        logger.error(f"User {slack_user_id} denied token refresh: {e}")
        await respond(
            ":x: *Permission Denied*\n"
            "Requires admin role."
        )
    except IntranetError as e:
        logger.error(f"Failed to refresh token for admin {slack_user_id}: {e}")
        await respond(f":x: Failed to refresh token: {e}")
    except Exception as e:
        logger.error(f"Unexpected error refreshing token for admin {slack_user_id}: {e}", exc_info=True)
        await respond(f":x: Unexpected error: {e}")


async def _handle_admin_holiday_pending_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    args: str,
    client: AsyncWebClient | None = None,
) -> None:
    """Handle admin holiday pending — list pending requests."""
    if not await _require_admin(respond, slack_user_id):
        return

    if not await _require_admin_holiday_scope(respond, slack_user_id):
        return

    # Parse optional page
    page = 1
    if args.strip():
        try:
            page = int(args.strip())
            if page < 1:
                await respond(":warning: Page must be 1 or greater.")
                return
        except ValueError:
            pass

    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            result = await intranet.get_admin_pending_holidays(page=page)

            if not result.holidays:
                await respond("No pending holiday requests found. :white_check_mark:")
                return

            lines = [f"*Pending Holiday Requests* :hourglass_flowing_sand: (page {page})"]

            for h in result.holidays:
                date_display = _format_holiday_dates(h)
                lines.append(
                    f"• #{h.id}: {h.user.name} — {date_display}"
                    f" ({h.working_days} day(s))"
                )
                if h.note:
                    lines.append(f"  _Note: {h.note}_")

            if result.summary:
                lines.append(
                    f"\n_Summary: {result.summary.total_pending} pending, "
                    f"{result.summary.total_users} users, "
                    f"{result.summary.total_working_days} working days total_"
                )

            await respond("\n".join(lines))

    except IntranetScopeError as e:
        logger.error(f"User {slack_user_id} lacks admin holiday scope: {e}")
        await respond(
            ":x: *Permission Denied*\n"
            "Your account doesn't have admin holiday management permission."
        )
    except IntranetError as e:
        logger.error(f"Failed to fetch pending holidays for admin {slack_user_id}: {e}")
        await respond(f":x: Failed to fetch pending holidays: {e}")
    except Exception as e:
        logger.error(f"Unexpected error fetching pending holidays for admin {slack_user_id}: {e}", exc_info=True)
        await respond(f":x: Unexpected error: {e}")


async def _handle_admin_holiday_approve_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    args: str,
    client: AsyncWebClient | None = None,
) -> None:
    """Handle admin holiday approve — bulk approve by IDs."""
    if not await _require_admin(respond, slack_user_id):
        return

    if not await _require_admin_holiday_scope(respond, slack_user_id):
        return

    if not args.strip():
        await respond(
            ":warning: *Usage:* `/ggp admin holiday approve <ids> [note]`\n"
            "*Examples:*\n"
            "• `/ggp admin holiday approve 123`\n"
            "• `/ggp admin holiday approve 123, 125, 127`\n"
            "• `/ggp admin holiday approve 150-155`\n"
            "• `/ggp admin holiday approve 150, 152-155, 158 Approved for project`"
        )
        return

    # Parse IDs and optional note
    ids, note = _parse_ids_and_text(args)

    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            result = await intranet.bulk_approve_holidays(ids=ids, note=note)

            lines = [":white_check_mark: *Holidays Approved*"]
            lines.append(f"• Approved: {result.approved_count}")
            if result.failed_count:
                lines.append(f"• Failed: {result.failed_count}")
            if result.total_working_days:
                lines.append(f"• Total working days: {result.total_working_days}")

            await respond("\n".join(lines))

    except IntranetError as e:
        logger.error(f"Failed to approve holidays for admin {slack_user_id}: {e}")
        await respond(f":x: Failed to approve holidays: {e}")
    except Exception as e:
        logger.error(f"Unexpected error approving holidays for admin {slack_user_id}: {e}", exc_info=True)
        await respond(f":x: Unexpected error: {e}")


async def _handle_admin_holiday_approve_all_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    client: AsyncWebClient | None = None,
) -> None:
    """Handle admin holiday approve-all — approve all pending."""
    if not await _require_admin(respond, slack_user_id):
        return

    if not await _require_admin_holiday_scope(respond, slack_user_id):
        return

    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            # Fetch pending count first to warn the admin
            pending = await intranet.get_admin_pending_holidays(page=1, per_page=1)
            if pending.summary:
                count = pending.summary.total_pending
                days = pending.summary.total_working_days
                if count > 0:
                    await respond(
                        f":warning: *This will approve all {count} pending holiday requests "
                        f"({days} working days).*\n"
                        "Run the command again to confirm."
                    )
                    return

            result = await intranet.approve_all_holidays()

            lines = [":white_check_mark: *All Holidays Approved*"]
            lines.append(f"• Approved: {result.approved_count}")
            if result.failed_count:
                lines.append(f"• Failed: {result.failed_count}")
            if result.total_working_days:
                lines.append(f"• Total working days: {result.total_working_days}")

            await respond("\n".join(lines))

    except IntranetError as e:
        logger.error(f"Failed to approve all holidays for admin {slack_user_id}: {e}")
        await respond(f":x: Failed to approve all holidays: {e}")
    except Exception as e:
        logger.error(f"Unexpected error approving all holidays for admin {slack_user_id}: {e}", exc_info=True)
        await respond(f":x: Unexpected error: {e}")


async def _handle_admin_holiday_deny_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    args: str,
    client: AsyncWebClient | None = None,
) -> None:
    """Handle admin holiday deny — bulk deny by IDs."""
    if not await _require_admin(respond, slack_user_id):
        return

    if not await _require_admin_holiday_scope(respond, slack_user_id):
        return

    if not args.strip():
        await respond(
            ":warning: *Usage:* `/ggp admin holiday deny <ids> [reason]`\n"
            "*Examples:*\n"
            "• `/ggp admin holiday deny 123 Insufficient coverage`\n"
            "• `/ggp admin holiday deny 123, 125, 127 Insufficient coverage`\n"
            "• `/ggp admin holiday deny 150-155 Company-wide freeze`"
        )
        return

    # Parse IDs and optional reason
    ids, reason = _parse_ids_and_text(args)
    if reason is None:
        reason = "No reason provided"

    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            result = await intranet.bulk_deny_holidays(ids=ids, reason=reason)

            lines = [":white_check_mark: *Holidays Denied*"]
            lines.append(f"• Denied: {result.denied_count}")
            if result.failed_count:
                lines.append(f"• Failed: {result.failed_count}")
            if result.total_working_days:
                lines.append(f"• Total working days: {result.total_working_days}")

            await respond("\n".join(lines))

    except IntranetError as e:
        logger.error(f"Failed to deny holidays for admin {slack_user_id}: {e}")
        await respond(f":x: Failed to deny holidays: {e}")
    except Exception as e:
        logger.error(f"Unexpected error denying holidays for admin {slack_user_id}: {e}", exc_info=True)
        await respond(f":x: Unexpected error: {e}")


async def _handle_admin_holiday_deny_all_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    args: str,
    client: AsyncWebClient | None = None,
) -> None:
    """Handle admin holiday deny-all — deny all pending."""
    if not await _require_admin(respond, slack_user_id):
        return

    if not await _require_admin_holiday_scope(respond, slack_user_id):
        return

    reason = args.strip() if args.strip() else "No reason provided"

    try:
        async with await IntranetClient.for_user(slack_user_id) as intranet:
            # Fetch pending count first to warn the admin
            pending = await intranet.get_admin_pending_holidays(page=1, per_page=1)
            if pending.summary:
                count = pending.summary.total_pending
                days = pending.summary.total_working_days
                if count > 0:
                    await respond(
                        f":warning: *This will deny all {count} pending holiday requests "
                        f"({days} working days).*\n"
                        "Run the command again to confirm."
                    )
                    return

            result = await intranet.deny_all_holidays(reason=reason)

            lines = [":white_check_mark: *All Holidays Denied*"]
            lines.append(f"• Denied: {result.denied_count}")
            if result.failed_count:
                lines.append(f"• Failed: {result.failed_count}")
            if result.total_working_days:
                lines.append(f"• Total working days: {result.total_working_days}")

            await respond("\n".join(lines))

    except IntranetError as e:
        logger.error(f"Failed to deny all holidays for admin {slack_user_id}: {e}")
        await respond(f":x: Failed to deny all holidays: {e}")
    except Exception as e:
        logger.error(f"Unexpected error denying all holidays for admin {slack_user_id}: {e}", exc_info=True)
        await respond(f":x: Unexpected error: {e}")


async def _handle_admin_holiday_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    args: str,
    client: AsyncWebClient | None = None,
) -> None:
    """Dispatch admin holiday subcommands.

    Args:
        respond: Slack respond function
        slack_user_id: The Slack user ID
        args: Subcommand and arguments
        client: Optional Slack WebClient
    """
    parts = args.strip().split(None, 1)
    subcommand = parts[0].lower() if parts else ""
    sub_args = parts[1] if len(parts) > 1 else ""

    if not subcommand:
        await respond(
            "*Usage:* `/ggp admin holiday <subcommand>`\n\n"
            "*Available subcommands:*\n"
            "• pending [page]\n"
            "• approve <ids> [note]\n"
            "• approve-all\n"
            "• deny <ids> [reason]\n"
            "• deny-all [reason]"
        )
        return

    if subcommand == "help":
        await respond(
            "*/ggp admin holiday [subcommand]*\n"
            "Admin holiday management commands.\n\n"
            "*Subcommands:*\n"
            "• pending [page] - List pending holiday requests\n"
            "• approve <ids> [note] - Approve holiday requests\n"
            "• approve-all - Approve all pending holidays\n"
            "• deny <ids> [reason] - Deny holiday requests\n"
            "• deny-all [reason] - Deny all pending holidays\n\n"
            "*Examples:*\n"
            "• /ggp admin holiday pending\n"
            "• /ggp admin holiday approve 123, 125-127\n"
            "• /ggp admin holiday approve-all\n"
            "• /ggp admin holiday deny 123 Insufficient coverage\n"
            "• /ggp admin holiday deny-all Company-wide freeze\n\n"
            "_Note: Requires admin role and `bot:admin:holiday` scope._"
        )
        return

    if subcommand == "pending":
        await _handle_admin_holiday_pending_subcommand(respond, slack_user_id, sub_args, client)
    elif subcommand == "approve":
        await _handle_admin_holiday_approve_subcommand(respond, slack_user_id, sub_args, client)
    elif subcommand == "approve-all":
        await _handle_admin_holiday_approve_all_subcommand(respond, slack_user_id, client)
    elif subcommand == "deny":
        await _handle_admin_holiday_deny_subcommand(respond, slack_user_id, sub_args, client)
    elif subcommand == "deny-all":
        await _handle_admin_holiday_deny_all_subcommand(respond, slack_user_id, sub_args, client)
    else:
        valid = ["pending", "approve", "approve-all", "deny", "deny-all"]
        suggestion = _suggest_command(subcommand, [f"admin holiday {cmd}" for cmd in valid])

        if suggestion:
            clean = suggestion.replace("admin holiday ", "")
            await respond(
                f":warning: Unknown admin holiday command '{subcommand}'.\n"
                f"Did you mean: `admin holiday {clean}`?\n\n"
                f"*Available commands:*\n"
                f"• pending [page]\n"
                f"• approve <ids> [note]\n"
                f"• approve-all\n"
                f"• deny <ids> [reason]\n"
                f"• deny-all [reason]"
            )
        else:
            await respond(
                f":warning: Unknown admin holiday command '{subcommand}'.\n\n"
                f"*Available commands:*\n"
                f"• pending [page]\n"
                f"• approve <ids> [note]\n"
                f"• approve-all\n"
                f"• deny <ids> [reason]\n"
                f"• deny-all [reason]"
            )


async def _handle_admin_subcommand(
    respond: AsyncRespond,
    slack_user_id: str,
    args: str,
    client: AsyncWebClient | None = None
) -> None:
    """Dispatch admin subcommands to their handlers.
    
    Args:
        respond: Slack respond function
        slack_user_id: The Slack user ID
        args: Subcommand and arguments (e.g., "cache clear @user")
        client: Optional Slack WebClient
    """
    # Parse the admin subcommand
    parts = args.strip().split(None, 2)
    subcommand = parts[0].lower() if parts else ""
    sub_args = " ".join(parts[1:]) if len(parts) > 1 else ""
    
    if subcommand == "help":
        await respond(
            "*/ggp admin [subcommand]*\n"
            "Administrative commands for bot management.\n\n"
            "*Subcommands:*\n"
            "• cache clear <@user> - Remove user from token cache\n"
            "• cache status - Show token cache statistics\n"
            "• gc status - Show GC schedule and last run\n"
            "• gc run - Manually trigger garbage collection\n"
            "• integrity check - Validate all databases\n"
            "• refresh <@user> - Refresh a user's API token\n\n"
            "*Examples:*\n"
            "• /ggp admin cache clear @john.doe\n"
            "• /ggp admin cache status\n"
            "• /ggp admin gc status\n"
            "• /ggp admin gc run\n"
            "• /ggp admin integrity check\n"
            "• /ggp admin refresh @john.doe\n\n"
            "_Note: Admin commands require an admin role._\n\n"
            "Run `/ggp admin holiday help` for holiday admin commands."
        )
        return

    if subcommand == "cache":
        # Parse cache sub-subcommand
        cache_parts = sub_args.split(None, 1)
        cache_cmd = cache_parts[0].lower() if cache_parts else ""
        cache_args = cache_parts[1] if len(cache_parts) > 1 else ""
        
        if cache_cmd == "clear":
            await _handle_admin_cache_clear_subcommand(respond, slack_user_id, cache_args, client)
        elif cache_cmd == "status":
            await _handle_admin_cache_status_subcommand(respond, slack_user_id, client)
        else:
            await respond(
                f":warning: Unknown cache command '{cache_cmd}'.\n\n"
                f"*Available cache commands:*\n"
                f"• /ggp admin cache clear <@user> - Remove user from token cache\n"
                f"• /ggp admin cache status - Show token cache statistics\n\n"
                f"Run `/ggp admin help` for more details."
            )
    
    elif subcommand == "gc":
        # Parse gc sub-subcommand
        gc_parts = sub_args.split(None, 1)
        gc_cmd = gc_parts[0].lower() if gc_parts else ""
        
        if gc_cmd == "status":
            await _handle_admin_gc_status_subcommand(respond, slack_user_id, client)
        elif gc_cmd == "run":
            await _handle_admin_gc_run_subcommand(respond, slack_user_id, client)
        else:
            await respond(
                f":warning: Unknown gc command '{gc_cmd}'.\n\n"
                f"*Available gc commands:*\n"
                f"• /ggp admin gc status - Show GC schedule and last run\n"
                f"• /ggp admin gc run - Manually trigger garbage collection\n\n"
                f"Run `/ggp admin help` for more details."
            )
    
    elif subcommand == "integrity":
        # Parse integrity sub-subcommand
        integrity_parts = sub_args.split(None, 1)
        integrity_cmd = integrity_parts[0].lower() if integrity_parts else ""
        
        if integrity_cmd == "check":
            await _handle_admin_integrity_check_subcommand(respond, slack_user_id, client)
        else:
            await respond(
                f":warning: Unknown integrity command '{integrity_cmd}'.\n\n"
                f"*Available integrity commands:*\n"
                f"• /ggp admin integrity check - Validate all databases\n\n"
                f"Run `/ggp admin help` for more details."
            )
    
    elif subcommand == "refresh":
        await _handle_admin_refresh_subcommand(respond, slack_user_id, sub_args, client)
    
    elif subcommand == "holiday":
        await _handle_admin_holiday_subcommand(respond, slack_user_id, sub_args, client)
    
    else:
        # Unknown admin subcommand
        valid_subcommands = list(ADMIN_SUBCOMMANDS.keys())
        suggestion = _suggest_command(subcommand, [f"admin {cmd}" for cmd in valid_subcommands])
        
        if suggestion:
            suggestion_clean = suggestion.replace("admin ", "")
            await respond(
                f":warning: Unknown admin command '{subcommand}'.\n"
                f"Did you mean: `admin {suggestion_clean}`?\n\n"
                f"*Available admin commands:*\n"
                f"• /ggp admin cache <clear|status> - Token cache management\n"
                f"• /ggp admin gc <status|run> - Garbage collection control\n"
                f"• /ggp admin integrity check - Database integrity checking\n"
                f"• /ggp admin refresh <@user> - Refresh a user's API token\n"
                f"• /ggp admin holiday <pending|approve|approve-all|deny|deny-all> - Holiday management\n\n"
                f"Run `/ggp admin help` for more details."
            )
        else:
            await respond(
                f":warning: Unknown admin command '{subcommand}'.\n\n"
                f"*Available admin commands:*\n"
                f"• /ggp admin cache <clear|status> - Token cache management\n"
                f"• /ggp admin gc <status|run> - Garbage collection control\n"
                f"• /ggp admin integrity check - Database integrity checking\n"
                f"• /ggp admin refresh <@user> - Refresh a user's API token\n"
                f"• /ggp admin holiday <pending|approve|approve-all|deny|deny-all> - Holiday management\n\n"
                f"Run `/ggp admin help` for more details."
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
    elif subcommand == "whois":
        await _handle_whois_subcommand(respond, slack_user_id, args, client)
    elif subcommand == "holiday":
        await _handle_holiday_subcommand(respond, slack_user_id, args, client)
    elif subcommand == "directory":
        await _handle_directory_subcommand(respond, slack_user_id, args, client)
    elif subcommand == "clock":
        await _handle_clock_subcommand(respond, slack_user_id, args, client)
    elif subcommand == "in":
        await _handle_clock_in_out_subcommand(respond, slack_user_id, "in", args, client)
    elif subcommand == "out":
        await _handle_clock_in_out_subcommand(respond, slack_user_id, "out", args, client)
    elif subcommand == "lunch":
        await _handle_clock_lunch_subcommand(respond, slack_user_id, client)
    elif subcommand == "admin":
        await _handle_admin_subcommand(respond, slack_user_id, args, client)
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
