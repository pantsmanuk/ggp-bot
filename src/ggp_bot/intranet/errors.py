"""Custom exceptions for intranet API errors - v0.99.5 format."""

from typing import Any


class IntranetError(Exception):
    """Base exception for intranet API errors."""
    
    def __init__(self, message: str, error_code: str | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.details = details


class IntranetAuthError(IntranetError):
    """Authentication failed or invalid token (UNAUTHENTICATED)."""
    pass


class IntranetScopeError(IntranetError):
    """Token lacks required permissions (INSUFFICIENT_SCOPE)."""
    pass


class IntranetRateLimitError(IntranetError):
    """Rate limit exceeded (RATE_LIMIT_EXCEEDED)."""
    pass


class IntranetValidationError(IntranetError):
    """Request validation failed (VALIDATION_ERROR)."""
    pass


class IntranetNotFoundError(IntranetError):
    """Requested resource not found (NOT_FOUND)."""
    pass


class IntranetInsufficientDaysError(IntranetError):
    """Not enough holiday entitlement (INSUFFICIENT_DAYS)."""
    pass


class IntranetOverlappingAbsenceError(IntranetError):
    """Date conflict with existing absence (OVERLAPPING_ABSENCE)."""
    pass


class IntranetSlackNotLinkedError(IntranetError):
    """Slack user not linked to intranet account (SLACK_USER_NOT_LINKED)."""
    pass


class IntranetServerError(IntranetError):
    """Internal server error from intranet API."""
    pass


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
    
    # Map error codes to exceptions
    match error_code:
        case "UNAUTHENTICATED":
            raise IntranetAuthError(message, error_code, details)
        case "INSUFFICIENT_SCOPE":
            raise IntranetScopeError(message, error_code, details)
        case "RATE_LIMIT_EXCEEDED":
            raise IntranetRateLimitError(message, error_code, details)
        case "VALIDATION_ERROR":
            raise IntranetValidationError(message, error_code, details)
        case "NOT_FOUND":
            raise IntranetNotFoundError(message, error_code, details)
        case "INSUFFICIENT_DAYS":
            raise IntranetInsufficientDaysError(message, error_code, details)
        case "OVERLAPPING_ABSENCE":
            raise IntranetOverlappingAbsenceError(message, error_code, details)
        case "SLACK_USER_NOT_LINKED":
            raise IntranetSlackNotLinkedError(message, error_code, details)
        case _:
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
