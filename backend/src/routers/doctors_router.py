from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import List, Optional

from src.database import get_db
from src.models import Doctor, Department, User
from src.auth import get_current_user, get_current_doctor, get_current_admin, get_password_hash
from src.patient_access import PatientAccess, patient_read_access

router = APIRouter(prefix="/doctors", tags=["Doctors Management"])

class DoctorCreate(BaseModel):
    email: str
    password: str
    full_name: str
    mobile_no: str
    blood_group: str = "O+"
    department_id: int
    specialization: str
    qualification: str
    license_number: Optional[str] = None
    experience_years: int = 0

@router.get("")
def list_doctors(department_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Doctor).join(User, Doctor.user_id == User.id)
    if department_id:
        query = query.filter(Doctor.department_id == department_id)
    
    doctors = query.all()
    result = []
    for doc in doctors:
        dept = db.query(Department).filter(Department.id == doc.department_id).first()
        result.append({
            "id": doc.id,
            "user_id": doc.user_id,
            "full_name": doc.user.full_name,
            "email": doc.user.email,
            "mobile_no": doc.user.mobile_no,
            "department_id": doc.department_id,
            "department_name": dept.name if dept else "General",
            "specialization": doc.specialization,
            "qualification": doc.qualification,
            "license_number": doc.license_number,
            "experience_years": doc.experience_years,
            "status": doc.status
        })
    return result

@router.post("")
def create_doctor(data: DoctorCreate, db: Session = Depends(get_db), current_user=Depends(get_current_admin)):
    existing_user = db.query(User).filter(
        User.email.is_not(None),
        func.lower(func.btrim(User.email)) == data.email.strip().lower(),
    ).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="User with email already exists")

    normalized_phone = "".join(ch for ch in data.mobile_no if ch.isdigit())
    phone_user = db.query(User).filter(
        User.mobile_no.is_not(None),
        func.regexp_replace(User.mobile_no, "[^0-9]", "", "g") == normalized_phone,
    ).first()
    if phone_user:
        raise HTTPException(status_code=400, detail="User with mobile number already exists")

    hashed_pw = get_password_hash(data.password)
    new_user = User(
        email=data.email,
        mobile_no=data.mobile_no,
        blood_group=data.blood_group,
        password_hash=hashed_pw,
        full_name=data.full_name,
        role="doctor"
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    new_doctor = Doctor(
        user_id=new_user.id,
        department_id=data.department_id,
        specialization=data.specialization,
        qualification=data.qualification,
        license_number=data.license_number,
        experience_years=data.experience_years,
        status="Active"
    )
    db.add(new_doctor)
    db.commit()
    db.refresh(new_doctor)

    return {"message": "Doctor account created successfully", "doctor_id": new_doctor.id}

@router.get("/me")
def get_doctor_profile(db: Session = Depends(get_db), current_user=Depends(get_current_doctor)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")
    
    dept = db.query(Department).filter(Department.id == doctor.department_id).first()
    return {
        "id": doctor.id,
        "user_id": doctor.user_id,
        "full_name": doctor.user.full_name,
        "email": doctor.user.email,
        "department_id": doctor.department_id,
        "department_name": dept.name if dept else "",
        "specialization": doctor.specialization,
        "qualification": doctor.qualification,
        "license_number": doctor.license_number,
        "experience_years": doctor.experience_years,
        "status": doctor.status
    }

@router.get("/patient/{patient_id}")
def get_patient_clinical_summary(patient_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_doctor)):
    access = patient_read_access(db, current_user, patient_id)
    patient = db.query(User).filter(User.id == patient_id).first()
    if not patient or patient.role not in ("patient", "user"):
        raise HTTPException(status_code=404, detail="Patient record not found")
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()

    # Fetch appointments
    from src.models import Appointment
    app_query = db.query(Appointment).filter(Appointment.patient_id == patient_id)
    if doctor:
        app_query = app_query.filter(Appointment.doctor_id == doctor.id)
    if access == PatientAccess.PREPARATION:
        app_query = app_query.filter(Appointment.status == "CONFIRMED")
    appointments = app_query.order_by(Appointment.appointment_date.desc()).all()

    app_list = []
    for app in appointments:
        app_list.append({
            "id": app.id,
            "appointment_date": app.appointment_date.strftime("%Y-%m-%d %H:%M") if app.appointment_date else "",
            "time_slot": app.time_slot,
            "status": app.status,
            "reason": app.reason,
            "notes": app.notes if access == PatientAccess.CLINICAL else None
        })

    profile = (patient.profile_data or {}) if access == PatientAccess.CLINICAL else {}
    if isinstance(profile, str):
        try:
            import json
            profile = json.loads(profile)
        except Exception:
            profile = {}

    return {
        "id": patient.id,
        "mrn": patient.mrn,
        "access_scope": access.value,
        "full_name": patient.full_name,
        "email": patient.email if access == PatientAccess.CLINICAL else None,
        "mobile_no": patient.mobile_no if access == PatientAccess.CLINICAL else None,
        "blood_group": patient.blood_group if access == PatientAccess.CLINICAL else None,
        "role": patient.role,
        "profile_data": profile,
        "created_at": patient.created_at.strftime("%Y-%m-%d") if patient.created_at else "",
        "appointments": app_list,
        "total_consultations": len(app_list)
    }

