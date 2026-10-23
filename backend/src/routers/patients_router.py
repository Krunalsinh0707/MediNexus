"""Staff patient identity registry (patient records remain in ``users``)."""

import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from src.auth import TokenData, require_patient_management_role
from src.database import get_db
from src.models import AuditLog, User

router = APIRouter(prefix="/patients", tags=["Patient Registry"])


class PatientSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)


class PatientCreateRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    date_of_birth: Optional[date] = None
    email: Optional[str] = Field(default=None, max_length=255)
    mobile_no: Optional[str] = Field(default=None, max_length=20)
    blood_group: Optional[str] = Field(default=None, max_length=5)
    confirm_demographic_match: bool = False


def _normalized_name(value: str) -> str:
    return " ".join(value.lower().split())


def _normalized_phone(value: Optional[str]) -> Optional[str]:
    digits = re.sub(r"\D", "", value or "")
    return digits or None


def _normalized_email(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip().lower()
    return value or None


def _patient_base_query(db: Session):
    return db.query(User).filter(User.role.in_(("user", "patient")))


def _exact_identifier_matches(db: Session, email: Optional[str], phone: Optional[str]):
    terms = []
    if email:
        terms.append(func.lower(func.btrim(User.email)) == email)
    if phone:
        terms.append(func.regexp_replace(User.mobile_no, "[^0-9]", "", "g") == phone)
    if not terms:
        return []
    return db.query(User).filter(or_(*terms)).order_by(User.id).all()


def _demographic_matches(db: Session, full_name: str, dob: Optional[date]):
    if dob is None:
        return []
    return (
        _patient_base_query(db)
        .filter(
            func.lower(func.regexp_replace(func.btrim(User.full_name), r"\s+", " ", "g"))
            == _normalized_name(full_name),
            User.date_of_birth == dob,
        )
        .order_by(User.id)
        .limit(10)
        .all()
    )


def _public_patient(user: User) -> dict:
    return {
        "id": user.id,
        "mrn": user.mrn,
        "full_name": user.full_name,
        "date_of_birth": user.date_of_birth,
        "email": user.email,
        "mobile_no": user.mobile_no,
        "blood_group": user.blood_group,
        "created_at": user.created_at,
    }


def _audit(db: Session, actor_id: int, action: str, details: dict) -> None:
    db.add(AuditLog(user_id=actor_id, action=action, details=details, status="Success"))


@router.post("/search")
def search_patients(
    request: PatientSearchRequest,
    db: Session = Depends(get_db),
    actor: TokenData = Depends(require_patient_management_role),
):
    term = request.query.strip()
    if not term:
        raise HTTPException(status_code=422, detail="Search text is required")
    email = _normalized_email(term)
    phone = _normalized_phone(term)
    predicates = [User.full_name.ilike(f"%{term}%"), User.mrn == term.upper()]
    if email:
        predicates.append(func.lower(func.btrim(User.email)) == email)
    if phone:
        predicates.append(func.regexp_replace(User.mobile_no, "[^0-9]", "", "g") == phone)
    query = _patient_base_query(db).filter(or_(*predicates))
    total = query.count()
    patients = query.order_by(User.full_name, User.id).offset(request.offset).limit(request.limit).all()
    _audit(db, actor.user_id, "Patient registry search", {"result_count": len(patients)})
    db.commit()
    return {"items": [_public_patient(patient) for patient in patients], "total": total}


@router.post("", status_code=201)
def register_patient(
    request: PatientCreateRequest,
    db: Session = Depends(get_db),
    actor: TokenData = Depends(require_patient_management_role),
):
    full_name = " ".join(request.full_name.split())
    if len(full_name) < 2:
        raise HTTPException(status_code=422, detail="Full name must contain at least two non-space characters")
    email = _normalized_email(request.email)
    phone = _normalized_phone(request.mobile_no)
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=422, detail="Invalid email format")
    if request.email and not email:
        raise HTTPException(status_code=422, detail="Email cannot be blank")
    if request.mobile_no and (not phone or not 10 <= len(phone) <= 15):
        raise HTTPException(status_code=422, detail="Mobile number must contain 10 to 15 digits")
    blood_group = (request.blood_group or "").strip().upper() or None
    if blood_group and blood_group not in {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"}:
        raise HTTPException(status_code=422, detail="Invalid blood group")

    # Serialize concurrent creates sharing identifiers or demographic keys.
    lock_keys = [f"identity:{value}" for value in (email, phone) if value]
    if request.date_of_birth:
        lock_keys.append(f"demographic:{_normalized_name(full_name)}:{request.date_of_birth.isoformat()}")
    for lock_key in sorted(lock_keys):
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_key)::bigint)"), {"lock_key": lock_key})

    identifier_matches = _exact_identifier_matches(db, email, phone)
    if identifier_matches:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "duplicate_identifier", "message": "Email or mobile number is already associated with a patient record."},
        )

    candidates = _demographic_matches(db, full_name, request.date_of_birth)
    if candidates and not request.confirm_demographic_match:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "demographic_review_required", "message": "Possible matching patients require staff review.",
                    "matches": [_public_patient(candidate) for candidate in candidates]},
        )

    patient = User(
        full_name=full_name,
        email=email,
        mobile_no=phone,
        blood_group=blood_group,
        password_hash=None,
        role="patient",
        date_of_birth=request.date_of_birth,
        mrn=None,
    )
    db.add(patient)
    try:
        db.flush()
        db.refresh(patient)
        _audit(db, actor.user_id, "Patient registered", {"patient_id": patient.id, "mrn": patient.mrn})
        db.commit()
        db.refresh(patient)
    except Exception:
        db.rollback()
        raise
    return _public_patient(patient)
