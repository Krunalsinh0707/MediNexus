"""Outpatient visits and attributed clinical revisions; identity stays in users."""
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from src.model_base import Base


def reference(target, nullable=False, unique=False):
    return Column(Integer, ForeignKey(target, ondelete="RESTRICT"), nullable=nullable, unique=unique, index=True)


class Encounter(Base):
    __tablename__ = "encounters"
    id = Column(Integer, primary_key=True)
    patient_id = reference("users.id")
    appointment_id = reference("appointments.id", nullable=True, unique=True)
    doctor_id = reference("doctors.id", nullable=True)
    department_id = reference("departments.id", nullable=True)
    created_by_user_id = reference("users.id")
    creation_key = Column(String(64), nullable=False)
    creation_fingerprint = Column(String(64), nullable=False)
    chief_complaint = Column(Text, nullable=True)
    status = Column(String(24), nullable=False, server_default=text("'CHECKED_IN'"))
    version = Column(Integer, nullable=False, server_default=text("1"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    checked_in_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    cancelled_at = Column(DateTime(timezone=True))
    cancellation_reason = Column(Text)
    __table_args__ = (
        UniqueConstraint("created_by_user_id", "creation_key", name="uq_encounter_creation_request"),
        CheckConstraint("status IN ('CHECKED_IN','IN_PROGRESS','COMPLETED','CANCELLED')", name="ck_encounter_status"),
        CheckConstraint("version > 0", name="ck_encounter_version"),
        CheckConstraint("status NOT IN ('IN_PROGRESS','COMPLETED') OR (doctor_id IS NOT NULL AND started_at IS NOT NULL)", name="ck_encounter_started"),
        CheckConstraint("(status = 'COMPLETED') = (completed_at IS NOT NULL)", name="ck_encounter_completed"),
        CheckConstraint("(status = 'CANCELLED') = (cancelled_at IS NOT NULL)", name="ck_encounter_cancelled"),
        CheckConstraint("status <> 'CANCELLED' OR length(btrim(cancellation_reason)) > 0 AND cancellation_reason IS NOT NULL", name="ck_encounter_cancel_reason"),
        Index("ix_encounter_patient_created", "patient_id", "created_at"),
        Index("ix_encounter_doctor_status", "doctor_id", "status"),
    )


class EncounterNote(Base):
    __tablename__ = "encounter_notes"
    id = Column(Integer, primary_key=True)
    encounter_id = reference("encounters.id")
    revision = Column(Integer, nullable=False)
    previous_id = reference("encounter_notes.id", nullable=True, unique=True)
    kind = Column(String(16), nullable=False, server_default=text("'CONSULTATION'"))
    subjective = Column(Text, nullable=False, server_default=text("''"))
    objective = Column(Text, nullable=False, server_default=text("''"))
    assessment = Column(Text, nullable=False, server_default=text("''"))
    plan = Column(Text, nullable=False, server_default=text("''"))
    patient_summary = Column(Text, nullable=False, server_default=text("''"))
    reason = Column(Text)
    author_user_id = reference("users.id")
    author_doctor_id = reference("doctors.id")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    signed_at = Column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("encounter_id", "revision", name="uq_encounter_note_revision"),
        CheckConstraint("revision > 0", name="ck_note_revision"),
        CheckConstraint("kind IN ('CONSULTATION','ADDENDUM')", name="ck_note_kind"),
        CheckConstraint("kind <> 'ADDENDUM' OR (signed_at IS NOT NULL AND reason IS NOT NULL AND length(btrim(reason)) > 0)", name="ck_addendum_attribution"),
    )


class EncounterVitals(Base):
    __tablename__ = "encounter_vitals"
    id = Column(Integer, primary_key=True)
    encounter_id = reference("encounters.id")
    previous_id = reference("encounter_vitals.id", nullable=True, unique=True)
    recorded_by_user_id = reference("users.id")
    recorded_by_doctor_id = reference("doctors.id")
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
    reason = Column(Text)
    __table_args__ = (
        CheckConstraint("num_nonnulls(systolic_mmhg,diastolic_mmhg,pulse_bpm,respiratory_rate_per_min,temperature_c,spo2_percent,weight_kg,height_cm) > 0", name="ck_vitals_measurement"),
        CheckConstraint("spo2_percent BETWEEN 0 AND 100", name="ck_vitals_spo2"),
        CheckConstraint("previous_id IS NULL OR (reason IS NOT NULL AND length(btrim(reason)) > 0)", name="ck_vitals_correction_reason"),
    )


class EncounterDiagnosis(Base):
    __tablename__ = "encounter_diagnoses"
    id = Column(Integer, primary_key=True)
    encounter_id = reference("encounters.id")
    previous_id = reference("encounter_diagnoses.id", nullable=True, unique=True)
    recorded_by_user_id = reference("users.id")
    recorded_by_doctor_id = reference("doctors.id")
    description = Column(Text, nullable=False)
    coding_system = Column(String(64))
    code = Column(String(64))
    status = Column(String(24), nullable=False, server_default=text("'PROVISIONAL'"))
    is_primary = Column(Boolean, nullable=False, server_default=text("false"))
    reason = Column(Text)
    recorded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("length(btrim(description)) > 0", name="ck_diagnosis_description"),
        CheckConstraint("status IN ('PROVISIONAL','CONFIRMED','ENTERED_IN_ERROR')", name="ck_diagnosis_status"),
        CheckConstraint("(code IS NULL) = (coding_system IS NULL)", name="ck_diagnosis_code_system"),
        CheckConstraint("previous_id IS NULL OR (reason IS NOT NULL AND length(btrim(reason)) > 0)", name="ck_diagnosis_correction_reason"),
    )


class PatientAllergy(Base):
    __tablename__ = "patient_allergies"
    id = Column(Integer, primary_key=True)
    patient_id = reference("users.id")
    source_encounter_id = reference("encounters.id")
    previous_id = reference("patient_allergies.id", nullable=True, unique=True)
    substance = Column(String(255), nullable=False)
    reaction = Column(Text)
    severity = Column(String(16), nullable=False, server_default=text("'UNKNOWN'"))
    status = Column(String(24), nullable=False, server_default=text("'ACTIVE'"))
    reason = Column(Text)
    recorded_by_user_id = reference("users.id")
    recorded_by_doctor_id = reference("doctors.id")
    recorded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("length(btrim(substance)) > 0", name="ck_allergy_substance"),
        CheckConstraint("severity IN ('UNKNOWN','MILD','MODERATE','SEVERE')", name="ck_allergy_severity"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE','ENTERED_IN_ERROR')", name="ck_allergy_status"),
        CheckConstraint("previous_id IS NULL OR (reason IS NOT NULL AND length(btrim(reason)) > 0)", name="ck_allergy_correction_reason"),
    )


class EncounterAllergyReview(Base):
    __tablename__ = "encounter_allergy_reviews"
    id = Column(Integer, primary_key=True)
    encounter_id = reference("encounters.id")
    encounter_version = Column(Integer, nullable=False)
    outcome = Column(String(16), nullable=False)
    snapshot = Column(JSONB, nullable=False)
    reviewed_by_user_id = reference("users.id")
    reviewed_by_doctor_id = reference("doctors.id")
    reviewed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("encounter_id", "encounter_version", name="uq_encounter_allergy_review_version"),
        CheckConstraint("outcome IN ('UNKNOWN','NO_KNOWN','RECORDED')", name="ck_allergy_review_outcome"),
    )
