"""Slack @mention handlers for natural language interactions.

This module handles conversational interactions via @mentions,
parsing natural language and routing to appropriate command handlers.

Supports both @ggp-bot (primary) and @ggpbot (alias) mentions.
"""

import logging
import re
from typing import Callable, Awaitable

from slack_bolt.async_app import AsyncAck, AsyncSay
from slack_sdk.web.async_client import AsyncWebClient

from ggp_bot.slack.handlers.commands import (
    _check_user_linked,
    _handle_not_linked,
    _handle_holiday_list_subcommand,
    _handle_holiday_balance_subcommand,
    _handle_clock_status_subcommand,
    _handle_whois_subcommand,
    _handle_bank_holiday_subcommand,
    _handle_directory_search_subcommand,
    _handle_whoami_subcommand,
)
from ggp_bot.intranet.client import IntranetClient
from ggp_bot.intranet.errors import (
    IntranetError,
    IntranetAuthError,
    IntranetSlackNotLinkedError,
)

logger = logging.getLogger(__name__)

# Bot mention patterns (user IDs will be substituted)
MENTION_PATTERNS = [
    r"<@(\w+)>",  # Standard Slack mention <@U12345678>
]

# Intent patterns for natural language matching
INTENT_PATTERNS = {
    "holiday_list": [
        r"show\s+(?:my\s+)?holidays",
        r"what\s+holidays\s+(?:do\s+I\s+have\s+)?booked",
        r"list\s+(?:my\s+)?holidays",
        r"my\s+holiday\s+list",
    ],
    "holiday_balance": [
        r"holiday\s+balance",
        r"how\s+many\s+holidays?\s+(?:do\s+I\s+have\s+)?(?:left|remaining)",
        r"what['']?s\s+my\s+holiday\s+(?:balance|entitlement)",
        r"(?:show\s+)?(?:my\s+)?entitlement",
    ],
    "bank_holiday": [
        r"next\s+(?:public\s+)?holiday",
        r"bank\s+holiday",
        r"when['']?s\s+the\s+next\s+holiday",
        r"upcoming\s+holiday",
    ],
    "clock_status": [
        r"am\s+I\s+(?:clocked\s+)?in",
        r"clock\s+status",
        r"time\s+clock",
        r"am\s+I\s+working",
        r"show\s+(?:my\s+)?status",
    ],
    "whois": [
        r"who\s+(?:is|are)\s+<@(\w+)>",
        r"who['']?s\s+<@(\w+)>",
        r"tell\s+me\s+about\s+<@(\w+)>",
    ],
    "whoami": [
        r"who\s+am\s+I",
        r"show\s+(?:my\s+)?profile",
        r"my\s+profile",
    ],
    "directory_search": [
        r"find\s+(.+)",
        r"search\s+(?:for\s+)?(.+)",
        r"lookup\s+(.+)",
        r"who\s+works\s+in\s+(.+)",
    ],
    "help": [
        r"help",
        r"what\s+can\s+you\s+do",
        r"commands",
        r"how\s+do\s+I",
    ],
}


def _normalize_text(text: str) -> str:
    """Normalize text for intent matching.
    
    - Lowercase
    - Remove extra whitespace
    - Remove punctuation except @mentions
    """
    # Remove the bot mention itself (we handle that separately)
    text = re.sub(r"<@\w+>\s*", "", text)
    # Normalize whitespace
    text = " ".join(text.split())
    # Lowercase
    return text.lower().strip()


def _match_intent(text: str) -> tuple[str, dict]:
    """Match text against intent patterns.
    
    Returns:
        Tuple of (intent_name, extracted_params)
    """
    normalized = _normalize_text(text)
    
    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if match:
                # Extract any groups as params
                params = {}
                if match.groups():
                    params["target_user"] = match.group(1)
                return intent, params
    
    return "unknown", {}


async def _handle_mention_holiday_list(
    say: AsyncSay,
    slack_user_id: str,
    client: AsyncWebClient,
) -> None:
    """Handle holiday list intent via mention."""
    if not _check_user_linked(slack_user_id):
        await say(
            ":x: Your Slack account is not linked. "
            "Run `/ggp connect <email> <password>` to link your account."
        )
        return
    
    # Create a simple respond-like function for compatibility
    async def respond(text: str | None = None, blocks: list | None = None) -> None:
        if blocks:
            await say(blocks=blocks, text=text or "Holiday information")
        else:
            await say(text=text or "Holiday information")
    
    # Mock AsyncRespond for compatibility with existing handlers
    class MockRespond:
        async def __call__(self, text: str | None = None, blocks: list | None = None) -> None:
            await respond(text, blocks)
    
    await _handle_holiday_list_subcommand(MockRespond(), slack_user_id, client)


