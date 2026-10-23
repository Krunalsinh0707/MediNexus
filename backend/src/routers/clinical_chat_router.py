from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc, exists, select
from typing import Optional, List
from datetime import datetime

from src.auth import TokenData, get_current_user
from src.database import get_db
from src.models import (
    User, Doctor, Department,
    ClinicalConversation, ClinicalMessage, ClinicalAssignment,
    ClinicalAlert, ClinicalAIAnalysis, ClinicalEvent,
    ClinicalRoutingRule, DoctorDepartmentMembership, AuditLog
)
from src.schemas.clinical_chat import (
    CreateConversationRequest, SendMessageRequest,
    AssignDoctorRequest, AcknowledgeAlertRequest,
    EscalateConversationRequest, ResolveConversationRequest,
    RoutingRuleCreateRequest, RoutingRuleUpdateRequest, RoutingRuleResponse,
    DoctorDepartmentMembershipCreateRequest, DoctorDepartmentMembershipResponse,
    ClinicalMessageResponse, PatientSafeConversationResponse,
    DoctorConversationDetailResponse, DoctorInboxResponse, DoctorInboxItem,
    ClinicalEventResponse, ClinicalAIAnalysisResponse
)
from src.clinical_chat.access_policy import (
    require_patient_role, require_doctor_role, require_admin_role,
    can_patient_access_conversation, can_doctor_access_conversation,
    can_doctor_modify_conversation, get_doctor_profile,
    get_authorized_department_ids_for_doctor
)
from src.clinical_chat.orchestration import orchestrator

router = APIRouter(prefix="/clinical-chat", tags=["Clinical Chat Subsystem"])


def _require_hospital_admin(current_user: TokenData) -> None:
    if (current_user.role or "").lower() not in {"admin", "hospital_admin"}:
        raise HTTPException(status_code=403, detail="Hospital administrator authorization required")


def _format_message(msg: ClinicalMessage) -> ClinicalMessageResponse:
    sender_name = "System"
    if msg.sender_type == "patient":
        sender_name = msg.sender_user.full_name if msg.sender_user else "Patient"
    elif msg.sender_type == "doctor":
        sender_name = f"Dr. {msg.sender_user.full_name}" if msg.sender_user else "Attending Clinician"
    elif msg.sender_type == "assistant":
        sender_name = "HealthBot AI Assistant"

    return ClinicalMessageResponse(
        id=msg.id,
        conversation_id=msg.conversation_id,
        sender_type=msg.sender_type,
        sender_user_id=msg.sender_user_id,
        sender_name=sender_name,
        body=msg.body,
        created_at=msg.created_at
    )


# =========================================================================
# Patient Endpoints
# =========================================================================

@router.post("/conversations", response_model=PatientSafeConversationResponse)
def create_patient_conversation(
    req: CreateConversationRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_patient_role)
):
    """
    Patient creates a new clinical consultation thread.
    Optionally includes an initial message processed through deterministic triage.
    """
    conv = orchestrator.create_conversation(
        db=db,
        patient_id=current_user.user_id,
        title=req.title,
        initial_message=req.initial_message
    )

    messages = (
        db.query(ClinicalMessage)
        .filter(ClinicalMessage.conversation_id == conv.id)
        .order_by(ClinicalMessage.created_at.asc())
        .all()
    )

    return PatientSafeConversationResponse(
        id=conv.id,
        title=conv.title,
        status=conv.status,
        urgency=conv.urgency,
        escalation_status=conv.escalation_status,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        resolved_at=conv.resolved_at,
        messages=[_format_message(m) for m in messages]
    )


