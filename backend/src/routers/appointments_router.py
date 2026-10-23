from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from src.database import get_db
from src.models import Appointment, Doctor, Department, User, Notification, AuditLog
from src.auth import get_current_user
from src.security.rate_limiter import rate_limit
from src.encounter_service import refuse_linked_appointment_change

router = APIRouter(prefix="/appointments", tags=["Appointments"])

ALLOWED_APPOINTMENT_STATUSES = {"REQUESTED", "CONFIRMED", "REJECTED", "CANCELLED", "COMPLETED", "NO_SHOW"}
APPOINTMENT_TRANSITIONS = {
    "REQUESTED": {"CONFIRMED", "REJECTED", "CANCELLED"},
    "CONFIRMED": {"CANCELLED", "COMPLETED", "NO_SHOW"},
}

class AppointmentCreate(BaseModel):
    doctor_id: int
    department_id: Optional[int] = None
    appointment_date: str # ISO format string e.g. "2026-08-15 10:00:00"
    time_slot: str
    reason: Optional[str] = None

class AppointmentStatusUpdate(BaseModel):
    status: str # CONFIRMED, REJECTED, CANCELLED, COMPLETED
    notes: Optional[str] = None

@router.post("")
def book_appointment(
    data: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _limiter: None = Depends(rate_limit(max_requests=15, window_seconds=60, prefix="book_app"))
):
    doctor = db.query(Doctor).filter(Doctor.id == data.doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    if data.department_id:
        dept = db.query(Department).filter(Department.id == data.department_id).first()
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found")
        if doctor.department_id != data.department_id:
            raise HTTPException(status_code=400, detail="Doctor does not belong to the selected department")

    try:
        if "T" in data.appointment_date or " " in data.appointment_date:
            app_date = datetime.fromisoformat(data.appointment_date.replace("Z", "+00:00"))
        else:
            app_date = datetime.strptime(data.appointment_date, "%Y-%m-%d")
    except Exception:
        app_date = datetime.now()

    new_app = Appointment(
        patient_id=current_user.user_id,
        doctor_id=data.doctor_id,
        department_id=data.department_id or doctor.department_id,
        appointment_date=app_date,
        time_slot=data.time_slot,
        reason=data.reason,
        status="REQUESTED"
    )
    db.add(new_app)
    
    # Send notification to Doctor
    notif = Notification(
        user_id=doctor.user_id,
        title="New Appointment Request",
        message=f"New appointment request from patient for {data.time_slot}.",
        type="APPOINTMENT"
    )
    db.add(notif)

    db.commit()
    db.refresh(new_app)
    return {"message": "Appointment requested successfully", "appointment_id": new_app.id}

@router.get("/my")
def get_patient_appointments(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    appointments = db.query(Appointment).filter(Appointment.patient_id == current_user.user_id).order_by(Appointment.appointment_date.desc()).all()
    result = []
    for app in appointments:
        doc = db.query(Doctor).filter(Doctor.id == app.doctor_id).first()
        doc_user = db.query(User).filter(User.id == doc.user_id).first() if doc else None
        dept = db.query(Department).filter(Department.id == app.department_id).first()
        result.append({
            "id": app.id,
            "doctor_name": doc_user.full_name if doc_user else "Doctor",
            "specialization": doc.specialization if doc else "",
            "department_name": dept.name if dept else "General",
            "appointment_date": app.appointment_date.strftime("%Y-%m-%d %H:%M"),
            "time_slot": app.time_slot,
            "reason": app.reason,
            "status": app.status,
            "notes": app.notes
        })
    return result

@router.get("/doctor")
def get_doctor_appointments(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor and current_user.role not in ['admin', 'hospital_admin']:
        raise HTTPException(status_code=403, detail="Doctor profile required")

    query = db.query(Appointment)
    if doctor:
        query = query.filter(Appointment.doctor_id == doctor.id)

    appointments = query.order_by(Appointment.appointment_date.desc()).all()
    result = []
    for app in appointments:
        patient = db.query(User).filter(User.id == app.patient_id).first()
        result.append({
            "id": app.id,
            "patient_id": app.patient_id,
            "patient_name": patient.full_name if patient else "Patient",
            "patient_email": patient.email if patient else "",
            "patient_mobile": patient.mobile_no if patient else "",
            "appointment_date": app.appointment_date.strftime("%Y-%m-%d %H:%M"),
            "time_slot": app.time_slot,
            "reason": app.reason,
            "status": app.status,
            "notes": app.notes
        })
    return result

@router.get("/doctor/{doctor_id}/availability")
def get_appointment_availability(
    doctor_id: int,
    date_str: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    from datetime import date as dt_date, datetime as dt_datetime, timedelta
    from src.clinical_chat.clinical_actions import check_appointment_availability

    target_date = dt_date.today() + timedelta(days=1)
    if date_str:
        try:
            target_date = dt_datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid date format. Expected YYYY-MM-DD.")

    return check_appointment_availability(db, doctor_id, target_date)


@router.put("/{appointment_id}/status")
def update_appointment_status(appointment_id: int, update: AppointmentStatusUpdate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    status_clean = (update.status or "").strip().upper()
    if status_clean not in ALLOWED_APPOINTMENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid appointment status. Allowed: {', '.join(sorted(ALLOWED_APPOINTMENT_STATUSES))}")

    app = db.query(Appointment).filter(Appointment.id == appointment_id).with_for_update().populate_existing().first()
    if not app:
        raise HTTPException(status_code=404, detail="Appointment not found")

    user_role = (current_user.role or "").lower()
    if user_role in ['patient', 'user']:
        if app.patient_id != current_user.user_id:
            raise HTTPException(status_code=403, detail="Not authorized to update this appointment")
        if status_clean != "CANCELLED":
            raise HTTPException(status_code=400, detail="Patients may only cancel appointments")
    elif user_role in ['doctor', 'emergency_doctor']:
        doc = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
        if not doc or doc.status != "Active" or app.doctor_id != doc.id:
            raise HTTPException(status_code=403, detail="Doctor not assigned to this appointment")
    elif user_role not in ['admin', 'hospital_admin']:
        raise HTTPException(status_code=403, detail="Not authorized")

    refuse_linked_appointment_change(db, app.id)
    previous_status = app.status
    if status_clean not in APPOINTMENT_TRANSITIONS.get(previous_status, set()):
        raise HTTPException(status_code=409, detail="Appointment status transition is not allowed")
    app.status = status_clean
    if update.notes:
        app.notes = update.notes

    # Notify doctor if patient cancelled, or patient if doctor updated
    if user_role in ['patient', 'user']:
        doc = db.query(Doctor).filter(Doctor.id == app.doctor_id).first()
        if doc and doc.user_id:
            notif = Notification(
                user_id=doc.user_id,
                title="Appointment Cancelled by Patient",
                message=f"Appointment #{app.id} on {app.appointment_date.strftime('%Y-%m-%d')} has been cancelled by the patient.",
                type="APPOINTMENT"
            )
            db.add(notif)
    else:
        notif = Notification(
            user_id=app.patient_id,
            title=f"Appointment {update.status.title()}",
            message=f"Your appointment status has been updated to {update.status}.",
            type="APPOINTMENT"
        )
        db.add(notif)

    db.add(AuditLog(user_id=current_user.user_id, action="appointment_status_changed",
                    details={"appointment_id": app.id, "from_status": previous_status, "to_status": status_clean}))
    db.commit()
    return {"message": f"Appointment status updated to {update.status}"}
