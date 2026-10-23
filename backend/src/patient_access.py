"""Patient-scoped read authorization shared by chart, reports, and history.

Confirmed appointments permit preparation demographics only. Longitudinal
clinical records require an active encounter assigned to an active clinician.
"""
from enum import Enum

from fastapi import HTTPException

from src.models import Appointment, Doctor, Encounter, User


class PatientAccess(str, Enum):
    SELF = "self"
    PREPARATION = "preparation"
    CLINICAL = "clinical"


PATIENT_ROLES = {"patient", "user"}
CLINICIAN_ROLES = {"doctor", "emergency_doctor"}


def patient_read_access(db, actor, patient_id: int) -> PatientAccess:
    """Return the narrowest valid scope without trusting client-supplied role.

    Unknown patients and unauthorized patient IDs have the same 404 result.
    This helper must run before any protected content query or serialization.
    """
    user = db.get(User, actor.user_id)
    if not user or not user.password_hash or user.role != actor.role:
        raise HTTPException(401, "An eligible portal account is required")

    if user.role in PATIENT_ROLES:
        if patient_id != user.id:
            raise HTTPException(404, "Patient record not found")
        return PatientAccess.SELF

    if user.role not in CLINICIAN_ROLES:
        raise HTTPException(404, "Patient record not found")

    doctor = db.query(Doctor).filter(
        Doctor.user_id == user.id,
        Doctor.status == "Active",
    ).first()
    if doctor is None:
        raise HTTPException(404, "Patient record not found")

    assigned_visit = db.query(Encounter.id).filter(
        Encounter.patient_id == patient_id,
        Encounter.doctor_id == doctor.id,
        Encounter.status.in_(("CHECKED_IN", "IN_PROGRESS")),
    ).first()
    if assigned_visit:
        return PatientAccess.CLINICAL

    confirmed_appointment = db.query(Appointment.id).filter(
        Appointment.patient_id == patient_id,
        Appointment.doctor_id == doctor.id,
        Appointment.status == "CONFIRMED",
    ).first()
    if confirmed_appointment:
        return PatientAccess.PREPARATION

    raise HTTPException(404, "Patient record not found")


def require_clinical_history(db, actor, patient_id: int) -> PatientAccess:
    access = patient_read_access(db, actor, patient_id)
    if access == PatientAccess.PREPARATION:
        raise HTTPException(404, "Patient record not found")
    return access
