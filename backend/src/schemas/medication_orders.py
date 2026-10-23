"""Medication prescribing contracts with server-owned clinical attribution."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.schemas.clinical_orders import ClinicalOrderResponse, ClinicalOrderTransition


DurationUnit = Literal["DAYS", "WEEKS", "MONTHS", "DOSES"]


class MedicationOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    patient_id: int = Field(gt=0)
    encounter_id: int = Field(gt=0)
    priority: Literal["ROUTINE", "URGENT", "STAT"] = "ROUTINE"
    medication_identifier_system: str = Field(default="LOCAL", min_length=1, max_length=64)
    medication_identifier: str = Field(min_length=1, max_length=128)
    medication_display_name: str = Field(min_length=1, max_length=255)
    dose: Decimal = Field(gt=0, max_digits=12, decimal_places=4)
    dose_unit: str = Field(min_length=1, max_length=32)
    route: str = Field(min_length=1, max_length=64)
    frequency: str = Field(min_length=1, max_length=128)
    duration_value: int | None = Field(default=None, gt=0, le=3650)
    duration_unit: DurationUnit | None = None
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    quantity_unit: str = Field(min_length=1, max_length=64)
    start_date: date
    instructions: str | None = Field(default=None, max_length=4000)
    allergy_review_acknowledged: Literal[True]

    @model_validator(mode="after")
    def duration_is_complete(self):
        if (self.duration_value is None) != (self.duration_unit is None):
            raise ValueError("Duration value and unit must be provided together")
        return self


class MedicationAllergyWarning(BaseModel):
    source: Literal["clinician_recorded", "legacy_unverified"]
    match: Literal["EXACT_TEXT_MATCH", "REVIEW_RECORDED_ALLERGY", "REVIEW_LEGACY_TEXT"]
    substance: str
    severity: str | None = None
    message: str


class MedicationOrderDetailResponse(BaseModel):
    id: int
    order_id: int
    medication_identifier_system: str
    medication_identifier: str
    medication_display_name: str
    dose: Decimal
    dose_unit: str
    route: str
    frequency: str
    duration_value: int | None
    duration_unit: str | None
    quantity: Decimal
    quantity_unit: str
    start_date: date
    instructions: str | None
    allergy_review_id: int | None
    allergy_warnings: list[MedicationAllergyWarning] = Field(default_factory=list)
    allergy_acknowledged_at: datetime


class MedicationOrderResponse(BaseModel):
    order: ClinicalOrderResponse
    medication: MedicationOrderDetailResponse


class MedicationOrderListResponse(BaseModel):
    items: list[MedicationOrderResponse]
    total: int


MedicationOrderTransition = ClinicalOrderTransition
