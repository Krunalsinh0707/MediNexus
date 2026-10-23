"""Clinical order lifecycle and object-level authorization.

Callers own commit and rollback. Clinical narrative is retained in the order
record/history and excluded from general audit entries and notifications.
"""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import inspect, or_

from src import encounter_service
from src.clinical_chat.access_policy import get_authorized_department_ids_for_doctor
from src.clinical_order_models import (
    ClinicalOrder, ClinicalOrderEvent, LaboratoryOrderWorkflow,
    PharmacyDispenseWorkflow, RadiologyWorkflow,
)
from src.models import AuditLog, Department, Doctor, DoctorDepartmentMembership, Encounter, Notification, User


ORDER_TABLES = ("clinical_orders", "clinical_order_events")
ADMIN_ROLES = {"admin", "hospital_admin"}
CLINICAL_ROLES = {"doctor", "emergency_doctor"}
PATIENT_ROLES = {"patient", "user"}
ALLOWED_TRANSITIONS = {
    "DRAFT": {"SIGNED", "CANCELLED"},
    "SIGNED": {"ACCEPTED", "CANCELLED"},
    "ACCEPTED": {"IN_PROGRESS", "CANCELLED"},
    "IN_PROGRESS": {"COMPLETED", "CANCELLED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}
SPECIALIST_WORKFLOWS = {
    "LAB": LaboratoryOrderWorkflow,
    "IMAGING": RadiologyWorkflow,
    "MEDICATION": PharmacyDispenseWorkflow,
}


def fail(code, message):
    raise HTTPException(status_code=code, detail=message)


def now():
    return datetime.now(timezone.utc)


def require_order_schema(db):
    """Fail closed until the separately approved additive migration is applied."""
    try:
        inspector = inspect(db.get_bind())
        missing = [name for name in ORDER_TABLES if not inspector.has_table(name, schema="public")]
    except Exception as exc:
        raise HTTPException(503, "Clinical order storage readiness could not be verified") from exc
    if missing:
        raise HTTPException(503, "Clinical order storage is not installed")


def actor_for(db, token):
    return encounter_service.actor_for(db, token)


def audit(db, actor, order, action):
    db.add(AuditLog(
        user_id=actor.user_id,
        action="Clinical order " + action,
        status="Success",
        details={
            "order_id": order.id,
            "patient_id": order.patient_id,
            "encounter_id": order.encounter_id,
            "requesting_doctor_id": order.requested_by_doctor_id,
            "destination_department_id": order.destination_department_id,
            "order_type": order.order_type,
            "priority": order.priority,
            "status": order.status,
            "version": order.version,
        },
    ))


def add_event(db, order, actor, source, target, reason=None):
    db.add(ClinicalOrderEvent(
        order_id=order.id,
        sequence=order.version,
        order_version=order.version,
        from_status=source,
        to_status=target,
        actor_user_id=actor.user_id,
        actor_doctor_id=actor.doctor_id,
        reason=reason,
    ))


def department_ids(db, actor):
    if actor.role not in CLINICAL_ROLES or actor.doctor_id is None:
        return set()
    doctor = db.query(Doctor).join(User, User.id == Doctor.user_id).filter(
        Doctor.id == actor.doctor_id,
        Doctor.user_id == actor.user_id,
        Doctor.status == "Active",
        User.role.in_(CLINICAL_ROLES),
        User.password_hash.is_not(None),
    ).first()
    return set(get_authorized_department_ids_for_doctor(db, doctor)) if doctor else set()


def can_handle(db, actor, order):
    return actor.role in CLINICAL_ROLES and order.destination_department_id in department_ids(db, actor)


def readable_query(db, actor, patient_id=None, encounter_id=None):
    query = db.query(ClinicalOrder)
    if actor.role in ADMIN_ROLES:
        pass
    elif actor.role in CLINICAL_ROLES:
        departments = department_ids(db, actor)
        conditions = [ClinicalOrder.requested_by_doctor_id == actor.doctor_id]
        if departments:
            conditions.append(
                (ClinicalOrder.destination_department_id.in_(departments)) &
                ClinicalOrder.signed_at.is_not(None)
            )
        query = query.filter(or_(*conditions))
    elif actor.role in PATIENT_ROLES:
        query = query.filter(
            ClinicalOrder.patient_id == actor.user_id,
            # A cancelled unsigned draft remains internal to its requester.
            ClinicalOrder.signed_at.is_not(None),
        )
    else:
        fail(403, "Clinical order access is not permitted")
    if patient_id is not None:
        if actor.role in PATIENT_ROLES and actor.user_id != patient_id:
            fail(404, "Clinical order not found")
        query = query.filter(ClinicalOrder.patient_id == patient_id)
    if encounter_id is not None:
        query = query.filter(ClinicalOrder.encounter_id == encounter_id)
    return query


def readable(db, actor, order_id, lock=False):
    query = readable_query(db, actor).filter(ClinicalOrder.id == order_id)
    if lock:
        query = query.with_for_update().populate_existing()
    order = query.first()
    if order is None:
        fail(404, "Clinical order not found")
    return order


def create_order(db, actor, data, allow_medication=False, allow_imaging=False):
    if actor.role not in CLINICAL_ROLES or actor.doctor_id is None:
        fail(403, "An active clinician is required to create an order")
    if data.order_type == "MEDICATION" and not allow_medication:
        fail(422, "Use the medication prescribing endpoint for medication orders")
    if data.order_type == "IMAGING" and not allow_imaging:
        fail(422, "Use the imaging order endpoint so modality and body region are recorded")
    encounter = db.query(Encounter).filter(Encounter.id == data.encounter_id).with_for_update().populate_existing().first()
    if encounter is None:
        fail(404, "Visit not found")
    if encounter.patient_id != data.patient_id:
        fail(422, "Visit does not belong to the selected patient")
    encounter_service.assigned_clinician(actor, encounter)
    if encounter.status != "IN_PROGRESS":
        fail(409, "Orders can be created only during an in-progress visit")
    patient = db.get(User, data.patient_id)
    if patient is None or patient.role not in PATIENT_ROLES or not patient.mrn:
        fail(422, "Select a registered patient with an MRN")
    if db.get(Department, data.destination_department_id) is None:
        fail(422, "Destination department not found")

    order = ClinicalOrder(
        patient_id=patient.id,
        encounter_id=encounter.id,
        requested_by_user_id=actor.user_id,
        requested_by_doctor_id=actor.doctor_id,
        destination_department_id=data.destination_department_id,
        order_type=data.order_type,
        priority=data.priority,
        order_code=data.order_code,
        display_name=data.display_name,
        clinical_indication=data.clinical_indication,
        status="DRAFT",
        version=1,
    )
    db.add(order)
    db.flush()
    add_event(db, order, actor, None, "DRAFT")
    audit(db, actor, order, "draft created")
    return order


def recipient_user_ids(db, department_id):
    eligible = (
        User.role.in_(CLINICAL_ROLES),
        User.password_hash.is_not(None),
    )
    primary = db.query(Doctor.user_id).join(User, User.id == Doctor.user_id).filter(
        Doctor.department_id == department_id, Doctor.status == "Active", *eligible
    ).all()
    members = db.query(Doctor.user_id, DoctorDepartmentMembership.id).join(
        DoctorDepartmentMembership,
        DoctorDepartmentMembership.doctor_id == Doctor.id,
    ).join(
        User,
        User.id == Doctor.user_id,
    ).filter(
        DoctorDepartmentMembership.department_id == department_id,
        DoctorDepartmentMembership.is_active == True,
        Doctor.status == "Active",
        *eligible,
    ).all()
    from src.workforce_service import source_assignment_current
    return ({row[0] for row in primary} |
            {row[0] for row in members if source_assignment_current(db, "DOCTOR", row[1])})


def notify_signed(db, order):
    for user_id in recipient_user_ids(db, order.destination_department_id):
        if user_id == order.requested_by_user_id:
            continue
        db.add(Notification(
            user_id=user_id,
            title="New clinical order",
            message=f"A {order.priority.lower()} {order.order_type.lower()} order is ready for your department.",
            type="CLINICAL_ORDER",
        ))


def specialist_workflow_started(db, order):
    """Check for departmental activity before offering or accepting cancellation."""
    model = SPECIALIST_WORKFLOWS.get(order.order_type)
    if model is None or order.signed_at is None:
        return False
    try:
        installed = inspect(db.get_bind()).has_table(model.__tablename__, schema="public")
        if not installed:
            return False  # No department workflow can exist without its table.
        started = db.query(model.id).filter(model.order_id == order.id).first()
    except Exception as exc:
        raise HTTPException(503, "Department workflow readiness could not be verified") from exc
    return started is not None


def require_cancellable_specialist_order(db, order):
    if specialist_workflow_started(db, order):
        fail(409, "Department work has begun. Resolve the department workflow before changing this order")


def transition_order(db, actor, order_id, data, required_order_type=None):
    order = readable(db, actor, order_id, lock=True)
    if required_order_type is not None and order.order_type != required_order_type:
        fail(404, "Clinical order not found")
    if order.version != data.expected_version:
        fail(409, "This order changed. Reload it before retrying; your changes were not saved")
    source, target = order.status, data.status
    if order.order_type in {"MEDICATION", "LAB", "IMAGING"} and target not in {"SIGNED", "CANCELLED"}:
        fail(409, f"{order.order_type.title()} fulfillment requires its department workflow")
    if target not in ALLOWED_TRANSITIONS.get(source, set()):
        fail(409, f"Clinical order cannot move from {source} to {target}")

    requester = actor.role in CLINICAL_ROLES and actor.doctor_id == order.requested_by_doctor_id
    handler = can_handle(db, actor, order)
    timestamp = now()
    if target == "SIGNED":
        if not requester:
            fail(403, "Only the requesting active clinician may sign this order")
        encounter = db.get(Encounter, order.encounter_id)
        if encounter is None or encounter.patient_id != order.patient_id:
            fail(409, "The linked visit is unavailable or inconsistent")
        encounter_service.assigned_clinician(actor, encounter)
        if encounter.status != "IN_PROGRESS":
            fail(409, "The linked visit must be in progress when the order is signed")
        order.signed_at = timestamp
    elif target == "ACCEPTED":
        if not handler:
            fail(403, "Only an active clinician for the destination department may accept this order")
        order.accepted_at = timestamp
    elif target == "IN_PROGRESS":
        if not handler:
            fail(403, "Only an active clinician for the destination department may start this order")
        order.started_at = timestamp
    elif target == "COMPLETED":
        if not handler:
            fail(403, "Only an active clinician for the destination department may complete this order")
        order.completed_at = timestamp
    elif target == "CANCELLED":
        if not data.reason:
            fail(422, "Cancellation requires a reason")
        if not requester and not handler:
            fail(403, "Only the requester or destination department may cancel this order")
        require_cancellable_specialist_order(db, order)
        order.cancelled_at = timestamp
        order.cancellation_reason = data.reason

    order.status = target
    order.version += 1
    add_event(db, order, actor, source, target, data.reason)
    audit(db, actor, order, target.lower())
    if target == "SIGNED":
        notify_signed(db, order)
    elif target == "COMPLETED":
        db.add(Notification(
            user_id=order.patient_id,
            title="Clinical order completed",
            message="A clinical order from your visit has been completed.",
            type="CLINICAL_ORDER",
        ))
    db.flush()
    return order


def allowed_actions(db, actor, order):
    if order.status in {"COMPLETED", "CANCELLED"} or actor.role not in CLINICAL_ROLES:
        return []
    requester = actor.doctor_id == order.requested_by_doctor_id
    handler = can_handle(db, actor, order)
    actions = []
    if order.status == "DRAFT" and requester:
        encounter = db.get(Encounter, order.encounter_id)
        if (encounter is not None and encounter.patient_id == order.patient_id
                and encounter.doctor_id == actor.doctor_id and encounter.status == "IN_PROGRESS"):
            actions.append("SIGNED")
    elif order.status == "SIGNED" and handler and order.order_type not in {"MEDICATION", "LAB", "IMAGING"}:
        actions.append("ACCEPTED")
    elif order.status == "ACCEPTED" and handler and order.order_type not in {"MEDICATION", "LAB", "IMAGING"}:
        actions.append("IN_PROGRESS")
    elif order.status == "IN_PROGRESS" and handler and order.order_type not in {"MEDICATION", "LAB", "IMAGING"}:
        actions.append("COMPLETED")
    if (requester or handler) and not specialist_workflow_started(db, order):
        actions.append("CANCELLED")
    return actions


def projection(db, actor, order):
    names = (
        "id patient_id encounter_id requested_by_user_id requested_by_doctor_id "
        "destination_department_id order_type priority order_code display_name clinical_indication "
        "status version cancellation_reason created_at updated_at signed_at accepted_at started_at "
        "completed_at cancelled_at"
    ).split()
    result = {name: getattr(order, name) for name in names}
    if actor.role in PATIENT_ROLES:
        result["clinical_indication"] = None
        result["cancellation_reason"] = None
        result["events"] = []
    else:
        events = db.query(ClinicalOrderEvent).filter(
            ClinicalOrderEvent.order_id == order.id
        ).order_by(ClinicalOrderEvent.sequence).all()
        result["events"] = [{
            name: getattr(event, name)
            for name in "id sequence order_version from_status to_status actor_user_id actor_doctor_id reason created_at".split()
        } for event in events]
    result["allowed_actions"] = allowed_actions(db, actor, order)
    return result
