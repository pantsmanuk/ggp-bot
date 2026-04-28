"""Slack Block Kit formatters for rich message displays.

This module provides Block Kit builders for formatting time cards,
status displays, and other rich Slack messages.
"""

from datetime import datetime
from typing import Any

from ggp_bot.intranet.models import TimeClockEvent, TimeClockStatus


# Clock emojis for each hour (on the hour and half-hour)
# Format: (hour, is_half_hour) -> emoji
# Hours are 12-hour format (1-12)
_CLOCK_EMOJIS: dict[tuple[int, bool], str] = {
    (12, False): "🕛",  # 12:00
    (12, True): "🕧",   # 12:30
    (1, False): "🕐",   # 1:00
    (1, True): "🕜",    # 1:30
    (2, False): "🕑",   # 2:00
    (2, True): "🕝",    # 2:30
    (3, False): "🕒",   # 3:00
    (3, True): "🕞",    # 3:30
    (4, False): "🕓",   # 4:00
    (4, True): "🕟",    # 4:30
    (5, False): "🕔",   # 5:00
    (5, True): "🕠",    # 5:30
    (6, False): "🕕",   # 6:00
    (6, True): "🕡",    # 6:30
    (7, False): "🕖",   # 7:00
    (7, True): "🕢",    # 7:30
    (8, False): "🕗",   # 8:00
    (8, True): "🕣",    # 8:30
    (9, False): "🕘",   # 9:00
    (9, True): "🕤",    # 9:30
    (10, False): "🕙",  # 10:00
    (10, True): "🕥",   # 10:30
    (11, False): "🕚",  # 11:00
    (11, True): "🕦",   # 11:30
}


def _get_clock_emoji_for_time(timestamp: str) -> str:
    """Get the appropriate clock emoji for a given timestamp.

    Rounds to the nearest half-hour, preferring to round up at :15/:45.

    Args:
        timestamp: ISO 8601 datetime string

    Returns:
        Clock emoji corresponding to the rounded time
    """
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return "🕐"  # Default fallback

    hour = dt.hour
    minute = dt.minute

    # Convert 24-hour to 12-hour format
    hour_12 = hour % 12
    if hour_12 == 0:
        hour_12 = 12

    # Round to nearest half hour
    # 0-14 -> :00 (round down)
    # 15-44 -> :30 (round up from 15, round down from 30-44)
    # 45-59 -> next hour :00 (round up)
    if minute < 15:
        is_half = False
    elif minute < 45:
        is_half = True
    else:
        # Round up to next hour
        is_half = False
        hour_12 = hour_12 + 1
        if hour_12 > 12:
            hour_12 = 1

    return _CLOCK_EMOJIS.get((hour_12, is_half), "🕐")


def format_timecard_block(title: str, events: list[TimeClockEvent]) -> list[dict[str, Any]]:
    """Format a time card as Slack Block Kit blocks.
    
    Args:
        title: The card title (e.g., "Time Card - Today")
        events: List of time clock events
        
    Returns:
        List of Block Kit blocks for the message
    """
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": title,
                "emoji": True
            }
        }
    ]
    
    if not events:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "_No clock events recorded._"
            }
        })
        return blocks
    
    # Group events by day for week view
    from collections import defaultdict
    from datetime import datetime
    
    days = defaultdict(list)
    for event in events:
        # Parse date from ISO datetime
        try:
            dt = datetime.fromisoformat(event.time.replace('Z', '+00:00'))
            day_key = dt.strftime("%A %d/%m")  # "Monday 22/04"
        except:
            day_key = "Unknown"
        days[day_key].append(event)
    
    # Build display for each day
    for day_name, day_events in sorted(days.items()):
        day_lines = []
        
        # Pair up in/out events
        paired_events = []
        current_in = None
        
        for event in sorted(day_events, key=lambda e: e.time):
            if event.type == "in":
                current_in = event
            elif event.type == "out" and current_in:
                paired_events.append((current_in, event))
                current_in = None
            elif event.type == "out":
                # Out without matching in
                paired_events.append((None, event))
        
        # Handle unclosed in event
        if current_in:
            paired_events.append((current_in, None))
        
        # Format each pair
        for clock_in, clock_out in paired_events:
            if clock_in and clock_out:
                in_time = clock_in.event_time_12h
                out_time = clock_out.event_time_12h
                duration = clock_out.duration_formatted if clock_out.duration else ""
                
                line = f"• {in_time} → {out_time}"
                if duration:
                    line += f" ({duration})"
                
                # Add notes if present
                in_note = clock_in.note or ""
                out_note = clock_out.note or ""
                if in_note or out_note:
                    notes = []
                    if in_note:
                        notes.append(f"in: {in_note}")
                    if out_note:
                        notes.append(f"out: {out_note}")
                    line += f" _{', '.join(notes)}_"
                
                day_lines.append(line)
            
            elif clock_in and not clock_out:
                # Currently clocked in
                in_time = clock_in.event_time_12h
                line = f"• {in_time} → *Currently clocked in*"
                if clock_in.note:
                    line += f" _{clock_in.note}_"
                day_lines.append(line)
            
            elif clock_out and not clock_in:
                # Clock out without matching in
                out_time = clock_out.event_time_12h
                line = f"• ??:?? → {out_time} (missing clock in)"
                if clock_out.note:
                    line += f" _{clock_out.note}_"
                day_lines.append(line)
        
        if day_lines:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{day_name}*\n" + "\n".join(day_lines)
                }
            })
    
    return blocks


