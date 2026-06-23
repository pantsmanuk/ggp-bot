"""Tests for admin holiday management commands.

These tests verify the /ggp admin holiday subcommands:
- pending: list pending requests
- approve: bulk approve by IDs
- approve-all: approve all pending
- deny: bulk deny by IDs
- deny-all: deny all pending
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ggp_bot.slack.handlers.commands import (
    _handle_admin_holiday_subcommand,
    _handle_admin_holiday_pending_subcommand,
    _handle_admin_holiday_approve_subcommand,
    _handle_admin_holiday_approve_all_subcommand,
    _handle_admin_holiday_deny_subcommand,
    _handle_admin_holiday_deny_all_subcommand,
)
from ggp_bot.intranet.models import (
    AdminHoliday,
    AdminHolidayList,
    AdminHolidaySummary,
    AdminHolidayUser,
    AdminBulkResult,
    UserProfile,
)


@pytest.fixture
def mock_respond():
    return AsyncMock()


@pytest.fixture
def mock_client():
    return AsyncMock()


@pytest.fixture
def admin_user():
    """Return a UserProfile with admin role."""
    return UserProfile(
        id=1,
        name="Admin User",
        email="admin@ggpsystems.co.uk",
        department="Engineering",
        role="admin",
    )


@pytest.fixture
def regular_user():
    """Return a UserProfile with regular user role."""
    return UserProfile(
        id=2,
        name="Regular User",
        email="user@ggpsystems.co.uk",
        department="Engineering",
        role="user",
    )


@pytest.fixture
def admin_token():
    """Mock token with admin holiday scope."""
    token = MagicMock()
    token.has_scope.return_value = True
    token.scopes = ["bot:admin:holiday"]
    return token


@pytest.fixture
def admin_token_no_scope():
    """Mock token without admin holiday scope."""
    token = MagicMock()
    token.has_scope.return_value = False
    token.scopes = ["bot:holiday:write"]
    return token


@pytest.fixture
def sample_pending_holiday():
    """Return a sample pending AdminHoliday."""
    return AdminHoliday(
        id=123,
        user_id=2,
        user=AdminHolidayUser(id=2, name="John Doe", email="john@ggpsystems.co.uk", department="Engineering"),
        type="holiday",
        start="2026-07-01T00:00:00Z",
        end="2026-07-01T00:00:00Z",
        working_days=1.0,
        note="Vacation",
        approved=False,
    )


@pytest.fixture
def sample_pending_list(sample_pending_holiday):
    """Return a sample AdminHolidayList."""
    return AdminHolidayList(
        holidays=[sample_pending_holiday],
        summary=AdminHolidaySummary(total_pending=1, total_users=1, total_working_days=1.0),
    )


class TestAdminHolidayPending:
    """Verify admin holiday pending list command."""

    @pytest.mark.asyncio
    async def test_admin_can_list_pending_holidays(self, mock_respond, admin_user, admin_token, sample_pending_list):
        """Admin with correct scope can list pending holidays."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                admin_client.get_admin_pending_holidays = AsyncMock(return_value=sample_pending_list)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))
                # Also mock the admin check
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)

                await _handle_admin_holiday_pending_subcommand(mock_respond, "U_ADMIN", "", mock_client)

                mock_respond.assert_called_once()
                response = mock_respond.call_args[0][0]
                assert "Pending Holiday Requests" in response
                assert "John Doe" in response
                assert "123" in response
                assert "day(s)" in response

    @pytest.mark.asyncio
    async def test_admin_pending_shows_no_results(self, mock_respond, admin_user, admin_token):
        """Admin sees 'no pending' message when empty."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                admin_client.get_admin_pending_holidays = AsyncMock(return_value=AdminHolidayList(holidays=[]))
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)

                await _handle_admin_holiday_pending_subcommand(mock_respond, "U_ADMIN", "", mock_client)

                mock_respond.assert_called_once()
                response = mock_respond.call_args[0][0]
                assert "No pending holiday requests" in response

    @pytest.mark.asyncio
    async def test_non_admin_cannot_access_pending(self, mock_respond, regular_user):
        """Non-admin user receives access denied."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                admin_client.get_user_by_slack_id = AsyncMock(return_value=regular_user)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))

                await _handle_admin_holiday_pending_subcommand(mock_respond, "U_USER", "", mock_client)

                mock_respond.assert_called_once()
                response = mock_respond.call_args[0][0]
                assert "Admin Access Denied" in response

    @pytest.mark.asyncio
    async def test_admin_without_scope_gets_permission_error(self, mock_respond, admin_user, admin_token_no_scope):
        """Admin without bot:admin:holiday scope gets permission denied."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token_no_scope

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))

                await _handle_admin_holiday_pending_subcommand(mock_respond, "U_ADMIN", "", mock_client)

                mock_respond.assert_called_once()
                response = mock_respond.call_args[0][0]
                assert "Permission Denied" in response
                assert "bot:admin:holiday" in response

    @pytest.mark.asyncio
    async def test_admin_pending_pagination(self, mock_respond, admin_user, admin_token, sample_pending_list):
        """Admin can request specific page."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                admin_client.get_admin_pending_holidays = AsyncMock(return_value=sample_pending_list)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)

                await _handle_admin_holiday_pending_subcommand(mock_respond, "U_ADMIN", "2", mock_client)

                admin_client.get_admin_pending_holidays.assert_called_once_with(page=2)


