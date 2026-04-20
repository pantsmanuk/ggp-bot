"""Custom exceptions for intranet API errors."""


class IntranetError(Exception):
    """Base exception for intranet API errors."""
    pass


class IntranetAuthError(IntranetError):
    """Authentication failed or invalid token."""
    pass


class IntranetScopeError(IntranetError):
    """Token lacks required permissions."""
    pass


class IntranetRateLimitError(IntranetError):
    """Rate limit exceeded."""
    
    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class IntranetValidationError(IntranetError):
    """Request validation failed."""
    pass


class IntranetNotFoundError(IntranetError):
    """Requested resource not found."""
    pass


class IntranetServerError(IntranetError):
    """Internal server error from intranet API."""
    pass


def raise_for_api_error(response_data: dict, status_code: int) -> None:
    """Raise appropriate exception based on API error response.
    
    Args:
        response_data: The JSON response from the API
        status_code: HTTP status code
        
    Raises:
        IntranetError: Appropriate exception for the error
    """
    if status_code < 400:
        return
    
    # Get error details from response
    success = response_data.get("success", False)
    if success:
        return  # Not actually an error
    
    error_code = response_data.get("error", "UNKNOWN")
    message = response_data.get("message", "Unknown error")
    
    # Map error codes to exceptions
    match error_code:
        case "UNAUTHORIZED":
            raise IntranetAuthError(f"Authentication failed: {message}")
        case "INSUFFICIENT_SCOPE":
            raise IntranetScopeError(f"Insufficient permissions: {message}")
        case "RATE_LIMIT_EXCEEDED":
            retry_after = response_data.get("retry_after")
            raise IntranetRateLimitError(
                f"Rate limit exceeded: {message}", 
                retry_after=retry_after
            )
        case "VALIDATION_ERROR":
            raise IntranetValidationError(f"Validation failed: {message}")
        case "NOT_FOUND":
            raise IntranetNotFoundError(f"Not found: {message}")
        case _:
            if status_code >= 500:
                raise IntranetServerError(f"Server error ({status_code}): {message}")
            raise IntranetError(f"API error ({status_code}): {message}")
