"""Tests for clock-in public holiday guard rail.

These tests verify that /ggp clock in and /ggp in warn users on public holidays
unless they explicitly use the `force` flag.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ggp_bot.slack.handlers.commands import _handle_clock_in_out_subcommand
from ggp_bot.intranet.models import PublicHoliday


@pytest.fixture
def mock_respond():
    return AsyncMock()


@pytest.fixture
def mock_client():
    return AsyncMock()


@pytest.fixture
def mock_token():
    token = MagicMock()
    token.has_scope.return_value = True
    token.scopes = ["bot:timeclock:write"]
    return token


@pytest.fixture
def today_holiday():
    return PublicHoliday(
        date=datetime.now().strftime("%Y-%m-%d"),
        day_of_week="Monday",
        note="Spring Bank Holiday",
        days_until=0,
        is_today=True,
        is_tomorrow=False,
    )


@pytest.fixture
def future_holiday():
    return PublicHoliday(
        date="2099-12-25",
        day_of_week="Wednesday",
        note="Christmas Day",
        days_until=365,
        is_today=False,
        is_tomorrow=False,
    )


class TestClockInHolidayGuard:
    """Verify holiday guard rail behaviour for clock-in commands."""

    @pytest.mark.asyncio
    async def test_holiday_today_blocks_clock_in(self, mock_respond, mock_client, mock_token, today_holiday):
        """If today is a public holiday and user does not use force, warn and return."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = mock_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                # Bot client for holiday check
                holiday_client = AsyncMock()
                holiday_client.get_next_public_holiday = AsyncMock(return_value=today_holiday)
                MockClient.with_bot_token = MagicMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=holiday_client),
                    __aexit__=AsyncMock(return_value=False),
                ))
                # User client should never be reached
                user_client = AsyncMock()
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=user_client),
                    __aexit__=AsyncMock(return_value=False),
                ))

                await _handle_clock_in_out_subcommand(
                    mock_respond,
                    slack_user_id="U123",
                    event_type="in",
                    args="",
                    client=mock_client,
                )

                # Should have warned and stopped
                mock_respond.assert_awaited_once()
                response_text = mock_respond.call_args[0][0]
                assert "Public Holiday Today" in response_text
                assert "Spring Bank Holiday" in response_text
                assert "force" in response_text
                # User client never opened
                user_client.get_user_by_slack_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_holiday_today_force_allows_clock_in(self, mock_respond, mock_client, mock_token, today_holiday):
        """If today is a public holiday and user uses force, clock in proceeds."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = mock_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                holiday_client = AsyncMock()
                holiday_client.get_next_public_holiday = AsyncMock(return_value=today_holiday)
                MockClient.with_bot_token = MagicMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=holiday_client),
                    __aexit__=AsyncMock(return_value=False),
                ))

                user_client = AsyncMock()
                user_client.get_user_by_slack_id = AsyncMock(return_value=MagicMock(name="Alice"))
                user_client.clock_event = AsyncMock(return_value={"id": 42, "event": "09:00:00"})
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=user_client),
                    __aexit__=AsyncMock(return_value=False),
                ))

                with patch("ggp_bot.intranet.state_tracking.timeclock_tracker") as mock_tracker:
                    mock_tracker.should_notify.return_value = False

                    with patch("ggp_bot.slack.lunch_timer.lunch_timer_manager"):
                        with patch("ggp_bot.slack.formatters.format_clock_confirmation", return_value="Clocked in"):
                            await _handle_clock_in_out_subcommand(
                                mock_respond,
                                slack_user_id="U123",
                                event_type="in",
                                args="force Working on project",
                                client=mock_client,
                            )

                # Should clock in with note
                user_client.clock_event.assert_awaited_once()
                call_args = user_client.clock_event.call_args[0]
                assert call_args == ("in", "Working on project")
                mock_respond.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_holiday_allows_clock_in(self, mock_respond, mock_client, mock_token, future_holiday):
        """If today is not a public holiday, clock in proceeds normally."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = mock_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                holiday_client = AsyncMock()
                holiday_client.get_next_public_holiday = AsyncMock(return_value=future_holiday)
                MockClient.with_bot_token = MagicMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=holiday_client),
                    __aexit__=AsyncMock(return_value=False),
                ))

                user_client = AsyncMock()
                user_client.get_user_by_slack_id = AsyncMock(return_value=MagicMock(name="Alice"))
                user_client.clock_event = AsyncMock(return_value={"id": 42, "event": "09:00:00"})
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=user_client),
                    __aexit__=AsyncMock(return_value=False),
                ))

                with patch("ggp_bot.intranet.state_tracking.timeclock_tracker") as mock_tracker:
                    mock_tracker.should_notify.return_value = False

                    with patch("ggp_bot.slack.lunch_timer.lunch_timer_manager"):
                        with patch("ggp_bot.slack.formatters.format_clock_confirmation", return_value="Clocked in"):
                            await _handle_clock_in_out_subcommand(
                                mock_respond,
                                slack_user_id="U123",
                                event_type="in",
                                args="",
                                client=mock_client,
                            )

                user_client.clock_event.assert_awaited_once()
                mock_respond.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_holiday_api_failure_allows_clock_in(self, mock_respond, mock_client, mock_token):
        """If public holiday API fails, clock in proceeds (fail open)."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = mock_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                holiday_client = AsyncMock()
                holiday_client.get_next_public_holiday = AsyncMock(side_effect=Exception("API down"))
                MockClient.with_bot_token = MagicMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=holiday_client),
                    __aexit__=AsyncMock(return_value=False),
                ))

                user_client = AsyncMock()
                user_client.get_user_by_slack_id = AsyncMock(return_value=MagicMock(name="Alice"))
                user_client.clock_event = AsyncMock(return_value={"id": 42, "event": "09:00:00"})
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=user_client),
                    __aexit__=AsyncMock(return_value=False),
                ))

                with patch("ggp_bot.intranet.state_tracking.timeclock_tracker") as mock_tracker:
                    mock_tracker.should_notify.return_value = False

                    with patch("ggp_bot.slack.lunch_timer.lunch_timer_manager"):
                        with patch("ggp_bot.slack.formatters.format_clock_confirmation", return_value="Clocked in"):
                            await _handle_clock_in_out_subcommand(
                                mock_respond,
                                slack_user_id="U123",
                                event_type="in",
                                args="",
                                client=mock_client,
                            )

                user_client.clock_event.assert_awaited_once()
                mock_respond.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_force_only_no_note(self, mock_respond, mock_client, mock_token, today_holiday):
        """Using force with no note strips force flag and sets note to None."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = mock_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                holiday_client = AsyncMock()
                holiday_client.get_next_public_holiday = AsyncMock(return_value=today_holiday)
                MockClient.with_bot_token = MagicMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=holiday_client),
                    __aexit__=AsyncMock(return_value=False),
                ))

                user_client = AsyncMock()
                user_client.get_user_by_slack_id = AsyncMock(return_value=MagicMock(name="Alice"))
                user_client.clock_event = AsyncMock(return_value={"id": 42, "event": "09:00:00"})
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=user_client),
                    __aexit__=AsyncMock(return_value=False),
                ))

                with patch("ggp_bot.intranet.state_tracking.timeclock_tracker") as mock_tracker:
                    mock_tracker.should_notify.return_value = False

                    with patch("ggp_bot.slack.lunch_timer.lunch_timer_manager"):
                        with patch("ggp_bot.slack.formatters.format_clock_confirmation", return_value="Clocked in"):
                            await _handle_clock_in_out_subcommand(
                                mock_respond,
                                slack_user_id="U123",
                                event_type="in",
                                args="force",
                                client=mock_client,
                            )

                # Note should be None
                user_client.clock_event.assert_awaited_once_with("in", None)
                mock_respond.assert_awaited_once()