def format_timeclock_status_block(status: TimeClockStatus) -> list[dict[str, Any]]:
    """Format time clock status as Slack Block Kit blocks.
    
    Args:
        status: The time clock status
        
    Returns:
        List of Block Kit blocks
    """
    if status.is_clocked_in:
        status_emoji = "⏰"
        status_text = "Currently clocked *in*"
        
        fields = []
        
        if status.last_event:
            fields.append({
                "type": "mrkdwn",
                "text": f"*Since:*\n{status.last_event.event_time_12h}"
            })
        
        if status.current_duration:
            fields.append({
                "type": "mrkdwn",
                "text": f"*Duration:*\n{status.current_duration_formatted}"
            })
        
        # Only add note if present (Slack italic uses _text_)
        if status.last_event and status.last_event.note:
            fields.append({
                "type": "mrkdwn",
                "text": f"*Note:*\n_{status.last_event.note}_"
            })
        
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{status_emoji} {status_text}"
                }
            }
        ]
        
        if fields:
            blocks.append({
                "type": "section",
                "fields": fields
            })
        
        return blocks
    
    else:
        # Clocked out
        status_emoji = "⭕"
        status_text = "Currently clocked *out*"
        
        text = f"{status_emoji} {status_text}"
        
        if status.last_event:
            text += f"\n• Last clock out: {status.last_event.event_time_12h}"
            if status.last_event.note:
                text += f" _{status.last_event.note}_"
        
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text
                }
            }
        ]


def format_clock_confirmation(event_type: str, note: str | None = None) -> str:
    """Format a simple text confirmation for clock in/out.
    
    Args:
        event_type: "in" or "out"
        note: Optional note
        
    Returns:
        Formatted Slack mrkdwn string (using *bold* and _italic_)
    """
    bold_type = "*in*" if event_type == "in" else "*out*"
    text = f":white_check_mark: You clocked {bold_type}"
    
    if note:
        text += f" _{note}_"
    
    return text


def format_attendance_message(
    user_name: str,
    event_type: str,
    note: str | None = None,
    timestamp: str | None = None
) -> str:
    """Format the #Attendance channel message.

    Args:
        user_name: The user's display name
        event_type: "in", "out", or "lunch"
        note: Optional note
        timestamp: Optional ISO 8601 timestamp for clock emoji

    Returns:
        Formatted Slack mrkdwn string for #Attendance (using *bold* and _italic_)
    """
    # Get clock emoji based on timestamp
    clock_emoji = ""
    if timestamp:
        clock_emoji = _get_clock_emoji_for_time(timestamp)

    if event_type == "in":
        bold_type = "*in*"
        text = f"{clock_emoji} {user_name} clocked {bold_type}"
    elif event_type == "out":
        bold_type = "*out*"
        text = f"{clock_emoji} {user_name} clocked {bold_type}"
    elif event_type == "lunch":
        bold_type = "*lunch*"
        text = f"{clock_emoji} {user_name} started {bold_type}"
    else:
        # Fallback for unknown event types
        text = f"{clock_emoji} {user_name} {event_type}"

    if note:
        text += f" _({note})_"

    return text
