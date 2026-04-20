"""Intranet API client for GGP Laravel backend."""

import httpx
from typing import Any


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
    
    async def health_check(self) -> dict[str, Any]:
        """Check intranet API health status.
        
        Hits the /api/health endpoint which requires no authentication.
        
        Returns:
            Dict containing the health check response
            
        Raises:
            httpx.HTTPError: If the request fails
        """
        response = await self.client.get("/api/health")
        response.raise_for_status()
        return response.json()
    
    async def close(self) -> None:
        """Close the HTTP client connection."""
        await self.client.aclose()
    
    async def __aenter__(self) -> "IntranetClient":
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, *_) -> None:
        """Async context manager exit."""
        await self.close()
