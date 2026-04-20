"""Pydantic models for intranet API responses."""

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
    timestamp: datetime


class Holiday(BaseModel):
    """Holiday/absence record."""
    id: int
    user_id: int
    start_date: str = Field(description="Date in YYYY-MM-DD format")
    end_date: str = Field(description="Date in YYYY-MM-DD format")
    days: float
    status: str = Field(description="pending, approved, rejected, cancelled")
    type: str = Field(default="annual_leave", description="annual_leave, sick, etc.")
    notes: str | None = None
    requested_at: datetime | None = None
    approved_by: int | None = None
    approved_at: datetime | None = None


class HolidayBalance(BaseModel):
    """User's holiday entitlement summary."""
    total_entitlement: float
    days_used: float
    days_remaining: float
    pending_requests: float
    year: int


class PublicHoliday(BaseModel):
    """UK public holiday (bank holiday)."""
    date: str = Field(description="Date in YYYY-MM-DD format")
    note: str  # API returns 'note' with holiday name/description
    day_of_week: str
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


class UserProfile(BaseModel):
    """User profile from intranet."""
    id: int
    name: str
    email: str
    department: str | None = None
    job_title: str | None = None
    phone: str | None = None
    mobile: str | None = None
    location: str | None = None
    manager_id: int | None = None
    slack_user_id: str | None = None
    current_status: str | None = None
