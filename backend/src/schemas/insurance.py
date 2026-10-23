"""Strict, source-only insurance request contracts."""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PolicyCreate(Body):
    patient_id: int = Field(gt=0)
    department_id: int = Field(gt=0)
    insurer_code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    insurer_name: str = Field(min_length=2, max_length=255)
    plan_code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    member_identifier: str = Field(min_length=4, max_length=128, pattern=r"^[A-Za-z0-9._/-]+$")
    policyholder_relationship: Literal["SELF", "SPOUSE", "CHILD", "PARENT", "OTHER"]
    coverage_start: date
    coverage_end: date | None = None

    @model_validator(mode="after")
    def dates(self):
        if self.coverage_end and self.coverage_end < self.coverage_start:
            raise ValueError("Coverage end cannot precede start")
        return self


class PolicyUpdate(Body):
    expected_version: int = Field(gt=0)
    insurer_name: str = Field(min_length=2, max_length=255)
    plan_code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    policyholder_relationship: Literal["SELF", "SPOUSE", "CHILD", "PARENT", "OTHER"]
    coverage_start: date
    coverage_end: date | None = None
    reason: str = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def dates(self):
        if self.coverage_end and self.coverage_end < self.coverage_start:
            raise ValueError("Coverage end cannot precede start")
        return self


class EligibilityRecord(Body):
    expected_version: int = Field(gt=0)
    status: Literal["PENDING", "VERIFIED", "INELIGIBLE", "FAILED"]
    method: Literal["MANUAL_STAFF_ENTRY", "EXTERNAL_VERIFIED"]
    source_reference: str = Field(min_length=3, max_length=128)
    reason: str | None = Field(default=None, max_length=1000)


class ExpectedVersion(Body):
    expected_version: int = Field(gt=0)


class ClaimLineInput(Body):
    charge_id: int = Field(gt=0)
    requested_amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    review_reference: str = Field(min_length=3, max_length=128)


class ClaimCreate(Body):
    invoice_id: int = Field(gt=0)
    policy_id: int = Field(gt=0)
    lines: list[ClaimLineInput] = Field(min_length=1, max_length=100)
    creation_key: str = Field(min_length=8, max_length=100)

    @model_validator(mode="after")
    def distinct_lines(self):
        ids = [row.charge_id for row in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Claim lines must be distinct")
        return self


class ClaimCorrection(Body):
    expected_version: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=1000)
    lines: list[ClaimLineInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct_lines(self):
        ids = [row.charge_id for row in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Correction lines must be distinct")
        return self


class ClaimTransition(Body):
    expected_version: int = Field(gt=0)
    to_status: Literal["READY_FOR_REVIEW", "SUBMITTED", "ACKNOWLEDGED", "UNDER_REVIEW", "APPROVED", "PARTIALLY_APPROVED", "DENIED", "CANCELLED"]
    reason: str | None = Field(default=None, max_length=1000)
    source_reference: str | None = Field(default=None, min_length=3, max_length=128)
    insurer_reference: str | None = Field(default=None, min_length=3, max_length=128)
    insurer_reference_supplied: bool = False
    approved_amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    denied_amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    patient_responsibility: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)

    @model_validator(mode="after")
    def reference_attestation(self):
        if self.insurer_reference and not self.insurer_reference_supplied:
            raise ValueError("Insurer reference requires explicit source confirmation")
        if self.insurer_reference_supplied and not self.insurer_reference:
            raise ValueError("Provide the insurer-supplied reference")
        return self


class ManualReconciliation(Body):
    expected_version: int = Field(gt=0)
    billing_payment_id: int = Field(gt=0)
    source_reference: str = Field(min_length=3, max_length=128)
    insurer_origin_confirmed: Literal[True]
