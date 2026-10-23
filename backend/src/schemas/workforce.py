"""Strict workforce inputs; actors and staff identifiers come from server records."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def aware(value):
    return value.tzinfo is not None and value.utcoffset() is not None


class AssignmentCreate(Body):
    user_id: int = Field(gt=0)
    department_id: int = Field(gt=0)
    ward_id: int | None = Field(default=None, gt=0)
    location_id: int | None = Field(default=None, gt=0)
    source_module: Literal["DOCTOR", "WARD", "PHARMACY", "LABORATORY", "RADIOLOGY", "BILLING", "INVENTORY"]
    assignment_role: str = Field(min_length=2, max_length=32)
    starts_at: datetime
    expires_at: datetime | None = None
    reason: str = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def validate_scope(self):
        if not aware(self.starts_at) or self.expires_at and not aware(self.expires_at):
            raise ValueError("Assignment timestamps must include a timezone")
        if self.expires_at and self.expires_at <= self.starts_at:
            raise ValueError("Expiry must follow assignment start")
        if (self.source_module == "WARD") != (self.ward_id is not None):
            raise ValueError("Ward assignments require a ward; other assignments cannot include one")
        if (self.source_module == "INVENTORY") != (self.location_id is not None):
            raise ValueError("Inventory assignments require a location; others cannot include one")
        return self


class AssignmentChange(Body):
    expected_version: int = Field(gt=0)
    action: Literal["SUSPEND", "RESUME", "REVOKE"]
    reason: str = Field(min_length=3, max_length=1000)


class ShiftCreate(Body):
    user_id: int = Field(gt=0)
    department_id: int = Field(gt=0)
    ward_id: int | None = Field(default=None, gt=0)
    title: str = Field(min_length=2, max_length=100)
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def interval(self):
        if not aware(self.starts_at) or not aware(self.ends_at) or self.ends_at <= self.starts_at:
            raise ValueError("Shift requires timezone-aware increasing timestamps")
        return self


class ShiftChange(Body):
    expected_version: int = Field(gt=0)
    action: Literal["RESCHEDULE", "CANCEL"]
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    reason: str = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def interval(self):
        if self.action == "RESCHEDULE" and (self.starts_at is None or self.ends_at is None):
            raise ValueError("Rescheduling requires both times")
        if self.action == "CANCEL" and (self.starts_at is not None or self.ends_at is not None):
            raise ValueError("Cancellation cannot include replacement times")
        if self.starts_at and (not aware(self.starts_at) or not aware(self.ends_at) or self.ends_at <= self.starts_at):
            raise ValueError("Shift requires timezone-aware increasing timestamps")
        return self


class ClockOut(Body):
    expected_version: int = Field(gt=0)


class CorrectionCreate(Body):
    proposed_clock_out_at: datetime
    reason: str = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def timezone(self):
        if not aware(self.proposed_clock_out_at):
            raise ValueError("Correction timestamp must include a timezone")
        return self


class CorrectionDecision(Body):
    decision: Literal["APPROVED", "REJECTED"]
    reason: str = Field(min_length=3, max_length=1000)
