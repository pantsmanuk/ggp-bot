"""Regression checks against https://intranet.ggpsystems.co.uk/docs, 2026-11-17."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from ggp_bot.intranet.client import IntranetClient
from ggp_bot.intranet.errors import IntranetValidationError
from ggp_bot.intranet.models import PublicHoliday, TimeClockEvent, TimeClockStatus
from ggp_bot.slack.formatters import (
    format_timecard_block,
    format_timeclock_status_block,
)


def test_clock_display_uses_london_time_and_keeps_utc_timestamp():
    # During BST the local calendar date can differ from the UTC date.
    payload = {
        "id": 1234,
        "type": "in",
        "event": "2026-07-01T23:30:00.000000Z",
        "time": "00:30",
        "date": "2026-07-02",
        "note": None,
    }
    event = TimeClockEvent(**payload)
    assert event.event == payload["event"]
    assert event.event_time_12h == "12:30 AM"
    card = str(format_timecard_block("Today", [event]))
    assert "Thursday 02/07" in card
    assert "12:30 AM" in card

    for clocked_in in (True, False):
        status = TimeClockStatus(clocked_in=clocked_in, last_event=payload)
        assert "12:30 AM" in str(format_timeclock_status_block(status))


def test_clock_order_uses_utc_during_repeated_local_hour():
    # The two 01:30 events straddle the autumn clock change.
    events = [
        TimeClockEvent(id=2, type="out", event="2026-10-25T01:30:00Z",
                       time="01:30", date="2026-10-25"),
        TimeClockEvent(id=1, type="in", event="2026-10-25T00:30:00Z",
                       time="01:30", date="2026-10-25"),
    ]
    card = str(format_timecard_block("Today", events))
    assert "1:30 AM → 1:30 AM" in card
    assert "missing clock in" not in card


def test_clock_response_without_local_fields_still_parses():
    event = TimeClockEvent(id=1234, type="in", event="2026-04-22T14:30:00.000000Z")
    assert event.event_time_12h == "3:30 PM"
    assert "Wednesday 22/04" in str(format_timecard_block("Today", [event]))


@pytest.mark.parametrize(("start", "end", "day", "times"), [
    ("2026-07-01T22:30:00Z", "2026-07-01T23:30:00Z", "Wednesday 01/07", "11:30 PM → 12:30 AM"),
    ("2026-07-01T23:30:00Z", "2026-07-02T00:30:00Z", "Thursday 02/07", "12:30 AM → 1:30 AM"),
])
def test_clock_sessions_crossing_midnight_belong_to_start_day(start, end, day, times):
    events = [
        TimeClockEvent(id=2, type="out", event=end),
        TimeClockEvent(id=1, type="in", event=start),
    ]
    blocks = format_timecard_block("Week", events)
    assert len(blocks) == 2
    text = blocks[1]["text"]["text"]
    assert day in text
    assert times in text
    assert "Currently clocked in" not in text
    assert "missing clock in" not in text


def test_clock_order_accepts_mixed_timestamp_precision():
    events = [
        TimeClockEvent(id=2, type="out", event="2026-07-01T09:00:00.5Z"),
        TimeClockEvent(id=1, type="in", event="2026-07-01T09:00:00Z"),
    ]
    card = str(format_timecard_block("Today", events))
    assert "10:00 AM → 10:00 AM" in card
    assert "Currently clocked in" not in card
    assert "missing clock in" not in card


@pytest.mark.asyncio
async def test_admin_pending_accepts_documented_flat_response():
    data = {
        "holidays": [{
            "id": 123, "user_id": 7, "user_name": "Murray Crane",
            "user_department": "Engineering", "type": "holiday",
            "start_date": "2025-05-15", "start_time": "09:00",
            "end_date": "2025-05-15", "end_time": "13:00",
            "duration": "Half day (AM)", "working_days": 0.5,
            "note": "Dentist appointment", "paid": True, "approved": False,
            "created_at": "2025-05-01T14:30:00.000000Z", "days_notice": 14,
        }],
        "pagination": {"current_page": 1, "total": 15},
        "summary": {"total_pending": 15, "total_users": 8, "total_working_days": 12.5},
    }
    async with IntranetClient("https://example.com", token="test") as client:
        with patch.object(client, "_get", AsyncMock(return_value={"data": data})):
            result = await client.get_admin_pending_holidays()
    assert result.holidays[0].user_name == "Murray Crane"
    assert result.holidays[0].start_date == "2025-05-15"
    assert result.summary.total_pending == 15


@pytest.mark.asyncio
async def test_public_holiday_list_does_not_require_next_holiday_metadata():
    data = [{"date": "2025-05-05", "day_of_week": "Monday", "note": "Early May bank holiday"}]
    async with IntranetClient("https://example.com", token="test") as client:
        with patch.object(client, "_get", AsyncMock(return_value={"data": data})):
            holidays = await client.get_all_public_holidays()
    assert holidays[0].date == "2025-05-05"
    assert holidays[0].name == "Early May bank holiday"

    upcoming = PublicHoliday(
        date="2026-12-25T00:00:00.000000Z", day_of_week="Friday",
        note="Christmas Day", days_until=38, is_today=False, is_tomorrow=False,
    )
    assert upcoming.date == "2026-12-25"
    assert upcoming.is_today is False


@pytest.mark.asyncio
async def test_holiday_note_validation_explains_80_character_limit():
    response = httpx.Response(
        422,
        json={"success": False, "error": {
            "code": "VALIDATION_ERROR", "message": "Validation failed",
            "details": {"note": ["The note field must not be greater than 80 characters."]},
        }},
        request=httpx.Request("POST", "https://example.com/api/holidays/request"),
    )
    async with IntranetClient("https://example.com", token="test") as client:
        with patch.object(client.client, "post", AsyncMock(return_value=response)) as post:
            with pytest.raises(IntranetValidationError, match="80 characters"):
                await client.request_holiday("2026-12-01", "2026-12-01", note="x" * 81)
    assert post.call_args.kwargs["json"]["note"] == "x" * 81
