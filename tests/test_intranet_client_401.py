"""Regression tests for HTTP 401 handling in IntranetClient.

Verify that 401 responses from the intranet API are mapped to
IntranetAuthError with a user-friendly reconnect hint, while non-401
errors continue through the existing generic error path.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ggp_bot.intranet.client import IntranetClient
from ggp_bot.intranet.errors import IntranetAuthError, IntranetError


@pytest.fixture
def mock_401_response():
    """Return a response mock with status 401."""
    resp = MagicMock()
    resp.status_code = 401
    return resp


@pytest.fixture
def mock_400_json_response():
    """Return a response mock with status 400 and API error JSON body."""
    resp = MagicMock()
    resp.status_code = 400
    resp.json.return_value = {
        "success": False,
        "error": {"code": "VALIDATION_ERROR", "message": "Invalid input"},
    }
    return resp


class TestClient401Handling:
    """Verify 401 trapping in _get, _post, and _delete."""

    @pytest.mark.asyncio
    async def test_get_raises_auth_error_on_401(self, mock_401_response):
        with patch("httpx.AsyncClient") as MockClient:
            instance = MagicMock()
            instance.get = AsyncMock(return_value=mock_401_response)
            MockClient.return_value = instance

            client = IntranetClient(base_url="https://example.com", token="dead-token")
            with pytest.raises(IntranetAuthError) as exc_info:
                await client._get("/api/test")

            assert "/ggp connect" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_post_raises_auth_error_on_401(self, mock_401_response):
        with patch("httpx.AsyncClient") as MockClient:
            instance = MagicMock()
            instance.post = AsyncMock(return_value=mock_401_response)
            MockClient.return_value = instance

            client = IntranetClient(base_url="https://example.com", token="dead-token")
            with pytest.raises(IntranetAuthError) as exc_info:
                await client._post("/api/test", {"key": "value"})

            assert "/ggp connect" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_delete_raises_auth_error_on_401(self, mock_401_response):
        with patch("httpx.AsyncClient") as MockClient:
            instance = MagicMock()
            instance.delete = AsyncMock(return_value=mock_401_response)
            MockClient.return_value = instance

            client = IntranetClient(base_url="https://example.com", token="dead-token")
            with pytest.raises(IntranetAuthError) as exc_info:
                await client._delete("/api/test/1")

            assert "/ggp connect" in str(exc_info.value)


class TestClientNon401ErrorPath:
    """Verify non-401 errors still route through raise_for_api_error."""

    @pytest.mark.asyncio
    async def test_get_raises_validation_error_on_400(self, mock_400_json_response):
        with patch("httpx.AsyncClient") as MockClient:
            instance = MagicMock()
            instance.get = AsyncMock(return_value=mock_400_json_response)
            MockClient.return_value = instance

            client = IntranetClient(base_url="https://example.com", token="valid-token")
            with pytest.raises(IntranetError) as exc_info:
                await client._get("/api/test")

            assert exc_info.value.error_code == "VALIDATION_ERROR"
            assert "Invalid input" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_post_raises_validation_error_on_400(self, mock_400_json_response):
        with patch("httpx.AsyncClient") as MockClient:
            instance = MagicMock()
            instance.post = AsyncMock(return_value=mock_400_json_response)
            MockClient.return_value = instance

            client = IntranetClient(base_url="https://example.com", token="valid-token")
            with pytest.raises(IntranetError) as exc_info:
                await client._post("/api/test", {"key": "value"})

            assert exc_info.value.error_code == "VALIDATION_ERROR"