class TestAdminHolidayApprove:
    """Verify admin holiday approve commands."""

    @pytest.mark.asyncio
    async def test_admin_can_bulk_approve(self, mock_respond, admin_user, admin_token):
        """Admin can bulk approve holidays by IDs."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                result = AdminBulkResult(approved_count=3, failed_count=0, total_working_days=5.0)
                admin_client.bulk_approve_holidays = AsyncMock(return_value=result)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)

                await _handle_admin_holiday_approve_subcommand(mock_respond, "U_ADMIN", "123, 125, 127", mock_client)

                mock_respond.assert_called_once()
                response = mock_respond.call_args[0][0]
                assert "Holidays Approved" in response
                assert "Approved: 3" in response
                assert "5.0" in response

    @pytest.mark.asyncio
    async def test_admin_approve_with_note(self, mock_respond, admin_user, admin_token):
        """Admin can approve with optional note."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                result = AdminBulkResult(approved_count=1, total_working_days=1.0)
                admin_client.bulk_approve_holidays = AsyncMock(return_value=result)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)

                await _handle_admin_holiday_approve_subcommand(mock_respond, "U_ADMIN", "123 Approved for project", mock_client)

                admin_client.bulk_approve_holidays.assert_called_once_with(ids="123", note="Approved for project")

    @pytest.mark.asyncio
    async def test_admin_approve_all(self, mock_respond, admin_user, admin_token):
        """Admin can approve all pending holidays."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                # First call: get_admin_pending_holidays returns empty (no warning needed)
                admin_client.get_admin_pending_holidays = AsyncMock(
                    return_value=AdminHolidayList(holidays=[], summary=AdminHolidaySummary(total_pending=0, total_users=0, total_working_days=0.0))
                )
                result = AdminBulkResult(approved_count=15, total_working_days=23.5)
                admin_client.approve_all_holidays = AsyncMock(return_value=result)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)

                await _handle_admin_holiday_approve_all_subcommand(mock_respond, "U_ADMIN", mock_client)

                mock_respond.assert_called_once()
                response = mock_respond.call_args[0][0]
                assert "All Holidays Approved" in response
                assert "Approved: 15" in response
                assert "23.5" in response


class TestAdminHolidayDeny:
    """Verify admin holiday deny commands."""

    @pytest.mark.asyncio
    async def test_admin_can_bulk_deny(self, mock_respond, admin_user, admin_token):
        """Admin can bulk deny holidays by IDs with reason."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                result = AdminBulkResult(denied_count=2, failed_count=0, total_working_days=3.0)
                admin_client.bulk_deny_holidays = AsyncMock(return_value=result)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)

                await _handle_admin_holiday_deny_subcommand(mock_respond, "U_ADMIN", "123, 125 Insufficient coverage", mock_client)

                mock_respond.assert_called_once()
                response = mock_respond.call_args[0][0]
                assert "Holidays Denied" in response
                assert "Denied: 2" in response

    @pytest.mark.asyncio
    async def test_admin_deny_without_reason_defaults(self, mock_respond, admin_user, admin_token):
        """Admin deny without reason uses default message."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                result = AdminBulkResult(denied_count=1)
                admin_client.bulk_deny_holidays = AsyncMock(return_value=result)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)

                await _handle_admin_holiday_deny_subcommand(mock_respond, "U_ADMIN", "123", mock_client)

                admin_client.bulk_deny_holidays.assert_called_once_with(ids="123", reason="No reason provided")

    @pytest.mark.asyncio
    async def test_admin_deny_all(self, mock_respond, admin_user, admin_token):
        """Admin can deny all pending holidays with reason."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                # First call: get_admin_pending_holidays returns empty (no warning needed)
                admin_client.get_admin_pending_holidays = AsyncMock(
                    return_value=AdminHolidayList(holidays=[], summary=AdminHolidaySummary(total_pending=0, total_users=0, total_working_days=0.0))
                )
                result = AdminBulkResult(denied_count=10, total_working_days=15.0)
                admin_client.deny_all_holidays = AsyncMock(return_value=result)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)

                await _handle_admin_holiday_deny_all_subcommand(mock_respond, "U_ADMIN", "Company-wide freeze", mock_client)

                mock_respond.assert_called_once()
                response = mock_respond.call_args[0][0]
                assert "All Holidays Denied" in response
                assert "Denied: 10" in response


