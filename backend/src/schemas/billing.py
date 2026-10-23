"""Strict finance requests; amounts are decimal and prices come from tariffs."""
from datetime import date
from decimal import Decimal
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Money = Decimal


class TariffCreate(StrictBody):
    department_id: int = Field(gt=0)
    service_code: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=255)
    unit_price: Money = Field(ge=0, max_digits=14, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    tax_required: bool = False
    approval_reference: str = Field(min_length=3, max_length=128)


class InvoiceCreate(StrictBody):
    patient_id: int = Field(gt=0)
    department_id: int = Field(gt=0)
    appointment_id: int | None = Field(default=None, gt=0)
    encounter_id: int | None = Field(default=None, gt=0)
    admission_id: int | None = Field(default=None, gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    creation_key: str = Field(min_length=8, max_length=100)


class ChargeCreate(StrictBody):
    expected_version: int = Field(gt=0)
    tariff_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, le=1000000, max_digits=12, decimal_places=3)
    source_type: Literal["MANUAL", "APPOINTMENT", "ENCOUNTER", "ADMISSION", "CLINICAL_ORDER"]
    source_id: int | None = Field(default=None, gt=0)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @model_validator(mode="after")
    def source_pair(self):
        if (self.source_type == "MANUAL") != (self.source_id is None):
            raise ValueError("A real service identifier is required except for manual charges")
        return self


class IssueInvoice(StrictBody):
    expected_version: int = Field(gt=0)
    due_date: date


class CancelInvoice(StrictBody):
    expected_version: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=2000)


class AdjustmentRequest(StrictBody):
    expected_version: int = Field(gt=0)
    amount: Money = Field(gt=0, max_digits=14, decimal_places=2)
    reason: str = Field(min_length=1, max_length=2000)


class AdjustmentDecision(StrictBody):
    expected_version: int = Field(gt=0)
    approve: bool
    reason: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def rejected_reason(self):
        if not self.approve and not self.reason:
            raise ValueError("Rejection requires a reason")
        return self


class ManualPayment(StrictBody):
    expected_version: int = Field(gt=0)
    amount: Money = Field(gt=0, max_digits=14, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    method: Literal["CASH", "BANK_TRANSFER", "CHEQUE", "OTHER"]
    reference: str = Field(min_length=3, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=100)
    manual_evidence_confirmed: Literal[True]

    @model_validator(mode="after")
    def no_card_secrets(self):
        # A manual receipt reference is not a field for PAN/CVV or bank credentials.
        digits = re.sub(r"[\s-]", "", self.reference)
        if re.search(r"\d{13,19}", digits):
            raise ValueError("Card numbers and payment secrets must not be entered")
        return self


class ReversePayment(StrictBody):
    expected_version: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=2000)


class RefundRequest(StrictBody):
    expected_version: int = Field(gt=0)
    payment_id: int = Field(gt=0)
    amount: Money = Field(gt=0, max_digits=14, decimal_places=2)
    reason: str = Field(min_length=1, max_length=2000)