@router.get("/conversations/my", response_model=List[PatientSafeConversationResponse])
def get_my_conversations(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_patient_role)
):
    """
    Patient retrieves list of own consultations.
    """
    hidden = exists(select(ClinicalEvent.id).where(
        ClinicalEvent.conversation_id == ClinicalConversation.id,
        ClinicalEvent.event_type == "PATIENT_HIDDEN",
        ClinicalEvent.actor_user_id == current_user.user_id,
    ))
    convs = (
        db.query(ClinicalConversation)
        .filter(ClinicalConversation.patient_id == current_user.user_id)
        .filter(or_(ClinicalConversation.status != "RESOLVED", ~hidden))
        .order_by(ClinicalConversation.updated_at.desc())
        .all()
    )

    result = []
    for c in convs:
        recent_messages = (
            db.query(ClinicalMessage)
            .filter(ClinicalMessage.conversation_id == c.id)
            .order_by(ClinicalMessage.created_at.desc())
            .limit(1)
            .all()
        )
        result.append(PatientSafeConversationResponse(
            id=c.id,
            title=c.title,
            status=c.status,
            urgency=c.urgency,
            escalation_status=c.escalation_status,
            created_at=c.created_at,
            updated_at=c.updated_at,
            resolved_at=c.resolved_at,
            messages=[_format_message(m) for m in recent_messages]
        ))
    return result


