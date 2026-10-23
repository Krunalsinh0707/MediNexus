"""Explicit projections for the read-only patient history API."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HistoryEvent(BaseModel):
    id: str
    kind: str
    occurred_at: datetime
    title: str
    summary: str | None = None
    provenance: str
    encounter_id: int | None = None
    report_id: int | None = None
    clinician_user_id: int | None = None
    status: str | None = None
    corrected: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class HistoryPage(BaseModel):
    items: list[HistoryEvent]
    next_cursor: str | None = None
