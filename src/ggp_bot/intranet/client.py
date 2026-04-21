"""Intranet API client for GGP Laravel backend - aligned with API v0.99.5.

This client supports both bot-level authentication (for public endpoints) and
per-user authentication (for user-specific endpoints). After a user links their
Slack account via /connect, they receive their own Bearer token which is stored
and used for subsequent authenticated requests.
"""

import httpx
import logging
from typing import Any

from ggp_bot.intranet.errors import raise_for_api_error
from ggp_bot.intranet.models import (
    HealthStatus,
    PublicHoliday,
    HolidayEntitlement,
    HolidayRequest,
    UserProfile,
    UserSearchResult,
)
from ggp_bot.intranet.token_storage import token_storage, UserToken
from ggp_bot.config import settings

# Logger for this module
logger = logging.getLogger(__name__)


class IntranetClient:
    """HTTP client for GGP intranet API v0.99.5+.
    
    Supports both global bot token (for health checks, public info) and
    per-user tokens (for user-specific operations like holiday requests).
    
    To use per-user authentication:
        client = await IntranetClient.for_user(slack_user_id)
        # or
        async with IntranetClient.for_user(slack_user_id) as client:
            ...
    """
    
    # API version alignment
    API_VERSION = "v0.99.5"
    BOT_VERSION = "0.4.0"
    
    def __init__(self, base_url: str, token: str | None = None):
        """Initialize the intranet client.
        
        Args:
            base_url: The base URL for the intranet API
            token: Optional Bearer token for authenticated requests
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._user_token: UserToken | None = None
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": f"ggp-bot/{self.BOT_VERSION} (API {self.API_VERSION})",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=30.0,
        )
    
    @classmethod
    async def for_user(cls, slack_user_id: str) -> "IntranetClient":
        """Create a client authenticated as a specific Slack user.
        
        This retrieves the user's stored token and creates a client configured
        to make requests on their behalf with their permissions/scopes.
        
        Args:
            slack_user_id: The Slack user ID (e.g., U1234567890)
            
        Returns:
            IntranetClient configured with the user's token
            
        Raises:
            ValueError: If the user has no stored token (not linked)
        """
        user_token = token_storage.get_token(slack_user_id)
        if not user_token:
            logger.warning(f"No stored token found for user {slack_user_id}")
            raise ValueError(
                f"No stored token for user {slack_user_id}. "
                "Please link your account first with /connect"
            )
        logger.debug(f"Retrieved stored token for user {slack_user_id} with scopes: {user_token.scopes}")
        
        # Create client with user's token
        base_url = settings.intranet_base_url
        client = cls(base_url=base_url, token=user_token.token)
        client._user_token = user_token
        return client
    
    @classmethod
    def with_bot_token(cls) -> "IntranetClient":
        """Create a client using the global bot token.
        
        Use this for endpoints that don't require user-specific permissions
        or when making requests on behalf of the bot itself.
        
        Returns:
            IntranetClient configured with the bot token
        """
        base_url = settings.intranet_base_url
        token = settings.intranet_api_token
        return cls(base_url=base_url, token=token)
    
    @property
    def is_user_authenticated(self) -> bool:
        """Check if this client is using a per-user token."""
        return self._user_token is not None
    
    @property
    def scopes(self) -> list[str]:
        """Get the scopes available to the current token."""
        if self._user_token:
            return self._user_token.scopes
        return []
    
    def has_scope(self, scope: str) -> bool:
        """Check if the current token has a specific scope.
        
        Args:
            scope: The scope to check (e.g., "bot:holiday:write")
            
        Returns:
            True if the token has the scope, False otherwise
        """
        return scope in self.scopes
    
    async def _get(self, path: str, authenticated: bool = True) -> dict[str, Any]:
        """Make a GET request to the API."""
        if authenticated and not self.token:
            raise ValueError("Authentication required but no token provided")
        
        response = await self.client.get(path)
        
        if response.status_code >= 400:
            try:
                data = response.json()
                raise_for_api_error(data, response.status_code)
            except ValueError:
                response.raise_for_status()
        
        response.raise_for_status()
        data = response.json()
        raise_for_api_error(data, response.status_code)
        return data
    
    async def _post(self, path: str, json_data: dict[str, Any], authenticated: bool = True) -> dict[str, Any]:
        """Make a POST request to the API."""
        if authenticated and not self.token:
            raise ValueError("Authentication required but no token provided")
        
        response = await self.client.post(path, json=json_data)
        
        if response.status_code >= 400:
            try:
                data = response.json()
                raise_for_api_error(data, response.status_code)
            except ValueError:
                response.raise_for_status()
        
        response.raise_for_status()
        data = response.json()
        raise_for_api_error(data, response.status_code)
        return data
    
    async def _delete(self, path: str, authenticated: bool = True) -> dict[str, Any]:
        """Make a DELETE request to the API."""
        if authenticated and not self.token:
            raise ValueError("Authentication required but no token provided")
        
        response = await self.client.delete(path)
        
        if response.status_code >= 400:
            try:
                data = response.json()
                raise_for_api_error(data, response.status_code)
            except ValueError:
                response.raise_for_status()
        
        response.raise_for_status()
        data = response.json()
        raise_for_api_error(data, response.status_code)
        return data
    
    # ==================== Health & Public Info ====================
    
    async def health_check(self) -> HealthStatus:
        """Check intranet API health status."""
        data = await self._get("/api/health", authenticated=False)
        return HealthStatus(**data["data"])
    
    async def get_rate_limits(self) -> dict[str, Any]:
        """Get rate limiting information."""
        data = await self._get("/api/rate-limits", authenticated=False)
        return data["data"]
    
    # ==================== Public Holidays ====================
    
    async def get_next_public_holiday(self) -> PublicHoliday:
        """Get the next upcoming UK public holiday."""
        data = await self._get("/api/holidays/next-public", authenticated=False)
        return PublicHoliday(**data["data"])
    
    async def get_all_public_holidays(self) -> list[PublicHoliday]:
        """Get all UK public holidays."""
        data = await self._get("/api/holidays/public", authenticated=False)
        holidays_data = data.get("data", [])
        return [PublicHoliday(**h) for h in holidays_data]
    
    # ==================== Authentication ====================
    
    async def verify_token(self) -> dict[str, Any]:
        """Verify the current token and get token metadata.
        
        Calls POST /api/auth/verify to validate the token and retrieve
        information about the authenticated user and token scopes.
        
        Returns:
            Token verification data including:
            - valid: bool
            - user: UserProfile
            - scopes: list of scopes
            - expires_at: expiry timestamp (if applicable)
        """
        data = await self._post("/api/auth/verify", {})
        return data.get("data", {})
    
    # ==================== Holidays (Requires Auth) ====================
    
    async def get_holiday_entitlement(self) -> HolidayEntitlement:
        """Get current user's holiday entitlement.
        
        Returns:
            HolidayEntitlement with total, used, remaining, pending
        """
        data = await self._get("/api/holidays/entitlement")
        return HolidayEntitlement(**data["data"])
    
    async def get_my_holidays(self) -> list[HolidayRequest]:
        """Get current user's holiday requests.
        
        Returns:
            List of HolidayRequest records
        """
        data = await self._get("/api/holidays/mine")
        holidays_data = data.get("data", [])
        return [HolidayRequest(**h) for h in holidays_data]
    
    async def request_holiday(
        self, 
        start: str, 
        end: str, 
        note: str | None = None,
        half_day: str | None = None
    ) -> HolidayRequest:
        """Request a new holiday.
        
        Args:
            start: Start date in YYYY-MM-DD format
            end: End date in YYYY-MM-DD format
            note: Optional note for the request
            half_day: null, "AM", or "PM" for first day
            
        Returns:
            Created HolidayRequest
        """
        payload = {
            "start": start,
            "end": end,
            "half_day": half_day,
        }
        if note:
            payload["note"] = note
        
        data = await self._post("/api/holidays/request", payload)
        return HolidayRequest(**data["data"])
    
    async def cancel_holiday(self, holiday_id: int) -> dict[str, Any]:
        """Cancel a holiday request.
        
        Args:
            holiday_id: ID of the holiday to cancel
            
        Returns:
            Cancellation result with days returned
        """
        data = await self._delete(f"/api/holidays/{holiday_id}")
        return data["data"]
    
    # ==================== User & Directory ====================
    
    async def get_current_user(self) -> UserProfile:
        """Get current authenticated user's profile."""
        data = await self._get("/api/users/me")
        return UserProfile(**data["data"])
    
    async def get_user_by_slack_id(self, slack_user_id: str) -> UserProfile:
        """Get intranet user profile by Slack user ID.
        
        This is the primary way for the bot to identify which intranet
        user is associated with a Slack user.
        
        Args:
            slack_user_id: Slack user ID (e.g., U1234567890)
            
        Returns:
            UserProfile for the linked intranet user
            
        Raises:
            IntranetSlackNotLinkedError: If Slack user not linked to any intranet account
        """
        data = await self._get(f"/api/users/by-slack-id/{slack_user_id}")
        return UserProfile(**data["data"])
    
    async def search_users(self, query: str) -> list[UserSearchResult]:
        """Search for users in the directory.
        
        Args:
            query: Search string (name, email, etc.)
            
        Returns:
            List of matching users
        """
        data = await self._get(f"/api/users/search?q={query}")
        users_data = data.get("data", [])
        return [UserSearchResult(**u) for u in users_data]
    
    async def get_user_status(self, user_id: int) -> dict[str, Any]:
        """Get a user's current status (working, on holiday, clocked in)."""
        data = await self._get(f"/api/users/{user_id}/status")
        return data["data"]
    
    async def get_directory(self) -> list[UserSearchResult]:
        """Get full company directory."""
        data = await self._get("/api/directory")
        users_data = data.get("data", [])
        return [UserSearchResult(**u) for u in users_data]
    
    # ==================== Slack Account Linking ====================
    
    async def link_slack_account(
        self,
        slack_user_id: str,
        slack_email: str,
        slack_username: str,
        intranet_email: str,
        intranet_password: str
    ) -> dict[str, Any]:
        """Link a Slack account to an intranet user account.
        
        After successful linking, the API returns a personal Bearer token
        for the user which is stored for subsequent authenticated requests.
        
        Args:
            slack_user_id: Slack user ID (U1234567890)
            slack_email: User's Slack email
            slack_username: User's Slack username
            intranet_email: User's intranet/company email
            intranet_password: User's intranet password
            
        Returns:
            API response with success status, user info, and token data
        """
        payload = {
            "slack_user_id": slack_user_id,
            "slack_email": slack_email,
            "slack_username": slack_username,
            "intranet_email": intranet_email,
            "intranet_password": intranet_password,
        }
        
        data = await self._post("/api/auth/slack-link", payload)
        
        # DEBUG: Print full response structure
        print(f"[DEBUG] link_slack_account response: {data}")
        
        # Extract and store the token if provided
        # API may return token in different structures, try both:
        # Option 1: data.data.token { token: "...", scopes: [...] }
        # Option 2: data.data { plainTextToken: "...", scopes: [...] }
        response_data = data.get("data", {})
        print(f"[DEBUG] response_data: {response_data}")
        
        token_data = response_data.get("token")
        print(f"[DEBUG] token_data from nested: {token_data}")
        
        # If no nested token object, check for direct fields in data.data
        if not token_data and "plainTextToken" in response_data:
            print(f"[DEBUG] Using Laravel Sanctum format (plainTextToken)")
            token_data = {
                "token": response_data.get("plainTextToken"),
                "scopes": response_data.get("abilities", []),  # Laravel Sanctum uses 'abilities'
                "expires_at": response_data.get("expires_at")
            }
        
        print(f"[DEBUG] Final token_data: {token_data}, success: {data.get('success')}")
        
        if token_data and data.get("success", False):
            token = token_data.get("token")
            scopes = token_data.get("scopes", [])
            expires_at = token_data.get("expires_at")
            
            print(f"[DEBUG] Extracted token: {token[:10]}... if present, scopes: {scopes}")
            
            # Store the token for future use
            if token:
                print(f"[DEBUG] Calling token_storage.save_token for {slack_user_id}")
                token_storage.save_token(
                    slack_user_id=slack_user_id,
                    token=token,
                    scopes=scopes,
                    expires_at=expires_at
                )
                print(f"[DEBUG] Token saved to storage")
            else:
                print(f"[DEBUG] No token value found despite token_data being present")
        
        return {
            "success": data.get("success", False),
            "message": data.get("message", ""),
            "data": data.get("data"),
        }
    
    async def close(self) -> None:
        """Close the HTTP client connection."""
        await self.client.aclose()
    
    async def __aenter__(self) -> "IntranetClient":
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, *_) -> None:
        """Async context manager exit."""
        await self.close()
