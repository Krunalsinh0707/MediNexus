"""Inventory requests prohibit client supplied actors, stock totals and timestamps."""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ItemCreate(Body):
    code: str = Field(min_length=2, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=2, max_length=255)
    category: Literal["MEDICATION", "SUPPLY"]
    unit: str = Field(min_length=1, max_length=32)
    description: str | None = Field(default=None, max_length=4000)
    reorder_level: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=3)
    supplier_reference: str | None = Field(default=None, max_length=128)


class Receipt(Body):
    item_id: int = Field(gt=0)
    location_id: int = Field(gt=0)
    lot_number: str = Field(min_length=1, max_length=128)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    manufactured_on: date | None = None
    expires_on: date | None = None
    supplier_reference: str | None = Field(default=None, max_length=128)
    receipt_reference: str = Field(min_length=2, max_length=128)
    reason: str = Field(min_length=3, max_length=1000)
    request_key: str = Field(min_length=8, max_length=100)

    @model_validator(mode="after")
    def valid_dates_and_cost(self):
        if self.manufactured_on and self.expires_on and self.expires_on <= self.manufactured_on:
            raise ValueError("Expiry must follow manufacture date")
        if (self.unit_cost is None) != (self.currency is None):
            raise ValueError("Unit cost and currency must be supplied together")
        return self


class Movement(Body):
    expected_version: int = Field(gt=0)
    movement_type: Literal["RESERVE", "RELEASE", "ISSUE", "RETURN", "DAMAGE", "EXPIRY", "QUARANTINE", "RECALL", "ADJUST_IN", "ADJUST_OUT", "TRANSFER"]
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    destination_location_id: int | None = Field(default=None, gt=0)
    workflow_type: str | None = Field(default=None, min_length=2, max_length=32)
    workflow_reference: str | None = Field(default=None, min_length=2, max_length=128)
    related_movement_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=3, max_length=1000)
    reference: str = Field(min_length=2, max_length=128)
    request_key: str = Field(min_length=8, max_length=100)

    @model_validator(mode="after")
    def relationships(self):
        if self.movement_type in {"RESERVE", "RELEASE"} and (not self.workflow_type or not self.workflow_reference):
            raise ValueError("Reservation workflow type and reference are required")
        if self.movement_type == "TRANSFER" and self.destination_location_id is None:
            raise ValueError("Transfer destination is required")
        if self.movement_type != "TRANSFER" and self.destination_location_id is not None:
            raise ValueError("Destination is only accepted for transfers")
        if self.movement_type == "RETURN" and self.related_movement_id is None:
            raise ValueError("Return requires the recorded issue movement ID")
        if self.movement_type != "RETURN" and self.related_movement_id is not None:
            raise ValueError("Related movement is only accepted for returns")
        return self


class CountReport(Body):
    expected_version: int = Field(gt=0)
    counted_quantity: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    reason: str = Field(min_length=3, max_length=1000)


class CountDecision(Body):
    expected_version: int = Field(gt=0)
    decision: Literal["APPROVED", "REJECTED"]
    reason: str = Field(min_length=3, max_length=1000)
    request_key: str = Field(min_length=8, max_length=100)
