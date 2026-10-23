"""Attributed outpatient workflows. Callers own commit/rollback.

Write lock order: appointment (if any), patient, encounter. Clinical writes are
append-only, except signing the final draft in the completion transaction.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import exists, or_, select, text
from sqlalchemy.orm import aliased

from src.models import (
    Appointment, AuditLog, Department, Doctor, User, MedicalRecord,
    Encounter, EncounterNote, EncounterVitals, EncounterDiagnosis,
    PatientAllergy, EncounterAllergyReview,
)

ADMIN_ROLES = {"admin", "hospital_admin"}
CLINICAL_ROLES = {"doctor", "emergency_doctor"}
PATIENT_ROLES = {"user", "patient"}


def fail(code, message):
    raise HTTPException(status_code=code, detail=message)


@dataclass(frozen=True)
class Actor:
    user_id: int
    role: str
    doctor_id: int | None = None


def actor_for(db, token):
    # Re-read authoritative role: never grant clinical access from JWT fallback.
    user = db.get(User, token.user_id)
    if user is None or not user.password_hash or not user.role:
        fail(401, "An eligible portal account is required")
    doctor_id = None
    if user.role in CLINICAL_ROLES:
        doctor = db.query(Doctor).filter(Doctor.user_id == user.id, Doctor.status == "Active").first()
        if doctor is None:
            fail(403, "An active clinician profile is required")
        doctor_id = doctor.id
    elif user.role not in ADMIN_ROLES | PATIENT_ROLES:
        fail(403, "Encounter access is not permitted for this role")
    return Actor(user.id, user.role, doctor_id)


def now():
    return datetime.now(timezone.utc)


def active_doctor(db, doctor_id):
    doctor = db.query(Doctor).join(User, User.id == Doctor.user_id).filter(
        Doctor.id == doctor_id, Doctor.status == "Active",
        User.role.in_(CLINICAL_ROLES), User.password_hash.is_not(None),
    ).first()
    if doctor is None:
        fail(422, "Select an active clinician with an eligible portal account")
    return doctor


def assigned_clinician(actor, encounter):
    if actor.role not in CLINICAL_ROLES or actor.doctor_id != encounter.doctor_id:
        fail(403, "Only the assigned active clinician can write clinical records")


def version_matches(encounter, expected):
    if encounter.version != expected:
        fail(409, "This visit changed. Reload it before retrying; your changes were not saved")


def audit(db, actor, encounter, action):
    db.add(AuditLog(user_id=actor.user_id, action="Encounter " + action, status="Success", details={
        "encounter_id": encounter.id, "patient_id": encounter.patient_id,
        "version": encounter.version, "status": encounter.status,
        "doctor_id": encounter.doctor_id, "department_id": encounter.department_id,
        "appointment_id": encounter.appointment_id,
    }))


def lock_encounter(db, encounter_id, actor, expected):
    # Read immutable link IDs, then acquire locks in the shared order.
    link = db.execute(select(Encounter.patient_id, Encounter.appointment_id).where(Encounter.id == encounter_id)).first()
    if link is None:
        fail(404, "Visit not found")
    if link.appointment_id is not None:
        db.query(Appointment).filter(Appointment.id == link.appointment_id).with_for_update().populate_existing().one()
    db.query(User).filter(User.id == link.patient_id).with_for_update().populate_existing().one()
    encounter = db.query(Encounter).filter(Encounter.id == encounter_id).with_for_update().populate_existing().one()
    if actor.role not in ADMIN_ROLES:
        assigned_clinician(actor, encounter)
    version_matches(encounter, expected)
    return encounter


def clinical_write(db, encounter_id, actor, expected, completed=False):
    encounter = lock_encounter(db, encounter_id, actor, expected)
    assigned_clinician(actor, encounter)
    if encounter.status != ("COMPLETED" if completed else "IN_PROGRESS"):
        fail(409, "Visit is not in the required state for this clinical action")
    return encounter


def touched(db, actor, encounter, action):
    encounter.version += 1
    audit(db, actor, encounter, action)
    db.flush()
    return encounter


def create_encounter(db, actor, data):
    if actor.role not in ADMIN_ROLES | CLINICAL_ROLES:
        fail(403, "Staff check-in is required")
    if actor.role in CLINICAL_ROLES and data.appointment_id is None:
        fail(403, "Clinicians may check in only their own confirmed appointments")
    fingerprint = hashlib.sha256(json.dumps(data.model_dump(exclude={"creation_key"}), sort_keys=True).encode()).hexdigest()
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key)::bigint)"), {"key": f"encounter:{actor.user_id}:{data.creation_key}"})
    prior = db.query(Encounter).filter(Encounter.created_by_user_id == actor.user_id, Encounter.creation_key == data.creation_key).first()
    if prior:
        if prior.creation_fingerprint != fingerprint:
            fail(409, "Check-in key was already used with different details")
        return prior
    appointment = None
    doctor_id, department_id = data.doctor_id, data.department_id
    if data.appointment_id:
        appointment = db.query(Appointment).filter(Appointment.id == data.appointment_id).with_for_update().populate_existing().first()
        if appointment is None:
            fail(404, "Appointment not found")
        if appointment.patient_id != data.patient_id:
            fail(422, "Appointment does not belong to this patient")
        if actor.role in CLINICAL_ROLES and appointment.doctor_id != actor.doctor_id:
            fail(403, "Appointment is not assigned to this clinician")
        if appointment.status != "CONFIRMED":
            fail(409, "Check-in requires a confirmed appointment")
        if doctor_id not in (None, appointment.doctor_id) or department_id not in (None, appointment.department_id):
            fail(422, "Visit assignment must agree with the linked appointment")
        if db.query(Encounter.id).filter(Encounter.appointment_id == appointment.id).first():
            fail(409, "This appointment already has a visit")
        doctor_id, department_id = appointment.doctor_id, appointment.department_id
    patient = db.query(User).filter(User.id == data.patient_id).with_for_update().populate_existing().first()
    if patient is None or patient.role not in PATIENT_ROLES or not patient.mrn:
        fail(422, "Select a registered patient with an MRN")
    if doctor_id:
        doctor = active_doctor(db, doctor_id)
        if department_id not in (None, doctor.department_id):
            fail(422, "Clinician does not belong to the selected department")
        department_id = doctor.department_id
    if department_id and db.get(Department, department_id) is None:
        fail(422, "Department not found")
    encounter = Encounter(patient_id=patient.id, appointment_id=data.appointment_id,
        doctor_id=doctor_id, department_id=department_id, created_by_user_id=actor.user_id,
        creation_key=data.creation_key, creation_fingerprint=fingerprint,
        chief_complaint=data.chief_complaint, status="CHECKED_IN", version=1)
    db.add(encounter)
    db.flush()
    audit(db, actor, encounter, "checked in")
    return encounter


def assign(db, actor, encounter_id, data):
    if actor.role not in ADMIN_ROLES:
        fail(403, "Only registration staff can assign a visit")
    encounter = lock_encounter(db, encounter_id, actor, data.expected_version)
    if encounter.status != "CHECKED_IN":
        fail(409, "Assignment is fixed after the visit starts")
    doctor = active_doctor(db, data.doctor_id)
    if encounter.appointment_id:
        appointment = db.get(Appointment, encounter.appointment_id)
        if doctor.id != appointment.doctor_id:
            fail(409, "A linked visit must retain its appointment clinician")
    encounter.doctor_id, encounter.department_id = doctor.id, doctor.department_id
    return touched(db, actor, encounter, "assigned")


def latest_rows(db, model, **filters):
    successor = aliased(model)
    return db.query(model).filter(*[getattr(model, k) == v for k, v in filters.items()]).filter(
        ~exists(select(successor.id).where(successor.previous_id == model.id))
    ).order_by(model.id).all()


def allergy_snapshot(db, patient_id):
    return [{"id": row.id, "previous_id": row.previous_id, "substance": row.substance,
        "reaction": row.reaction, "severity": row.severity, "status": row.status,
        "source_encounter_id": row.source_encounter_id,
        "recorded_by_user_id": row.recorded_by_user_id, "recorded_by_doctor_id": row.recorded_by_doctor_id,
        "recorded_at": row.recorded_at.isoformat()}
        for row in latest_rows(db, PatientAllergy, patient_id=patient_id)]


def transition(db, actor, encounter_id, data):
    encounter = lock_encounter(db, encounter_id, actor, data.expected_version)
    target, source = data.status, encounter.status
    if source in {"COMPLETED", "CANCELLED"}:
        fail(409, "A finished visit cannot be reopened")
    if target == "IN_PROGRESS":
        assigned_clinician(actor, encounter)
        if source != "CHECKED_IN":
            fail(409, "Only a checked-in visit can be started")
        encounter.started_at = now()
    elif target == "CANCELLED":
        if source == "IN_PROGRESS":
            assigned_clinician(actor, encounter)
        if not data.reason:
            fail(422, "Cancellation requires a reason")
        encounter.cancelled_at, encounter.cancellation_reason = now(), data.reason
    elif target == "COMPLETED":
        assigned_clinician(actor, encounter)
        if source != "IN_PROGRESS":
            fail(409, "Only an in-progress visit can be completed")
        note = db.query(EncounterNote).filter(EncounterNote.encounter_id == encounter.id).order_by(EncounterNote.revision.desc()).first()
        if note is None or not note.assessment.strip() or not note.plan.strip() or not note.patient_summary.strip():
            fail(422, "Completion requires a final note with assessment, plan and patient summary")
        review = db.query(EncounterAllergyReview).filter(EncounterAllergyReview.encounter_id == encounter.id).order_by(EncounterAllergyReview.id.desc()).first()
        if review is None or review.snapshot != allergy_snapshot(db, encounter.patient_id):
            fail(409, "Review current allergies explicitly before completing this visit")
        if note.signed_at is not None or note.author_doctor_id != actor.doctor_id:
            fail(409, "The final unsigned note must belong to the assigned clinician")
        note.signed_at = now()
        encounter.completed_at = note.signed_at
    else:
        fail(422, "Unsupported transition")
    if encounter.appointment_id:
        appointment = db.get(Appointment, encounter.appointment_id)
        if appointment.status != "CONFIRMED":
            fail(409, "Linked appointment state changed; resolve the conflict before continuing")
        if target in {"COMPLETED", "CANCELLED"}:
            appointment.status = target
    encounter.status = target
    return touched(db, actor, encounter, target.lower())


def write_note(db, actor, encounter_id, data, addendum=False):
    encounter = clinical_write(db, encounter_id, actor, data.expected_version, completed=addendum)
    previous = db.query(EncounterNote).filter(EncounterNote.encounter_id == encounter.id).order_by(EncounterNote.revision.desc()).first()
    if addendum and not (data.assessment or data.plan or data.patient_summary or data.subjective or data.objective):
        fail(422, "Addendum cannot be empty")
    row = EncounterNote(encounter_id=encounter.id, revision=previous.revision + 1 if previous else 1,
        previous_id=previous.id if previous else None, kind="ADDENDUM" if addendum else "CONSULTATION",
        author_user_id=actor.user_id, author_doctor_id=actor.doctor_id,
        signed_at=now() if addendum else None, **data.model_dump(exclude={"expected_version"}))
    db.add(row)
    return touched(db, actor, encounter, "addendum signed" if addendum else "note revision saved")


def write_observation(db, actor, encounter_id, data, model):
    encounter = clinical_write(db, encounter_id, actor, data.expected_version)
    if data.previous_id:
        previous = db.get(model, data.previous_id)
        belongs = previous is not None and (previous.patient_id == encounter.patient_id if model is PatientAllergy else previous.encounter_id == encounter.id)
        if not belongs:
            fail(404, "Original observation not found for this patient/visit")
        if db.query(model.id).filter(model.previous_id == previous.id).first():
            fail(409, "This observation has already been corrected; reload the current revision")
    if model is EncounterDiagnosis and data.is_primary and data.status != "ENTERED_IN_ERROR":
        if any(row.is_primary and row.status != "ENTERED_IN_ERROR" and row.id != data.previous_id for row in latest_rows(db, model, encounter_id=encounter.id)):
            fail(409, "Correct the existing primary diagnosis before selecting another")
    fields = data.model_dump(exclude={"expected_version"})
    fields.update(recorded_by_user_id=actor.user_id, recorded_by_doctor_id=actor.doctor_id)
    if model is PatientAllergy:
        fields.update(patient_id=encounter.patient_id, source_encounter_id=encounter.id)
    else:
        fields.update(encounter_id=encounter.id)
    db.add(model(**fields))
    return touched(db, actor, encounter, model.__tablename__ + " recorded")


def review_allergies(db, actor, encounter_id, data):
    encounter = clinical_write(db, encounter_id, actor, data.expected_version)
    snapshot = allergy_snapshot(db, encounter.patient_id)
    active = [row for row in snapshot if row["status"] == "ACTIVE"]
    if data.outcome == "NO_KNOWN" and active:
        fail(409, "Active allergy records prevent a no-known-allergies assertion")
    if data.outcome == "RECORDED" and not active:
        fail(422, "No active allergies are recorded; choose unknown or explicitly no known allergies")
    db.add(EncounterAllergyReview(encounter_id=encounter.id, encounter_version=encounter.version + 1,
        outcome=data.outcome, snapshot=snapshot, reviewed_by_user_id=actor.user_id, reviewed_by_doctor_id=actor.doctor_id))
    return touched(db, actor, encounter, "allergies reviewed")


def readable_query(db, actor, patient_id=None):
    query = db.query(Encounter)
    if actor.role in ADMIN_ROLES:
        pass
    elif actor.role in CLINICAL_ROLES:
        if patient_id is not None:
            assigned = db.query(Encounter.id).filter(Encounter.patient_id == patient_id, Encounter.doctor_id == actor.doctor_id,
                Encounter.status.in_(("CHECKED_IN", "IN_PROGRESS"))).first()
            if assigned:
                query = query.filter(or_(Encounter.doctor_id == actor.doctor_id, Encounter.status == "COMPLETED"))
            else:
                query = query.filter(Encounter.doctor_id == actor.doctor_id)
        else:
            query = query.filter(Encounter.doctor_id == actor.doctor_id)
    elif actor.role in PATIENT_ROLES:
        query = query.filter(Encounter.patient_id == actor.user_id, Encounter.status == "COMPLETED")
    else:
        fail(403, "Encounter access is not permitted")
    if patient_id is not None:
        query = query.filter(Encounter.patient_id == patient_id)
    return query


def readable(db, actor, encounter_id):
    # Restrict before loading any clinical contents.
    patient_id = db.query(Encounter.patient_id).filter(Encounter.id == encounter_id).scalar()
    encounter = readable_query(db, actor, patient_id).filter(Encounter.id == encounter_id).first() if patient_id else None
    if encounter is None:
        fail(404, "Visit not found")
    return encounter


def fields(row, names):
    return {name: getattr(row, name) for name in names.split()}


def overview(db, encounter):
    patient = db.get(User, encounter.patient_id)
    result = fields(encounter, "id patient_id appointment_id doctor_id department_id status version created_at checked_in_at started_at completed_at cancelled_at")
    result.update(patient_name=patient.full_name, mrn=patient.mrn)
    return result


def detail(db, actor, encounter):
    result = overview(db, encounter)
    if actor.role in ADMIN_ROLES:
        return result
    if actor.role in PATIENT_ROLES:
        notes = db.query(EncounterNote).filter(EncounterNote.encounter_id == encounter.id, EncounterNote.signed_at.is_not(None)).order_by(EncounterNote.revision).all()
        result["summaries"] = [fields(note, "id revision kind patient_summary author_doctor_id signed_at") for note in notes]
        return result
    result.update(chief_complaint=encounter.chief_complaint, cancellation_reason=encounter.cancellation_reason)
    result["notes"] = [fields(row, "id revision previous_id kind subjective objective assessment plan patient_summary reason author_user_id author_doctor_id created_at signed_at")
        for row in db.query(EncounterNote).filter(EncounterNote.encounter_id == encounter.id).order_by(EncounterNote.revision).all()]
    result["vitals"] = [fields(row, "id previous_id systolic_mmhg diastolic_mmhg pulse_bpm respiratory_rate_per_min temperature_c spo2_percent weight_kg height_cm reason measured_at recorded_at recorded_by_user_id recorded_by_doctor_id")
        for row in db.query(EncounterVitals).filter(EncounterVitals.encounter_id == encounter.id).order_by(EncounterVitals.id).all()]
    result["diagnoses"] = [fields(row, "id previous_id description coding_system code status is_primary reason recorded_at recorded_by_user_id recorded_by_doctor_id")
        for row in db.query(EncounterDiagnosis).filter(EncounterDiagnosis.encounter_id == encounter.id).order_by(EncounterDiagnosis.id).all()]
    result["allergy_reviews"] = [fields(row, "id encounter_version outcome snapshot reviewed_by_user_id reviewed_by_doctor_id reviewed_at")
        for row in db.query(EncounterAllergyReview).filter(EncounterAllergyReview.encounter_id == encounter.id).order_by(EncounterAllergyReview.id).all()]
    return result


def allergy_context(db, actor, encounter):
    if actor.role not in CLINICAL_ROLES:
        fail(403, "Clinical allergy context requires an assigned clinician")
    patient = db.get(User, encounter.patient_id)
    profile = patient.profile_data if isinstance(patient.profile_data, dict) else {}
    clinical = profile.get("clinical") if isinstance(profile.get("clinical"), dict) else {}
    legacy = [value for value in (profile.get("allergies"), clinical.get("allergies")) if isinstance(value, str) and value.strip()]
    legacy += [row.allergies for row in db.query(MedicalRecord).filter(MedicalRecord.patient_id == patient.id).all() if row.allergies]
    return {"current_records": allergy_snapshot(db, patient.id), "legacy_unverified": legacy,
        "message": "Legacy text and absent records do not establish no known allergies. Review explicitly for this visit."}


def refuse_linked_appointment_change(db, appointment_id):
    # Caller locks the appointment first, serializing against encounter creation.
    if db.query(Encounter.id).filter(Encounter.appointment_id == appointment_id).first():
        fail(409, "This appointment has a visit. Manage completion or cancellation in the visit workspace; rescheduling is unavailable")
