"""Test script for basic intranet connectivity."""

import asyncio
from ggp_bot.intranet.client import IntranetClient
from ggp_bot.config import settings


async def test_health_check():
    """Test basic connectivity to intranet health endpoint."""
    print(f"Testing connectivity to: {settings.intranet_base_url}")
    print("-" * 50)
    
    # Create client without token (health endpoint doesn't need auth)
    async with IntranetClient(
        base_url=settings.intranet_base_url,
        token=settings.intranet_api_token
    ) as client:
        try:
            result = await client.health_check()
            print("✅ Health check successful!")
            print(f"Response: {result}")
        except Exception as e:
            print(f"❌ Health check failed: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(test_health_check())
