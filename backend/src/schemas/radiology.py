from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class ImagingOrderCreate(BaseModel):
    model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)
    patient_id:int=Field(gt=0); encounter_id:int=Field(gt=0)
    priority:Literal["ROUTINE","URGENT","STAT"]="ROUTINE"
    procedure_code:str|None=Field(default=None,max_length=64)
    requested_procedure:str=Field(min_length=1,max_length=255)
    modality:str=Field(min_length=1,max_length=32)
    body_region:str=Field(min_length=1,max_length=128)
    clinical_indication:str|None=Field(default=None,max_length=4000)

class RadiologyTransition(BaseModel):
    model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)
    expected_version:int=Field(ge=0)
    status:Literal["ACCEPTED","CLARIFICATION_REQUESTED","REJECTED","SCHEDULED","READY_FOR_IMAGING","ACQUISITION_IN_PROGRESS","ACQUISITION_COMPLETED","INTERPRETATION_IN_PROGRESS","CANCELLED"]
    reason:str|None=Field(default=None,min_length=1,max_length=4000)
    scheduled_at:datetime|None=None
    study_identifier:str|None=Field(default=None,min_length=1,max_length=128)
    @model_validator(mode="after")
    def fields_for_action(self):
        if self.status in {"CLARIFICATION_REQUESTED","REJECTED","CANCELLED"} and not self.reason: raise ValueError("A reason is required")
        if self.status=="SCHEDULED" and self.scheduled_at is None: raise ValueError("Scheduling requires a timestamp")
        if self.status=="ACQUISITION_IN_PROGRESS" and not self.study_identifier: raise ValueError("Acquisition requires a study identifier")
        if self.status!="SCHEDULED" and self.scheduled_at is not None: raise ValueError("scheduled_at is accepted only for scheduling")
        if self.status!="ACQUISITION_IN_PROGRESS" and self.study_identifier is not None: raise ValueError("study_identifier is accepted only when acquisition begins")
        return self

class RadiologyReportCreate(BaseModel):
    model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)
    expected_workflow_version:int=Field(ge=1); study_id:int=Field(gt=0)
    findings:str=Field(min_length=1,max_length=20000); impression:str=Field(min_length=1,max_length=10000)
    amendment_reason:str|None=Field(default=None,min_length=1,max_length=4000)

class RadiologyReportTransition(BaseModel):
    model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)
    expected_workflow_version:int=Field(ge=1); expected_report_version:int=Field(ge=1)
    status:Literal["VERIFIED","FINALIZED","REJECTED"]
    comment:str|None=Field(default=None,min_length=1,max_length=4000)
    @model_validator(mode="after")
    def rejection_reason(self):
        if self.status=="REJECTED" and not self.comment: raise ValueError("Rejecting a report requires a comment")
        return self

class RadiologyQueueResponse(BaseModel):
    items:list[dict]; total:int
