"""Intranet API client for GGP Laravel backend."""

import httpx
from typing import Any

from ggp_bot.intranet.errors import raise_for_api_error
from ggp_bot.intranet.models import (
    ApiResponse,
    HealthStatus,
    Holiday,
    HolidayBalance,
    PublicHoliday,
    UserProfile,
)


class IntranetClient:
    """HTTP client for GGP intranet API."""
    
    def __init__(self, base_url: str, token: str | None = None):
        """Initialize the intranet client.
        
        Args:
            base_url: The base URL for the intranet API (e.g., https://intranet.ggpsystems.co.uk)
            token: Optional Bearer token for authenticated requests
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        
        # Build headers - auth is optional for some endpoints like /health
        headers = {
            "Accept": "application/json",
            "User-Agent": "ggp-bot/0.1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=30.0,
        )
    
    async def _get(self, path: str, authenticated: bool = True) -> dict[str, Any]:
        """Make a GET request to the API.
        
        Args:
            path: API endpoint path (e.g., "/api/health")
            authenticated: Whether this endpoint requires authentication
            
        Returns:
            Parsed JSON response
            
        Raises:
            IntranetError: If the API returns an error
            httpx.HTTPError: If the HTTP request fails
        """
        if authenticated and not self.token:
            raise ValueError("Authentication required but no token provided")
        
        response = await self.client.get(path)
        
        # Handle HTTP errors
        if response.status_code >= 400:
            try:
                data = response.json()
                raise_for_api_error(data, response.status_code)
            except ValueError:
                # Not valid JSON
                response.raise_for_status()
        
        response.raise_for_status()
        data = response.json()
        raise_for_api_error(data, response.status_code)
        return data
    
    async def _post(self, path: str, json_data: dict[str, Any], authenticated: bool = True) -> dict[str, Any]:
        """Make a POST request to the API.
        
        Args:
            path: API endpoint path
            json_data: JSON payload
            authenticated: Whether this endpoint requires authentication
            
        Returns:
            Parsed JSON response
        """
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
    
    async def health_check(self) -> HealthStatus:
        """Check intranet API health status.
        
        Hits the /api/health endpoint which requires no authentication.
        
        Returns:
            HealthStatus model with API version and status
        """
        data = await self._get("/api/health", authenticated=False)
        return HealthStatus(**data["data"])
    
    async def get_current_user(self) -> UserProfile:
        """Get current authenticated user's profile.
        
        Returns:
            UserProfile with user details
        """
        data = await self._get("/api/users/me")
        return UserProfile(**data["data"])
    
    # ==================== Holidays API ====================
    
    async def get_holiday_balance(self) -> HolidayBalance:
        """Get current user's holiday balance.
        
        Returns:
            HolidayBalance with entitlement, used, remaining days
        """
        data = await self._get("/api/holidays/balance")
        return HolidayBalance(**data["data"])
    
    async def list_holidays(self, status: str | None = None, year: int | None = None) -> list[Holiday]:
        """List current user's holidays.
        
        Args:
            status: Filter by status (pending, approved, rejected, cancelled)
            year: Filter by year (defaults to current)
            
        Returns:
            List of Holiday records
        """
        params = {}
        if status:
            params["status"] = status
        if year:
            params["year"] = year
        
        # Build query string
        query = "&".join(f"{k}={v}" for k, v in params.items())
        path = f"/api/holidays?{query}" if query else "/api/holidays"
        
        data = await self._get(path)
        holidays_data = data.get("data", [])
        return [Holiday(**h) for h in holidays_data]
    
    async def book_holiday(self, start_date: str, days: float, end_date: str | None = None, notes: str | None = None) -> Holiday:
        """Book a new holiday.
        
        Args:
            start_date: Start date in DD/MM/YYYY format (will be converted to ISO)
            days: Number of days to book
            end_date: Optional end date in DD/MM/YYYY format (calculated if not provided)
            notes: Optional notes for the request
            
        Returns:
            Created Holiday record
        """
        payload = {
            "start_date": start_date,
            "days": days,
        }
        if end_date:
            payload["end_date"] = end_date
        if notes:
            payload["notes"] = notes
        
        data = await self._post("/api/holidays", payload)
        return Holiday(**data["data"])
    
    async def cancel_holiday(self, holiday_id: int) -> bool:
        """Cancel a pending holiday request.
        
        Args:
            holiday_id: ID of the holiday to cancel
            
        Returns:
            True if successfully cancelled
        """
        await self._post(f"/api/holidays/{holiday_id}/cancel", {})
        return True
    
    async def get_next_public_holiday(self) -> PublicHoliday:
        """Get the next upcoming UK public holiday.
        
        Returns:
            PublicHoliday record
        """
        data = await self._get("/api/holidays/next-public")
        return PublicHoliday(**data["data"])
    
    async def link_slack_account(
        self, 
        email: str, 
        password: str, 
        slack_user_id: str
    ) -> dict:
        """Link a Slack account to an intranet user account.
        
        Args:
            email: User's intranet email address
            password: User's intranet password
            slack_user_id: Slack user ID (from command context)
            
        Returns:
            API response dict with success status and message
        """
        payload = {
            "email": email,
            "password": password,
            "slack_user_id": slack_user_id,
        }
        
        data = await self._post("/api/auth/slack-link", payload)
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
