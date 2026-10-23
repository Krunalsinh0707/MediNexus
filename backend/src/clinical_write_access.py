"""Server-owned authorization for writes to a patient's clinical record."""
from fastapi import HTTPException

from src.models import Doctor, Encounter, ReportReviewRequest, User


CLINICIAN_ROLES = {"doctor", "emergency_doctor"}


def active_clinician(db, actor):
    user = db.get(User, actor.user_id)
    if user is None or not user.password_hash or user.role != actor.role:
        raise HTTPException(401, "An eligible portal account is required")
    if user.role not in CLINICIAN_ROLES:
        raise HTTPException(403, "An active clinician is required")
    doctor = db.query(Doctor).filter(Doctor.user_id == user.id, Doctor.status == "Active").first()
    if doctor is None:
        raise HTTPException(403, "An active clinician profile is required")
    return doctor


def in_progress_visit(db, patient_id, doctor_id):
    return db.query(Encounter).filter(
        Encounter.patient_id == patient_id,
        Encounter.doctor_id == doctor_id,
        Encounter.status == "IN_PROGRESS",
    ).first()


def require_report_creation(db, actor, patient_id, department_id):
    doctor = active_clinician(db, actor)
    visit = in_progress_visit(db, patient_id, doctor.id)
    if visit is None:
        raise HTTPException(404, "An assigned in-progress visit is required for this patient")
    if visit.department_id != department_id or doctor.department_id != department_id:
        raise HTTPException(422, "Report department must match the assigned visit and clinician")
    return doctor


def require_report_review(db, actor, report, doctor=None):
    doctor = doctor or active_clinician(db, actor)
    if in_progress_visit(db, report.patient_id, doctor.id):
        return doctor
    assignment = db.query(ReportReviewRequest.id).filter(
        ReportReviewRequest.report_id == report.id,
        ReportReviewRequest.patient_id == report.patient_id,
        ReportReviewRequest.doctor_id == doctor.id,
        ReportReviewRequest.status.in_(("PENDING", "IN_REVIEW")),
    ).first()
    if assignment is None:
        raise HTTPException(404, "Report review assignment not found")
    return doctor
