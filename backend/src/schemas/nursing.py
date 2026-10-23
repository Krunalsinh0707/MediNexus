"""Nursing writes accept measurements and intentions, never identity or status attribution."""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ObservationWrite(StrictBody):
    measured_at: AwareDatetime
    previous_id: int | None = Field(default=None, gt=0)
    correction_reason: str | None = Field(default=None, min_length=1, max_length=2000)
    systolic_mmhg: Decimal | None = Field(default=None, ge=20, le=400, decimal_places=2)
    diastolic_mmhg: Decimal | None = Field(default=None, ge=10, le=300, decimal_places=2)
    pulse_bpm: Decimal | None = Field(default=None, ge=10, le=300, decimal_places=2)
    respiratory_rate_per_min: Decimal | None = Field(default=None, ge=2, le=100, decimal_places=2)
    temperature_c: Decimal | None = Field(default=None, ge=20, le=50, decimal_places=2)
    spo2_percent: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    weight_kg: Decimal | None = Field(default=None, gt=0, le=600, decimal_places=2)
    height_cm: Decimal | None = Field(default=None, ge=30, le=300, decimal_places=2)

    @model_validator(mode="after")
    def validate_measurement(self):
        fields = ("systolic_mmhg", "diastolic_mmhg", "pulse_bpm", "respiratory_rate_per_min",
                  "temperature_c", "spo2_percent", "weight_kg", "height_cm")
        if not any(getattr(self, name) is not None for name in fields):
            raise ValueError("Record at least one measured vital sign")
        if (self.systolic_mmhg is None) != (self.diastolic_mmhg is None):
            raise ValueError("Blood pressure requires both systolic and diastolic values")
        if self.systolic_mmhg is not None and self.systolic_mmhg <= self.diastolic_mmhg:
            raise ValueError("Systolic pressure must exceed diastolic pressure")
        if self.measured_at > datetime.now(self.measured_at.tzinfo):
            raise ValueError("Measurement cannot be in the future")
        if self.previous_id is not None and not self.correction_reason:
            raise ValueError("Correction requires a reason")
        if self.previous_id is None and self.correction_reason is not None:
            raise ValueError("Correction reason requires a previous observation")
        return self


class NoteWrite(StrictBody):
    kind: Literal["ASSESSMENT", "HANDOVER"]
    content: str = Field(min_length=1, max_length=20000)


class PlanWrite(StrictBody):
    goal: str = Field(min_length=1, max_length=4000)
    intervention: str = Field(min_length=1, max_length=4000)


class TaskWrite(StrictBody):
    description: str = Field(min_length=1, max_length=4000)


class Transition(StrictBody):
    expected_version: int = Field(gt=0)
    status: Literal["ACTIVE", "COMPLETED", "CANCELLED", "IN_PROGRESS", "DONE"]
    reason: str | None = Field(default=None, min_length=1, max_length=2000)
