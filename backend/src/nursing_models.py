"""Nursing extension to the inpatient contract.

EncounterVitals remains the clinician vital record. Its nonnullable doctor ID
precludes nurse attribution, so nursing observations are append-only here.
"""
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.sql import func

from src.inpatient_models import InpatientBase


def ref(target, nullable=False, unique=False):
    return Column(Integer, ForeignKey(target, ondelete="RESTRICT"), nullable=nullable, unique=unique, index=True)


class NursingObservation(InpatientBase):
    __tablename__ = "nursing_observations"
    id = Column(Integer, primary_key=True)
    admission_id = ref("inpatient_admissions.id")
    patient_id = ref("users.id")
    encounter_id = ref("encounters.id")
    previous_id = ref("nursing_observations.id", nullable=True, unique=True)
    recorded_by_user_id = ref("users.id")
    measured_at = Column(DateTime(timezone=True), nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    systolic_mmhg = Column(Numeric(7, 2))
    diastolic_mmhg = Column(Numeric(7, 2))
    pulse_bpm = Column(Numeric(7, 2))
    respiratory_rate_per_min = Column(Numeric(7, 2))
    temperature_c = Column(Numeric(7, 2))
    spo2_percent = Column(Numeric(5, 2))
    weight_kg = Column(Numeric(7, 2))
    height_cm = Column(Numeric(7, 2))
    correction_reason = Column(Text)
    __table_args__ = (
        CheckConstraint("num_nonnulls(systolic_mmhg,diastolic_mmhg,pulse_bpm,respiratory_rate_per_min,temperature_c,spo2_percent,weight_kg,height_cm) > 0", name="ck_nursing_observation_measurement"),
        CheckConstraint("spo2_percent BETWEEN 0 AND 100", name="ck_nursing_observation_spo2"),
        CheckConstraint("previous_id IS NULL OR correction_reason IS NOT NULL AND length(btrim(correction_reason)) > 0", name="ck_nursing_observation_correction"),
        Index("ix_nursing_observation_admission_time", "admission_id", "measured_at"),
    )


class NursingNote(InpatientBase):
    __tablename__ = "nursing_notes"
    id = Column(Integer, primary_key=True)
    admission_id = ref("inpatient_admissions.id")
    patient_id = ref("users.id")
    encounter_id = ref("encounters.id")
    author_user_id = ref("users.id")
    kind = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("kind IN ('ASSESSMENT','HANDOVER')", name="ck_nursing_note_kind"),
        CheckConstraint("length(btrim(content)) > 0", name="ck_nursing_note_content"),
    )


class NursingCarePlan(InpatientBase):
    __tablename__ = "nursing_care_plans"
    id = Column(Integer, primary_key=True)
    admission_id = ref("inpatient_admissions.id")
    patient_id = ref("users.id")
    encounter_id = ref("encounters.id")
    created_by_user_id = ref("users.id")
    goal = Column(Text, nullable=False)
    intervention = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, server_default=text("'DRAFT'"))
    version = Column(Integer, nullable=False, server_default=text("1"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finalized_at = Column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT','ACTIVE','COMPLETED','CANCELLED')", name="ck_nursing_plan_status"),
        CheckConstraint("version > 0", name="ck_nursing_plan_version"),
        CheckConstraint("length(btrim(goal)) > 0 AND length(btrim(intervention)) > 0", name="ck_nursing_plan_content"),
    )


class NursingTask(InpatientBase):
    __tablename__ = "nursing_tasks"
    id = Column(Integer, primary_key=True)
    plan_id = ref("nursing_care_plans.id")
    admission_id = ref("inpatient_admissions.id")
    patient_id = ref("users.id")
    encounter_id = ref("encounters.id")
    description = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, server_default=text("'PENDING'"))
    version = Column(Integer, nullable=False, server_default=text("1"))
    created_by_user_id = ref("users.id")
    completed_by_user_id = ref("users.id", nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','IN_PROGRESS','DONE','CANCELLED')", name="ck_nursing_task_status"),
        CheckConstraint("version > 0 AND length(btrim(description)) > 0", name="ck_nursing_task_content"),
        CheckConstraint("(status = 'DONE') = (completed_at IS NOT NULL)", name="ck_nursing_task_completion"),
    )


class NursingWorkflowEvent(InpatientBase):
    __tablename__ = "nursing_workflow_events"
    id = Column(Integer, primary_key=True)
    admission_id = ref("inpatient_admissions.id")
    patient_id = ref("users.id")
    encounter_id = ref("encounters.id")
    plan_id = ref("nursing_care_plans.id", nullable=True)
    task_id = ref("nursing_tasks.id", nullable=True)
    sequence = Column(Integer, nullable=False)
    from_status = Column(String(16), nullable=True)
    to_status = Column(String(16), nullable=False)
    actor_user_id = ref("users.id")
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("(plan_id IS NULL) <> (task_id IS NULL)", name="ck_nursing_event_target"),
        Index("uq_nursing_plan_event", "plan_id", "sequence", unique=True),
        Index("uq_nursing_task_event", "task_id", "sequence", unique=True),
    )