class TestAdminHolidayDispatcher:
    """Verify the admin holiday subcommand dispatcher."""

    @pytest.mark.asyncio
    async def test_dispatcher_routes_pending(self, mock_respond, admin_user, admin_token, sample_pending_list):
        """Dispatcher routes 'pending' to pending handler."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                admin_client.get_admin_pending_holidays = AsyncMock(return_value=sample_pending_list)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)

                await _handle_admin_holiday_subcommand(mock_respond, "U_ADMIN", "pending", mock_client)

                mock_respond.assert_called_once()
                response = mock_respond.call_args[0][0]
                assert "Pending Holiday Requests" in response

    @pytest.mark.asyncio
    async def test_dispatcher_unknown_subcommand(self, mock_respond, admin_user, admin_token):
        """Dispatcher shows help for unknown subcommand."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))

                await _handle_admin_holiday_subcommand(mock_respond, "U_ADMIN", "unknown", mock_client)

                mock_respond.assert_called_once()
                response = mock_respond.call_args[0][0]
                assert "Unknown admin holiday command" in response
                assert "pending" in response
                assert "approve" in response
                assert "deny" in response

    @pytest.mark.asyncio
    async def test_dispatcher_empty_shows_help(self, mock_respond, admin_user, admin_token):
        """Dispatcher shows usage help when no subcommand given."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))

                await _handle_admin_holiday_subcommand(mock_respond, "U_ADMIN", "", mock_client)

                mock_respond.assert_called_once()
                response = mock_respond.call_args[0][0]
                assert "Usage" in response
                assert "pending" in response


class TestAdminHolidayValidation:
    """Verify input validation edge cases."""

    @pytest.mark.asyncio
    async def test_approve_requires_ids(self, mock_respond, admin_user, admin_token):
        """Approve without IDs shows usage help."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))

                await _handle_admin_holiday_approve_subcommand(mock_respond, "U_ADMIN", "", mock_client)

                mock_respond.assert_called_once()
                response = mock_respond.call_args[0][0]
                assert "Usage" in response
                assert "admin holiday approve" in response

    @pytest.mark.asyncio
    async def test_deny_requires_ids(self, mock_respond, admin_user, admin_token):
        """Deny without IDs shows usage help."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))

                await _handle_admin_holiday_deny_subcommand(mock_respond, "U_ADMIN", "", mock_client)

                mock_respond.assert_called_once()
                response = mock_respond.call_args[0][0]
                assert "Usage" in response
                assert "admin holiday deny" in response

    @pytest.mark.asyncio
    async def test_deny_all_without_reason_defaults(self, mock_respond, admin_user, admin_token):
        """Deny-all without reason uses default."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                # First call: get_admin_pending_holidays returns empty (no warning needed)
                admin_client.get_admin_pending_holidays = AsyncMock(
                    return_value=AdminHolidayList(holidays=[], summary=AdminHolidaySummary(total_pending=0, total_users=0, total_working_days=0.0))
                )
                result = AdminBulkResult(denied_count=5)
                admin_client.deny_all_holidays = AsyncMock(return_value=result)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)

                await _handle_admin_holiday_deny_all_subcommand(mock_respond, "U_ADMIN", "", mock_client)

                admin_client.deny_all_holidays.assert_called_once_with(reason="No reason provided")


