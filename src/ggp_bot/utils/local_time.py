"""Europe/London display rules, independent of the bot host's timezone."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")


def london_datetime(value: str | datetime) -> datetime:
    """Convert an API timestamp to London time; unqualified API times are UTC."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LONDON)


def london_date(value: str) -> str:
    """Keep calendar dates intact; convert timestamp dates to London first."""
    if len(value) == 10:
        return date.fromisoformat(value).isoformat()
    return london_datetime(value).date().isoformat()


def format_london_timestamp(value: str | datetime) -> str:
    """Include GMT/BST so an absolute time's display timezone is explicit."""
    return london_datetime(value).strftime("%Y-%m-%d %H:%M:%S %Z")
