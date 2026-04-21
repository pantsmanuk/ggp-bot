"""Pydantic models for intranet API responses - v0.99.5."""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    """Base API response wrapper used by Laravel backend."""
    success: bool
    data: dict[str, Any] | list[dict[str, Any]] | None = None
    message: str | None = None
    meta: dict[str, Any] | None = None


class HealthStatus(BaseModel):
    """Health check response data."""
    status: str
    version: str
    timestamp: datetime | None = None


class PublicHoliday(BaseModel):
    """UK public holiday (bank holiday)."""
    date: str = Field(description="Date in YYYY-MM-DD format")
    day_of_week: str
    note: str
    days_until: int
    is_today: bool
    is_tomorrow: bool
    
    @property
    def name(self) -> str:
        """Alias for note for convenience."""
        return self.note
    
    @property
    def description(self) -> str:
        """Alias for note for convenience."""
        return self.note


class HolidayEntitlement(BaseModel):
    """User's holiday entitlement summary - from /holidays/entitlement."""
    entitlement: dict[str, float] = Field(
        description="Contains total, used, remaining, pending"
    )
    company_year: dict[str, str] = Field(
        description="Contains start and end dates"
    )
    
    @property
    def total(self) -> float:
        return self.entitlement.get("total", 0)
    
    @property
    def used(self) -> float:
        return self.entitlement.get("used", 0)
    
    @property
    def remaining(self) -> float:
        return self.entitlement.get("remaining", 0)
    
    @property
    def pending(self) -> float:
        return self.entitlement.get("pending", 0)


class HolidayLinks(BaseModel):
    """Links for holiday actions."""
    cancel: str | None = None


class HolidayRequest(BaseModel):
    """Holiday/absence request record - from /holidays/mine."""
    id: int
    type: str = Field(default="holiday")
    start: str = Field(description="ISO 8601 datetime string")
    end: str = Field(description="ISO 8601 datetime string")
    half_day: str | None = Field(default=None, description="AM, PM, or null (deprecated, use start_half_day/end_half_day)")
    start_half_day: str | None = Field(default=None, description="AM, PM, or null for start date")
    end_half_day: str | None = Field(default=None, description="AM, PM, or null for end date")
    working_days: float
    note: str | None = None
    approved: bool
    links: HolidayLinks | None = None
    
    @property
    def status(self) -> str:
        """Human-readable status."""
        return "approved" if self.approved else "pending"
    
    @property
    def start_date(self) -> str:
        """Extract date portion from start datetime."""
        return self.start[:10] if self.start else ""
    
    @property
    def end_date(self) -> str:
        """Extract date portion from end datetime."""
        return self.end[:10] if self.end else ""
    
    @property
    def half_day_summary(self) -> str:
        """Human-readable half-day summary."""
        parts = []
        if self.start_half_day:
            parts.append(f"start {self.start_half_day}")
        if self.end_half_day:
            parts.append(f"end {self.end_half_day}")
        if not parts and self.half_day:
            # Legacy support
            parts.append(f"{self.half_day}")
        return f" ({', '.join(parts)})" if parts else ""


class UserProfile(BaseModel):
    """User profile from intranet - from /users/me."""
    id: int
    name: str
    email: str
    department: str | None = None
    job_title: str | None = Field(default=None, alias="title")
    phone: str | None = None
    mobile: str | None = None
    location: str | None = None
    manager_id: int | None = None
    slack_linked: bool = False
    slack_user_id: str | None = None


class UserSearchResult(BaseModel):
    """User search result from directory - from /users/search or /directory."""
    id: int
    name: str
    given_name: str | None = None
    email: str
    department: str | None = None
    title: str | None = None
    slack_linked: bool = False


class UserStatus(BaseModel):
    """User's current work status - from /users/{id}/status."""
    is_working: bool
    clocked_in: bool
    current_absence: dict[str, Any] | None = None


class ApiErrorDetail(BaseModel):
    """API error details from error responses."""
    code: str
    message: str
    details: dict[str, Any] | None = None