async def _handle_mention_holiday_balance(
    say: AsyncSay,
    slack_user_id: str,
    client: AsyncWebClient,
) -> None:
    """Handle holiday balance intent via mention."""
    if not _check_user_linked(slack_user_id):
        await say(
            ":x: Your Slack account is not linked. "
            "Run `/ggp connect <email> <password>` to link your account."
        )
        return
    
    async def respond(text: str | None = None, blocks: list | None = None) -> None:
        if blocks:
            await say(blocks=blocks, text=text or "Holiday balance")
        else:
            await say(text=text or "Holiday balance")
    
    class MockRespond:
        async def __call__(self, text: str | None = None, blocks: list | None = None) -> None:
            await respond(text, blocks)
    
    await _handle_holiday_balance_subcommand(MockRespond(), slack_user_id, client)


async def _handle_mention_bank_holiday(
    say: AsyncSay,
    slack_user_id: str,
    client: AsyncWebClient,
) -> None:
    """Handle bank holiday intent via mention."""
    # Bank holiday is a public command - no auth required
    async def respond(text: str | None = None, blocks: list | None = None) -> None:
        if blocks:
            await say(blocks=blocks, text=text or "Bank holiday info")
        else:
            await say(text=text or "Bank holiday info")
    
    class MockRespond:
        async def __call__(self, text: str | None = None, blocks: list | None = None) -> None:
            await respond(text, blocks)
    
    await _handle_bank_holiday_subcommand(MockRespond(), client)


async def _handle_mention_clock_status(
    say: AsyncSay,
    slack_user_id: str,
    client: AsyncWebClient,
) -> None:
    """Handle clock status intent via mention."""
    if not _check_user_linked(slack_user_id):
        await say(
            ":x: Your Slack account is not linked. "
            "Run `/ggp connect <email> <password>` to link your account."
        )
        return
    
    async def respond(text: str | None = None, blocks: list | None = None) -> None:
        if blocks:
            await say(blocks=blocks, text=text or "Clock status")
        else:
            await say(text=text or "Clock status")
    
    class MockRespond:
        async def __call__(self, text: str | None = None, blocks: list | None = None) -> None:
            await respond(text, blocks)
    
    await _handle_clock_status_subcommand(MockRespond(), slack_user_id, client)


async def _handle_mention_whois(
    say: AsyncSay,
    slack_user_id: str,
    target_user: str,
    client: AsyncWebClient,
) -> None:
    """Handle whois intent via mention."""
    if not _check_user_linked(slack_user_id):
        await say(
            ":x: Your Slack account is not linked. "
            "Run `/ggp connect <email> <password>` to link your account."
        )
        return
    
    async def respond(text: str | None = None, blocks: list | None = None) -> None:
        if blocks:
            await say(blocks=blocks, text=text or "User info")
        else:
            await say(text=text or "User info")
    
    class MockRespond:
        async def __call__(self, text: str | None = None, blocks: list | None = None) -> None:
            await respond(text, blocks)
    
    # Format as proper mention for the whois handler
    mention_text = f"<@{target_user}>"
    await _handle_whois_subcommand(MockRespond(), slack_user_id, mention_text, client)


async def _handle_mention_whoami(
    say: AsyncSay,
    slack_user_id: str,
    client: AsyncWebClient,
) -> None:
    """Handle whoami intent via mention."""
    if not _check_user_linked(slack_user_id):
        await say(
            ":x: Your Slack account is not linked. "
            "Run `/ggp connect <email> <password>` to link your account."
        )
        return
    
    async def respond(text: str | None = None, blocks: list | None = None) -> None:
        if blocks:
            await say(blocks=blocks, text=text or "Your profile")
        else:
            await say(text=text or "Your profile")
    
    class MockRespond:
        async def __call__(self, text: str | None = None, blocks: list | None = None) -> None:
            await respond(text, blocks)
    
    await _handle_whoami_subcommand(MockRespond(), slack_user_id, client)


async def _handle_mention_directory_search(
    say: AsyncSay,
    slack_user_id: str,
    query: str,
    client: AsyncWebClient,
) -> None:
    """Handle directory search intent via mention."""
    if not _check_user_linked(slack_user_id):
        await say(
            ":x: Your Slack account is not linked. "
            "Run `/ggp connect <email> <password>` to link your account."
        )
        return
    
    async def respond(text: str | None = None, blocks: list | None = None) -> None:
        if blocks:
            await say(blocks=blocks, text=text or "Directory search")
        else:
            await say(text=text or "Directory search")
    
    class MockRespond:
        async def __call__(self, text: str | None = None, blocks: list | None = None) -> None:
            await respond(text, blocks)
    
    await _handle_directory_search_subcommand(MockRespond(), slack_user_id, query, client)


