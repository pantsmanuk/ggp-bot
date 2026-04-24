"""Custom exceptions for intranet API errors - v1.0.0 format.

This module defines exceptions that map to the standardized API error response
codes from the Laravel intranet. All errors follow the format:

    {
        "success": false,
        "error": {
            "code": "ERROR_CODE",
            "message": "Human readable description",
            "details": {...}
        }
    }
"""

from typing import Any


class IntranetError(Exception):
    """Base exception for intranet API errors.
    
    Attributes:
        message: Human-readable error message
        error_code: Machine-readable error code from API
        details: Additional error context (may include field validation errors)
    """
    
    def __init__(
        self, 
        message: str, 
        error_code: str | None = None, 
        details: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.error_code = error_code
        self.details = details


class IntranetAuthError(IntranetError):
    """Authentication failed or invalid token (UNAUTHENTICATED).
    
    This error occurs when:
    - No token is provided for an authenticated endpoint
    - The token is invalid or malformed
    - The user associated with the token no longer exists
    """
    pass


class IntranetTokenExpiredError(IntranetAuthError):
    """Token has expired (TOKEN_EXPIRED).
    
    User needs to re-authenticate via /connect to obtain a new token.
    """
    pass


class IntranetInvalidCredentialsError(IntranetAuthError):
    """Invalid email/password during account linking (INVALID_CREDENTIALS).
    
    Occurs during /api/auth/slack-link when the intranet credentials are incorrect.
    """
    pass


class IntranetScopeError(IntranetError):
    """Token lacks required permissions (INSUFFICIENT_SCOPE).
    
    The API uses token scopes for granular permissions:
    - bot:read - Read general information
    - bot:write - Write operations
    - bot:directory - User directory access
    - bot:timeclock - Time clock operations
    - bot:holiday:read - Read holiday data
    - bot:holiday:write - Book holidays
    
    This error indicates the user's token doesn't have the required scope.
    """
    pass


class IntranetRateLimitError(IntranetError):
    """Rate limit exceeded (RATE_LIMIT_EXCEEDED).
    
    The API enforces rate limits:
    - Read operations: 120 requests/minute per token
    - Write operations: 60 requests/minute per token
    
    Response includes retry-after guidance in details.
    """
    pass


class IntranetSlackRateLimitError(IntranetError):
    """Slack rate limit warning from API (SLACK_RATE_LIMIT).
    
    The API includes X-Slack-RateLimit headers and may return this error
    to warn that the bot should slow down its Slack message sending.
    Slack Free Tier has a hard limit of 1 message/second per channel.
    """
    pass


class IntranetValidationError(IntranetError):
    """Request validation failed (VALIDATION_ERROR).
    
    Details include field-specific validation errors:
        "details": {
            "field_name": ["error message 1", "error message 2"]
        }
    """
    pass


class IntranetNotFoundError(IntranetError):
    """Requested resource not found (NOT_FOUND).
    
    Occurs when:
    - Holiday request ID doesn't exist
    - User ID doesn't exist
    - Endpoint doesn't exist
    """
    pass


class IntranetInsufficientDaysError(IntranetError):
    """Not enough holiday entitlement (INSUFFICIENT_DAYS).
    
    Details include:
        "details": {
            "shortfall": 2.5,
            "remaining_days": 5.0,
            "requested_days": 7.5
        }
    """
    pass


class IntranetOverlappingAbsenceError(IntranetError):
    """Date conflict with existing absence (OVERLAPPING_ABSENCE).
    
    Requested holiday dates overlap with an existing approved or pending
    absence request.
    """
    pass


class IntranetSlackNotLinkedError(IntranetError):
    """Slack user not linked to intranet account (SLACK_USER_NOT_LINKED).
    
    Occurs when attempting to access user-specific endpoints before
    running the /connect command to link accounts.
    """
    pass


class IntranetDuplicateLinkError(IntranetError):
    """Slack account already linked to another user (DUPLICATE_LINK).
    
    Occurs when attempting to link a Slack user ID that is already
    associated with a different intranet account.
    """
    pass


class IntranetServerError(IntranetError):
    """Internal server error from intranet API (HTTP 5xx).
    
    Indicates a problem with the Laravel backend. These should be rare
    and may indicate a bug or temporary outage.
    """
    pass


# Error code to exception class mapping
ERROR_CODE_MAP = {
    "UNAUTHENTICATED": IntranetAuthError,
    "TOKEN_EXPIRED": IntranetTokenExpiredError,
    "INVALID_CREDENTIALS": IntranetInvalidCredentialsError,
    "INSUFFICIENT_SCOPE": IntranetScopeError,
    "RATE_LIMIT_EXCEEDED": IntranetRateLimitError,
    "SLACK_RATE_LIMIT": IntranetSlackRateLimitError,
    "VALIDATION_ERROR": IntranetValidationError,
    "NOT_FOUND": IntranetNotFoundError,
    "INSUFFICIENT_DAYS": IntranetInsufficientDaysError,
    "OVERLAPPING_ABSENCE": IntranetOverlappingAbsenceError,
    "SLACK_USER_NOT_LINKED": IntranetSlackNotLinkedError,
    "DUPLICATE_LINK": IntranetDuplicateLinkError,
}


def raise_for_api_error(response_data: dict, status_code: int) -> None:
    """Raise appropriate exception based on API error response.
    
    API Error Format (v0.99.5):
    {
        "success": false,
        "error": {
            "code": "ERROR_CODE",
            "message": "Human readable description",
            "details": {...}
        }
    }
    
    Args:
        response_data: The JSON response from the API
        status_code: HTTP status code
        
    Raises:
        IntranetError: Appropriate exception for the error
    """
    # If success is True, no error
    success = response_data.get("success", True)
    if success:
        return
    
    # Extract error details from nested structure
    error_info = response_data.get("error", {})
    error_code = error_info.get("code", "UNKNOWN")
    message = error_info.get("message", "Unknown error")
    details = error_info.get("details")
    
    # Get exception class from mapping, fallback to generic errors
    exception_class = ERROR_CODE_MAP.get(error_code)
    
    if exception_class:
        raise exception_class(message, error_code, details)
    
    # Fallback for unknown error codes
    if status_code >= 500:
        raise IntranetServerError(
            f"Server error ({status_code}): {message}", 
            error_code, 
            details
        )
    
    raise IntranetError(
        f"API error ({status_code}): {message}",
        error_code,
        details
    )
