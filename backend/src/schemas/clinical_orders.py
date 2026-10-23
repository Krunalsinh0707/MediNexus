"""Typed clinical order API contracts; attribution is always server-owned."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


OrderType = Literal["LAB", "IMAGING", "MEDICATION", "PROCEDURE", "OTHER"]
OrderPriority = Literal["ROUTINE", "URGENT", "STAT"]
OrderStatus = Literal["DRAFT", "SIGNED", "ACCEPTED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ClinicalOrderCreate(Request):
    patient_id: int = Field(gt=0)
    encounter_id: int = Field(gt=0)
    destination_department_id: int = Field(gt=0)
    order_type: OrderType
    priority: OrderPriority = "ROUTINE"
    order_code: str | None = Field(default=None, min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    clinical_indication: str | None = Field(default=None, max_length=4000)


class ClinicalOrderTransition(Request):
    expected_version: int = Field(ge=1)
    status: Literal["SIGNED", "ACCEPTED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
    reason: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def cancellation_requires_reason(self):
        if self.status == "CANCELLED" and not self.reason:
            raise ValueError("Cancellation requires a reason")
        if self.status != "CANCELLED" and self.reason is not None:
            raise ValueError("A reason is accepted only when cancelling an order")
        return self


class ClinicalOrderEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sequence: int
    order_version: int
    from_status: str | None
    to_status: str
    actor_user_id: int
    actor_doctor_id: int | None
    reason: str | None
    created_at: datetime


class ClinicalOrderResponse(BaseModel):
    id: int
    patient_id: int
    encounter_id: int
    requested_by_user_id: int
    requested_by_doctor_id: int
    destination_department_id: int
    order_type: str
    priority: str
    order_code: str | None
    display_name: str
    clinical_indication: str | None
    status: str
    version: int
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime
    signed_at: datetime | None
    accepted_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    allowed_actions: list[str] = Field(default_factory=list)
    events: list[ClinicalOrderEventResponse] = Field(default_factory=list)


class ClinicalOrderListResponse(BaseModel):
    items: list[ClinicalOrderResponse]
    total: int
