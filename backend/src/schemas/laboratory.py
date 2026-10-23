from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


LabWorkflowStatus = Literal[
    "ACCEPTED", "CLARIFICATION_REQUESTED", "REJECTED", "COLLECTION_PENDING",
    "COLLECTED", "RECEIVED", "SPECIMEN_REJECTED", "PROCESSING",
]


class LaboratoryWorkflowTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_version: int = Field(ge=0)
    status: LabWorkflowStatus
    reason: str | None = Field(default=None, min_length=1, max_length=4000)
    specimen_identifier: str | None = Field(default=None, min_length=1, max_length=128)
    specimen_type: str | None = Field(default=None, min_length=1, max_length=128)
    recollection_requested: bool = False

    @model_validator(mode="after")
    def validate_action_fields(self):
        reason_required = self.status in {"CLARIFICATION_REQUESTED", "REJECTED", "SPECIMEN_REJECTED"}
        if reason_required and not self.reason:
            raise ValueError("A reason is required for this transition")
        collecting = self.status == "COLLECTED"
        if collecting and (not self.specimen_identifier or not self.specimen_type):
            raise ValueError("Collection requires a specimen identifier and type")
        if not collecting and (self.specimen_identifier is not None or self.specimen_type is not None):
            raise ValueError("Specimen fields are accepted only when recording collection")
        if self.recollection_requested and self.status != "SPECIMEN_REJECTED":
            raise ValueError("Recollection can be requested only when rejecting a specimen")
        return self


class LaboratoryResultCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_workflow_version: int = Field(ge=1)
    specimen_id: int = Field(gt=0)
    test_identifier: str = Field(min_length=1, max_length=128)
    test_name: str = Field(min_length=1, max_length=255)
    result_value: str = Field(min_length=1, max_length=255)
    result_unit: str | None = Field(default=None, max_length=64)
    correction_reason: str | None = Field(default=None, min_length=1, max_length=4000)


class LaboratoryResultTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_workflow_version: int = Field(ge=1)
    expected_result_version: int = Field(ge=1)
    status: Literal["REJECTED", "VERIFIED", "FINALIZED"]
    comment: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def rejection_requires_comment(self):
        if self.status == "REJECTED" and not self.comment:
            raise ValueError("Rejecting a result requires a comment")
        return self


class LaboratoryQueueResponse(BaseModel):
    items: list[dict]
    total: int
