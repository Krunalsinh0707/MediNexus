from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AdmissionRequest(StrictBody):
    patient_id: int = Field(gt=0)
    source_encounter_id: int = Field(gt=0)
    ward_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=4000)


class AdmissionDecision(StrictBody):
    expected_version: int = Field(gt=0)
    decision: Literal["ADMIT", "REJECT"]
    bed_id: int | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def required_fields(self):
        if self.decision == "ADMIT" and self.bed_id is None:
            raise ValueError("Admission requires a bed")
        if self.decision == "REJECT" and not self.reason:
            raise ValueError("Rejection requires a reason")
        return self


class TransferRequest(StrictBody):
    expected_version: int = Field(gt=0)
    ward_id: int = Field(gt=0)
    bed_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=4000)


class DischargeRequest(StrictBody):
    expected_version: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=4000)


class DischargePlanRequest(StrictBody):
    expected_version: int = Field(gt=0)
    planned_at: datetime
    reason: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def timezone_required(self):
        if self.planned_at.tzinfo is None or self.planned_at.utcoffset() is None:
            raise ValueError("Planned discharge time must include a timezone")
        return self


class BedStatusRequest(StrictBody):
    expected_version: int = Field(gt=0)
    status: Literal["AVAILABLE", "BLOCKED", "CLEANING"]
    reason: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def maintenance_reason(self):
        if self.status != "AVAILABLE" and not self.reason:
            raise ValueError("Blocking and cleaning require a reason")
        return self


class BedReservationRequest(StrictBody):
    admission_id: int = Field(gt=0)
    expected_bed_version: int = Field(gt=0)


class BedReleaseRequest(StrictBody):
    expected_bed_version: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=4000)
