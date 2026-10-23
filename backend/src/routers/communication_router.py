from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional

from src.database import get_db
from src.models import PatientDoctorMessage, Doctor, User, Appointment, Encounter, Notification, AuditLog
from src.auth import get_current_user
from src.patient_access import require_clinical_history
from src.security.rate_limiter import rate_limit

router = APIRouter(prefix="/communications", tags=["Patient-Doctor Messaging"])

class MessageSend(BaseModel):
    doctor_id: int
    patient_id: Optional[int] = None
    appointment_id: Optional[int] = None
    message: str

@router.post("")
def send_message(
    data: MessageSend,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _limiter: None = Depends(rate_limit(max_requests=30, window_seconds=60, prefix="comm_msg"))
):
    actor = db.get(User, current_user.user_id)
    if actor is None or not actor.password_hash or actor.role != current_user.role:
        raise HTTPException(status_code=401, detail="An eligible portal account is required")
    if actor.role not in {"patient", "user", "doctor", "emergency_doctor"}:
        raise HTTPException(status_code=403, detail="Clinical messages require a patient or clinician")

    doctor = db.query(Doctor).filter(Doctor.id == data.doctor_id, Doctor.status == "Active").first()
    doctor_account = db.get(User, doctor.user_id) if doctor else None
    if not doctor_account or not doctor_account.password_hash or doctor_account.role not in {"doctor", "emergency_doctor"}:
        raise HTTPException(status_code=404, detail="Active clinician not found")

    if actor.role in {"patient", "user"}:
        patient_id = actor.id
        if data.patient_id is not None and data.patient_id != patient_id:
            raise HTTPException(status_code=403, detail="Cannot send on behalf of another patient")
    else:
        if doctor.user_id != actor.id or not data.patient_id:
            raise HTTPException(status_code=403, detail="Clinician and patient relationship required")
        patient_id = data.patient_id

    target_patient = db.get(User, patient_id)
    if target_patient is None or target_patient.role not in {"patient", "user"}:
        raise HTTPException(status_code=404, detail="Patient record not found")

    appointment = None
    if data.appointment_id is not None:
        appointment = db.query(Appointment).filter(Appointment.id == data.appointment_id).with_for_update().first()
        if (appointment is None or appointment.patient_id != patient_id or
                appointment.doctor_id != doctor.id or appointment.status != "CONFIRMED"):
            raise HTTPException(status_code=404, detail="Confirmed appointment for this patient and clinician not found")

    active_visit = db.query(Encounter.id).filter(
        Encounter.patient_id == patient_id, Encounter.doctor_id == doctor.id,
        Encounter.status.in_(("CHECKED_IN", "IN_PROGRESS")),
    ).first()
    if actor.role in {"doctor", "emergency_doctor"} and active_visit is None:
        raise HTTPException(status_code=404, detail="An assigned active visit is required to send this message")
    if actor.role in {"patient", "user"} and active_visit is None and appointment is None:
        appointment = db.query(Appointment).filter(
            Appointment.patient_id == patient_id, Appointment.doctor_id == doctor.id,
            Appointment.status == "CONFIRMED",
        ).with_for_update().first()
        if appointment is None:
            raise HTTPException(status_code=404, detail="A confirmed appointment or active visit is required")

    msg_text = (data.message or "").strip()[:2000]
    if not msg_text:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    new_msg = PatientDoctorMessage(
        appointment_id=data.appointment_id,
        patient_id=patient_id,
        doctor_id=data.doctor_id,
        sender_id=current_user.user_id,
        message=msg_text
    )
    db.add(new_msg)

    recipient_id = doctor.user_id if current_user.user_id != doctor.user_id else patient_id
    db.add(Notification(
        user_id=recipient_id,
        title="New Healthcare Message",
        message=f"You received a new message regarding your consultation.",
        type="CHAT"
    ))
    db.add(AuditLog(user_id=actor.id, action="legacy_clinical_message_sent",
                    details={"patient_id": patient_id, "doctor_id": doctor.id,
                             "appointment_id": data.appointment_id}))

    db.commit()
    return {"message": "Message sent successfully"}

@router.get("/doctor/{doctor_id}")
def get_conversation_with_doctor(doctor_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    messages = db.query(PatientDoctorMessage).filter(
        PatientDoctorMessage.patient_id == current_user.user_id,
        PatientDoctorMessage.doctor_id == doctor_id
    ).order_by(PatientDoctorMessage.created_at.asc()).all()

    result = []
    for m in messages:
        sender = db.query(User).filter(User.id == m.sender_id).first()
        result.append({
            "id": m.id,
            "sender_id": m.sender_id,
            "sender_name": sender.full_name if sender else "User",
            "message": m.message,
            "is_me": m.sender_id == current_user.user_id,
            "created_at": m.created_at.strftime("%H:%M, %b %d")
        })
    return result

@router.get("/patient/{patient_id}")
def get_conversation_with_patient(patient_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_clinical_history(db, current_user, patient_id)
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor:
        raise HTTPException(status_code=403, detail="Doctor profile required")

    messages = db.query(PatientDoctorMessage).filter(
        PatientDoctorMessage.patient_id == patient_id,
        PatientDoctorMessage.doctor_id == doctor.id
    ).order_by(PatientDoctorMessage.created_at.asc()).all()

    result = []
    for m in messages:
        sender = db.query(User).filter(User.id == m.sender_id).first()
        result.append({
            "id": m.id,
            "sender_id": m.sender_id,
            "sender_name": sender.full_name if sender else "User",
            "message": m.message,
            "is_me": m.sender_id == current_user.user_id,
            "created_at": m.created_at.strftime("%H:%M, %b %d")
        })
    return result
