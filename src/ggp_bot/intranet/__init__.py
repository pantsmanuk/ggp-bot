"""Intranet API module for GGP Bot.

This module provides:
- IntranetClient: HTTP client for the Laravel 13 intranet API
- TokenStorage: Persistent storage for per-user API tokens
- Error classes: Specific exceptions for API error handling
- Models: Pydantic models for API responses

The authentication model uses per-user Bearer tokens obtained during
the Slack account linking process via /api/auth/slack-link.
"""

from ggp_bot.intranet.client import IntranetClient
from ggp_bot.intranet.token_storage import TokenStorage, UserToken, token_storage
from ggp_bot.intranet.errors import (
    IntranetError,
    IntranetAuthError,
    IntranetTokenExpiredError,
    IntranetInvalidCredentialsError,
    IntranetScopeError,
    IntranetRateLimitError,
    IntranetSlackRateLimitError,
    IntranetValidationError,
    IntranetNotFoundError,
    IntranetInsufficientDaysError,
    IntranetOverlappingAbsenceError,
    IntranetSlackNotLinkedError,
    IntranetDuplicateLinkError,
    IntranetServerError,
    ERROR_CODE_MAP,
)
from ggp_bot.intranet.models import (
    ApiResponse,
    HealthStatus,
    PublicHoliday,
    HolidayEntitlement,
    HolidayRequest,
    UserProfile,
    UserSearchResult,
    UserStatus,
    ApiErrorDetail,
)

__all__ = [
    # Client
    "IntranetClient",
    # Token Storage
    "TokenStorage",
    "UserToken",
    "token_storage",
    # Errors
    "IntranetError",
    "IntranetAuthError",
    "IntranetTokenExpiredError",
    "IntranetInvalidCredentialsError",
    "IntranetScopeError",
    "IntranetRateLimitError",
    "IntranetSlackRateLimitError",
    "IntranetValidationError",
    "IntranetNotFoundError",
    "IntranetInsufficientDaysError",
    "IntranetOverlappingAbsenceError",
    "IntranetSlackNotLinkedError",
    "IntranetDuplicateLinkError",
    "IntranetServerError",
    "ERROR_CODE_MAP",
    # Models
    "ApiResponse",
    "HealthStatus",
    "PublicHoliday",
    "HolidayEntitlement",
    "HolidayRequest",
    "UserProfile",
    "UserSearchResult",
    "UserStatus",
    "ApiErrorDetail",
]
