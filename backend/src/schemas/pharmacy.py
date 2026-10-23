from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PharmacyStatus = Literal[
    "ACCEPTED", "CLARIFICATION_REQUESTED", "REJECTED", "IN_PROGRESS",
    "PARTIALLY_DISPENSED", "COMPLETED",
]


class PharmacyTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_version: int = Field(ge=0)
    status: PharmacyStatus
    reason: str | None = Field(default=None, min_length=1, max_length=4000)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    quantity_unit: str | None = Field(default=None, min_length=1, max_length=64)
    stock_item_identifier: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def fields_match_action(self):
        if self.status in {"CLARIFICATION_REQUESTED", "REJECTED"} and not self.reason:
            raise ValueError("A reason is required for rejection or clarification")
        dispensing = self.status in {"PARTIALLY_DISPENSED", "COMPLETED"}
        supplied = (self.quantity, self.quantity_unit, self.stock_item_identifier)
        if dispensing and any(value is None for value in supplied):
            raise ValueError("Dispensing requires quantity, unit, and stock item identifier")
        if not dispensing and any(value is not None for value in supplied):
            raise ValueError("Dispensing fields are accepted only for a dispensing action")
        return self


class PharmacyQueueResponse(BaseModel):
    items: list[dict]
    total: int
