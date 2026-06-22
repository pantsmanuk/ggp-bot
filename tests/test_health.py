"""Test script for basic intranet connectivity.

This test verifies the bot can connect to the intranet API health endpoint.
The health endpoint is public and uses the bot token rather than per-user auth.
"""

import asyncio

import pytest

from ggp_bot.intranet import IntranetClient
from ggp_bot.config import settings


@pytest.mark.asyncio
async def test_health_check():
    """Test basic connectivity to intranet health endpoint."""
    print(f"Testing connectivity to: {settings.intranet_base_url}")
    print("-" * 50)
    
    # Create client with bot token (health endpoint uses bot-level auth)
    async with IntranetClient.with_bot_token() as client:
        try:
            result = await client.health_check()
            print("✅ Health check successful!")
            print(f"Status: {result.status}")
            print(f"Version: {result.version}")
            if result.timestamp:
                print(f"Timestamp: {result.timestamp}")
        except Exception as e:
            print(f"❌ Health check failed: {e}")
            raise


@pytest.mark.asyncio
async def test_rate_limits():
    """Test retrieving rate limit information."""
    print("\nTesting rate limits endpoint...")
    print("-" * 50)
    
    async with IntranetClient.with_bot_token() as client:
        try:
            limits = await client.get_rate_limits()
            print("✅ Rate limits retrieved successfully!")
            print(f"API limits: {limits}")
        except Exception as e:
            print(f"❌ Rate limits check failed: {e}")
            raise


if __name__ == "__main__":
    print("GGP Bot Intranet API Tests")
    print("=" * 50)
    asyncio.run(test_health_check())
    asyncio.run(test_rate_limits())
    print("\n✨ All tests completed!")
