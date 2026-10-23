"""Explicit write contracts; identity, authorship and timestamps are server-owned."""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EncounterCreate(Request):
    patient_id: int = Field(gt=0)
    appointment_id: int | None = Field(default=None, gt=0)
    doctor_id: int | None = Field(default=None, gt=0)
    department_id: int | None = Field(default=None, gt=0)
    creation_key: str = Field(min_length=8, max_length=64)
    chief_complaint: str | None = Field(default=None, max_length=4000)


class Versioned(Request):
    expected_version: int = Field(ge=1)


class Assignment(Versioned):
    doctor_id: int = Field(gt=0)


class Transition(Versioned):
    status: Literal["IN_PROGRESS", "COMPLETED", "CANCELLED"]
    reason: str | None = Field(default=None, min_length=1, max_length=4000)


class NoteWrite(Versioned):
    subjective: str = Field(default="", max_length=20000)
    objective: str = Field(default="", max_length=20000)
    assessment: str = Field(default="", max_length=20000)
    plan: str = Field(default="", max_length=20000)
    patient_summary: str = Field(default="", max_length=20000)


class AddendumWrite(NoteWrite):
    reason: str = Field(min_length=1, max_length=4000)


class Correction(Versioned):
    previous_id: int | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def correction_requires_reason(self):
        if self.previous_id is not None and not self.reason:
            raise ValueError("Corrections require a reason")
        return self


class VitalsWrite(Correction):
    measured_at: AwareDatetime
    systolic_mmhg: Decimal | None = Field(default=None, gt=0, lt=100000, max_digits=7, decimal_places=2)
    diastolic_mmhg: Decimal | None = Field(default=None, gt=0, lt=100000, max_digits=7, decimal_places=2)
    pulse_bpm: Decimal | None = Field(default=None, gt=0, lt=100000, max_digits=7, decimal_places=2)
    respiratory_rate_per_min: Decimal | None = Field(default=None, gt=0, lt=100000, max_digits=7, decimal_places=2)
    temperature_c: Decimal | None = Field(default=None, gt=0, lt=100, max_digits=7, decimal_places=2)
    spo2_percent: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    weight_kg: Decimal | None = Field(default=None, gt=0, lt=100000, max_digits=7, decimal_places=2)
    height_cm: Decimal | None = Field(default=None, gt=0, lt=100000, max_digits=7, decimal_places=2)

    @model_validator(mode="after")
    def has_measurement(self):
        fields = ("systolic_mmhg", "diastolic_mmhg", "pulse_bpm", "respiratory_rate_per_min", "temperature_c", "spo2_percent", "weight_kg", "height_cm")
        if not any(getattr(self, name) is not None for name in fields):
            raise ValueError("Record at least one measured vital")
        if self.measured_at > datetime.now(self.measured_at.tzinfo):
            raise ValueError("Measurement time cannot be in the future")
        return self


class DiagnosisWrite(Correction):
    description: str = Field(min_length=1, max_length=4000)
    coding_system: str | None = Field(default=None, min_length=1, max_length=64)
    code: str | None = Field(default=None, min_length=1, max_length=64)
    status: Literal["PROVISIONAL", "CONFIRMED", "ENTERED_IN_ERROR"] = "PROVISIONAL"
    is_primary: bool = False

    @model_validator(mode="after")
    def coding_pair(self):
        if (self.code is None) != (self.coding_system is None):
            raise ValueError("Diagnosis code and coding system must be supplied together")
        if self.status == "ENTERED_IN_ERROR" and self.previous_id is None:
            raise ValueError("Mark an existing diagnosis as entered in error using a correction")
        return self


class AllergyWrite(Correction):
    substance: str = Field(min_length=1, max_length=255)
    reaction: str | None = Field(default=None, max_length=4000)
    severity: Literal["UNKNOWN", "MILD", "MODERATE", "SEVERE"] = "UNKNOWN"
    status: Literal["ACTIVE", "INACTIVE", "ENTERED_IN_ERROR"] = "ACTIVE"

    @model_validator(mode="after")
    def status_requires_existing(self):
        if self.status != "ACTIVE" and self.previous_id is None:
            raise ValueError("Inactive/error assertions must correct an existing allergy")
        return self


class AllergyReview(Versioned):
    outcome: Literal["UNKNOWN", "NO_KNOWN", "RECORDED"]