@router.delete("/conversations/{conversation_id}")
def delete_patient_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user)
):
    """Hide a resolved consultation from its patient's list; retain all clinical records."""
    conv = db.query(ClinicalConversation).filter(ClinicalConversation.id == conversation_id).with_for_update().first()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    user_role = (current_user.role or "").lower()
    if user_role not in ["patient", "user"] or not can_patient_access_conversation(conv, current_user.user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    if conv.status != "RESOLVED":
        raise HTTPException(status_code=409, detail="Only resolved consultations can be hidden; clinical history is retained")
    previous = db.query(ClinicalEvent.id).filter(
        ClinicalEvent.conversation_id == conv.id,
        ClinicalEvent.event_type == "PATIENT_HIDDEN",
        ClinicalEvent.actor_user_id == current_user.user_id,
    ).first()
    if previous:
        return {"message": "Conversation is already hidden; clinical history is retained", "id": conversation_id, "hidden": True}
    db.add(ClinicalEvent(conversation_id=conv.id, actor_user_id=current_user.user_id,
                         event_type="PATIENT_HIDDEN", reason="Patient hid resolved consultation from list"))
    db.commit()
    return {"message": "Conversation hidden from your list; clinical history is retained", "id": conversation_id, "hidden": True}


@router.get("/doctors/{doctor_id}/availability")
def get_doctor_availability_endpoint(
    doctor_id: int,
    date_str: Optional[str] = Query(None, alias="date"),
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Calculates actual appointment slot availability for a doctor on a specific date.
    """
    from datetime import date as dt_date, datetime, timedelta
    from src.clinical_chat.clinical_actions import check_appointment_availability

    target_date = dt_date.today() + timedelta(days=1)
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    return check_appointment_availability(db, doctor_id, target_date)


# =========================================================================
# Unified Scoped Conversation Detail & Messages
# =========================================================================

@router.get("/conversations/{conversation_id}")
def get_conversation_detail(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Retrieves conversation details.
    Patients receive a patient-safe view (no internal AI analyses or alerts).
    Doctors receive a clinical view with patient info, AI analyses, and alert status.
    """
    conv = db.query(ClinicalConversation).filter(ClinicalConversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    user_role = (current_user.role or "").lower()

    if user_role in ["patient", "user"]:
        if not can_patient_access_conversation(conv, current_user.user_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        messages = (
            db.query(ClinicalMessage)
            .filter(ClinicalMessage.conversation_id == conv.id)
            .order_by(ClinicalMessage.created_at.asc())
            .all()
        )
        return PatientSafeConversationResponse(
            id=conv.id,
            title=conv.title,
            status=conv.status,
            urgency=conv.urgency,
            escalation_status=conv.escalation_status,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            resolved_at=conv.resolved_at,
            messages=[_format_message(m) for m in messages]
        )

    elif user_role in ["doctor", "emergency_doctor"]:
        authorized, reason = can_doctor_access_conversation(db, conv, current_user)
        if not authorized:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Access denied: {reason}")

        messages = (
            db.query(ClinicalMessage)
            .filter(ClinicalMessage.conversation_id == conv.id)
            .order_by(ClinicalMessage.created_at.asc())
            .all()
        )

        patient = db.query(User).filter(User.id == conv.patient_id).first()
        dept = db.query(Department).filter(Department.id == conv.department_id).first() if conv.department_id else None
        assigned_doc = db.query(Doctor).filter(Doctor.id == conv.assigned_doctor_id).first() if conv.assigned_doctor_id else None

        alerts = db.query(ClinicalAlert).filter(ClinicalAlert.conversation_id == conv.id).order_by(ClinicalAlert.escalated_at.desc()).all()
        analyses = db.query(ClinicalAIAnalysis).filter(ClinicalAIAnalysis.conversation_id == conv.id).order_by(ClinicalAIAnalysis.created_at.desc()).all()

        return DoctorConversationDetailResponse(
            id=conv.id,
            title=conv.title,
            status=conv.status,
            urgency=conv.urgency,
            escalation_status=conv.escalation_status,
            patient_id=conv.patient_id,
            patient_name=patient.full_name if patient else "Unknown Patient",
            patient_email=patient.email if patient else None,
            patient_blood_group=patient.blood_group if patient else None,
            department_id=conv.department_id,
            department_name=dept.name if dept else None,
            assigned_doctor_id=conv.assigned_doctor_id,
            assigned_doctor_name=f"Dr. {assigned_doc.user.full_name}" if assigned_doc and assigned_doc.user else None,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            resolved_at=conv.resolved_at,
            messages=[_format_message(m) for m in messages],
            alerts=alerts,
            ai_analyses=analyses
        )

    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


@router.get("/conversations/{conversation_id}/messages", response_model=List[ClinicalMessageResponse])
def get_conversation_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Returns messages for a specific consultation, subject to authorization scoping.
    """
    conv = db.query(ClinicalConversation).filter(ClinicalConversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    user_role = (current_user.role or "").lower()
    if user_role in ["patient", "user"]:
        if not can_patient_access_conversation(conv, current_user.user_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    elif user_role in ["doctor", "emergency_doctor"]:
        authorized, reason = can_doctor_access_conversation(db, conv, current_user)
        if not authorized:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Access denied: {reason}")
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    messages = (
        db.query(ClinicalMessage)
        .filter(ClinicalMessage.conversation_id == conv.id)
        .order_by(ClinicalMessage.created_at.asc())
        .all()
    )
    return [_format_message(m) for m in messages]


@router.post("/conversations/{conversation_id}/messages")
def post_conversation_message(
    conversation_id: int,
    req: SendMessageRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Submits a message to an existing conversation.
    If sent by patient: runs classification, routing, and assistant reply.
    If sent by clinician: records doctor reply and notifies patient.
    """
    conv = db.query(ClinicalConversation).filter(ClinicalConversation.id == conversation_id).with_for_update().populate_existing().first()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conv.status == "RESOLVED":
        raise HTTPException(status_code=409, detail="Resolved conversations cannot receive messages")

    user_role = (current_user.role or "").lower()

    if user_role in ["patient", "user"]:
        if not can_patient_access_conversation(conv, current_user.user_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        return orchestrator.process_patient_message(
            db=db,
            conversation=conv,
            patient_id=current_user.user_id,
            message_text=req.message
        )

    elif user_role in ["doctor", "emergency_doctor"]:
        if not can_doctor_modify_conversation(db, conv, current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Doctor not authorized for this conversation")

        db.add(AuditLog(user_id=current_user.user_id, action="clinical_chat_reply",
                        details={"conversation_id": conv.id}))
        doc_msg = orchestrator.process_doctor_reply(
            db=db,
            conversation=conv,
            doctor_user_id=current_user.user_id,
            message_text=req.message
        )
        return {
            "conversation_id": conv.id,
            "status": conv.status,
            "doctor_message": _format_message(doc_msg)
        }

    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


# =========================================================================
# Doctor Clinical Console Endpoints
# =========================================================================

@router.get("/doctor/inbox", response_model=DoctorInboxResponse)
def get_doctor_inbox(
    queue: str = Query("all", description="Queue filter: 'all', 'assigned', 'department', 'emergency'"),
    status_filter: Optional[str] = Query(None, alias="status"),
    urgency_filter: Optional[str] = Query(None, alias="urgency"),
    search: Optional[str] = Query(None),
    updated_since: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_doctor_role)
):
    """
    Returns authorized conversations for the Doctor Clinical Chat Console.
    Supports short-interval live polling via updated_since.
    """
    doctor = get_doctor_profile(db, current_user.user_id)
    if not doctor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Doctor profile not found")

    authorized_depts = get_authorized_department_ids_for_doctor(db, doctor)
    is_emergency_role = doctor.user.role == "emergency_doctor"

    query = db.query(ClinicalConversation)

    # Scoping conditions
    scope_conditions = []
    if doctor.id:
        scope_conditions.append(ClinicalConversation.assigned_doctor_id == doctor.id)

    if authorized_depts:
        scope_conditions.append(ClinicalConversation.department_id.in_(authorized_depts))

    if is_emergency_role:
        emerg_dept = db.query(Department).filter(Department.code == "EMERG").first()
        if emerg_dept:
            scope_conditions.append(ClinicalConversation.department_id == emerg_dept.id)
        scope_conditions.append(ClinicalConversation.urgency == "EMERGENCY_REVIEW")

    if not scope_conditions:
        return DoctorInboxResponse(conversations=[], total=0, unread_alerts_count=0)

    query = query.filter(or_(*scope_conditions))

    # Queue filters
    if queue == "assigned":
        query = query.filter(ClinicalConversation.assigned_doctor_id == doctor.id)
    elif queue == "department":
        if authorized_depts:
            query = query.filter(ClinicalConversation.department_id.in_(authorized_depts))
    elif queue == "emergency":
        query = query.filter(
            or_(
                ClinicalConversation.urgency == "EMERGENCY_REVIEW",
                ClinicalConversation.escalation_status == "PENDING_ACK"
            )
        )

    if status_filter:
        query = query.filter(ClinicalConversation.status == status_filter)

    if urgency_filter:
        query = query.filter(ClinicalConversation.urgency == urgency_filter)

    if updated_since:
        query = query.filter(ClinicalConversation.updated_at >= updated_since)

    # Search filter
    if search:
        search_pattern = f"%{search.strip()}%"
        query = query.join(User, ClinicalConversation.patient_id == User.id).filter(
            or_(
                ClinicalConversation.title.ilike(search_pattern),
                User.full_name.ilike(search_pattern),
                User.email.ilike(search_pattern)
            )
        )

    # Order by priority: PENDING_ACK first, then most urgent, then latest update
    convs = query.order_by(
        desc(ClinicalConversation.escalation_status == "PENDING_ACK"),
        desc(ClinicalConversation.urgency == "EMERGENCY_REVIEW"),
        desc(ClinicalConversation.urgency == "HIGH_PRIORITY"),
        desc(ClinicalConversation.updated_at)
    ).limit(100).all()

    # Calculate unread alerts
    unread_alerts = db.query(ClinicalAlert).filter(
        ClinicalAlert.status == "TRIGGERED",
        or_(
            ClinicalAlert.assigned_doctor_id == doctor.id,
            ClinicalAlert.department_id.in_(authorized_depts) if authorized_depts else False
        )
    ).count()

    items = []
    for c in convs:
        patient = db.query(User).filter(User.id == c.patient_id).first()
        dept = db.query(Department).filter(Department.id == c.department_id).first() if c.department_id else None
        doc = db.query(Doctor).filter(Doctor.id == c.assigned_doctor_id).first() if c.assigned_doctor_id else None

        latest_msg = (
            db.query(ClinicalMessage)
            .filter(ClinicalMessage.conversation_id == c.id)
            .order_by(ClinicalMessage.created_at.desc())
            .first()
        )

        has_active_alert = db.query(ClinicalAlert).filter(
            ClinicalAlert.conversation_id == c.id,
            ClinicalAlert.status == "TRIGGERED"
        ).count() > 0

        items.append(DoctorInboxItem(
            id=c.id,
            title=c.title,
            patient_id=c.patient_id,
            patient_name=patient.full_name if patient else "Patient",
            status=c.status,
            urgency=c.urgency,
            escalation_status=c.escalation_status,
            department_id=c.department_id,
            department_name=dept.name if dept else None,
            assigned_doctor_id=c.assigned_doctor_id,
            assigned_doctor_name=f"Dr. {doc.user.full_name}" if doc and doc.user else None,
            latest_message_snippet=latest_msg.body[:90] if latest_msg else None,
            has_active_alert=has_active_alert,
            created_at=c.created_at,
            updated_at=c.updated_at
        ))

    return DoctorInboxResponse(
        conversations=items,
        total=len(items),
        unread_alerts_count=unread_alerts
    )


@router.post("/conversations/{conversation_id}/acknowledge")
def acknowledge_alert(
    conversation_id: int,
    req: AcknowledgeAlertRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_doctor_role)
):
    """
    Clinician acknowledges an active clinical alert.
    """
    conv = db.query(ClinicalConversation).filter(ClinicalConversation.id == conversation_id).with_for_update().populate_existing().first()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    if not can_doctor_modify_conversation(db, conv, current_user, "acknowledge"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Doctor not authorized")
    if conv.escalation_status != "PENDING_ACK":
        raise HTTPException(status_code=409, detail="Only a pending alert can be acknowledged")

    db.add(AuditLog(user_id=current_user.user_id, action="clinical_alert_acknowledged",
                    details={"conversation_id": conv.id}))
    updated = orchestrator.acknowledge_alert(
        db=db,
        conversation=conv,
        doctor_user_id=current_user.user_id,
        notes=req.notes
    )
    return {
        "conversation_id": updated.id,
        "escalation_status": updated.escalation_status,
        "message": "Alert successfully acknowledged."
    }


@router.post("/conversations/{conversation_id}/assign")
def assign_conversation(
    conversation_id: int,
    req: AssignDoctorRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_doctor_role)
):
    """
    Assigns or transfers a conversation to a specific doctor or department.
    """
    conv = db.query(ClinicalConversation).filter(ClinicalConversation.id == conversation_id).with_for_update().populate_existing().first()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    if not can_doctor_modify_conversation(db, conv, current_user, "assign"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Doctor not authorized")
    if req.doctor_id is None:
        raise HTTPException(status_code=400, detail="An active target clinician is required")
    target = db.query(Doctor).join(User, User.id == Doctor.user_id).filter(
        Doctor.id == req.doctor_id, Doctor.status == "Active",
        User.role.in_(("doctor", "emergency_doctor")), User.password_hash.is_not(None),
    ).first()
    if target is None:
        raise HTTPException(status_code=400, detail="Target clinician must have an active profile and account")
    target_department_id = req.department_id if req.department_id is not None else conv.department_id
    if target_department_id is not None and target.department_id != target_department_id:
        membership = db.query(DoctorDepartmentMembership).filter(
            DoctorDepartmentMembership.doctor_id == target.id,
            DoctorDepartmentMembership.department_id == target_department_id,
            DoctorDepartmentMembership.is_active == True,
        ).first()
        if membership is None:
            raise HTTPException(status_code=400, detail="Target clinician is not assigned to the requested department")
        from src.workforce_service import source_assignment_current
        if not source_assignment_current(db, "DOCTOR", membership.id):
            raise HTTPException(status_code=400, detail="Target clinician's managed department assignment has expired")

    db.add(AuditLog(user_id=current_user.user_id, action="clinical_chat_assigned",
                    details={"conversation_id": conv.id, "target_doctor_id": target.id,
                             "department_id": target_department_id}))
    updated = orchestrator.assign_conversation(
        db=db,
        conversation=conv,
        actor_user_id=current_user.user_id,
        doctor_id=req.doctor_id,
        department_id=req.department_id,
        reason=req.reason
    )
    return {
        "conversation_id": updated.id,
        "department_id": updated.department_id,
        "assigned_doctor_id": updated.assigned_doctor_id,
        "message": "Clinical assignment updated successfully."
    }


@router.post("/conversations/{conversation_id}/escalate")
def escalate_conversation(
    conversation_id: int,
    req: EscalateConversationRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_doctor_role)
):
    """
    Manually escalates a conversation's clinical urgency.
    """
    conv = db.query(ClinicalConversation).filter(ClinicalConversation.id == conversation_id).with_for_update().populate_existing().first()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    if not can_doctor_modify_conversation(db, conv, current_user, "escalate"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Doctor not authorized")
    urgency_rank = {"LOW_PRIORITY": 0, "NORMAL": 1, "MODERATE": 2, "HIGH_PRIORITY": 3, "EMERGENCY_REVIEW": 4}
    if urgency_rank[req.urgency] <= urgency_rank[conv.urgency]:
        raise HTTPException(status_code=409, detail="Escalation must increase urgency")
    if req.department_id is not None and db.query(Department).filter(Department.id == req.department_id).first() is None:
        raise HTTPException(status_code=400, detail="Target department not found")

    db.add(AuditLog(user_id=current_user.user_id, action="clinical_chat_escalated",
                    details={"conversation_id": conv.id, "from_urgency": conv.urgency,
                             "to_urgency": req.urgency}))
    updated = orchestrator.escalate_conversation(
        db=db,
        conversation=conv,
        actor_user_id=current_user.user_id,
        target_urgency=req.urgency,
        reason=req.reason,
        department_id=req.department_id
    )
    return {
        "conversation_id": updated.id,
        "urgency": updated.urgency,
        "escalation_status": updated.escalation_status,
        "message": "Conversation successfully escalated."
    }


@router.post("/conversations/{conversation_id}/resolve")
def resolve_conversation(
    conversation_id: int,
    req: ResolveConversationRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_doctor_role)
):
    """
    Clinician resolves a clinical consultation.
    """
    conv = db.query(ClinicalConversation).filter(ClinicalConversation.id == conversation_id).with_for_update().populate_existing().first()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    if not can_doctor_modify_conversation(db, conv, current_user, "resolve"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Doctor not authorized")
    if conv.escalation_status == "PENDING_ACK" or conv.status not in {"DOCTOR_RESPONDED", "ESCALATED"}:
        raise HTTPException(status_code=409, detail="Conversation is not ready for clinical resolution")

    db.add(AuditLog(user_id=current_user.user_id, action="clinical_chat_resolved",
                    details={"conversation_id": conv.id}))
    updated = orchestrator.resolve_conversation(
        db=db,
        conversation=conv,
        actor_user_id=current_user.user_id,
        resolution_notes=req.resolution_notes
    )
    return {
        "conversation_id": updated.id,
        "status": updated.status,
        "resolved_at": updated.resolved_at,
        "message": "Conversation marked as clinically resolved."
    }


@router.get("/conversations/{conversation_id}/events", response_model=List[ClinicalEventResponse])
def get_conversation_events(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_doctor_role)
):
    """
    Returns the complete, append-only clinical workflow timeline for authorized clinicians.
    """
    conv = db.query(ClinicalConversation).filter(ClinicalConversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    authorized, _ = can_doctor_access_conversation(db, conv, current_user)
    if not authorized:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Doctor not authorized")

    events = (
        db.query(ClinicalEvent)
        .filter(ClinicalEvent.conversation_id == conv.id)
        .order_by(ClinicalEvent.created_at.asc())
        .all()
    )

    result = []
    for ev in events:
        actor_name = None
        if ev.actor_user_id:
            u = db.query(User).filter(User.id == ev.actor_user_id).first()
            actor_name = u.full_name if u else f"User #{ev.actor_user_id}"
        else:
            actor_name = "System / Triage Engine"

        result.append(ClinicalEventResponse(
            id=ev.id,
            conversation_id=ev.conversation_id,
            event_type=ev.event_type,
            actor_user_id=ev.actor_user_id,
            actor_name=actor_name,
            state_before=ev.state_before,
            state_after=ev.state_after,
            reason=ev.reason,
            created_at=ev.created_at
        ))
    return result


@router.get("/conversations/{conversation_id}/ai-analysis", response_model=List[ClinicalAIAnalysisResponse])
def get_conversation_ai_analyses(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_doctor_role)
):
    """
    Returns AI/deterministic triage analysis records for authorized clinicians.
    """
    conv = db.query(ClinicalConversation).filter(ClinicalConversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    authorized, _ = can_doctor_access_conversation(db, conv, current_user)
    if not authorized:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Doctor not authorized")

    analyses = (
        db.query(ClinicalAIAnalysis)
        .filter(ClinicalAIAnalysis.conversation_id == conv.id)
        .order_by(ClinicalAIAnalysis.created_at.desc())
        .all()
    )
    return analyses


# =========================================================================
# Administration Endpoints (Routing Rules & Doctor Memberships)
# =========================================================================

@router.get("/routing-rules", response_model=List[RoutingRuleResponse])
def list_routing_rules(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_admin_role)
):
    """
    Administrator lists all clinical routing rules.
    """
    _require_hospital_admin(current_user)
    rules = db.query(ClinicalRoutingRule).order_by(ClinicalRoutingRule.created_at.desc()).all()
    res = []
    for r in rules:
        dept = db.query(Department).filter(Department.id == r.department_id).first()
        res.append(RoutingRuleResponse(
            id=r.id,
            category_or_indicator=r.category_or_indicator,
            department_id=r.department_id,
            department_name=dept.name if dept else None,
            priority=r.priority,
            is_enabled=r.is_enabled,
            version=r.version,
            created_at=r.created_at
        ))
    return res


@router.post("/routing-rules", response_model=RoutingRuleResponse)
def create_routing_rule(
    req: RoutingRuleCreateRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_admin_role)
):
    """
    Administrator adds a new clinical routing rule.
    """
    _require_hospital_admin(current_user)
    dept = db.query(Department).filter(Department.id == req.department_id).first()
    if not dept:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    rule = ClinicalRoutingRule(
        category_or_indicator=req.category_or_indicator,
        department_id=req.department_id,
        priority=req.priority,
        is_enabled=req.is_enabled,
        version=req.version
    )
    db.add(rule)
    db.flush()
    db.add(AuditLog(user_id=current_user.user_id, action="clinical_routing_rule_created",
                    details={"rule_id": rule.id, "department_id": req.department_id}))
    db.commit()
    db.refresh(rule)

    return RoutingRuleResponse(
        id=rule.id,
        category_or_indicator=rule.category_or_indicator,
        department_id=rule.department_id,
        department_name=dept.name,
        priority=rule.priority,
        is_enabled=rule.is_enabled,
        version=rule.version,
        created_at=rule.created_at
    )


@router.put("/routing-rules/{rule_id}", response_model=RoutingRuleResponse)
def update_routing_rule(
    rule_id: int,
    req: RoutingRuleUpdateRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_admin_role)
):
    """
    Administrator updates an existing routing rule.
    """
    _require_hospital_admin(current_user)
    rule = db.query(ClinicalRoutingRule).filter(ClinicalRoutingRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routing rule not found")

    if req.category_or_indicator is not None:
        rule.category_or_indicator = req.category_or_indicator
    if req.department_id is not None:
        dept = db.query(Department).filter(Department.id == req.department_id).first()
        if not dept:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")
        rule.department_id = req.department_id
    if req.priority is not None:
        rule.priority = req.priority
    if req.is_enabled is not None:
        rule.is_enabled = req.is_enabled

    db.add(AuditLog(user_id=current_user.user_id, action="clinical_routing_rule_updated",
                    details={"rule_id": rule.id, "department_id": rule.department_id}))
    db.commit()
    db.refresh(rule)

    dept = db.query(Department).filter(Department.id == rule.department_id).first()
    return RoutingRuleResponse(
        id=rule.id,
        category_or_indicator=rule.category_or_indicator,
        department_id=rule.department_id,
        department_name=dept.name if dept else None,
        priority=rule.priority,
        is_enabled=rule.is_enabled,
        version=rule.version,
        created_at=rule.created_at
    )


@router.get("/doctor-memberships", response_model=List[DoctorDepartmentMembershipResponse])
def list_doctor_memberships(
    department_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Lists doctor department coverage memberships.
    """
    _require_hospital_admin(current_user)
    query = db.query(DoctorDepartmentMembership)
    if department_id:
        query = query.filter(DoctorDepartmentMembership.department_id == department_id)
    memberships = query.all()

    res = []
    for m in memberships:
        doc = db.query(Doctor).filter(Doctor.id == m.doctor_id).first()
        dept = db.query(Department).filter(Department.id == m.department_id).first()
        res.append(DoctorDepartmentMembershipResponse(
            id=m.id,
            doctor_id=m.doctor_id,
            doctor_name=f"Dr. {doc.user.full_name}" if doc and doc.user else None,
            department_id=m.department_id,
            department_name=dept.name if dept else None,
            role=m.role,
            is_active=m.is_active,
            created_at=m.created_at
        ))
    return res


@router.post("/doctor-memberships", response_model=DoctorDepartmentMembershipResponse)
def create_doctor_membership(
    req: DoctorDepartmentMembershipCreateRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_admin_role)
):
    """
    Administrator adds a doctor to a department coverage role (MEMBER, RESPONDER, LEAD).
    """
    _require_hospital_admin(current_user)
    doc = db.query(Doctor).join(User, User.id == Doctor.user_id).filter(
        Doctor.id == req.doctor_id, Doctor.status == "Active",
        User.role.in_(("doctor", "emergency_doctor")), User.password_hash.is_not(None),
    ).first()
    if not doc:
        raise HTTPException(status_code=400, detail="Active target clinician account required")
    dept = db.query(Department).filter(Department.id == req.department_id).first()
    if not dept:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    membership = DoctorDepartmentMembership(
        doctor_id=req.doctor_id,
        department_id=req.department_id,
        role=req.role,
        is_active=req.is_active
    )
    db.add(membership)
    db.flush()
    db.add(AuditLog(user_id=current_user.user_id, action="clinical_membership_created",
                    details={"membership_id": membership.id, "doctor_id": req.doctor_id,
                             "department_id": req.department_id}))
    db.commit()
    db.refresh(membership)

    return DoctorDepartmentMembershipResponse(
        id=membership.id,
        doctor_id=membership.doctor_id,
        doctor_name=f"Dr. {doc.user.full_name}" if doc.user else None,
        department_id=membership.department_id,
        department_name=dept.name,
        role=membership.role,
        is_active=membership.is_active,
        created_at=membership.created_at
    )