class TestAdminHolidayExceptions:
    """Verify exception handling paths."""

    @pytest.mark.asyncio
    async def test_pending_intranet_error(self, mock_respond, admin_user, admin_token):
        """IntranetError during pending listing returns error message."""
        from ggp_bot.intranet.errors import IntranetError
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                admin_client.get_admin_pending_holidays = AsyncMock(
                    side_effect=IntranetError("API down", "SERVER_ERROR")
                )
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)

                await _handle_admin_holiday_pending_subcommand(mock_respond, "U_ADMIN", "", mock_client)

                mock_respond.assert_called_once()
                response = mock_respond.call_args[0][0]
                assert "Failed to fetch pending holidays" in response

    @pytest.mark.asyncio
    async def test_approve_intranet_error(self, mock_respond, admin_user, admin_token):
        """IntranetError during approve returns error message."""
        from ggp_bot.intranet.errors import IntranetError
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                admin_client.bulk_approve_holidays = AsyncMock(
                    side_effect=IntranetError("Not found", "NOT_FOUND")
                )
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)

                await _handle_admin_holiday_approve_subcommand(
                    mock_respond, "U_ADMIN", "123, 125", mock_client
                )

                mock_respond.assert_called_once()
                response = mock_respond.call_args[0][0]
                assert "Failed to approve holidays" in response


class TestAdminHolidayParsing:
    """Verify ID parsing edge cases."""

    @pytest.mark.asyncio
    async def test_dispatcher_empty_shows_usage(self, mock_respond, admin_user, admin_token):
        """Empty subcommand shows usage help, not 'Unknown command'."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))

                await _handle_admin_holiday_subcommand(mock_respond, "U_ADMIN", "", mock_client)

                mock_respond.assert_called_once()
                response = mock_respond.call_args[0][0]
                assert "Usage" in response
                assert "pending" in response
                assert "approve" in response
                assert "deny" in response
                assert "Unknown" not in response

    @pytest.mark.asyncio
    async def test_approve_parses_multi_id_with_spaces(self, mock_respond, admin_user, admin_token):
        """Multi-ID input with spaces after commas parses correctly."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                result = AdminBulkResult(approved_count=3)
                admin_client.bulk_approve_holidays = AsyncMock(return_value=result)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)

                await _handle_admin_holiday_approve_subcommand(
                    mock_respond, "U_ADMIN", "123, 125, 127 Approved for project", mock_client
                )

                admin_client.bulk_approve_holidays.assert_called_once_with(
                    ids="123, 125, 127", note="Approved for project"
                )

    @pytest.mark.asyncio
    async def test_deny_parses_multi_id_with_spaces(self, mock_respond, admin_user, admin_token):
        """Multi-ID deny with spaces after commas parses correctly."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                result = AdminBulkResult(denied_count=3)
                admin_client.bulk_deny_holidays = AsyncMock(return_value=result)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)

                await _handle_admin_holiday_deny_subcommand(
                    mock_respond, "U_ADMIN", "123, 125, 127 Company-wide freeze", mock_client
                )

                admin_client.bulk_deny_holidays.assert_called_once_with(
                    ids="123, 125, 127", reason="Company-wide freeze"
                )

    @pytest.mark.asyncio
    async def test_approve_parses_single_id_no_text(self, mock_respond, admin_user, admin_token):
        """Single ID without trailing text parses correctly."""
        with patch("ggp_bot.slack.handlers.commands.token_storage") as mock_storage:
            mock_storage.has_token.return_value = True
            mock_storage.get_token.return_value = admin_token

            with patch("ggp_bot.slack.handlers.commands.IntranetClient") as MockClient:
                admin_client = AsyncMock()
                result = AdminBulkResult(approved_count=1)
                admin_client.bulk_approve_holidays = AsyncMock(return_value=result)
                MockClient.for_user = AsyncMock(return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=admin_client),
                    __aexit__=AsyncMock(return_value=False),
                ))
                admin_client.get_user_by_slack_id = AsyncMock(return_value=admin_user)

                await _handle_admin_holiday_approve_subcommand(
                    mock_respond, "U_ADMIN", "150-155", mock_client
                )

                admin_client.bulk_approve_holidays.assert_called_once_with(
                    ids="150-155", note=None
                )
