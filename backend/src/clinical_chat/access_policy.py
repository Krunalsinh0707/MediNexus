from fastapi import HTTPException, status, Depends
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import Optional, List, Tuple

from src.auth import TokenData, get_current_user
from src.database import get_db
from src.models import (
    User, Doctor, Department,
    ClinicalConversation, ClinicalAssignment,
    DoctorDepartmentMembership
)

def require_patient_role(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Enforces that the authenticated user is a patient."""
    role = (current_user.role or "").lower()
    if role not in ["patient", "user"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Patient role required."
        )
    return current_user

def require_doctor_role(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Enforces that the authenticated user is a clinician (doctor, emergency doctor)."""
    role = (current_user.role or "").lower()
    if role not in ["doctor", "emergency_doctor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Clinician authorization required."
        )
    return current_user

def require_admin_role(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Enforces that the authenticated user has administrative privileges."""
    role = (current_user.role or "").lower()
    if role not in ["admin", "hospital_admin", "department_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Administrator privileges required."
        )
    return current_user

def get_doctor_profile(db: Session, user_id: int) -> Optional[Doctor]:
    """Retrieves the Doctor record linked to a user account."""
    return db.query(Doctor).join(User, User.id == Doctor.user_id).filter(
        Doctor.user_id == user_id, Doctor.status == "Active",
        User.role.in_(("doctor", "emergency_doctor")), User.password_hash.is_not(None),
    ).first()

def get_authorized_department_ids_for_doctor(db: Session, doctor: Doctor) -> List[int]:
    """
    Returns all department IDs a doctor is authorized to view (primary department + active memberships).
    """
    dept_ids = set()
    if doctor.department_id:
        dept_ids.add(doctor.department_id)

    memberships = db.query(DoctorDepartmentMembership).filter(
        DoctorDepartmentMembership.doctor_id == doctor.id,
        DoctorDepartmentMembership.is_active == True
    ).all()
    from src.workforce_service import source_assignment_current
    for m in memberships:
        if source_assignment_current(db, "DOCTOR", m.id):
            dept_ids.add(m.department_id)

    # Also check if doctor is designated head_doctor_id of any department
    headed_depts = db.query(Department).filter(Department.head_doctor_id == doctor.id).all()
    for hd in headed_depts:
        dept_ids.add(hd.id)

    return list(dept_ids)

def can_patient_access_conversation(conversation: ClinicalConversation, patient_user_id: int) -> bool:
    """Verifies that the conversation belongs to the patient."""
    return conversation.patient_id == patient_user_id

def can_doctor_access_conversation(
    db: Session,
    conversation: ClinicalConversation,
    doctor_user: TokenData
) -> Tuple[bool, Optional[str]]:
    """
    Checks if a doctor is authorized to view a clinical conversation.
    Returns (authorized: bool, reason: str).
    """
    doctor = get_doctor_profile(db, doctor_user.user_id)
    if not doctor:
        return False, "Doctor profile not found"

    # 1. Directly assigned doctor
    if conversation.assigned_doctor_id == doctor.id:
        return True, "Directly assigned doctor"

    # Check active clinical assignments history
    active_assign = db.query(ClinicalAssignment).filter(
        ClinicalAssignment.conversation_id == conversation.id,
        ClinicalAssignment.doctor_id == doctor.id,
        ClinicalAssignment.is_active == True
    ).first()
    if active_assign:
        return True, "Active clinical assignment"

    # 2. Emergency doctor coverage for emergencies
    is_emergency_role = doctor.user.role == "emergency_doctor"
    is_emergency_urgency = conversation.urgency == "EMERGENCY_REVIEW"
    emergency_dept = db.query(Department).filter(Department.code == "EMERG").first()
    is_emergency_dept = emergency_dept and conversation.department_id == emergency_dept.id

    if is_emergency_role and (is_emergency_urgency or is_emergency_dept):
        return True, "Emergency doctor coverage"

    # 3. Department scope
    authorized_depts = get_authorized_department_ids_for_doctor(db, doctor)
    if conversation.department_id and conversation.department_id in authorized_depts:
        return True, "Department team member"

    return False, "Not within authorized clinical scope"

def can_doctor_modify_conversation(
    db: Session,
    conversation: ClinicalConversation,
    doctor_user: TokenData,
    action: str = "reply",
) -> bool:
    """
    Department coverage permits reading; clinical mutations require assignment.
    An unassigned conversation can be claimed/triaged by its covering team.
    Emergency clinicians can acknowledge/escalate emergency coverage.
    """
    doctor = get_doctor_profile(db, doctor_user.user_id)
    if doctor is None or conversation.status == "RESOLVED":
        return False
    if conversation.assigned_doctor_id == doctor.id:
        return True
    active_assignment = db.query(ClinicalAssignment.id).filter(
        ClinicalAssignment.conversation_id == conversation.id,
        ClinicalAssignment.doctor_id == doctor.id,
        ClinicalAssignment.is_active == True,
    ).first()
    if active_assignment:
        return True
    authorized, _ = can_doctor_access_conversation(db, conversation, doctor_user)
    if not authorized:
        return False
    if (doctor.user.role == "emergency_doctor" and conversation.urgency == "EMERGENCY_REVIEW"
            and action in {"acknowledge", "escalate"}):
        return True
    return conversation.assigned_doctor_id is None and action in {"assign", "acknowledge", "escalate"}
