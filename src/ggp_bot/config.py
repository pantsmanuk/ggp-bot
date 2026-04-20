"""Configuration settings for ggp-bot."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Slack - required for bot operation
    slack_bot_token: str = Field(
        description="Bot User OAuth Token (starts with xoxb-)"
    )
    slack_signing_secret: str = Field(
        description="Signing secret for request verification"
    )
    slack_app_token: str = Field(
        description="App-Level Token for Socket Mode (starts with xapp-)"
    )
    
    # Intranet (Laravel 13) - required for basic health check
    intranet_base_url: str = Field(
        default="https://intranet.ggpsystems.co.uk",
        description="Base URL for the GGP intranet API"
    )
    
    # Optional: API token (not needed for /health endpoint)
    intranet_api_token: str | None = Field(
        default=None,
        description="Bearer token for authenticated intranet API calls"
    )
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # Ignore extra env vars not defined in this model


# Global settings instance
settings = Settings()
