"""Date parsing utilities for UK and ISO formats.

Supports multiple date formats commonly used in the UK:
- ISO format: 2026-04-23
- UK slashes: 23/04/2026
- UK dashes: 23-04-2026  
- UK verbose: 23 Apr 2026

All formats are parsed and converted to ISO format (YYYY-MM-DD) for API compatibility.
"""

import re
from datetime import datetime
from typing import Tuple


def parse_date(date_str: str) -> str:
    """Parse a date string in various formats and return ISO format (YYYY-MM-DD).
    
    Supports:
    - ISO: 2026-04-23
    - UK slashes: 23/04/2026
    - UK dashes: 23-04-2026
    - UK verbose: 23 Apr 2026, 23 April 2026
    
    Args:
        date_str: Date string in any supported format
        
    Returns:
        ISO formatted date string (YYYY-MM-DD)
        
    Raises:
        ValueError: If date format is not recognized or date is invalid
    """
    date_str = date_str.strip()
    
    # ISO format: 2026-04-23
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
            return date_str
        except ValueError:
            raise ValueError(f"Invalid ISO date: {date_str}")
    
    # UK slashes: 23/04/2026
    if re.match(r'^\d{2}/\d{2}/\d{4}$', date_str):
        try:
            dt = datetime.strptime(date_str, '%d/%m/%Y')
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            raise ValueError(f"Invalid UK slash date: {date_str}")
    
    # UK dashes: 23-04-2026
    if re.match(r'^\d{2}-\d{2}-\d{4}$', date_str):
        try:
            dt = datetime.strptime(date_str, '%d-%m-%Y')
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            raise ValueError(f"Invalid UK dash date: {date_str}")
    
    # UK verbose: 23 Apr 2026 or 23 April 2026
    verbose_match = re.match(r'^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$', date_str)
    if verbose_match:
        try:
            dt = datetime.strptime(date_str, '%d %b %Y')
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            try:
                dt = datetime.strptime(date_str, '%d %B %Y')
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                raise ValueError(f"Invalid verbose date: {date_str}")
    
    raise ValueError(f"Unrecognized date format: {date_str}. Use YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, or 'DD Mon YYYY'")


def format_date_uk(date_str: str) -> str:
    """Convert an ISO date to UK format for display.
    
    Args:
        date_str: ISO date string (YYYY-MM-DD)
        
    Returns:
        UK formatted date (DD/MM/YYYY)
    """
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    return dt.strftime('%d/%m/%Y')


def parse_holiday_request(text: str) -> Tuple[str, str, str | None, str | None, str | None]:
    """Parse a holiday request command string.
    
    Expected formats:
    - /ggp holiday new <start> <end> [note]
    - /ggp holiday new <start> AM <end> PM [note]
    - /ggp holiday new 23/04/2026 25/04/2026 Vacation
    - /ggp holiday new 23/04/2026 AM 25/04/2026 PM Doctor appointment
    
    Args:
        text: The command text after the command name
        
    Returns:
        Tuple of (start_date, end_date, start_half_day, end_half_day, note)
        Dates are returned in ISO format (YYYY-MM-DD)
        If only one date provided, end_date defaults to start_date (single-day booking)
        
    Raises:
        ValueError: If the format is invalid
    """
    parts = text.strip().split()
    
    if len(parts) < 1:
        raise ValueError("Please provide at least a start date")
    
    # Look for half_day markers (AM/PM) which are not dates
    parsed_parts = []
    i = 0
    
    while i < len(parts):
        part = parts[i]
        
        # Check if this is a half-day marker
        if part.upper() in ('AM', 'PM'):
            parsed_parts.append(('half_day', part.upper()))
            i += 1
            continue
        
        # Try to parse as a date (might span multiple parts like "23 Apr 2026")
        # First, try single-part formats (ISO, UK slashes, UK dashes)
        if re.match(r'^(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{2}-\d{2}-\d{4})$', part):
            try:
                iso_date = parse_date(part)
                parsed_parts.append(('date', iso_date))
                i += 1
                continue
            except ValueError:
                pass
        
        # Try verbose format: "23 Apr 2026" (3 parts)
        if i + 2 < len(parts):
            verbose_attempt = f"{part} {parts[i+1]} {parts[i+2]}"
            try:
                iso_date = parse_date(verbose_attempt)
                parsed_parts.append(('date', iso_date))
                i += 3
                continue
            except ValueError:
                pass
        
        # Not a date or half-day marker, treat as start of note
        note = ' '.join(parts[i:])
        parsed_parts.append(('note', note))
        break
    
    # Extract dates and half-day markers
    dates = [p[1] for p in parsed_parts if p[0] == 'date']
    half_days = [p[1] for p in parsed_parts if p[0] == 'half_day']
    notes = [p[1] for p in parsed_parts if p[0] == 'note']
    
    if len(dates) < 1:
        raise ValueError("Please provide at least a start date")
    
    if len(dates) > 2:
        raise ValueError("Please provide at most two dates (start and end)")
    
    start_date = dates[0]
    # If only one date provided, default end_date to start_date (single-day booking)
    end_date = dates[1] if len(dates) >= 2 else start_date
    
    # Map half-day markers
    start_half_day = None
    end_half_day = None
    
    if len(half_days) >= 1:
        start_half_day = half_days[0]
    if len(half_days) >= 2:
        end_half_day = half_days[1]
    
    note = notes[0] if notes else None
    
    return start_date, end_date, start_half_day, end_half_day, note
