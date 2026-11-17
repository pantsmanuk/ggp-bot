"""Slack displays use London time regardless of the host timezone."""

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from ggp_bot.intranet.models import (
    CalendarHoliday,
    HealthStatus,
    HolidayRequest,
    TimeClockEvent,
    UserProfile,
)
from ggp_bot.slack.formatters import format_attendance_message, format_timecard_block
from ggp_bot.slack.handlers.commands import (
    _handle_admin_gc_status_subcommand,
    _handle_status_subcommand,
    _handle_whois_subcommand,
)
from ggp_bot.utils.local_time import format_london_timestamp, london_date


@pytest.mark.parametrize(("timestamp", "expected"), [
    ("2026-01-01T12:30:00Z", "2026-01-01 12:30:00 GMT"),
    ("2026-07-01T12:30:00Z", "2026-07-01 13:30:00 BST"),
    ("2026-03-29T00:30:00Z", "2026-03-29 00:30:00 GMT"),
    ("2026-03-29T01:30:00Z", "2026-03-29 02:30:00 BST"),
    ("2026-10-25T00:30:00Z", "2026-10-25 01:30:00 BST"),
    ("2026-10-25T01:30:00Z", "2026-10-25 01:30:00 GMT"),
    ("2026-07-01T23:30:00Z", "2026-07-02 00:30:00 BST"),
    ("2026-07-01T12:30:00-04:00", "2026-07-01 17:30:00 BST"),
    ("2026-07-01T12:30:00", "2026-07-01 13:30:00 BST"),
])
def test_london_offsets_and_clock_changes(timestamp, expected):
    assert format_london_timestamp(timestamp) == expected


@pytest.mark.parametrize("event_type", ["in", "out", "lunch"])
@pytest.mark.parametrize(("timestamp", "emoji"), [
    ("2026-01-01T12:30:00Z", "🕧"),
    ("2026-07-01T12:30:00Z", "🕜"),
])
def test_attendance_clock_emoji_uses_london_time(event_type, timestamp, emoji):
    assert format_attendance_message("Alice", event_type, timestamp=timestamp).startswith(emoji)


def test_clock_timestamp_overrides_conflicting_api_display_fields():
    event = TimeClockEvent(
        id=1, type="in", event="2026-07-01T23:30:00Z",
        date="2026-07-01", time="23:30",
    )
    assert event.event_time_12h == "12:30 AM"
    assert "Thursday 02/07" in str(format_timecard_block("Today", [event]))


def test_holiday_dates_convert_timestamps_but_preserve_calendar_dates():
    assert london_date("2026-07-01") == "2026-07-01"
    holiday = HolidayRequest(
        id=1, start="2026-06-30T23:00:00Z", end="2026-07-01T23:00:00Z",
        working_days=2, approved=True,
    )
    assert holiday.start_date == "2026-07-01"
    assert holiday.end_date == "2026-07-02"
    bank_holiday = CalendarHoliday(
        date="2026-05-03T23:00:00Z", day_of_week="Monday", note="May bank holiday",
    )
    assert bank_holiday.date == "2026-05-04"


@pytest.mark.asyncio
@pytest.mark.parametrize(("timestamp", "expected"), [
    ("2026-01-01T12:30:00Z", "2026-01-01 12:30:00 GMT"),
    ("2026-07-01T12:30:00Z", "2026-07-01 13:30:00 BST"),
])
async def test_health_status_displays_london_time(timestamp, expected):
    client = AsyncMock()
    client.health_check.return_value = HealthStatus(
        status="healthy", version="1.0.1", timestamp=timestamp,
    )
    context = AsyncMock()
    context.__aenter__.return_value = client
    respond = AsyncMock()
    with patch("ggp_bot.slack.handlers.commands.IntranetClient.with_bot_token", return_value=context):
        await _handle_status_subcommand(respond)
    assert expected in respond.call_args.args[0]


@pytest.mark.asyncio
async def test_whois_displays_absence_dates_in_london():
    client = AsyncMock()
    client.get_user_by_slack_id.return_value = UserProfile(id=1, name="Alice", email="alice@example.com")
    client.get_user_status.return_value = {"status": {"current_absence": {
        "type": "holiday", "start": "2026-06-30T23:00:00Z", "end": "2026-07-01",
    }}}
    context = AsyncMock()
    context.__aenter__.return_value = client
    respond = AsyncMock()
    with (
        patch("ggp_bot.slack.handlers.commands._check_user_linked", return_value=True),
        patch("ggp_bot.slack.handlers.commands.IntranetClient.for_user", AsyncMock(return_value=context)),
    ):
        await _handle_whois_subcommand(respond, "U_TEST", "<@UALICE>")
    message = respond.call_args.args[0]
    assert "'start': '2026-07-01'" in message
    assert "'end': '2026-07-01'" in message


@pytest.fixture(params=["UTC", "America/New_York"])
def host_timezone(request, monkeypatch):
    monkeypatch.setenv("TZ", request.param)
    time.tzset()
    try:
        yield
    finally:
        monkeypatch.undo()
        time.tzset()


@pytest.mark.asyncio
async def test_cleanup_status_converts_host_local_schedule(host_timezone):
    # The scheduler emits naive timestamps in the host's timezone.
    last_run = datetime(2026, 7, 1, 12, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    next_run = datetime(2026, 7, 2, 12, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    status = {"running": True, "last_run": last_run.isoformat(), "next_run": next_run.isoformat()}
    respond = AsyncMock()
    with (
        patch("ggp_bot.slack.handlers.commands._require_admin", AsyncMock(return_value=True)),
        patch("ggp_bot.slack.handlers.commands.cleanup_scheduler.get_status", return_value=status),
    ):
        await _handle_admin_gc_status_subcommand(respond, "U_ADMIN")
    message = respond.call_args.args[0]
    assert "2026-07-01 13:00:00 BST" in message
    assert "2026-07-02 13:00:00 BST" in message


def test_api_timestamp_conversion_does_not_use_host_timezone(host_timezone):
    event = TimeClockEvent(id=1, type="in", event="2026-07-01T12:30:00Z")
    assert event.event_time_12h == "1:30 PM"
    assert format_london_timestamp("2026-07-01T12:30:00") == "2026-07-01 13:30:00 BST"