async def _handle_mention_help(
    say: AsyncSay,
    slack_user_id: str,
) -> None:
    """Handle help intent via mention."""
    is_connected = _check_user_linked(slack_user_id)
    
    help_text = (
        "*Hi! I'm GGP Bot. Here's what I can help you with:*\n\n"
        "*Privacy Note:* When you @mention me, my responses are visible to everyone in this channel. "
        "For private queries (sensitive info), use slash commands — only you will see the response.\n\n"
    )
    
    help_text += (
        "*Available via @mention (public):*\n"
        "• Show my holidays\n"
        "• What's my holiday balance?\n"
        "• Am I clocked in?\n"
        "• Who is @user?\n"
        "• Find John / Search engineering\n"
        "• Next public holiday\n\n"
    )
    
    if is_connected:
        help_text += (
            "*Slash-only for privacy:*\n"
            "• `/ggp holiday new` - Book time off (private)\n"
            "• `/ggp holiday cancel` - Cancel holidays (private)\n"
            "• `/ggp clock in/out/lunch` - Clock actions (private)\n"
            "• `/ggp clock today/week` - Detailed timecards (private)\n"
            "• `/ggp whoami` - Your full profile (private)\n\n"
        )
    
    if not is_connected:
        help_text += (
            "\n\n*Getting started:*\n"
            "Run `/ggp connect <email> <password>` to link your Slack account "
            "and access personalized commands."
        )
    
    await say(help_text)


async def _handle_mention_unknown(
    say: AsyncSay,
    slack_user_id: str,
    original_text: str,
) -> None:
    """Handle unknown intent with helpful fallback."""
    is_connected = _check_user_linked(slack_user_id)
    
    response = (
        f"I'm not sure what you mean by \"{original_text}\"\n\n"
        "*Try asking me things like:*\n"
    )
    
    if is_connected:
        response += (
            "• Show my holidays\n"
            "• What's my holiday balance?\n"
            "• Am I clocked in?\n"
            "• Who is @user?\n\n"
        )
    else:
        response += (
            "• Show my holidays (after connecting)\n"
            "• What's my holiday balance? (after connecting)\n\n"
        )
    
    response += (
        "Or run `/ggp help` for all available commands.\n\n"
        "_:lock: *Privacy tip:* Use slash commands (like `/ggp holiday balance`) for private responses. "
        "@mentions are visible to everyone in the channel._"
    )
    
    await say(response)


async def handle_mention(
    ack: AsyncAck,
    say: AsyncSay,
    event: dict,
    client: AsyncWebClient,
) -> None:
    """Main entry point for @mention handling.
    
    Parses the mention text, determines intent, and routes to appropriate handler.
    
    Args:
        ack: Slack Bolt ack function
        say: Slack Bolt say function (posts message to channel)
        event: The mention event dictionary
        client: Slack WebClient for API calls
    """
    await ack()
    
    slack_user_id = event.get("user", "")
    text = event.get("text", "")
    
    logger.debug(f"Mention from {slack_user_id}: {text}")
    
    # Match intent
    intent, params = _match_intent(text)
    logger.debug(f"Matched intent: {intent} with params: {params}")
    
    # Route to handler
    if intent == "holiday_list":
        await _handle_mention_holiday_list(say, slack_user_id, client)
    elif intent == "holiday_balance":
        await _handle_mention_holiday_balance(say, slack_user_id, client)
    elif intent == "bank_holiday":
        await _handle_mention_bank_holiday(say, slack_user_id, client)
    elif intent == "clock_status":
        await _handle_mention_clock_status(say, slack_user_id, client)
    elif intent == "whois":
        target_user = params.get("target_user", "")
        if target_user:
            await _handle_mention_whois(say, slack_user_id, target_user, client)
        else:
            await say(
                ":warning: Please mention a user to look up.\n"
                "Example: @ggp-bot who is @john.doe"
            )
    elif intent == "whoami":
        await _handle_mention_whoami(say, slack_user_id, client)
    elif intent == "directory_search":
        query = params.get("query", "").strip()
        if query:
            await _handle_mention_directory_search(say, slack_user_id, query, client)
        else:
            await say(
                ":warning: Please provide a search term.\n"
                "Example: @ggp-bot find John"
            )
    elif intent == "help":
        await _handle_mention_help(say, slack_user_id)
    else:
        await _handle_mention_unknown(say, slack_user_id, text)
