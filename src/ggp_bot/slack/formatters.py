"""Slack Block Kit formatters for rich message displays.

This module provides Block Kit builders for formatting time cards,
status displays, and other rich Slack messages.
"""

from typing import Any

from ggp_bot.intranet.models import TimeClockEvent, TimeClockStatus


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


def format_attendance_message(user_name: str, event_type: str, note: str | None = None) -> str:
    """Format the #Attendance channel message.
    
    Args:
        user_name: The user's display name
        event_type: "in" or "out"
        note: Optional note
        
    Returns:
        Formatted Slack mrkdwn string for #Attendance (using *bold* and _italic_)
    """
    bold_type = "*in*" if event_type == "in" else "*out*"
    text = f"{user_name} clocked {bold_type}"
    
    if note:
        text += f" _{note}_"
    
    return text
