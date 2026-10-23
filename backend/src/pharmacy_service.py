"""Department-scoped pharmacy review and dispensing contracts."""

from dataclasses import dataclass
from decimal import Decimal
import os

from fastapi import HTTPException
from sqlalchemy import func, inspect, or_

from src import clinical_order_service as orders
from src.clinical_order_models import (
    ClinicalOrder, MedicationOrderDetail, PharmacyDispenseEvent,
    PharmacyDispenseRecord, PharmacyDispenseWorkflow, PharmacyStaffAssignment,
)
from src.models import AuditLog, Department, Doctor, Notification, User


PHARMACY_TABLES = (
    "pharmacy_staff_assignments", "pharmacy_dispense_workflows",
    "pharmacy_dispense_events", "pharmacy_dispense_records",
)
REVIEW_TRANSITIONS = {
    "AWAITING_REVIEW": {"ACCEPTED", "CLARIFICATION_REQUESTED", "REJECTED"},
    "CLARIFICATION_REQUESTED": {"ACCEPTED", "REJECTED"},
    "ACCEPTED": {"IN_PROGRESS"},
    "IN_PROGRESS": {"PARTIALLY_DISPENSED", "COMPLETED"},
    "PARTIALLY_DISPENSED": {"PARTIALLY_DISPENSED", "COMPLETED"},
    "REJECTED": set(),
    "COMPLETED": set(),
}


@dataclass(frozen=True)
class PharmacyActor:
    user_id: int
    assignment_id: int
    department_id: int
    assignment_role: str


class UnavailableInventoryGateway:
    def is_configured(self):
        return False

    def verify_available(self, **_kwargs):
        raise HTTPException(503, "Inventory stock verification is unavailable")

    def dispense(self, **_kwargs):
        raise HTTPException(503, "Inventory dispensing transaction is unavailable")


inventory_gateway = UnavailableInventoryGateway()


def require_pharmacy_schema(db):
    from src import medication_order_service
    medication_order_service.require_medication_schema(db)
    try:
        inspector = inspect(db.get_bind())
        missing = [name for name in PHARMACY_TABLES if not inspector.has_table(name, schema="public")]
    except Exception as exc:
        raise HTTPException(503, "Pharmacy storage readiness could not be verified") from exc
    if missing:
        raise HTTPException(503, "Pharmacy storage is not installed")


def actor_for(db, token):
    user = db.get(User, token.user_id)
    if user is None or not user.password_hash:
        orders.fail(401, "An eligible portal account is required")
    if user.role != "department_admin":
        orders.fail(403, "An assigned pharmacy staff account is required")
    code = os.getenv("HMS_PHARMACY_DEPARTMENT_CODE", "PHARM").strip().upper()
    assignment = db.query(PharmacyStaffAssignment).join(
        Department, Department.id == PharmacyStaffAssignment.department_id,
    ).filter(
        PharmacyStaffAssignment.user_id == user.id,
        PharmacyStaffAssignment.is_active == 1,
        func.upper(Department.code) == code,
    ).first()
    if assignment is None:
        orders.fail(403, "No active assignment exists for the configured pharmacy department")
    if assignment.assignment_role not in {"PHARMACY_STAFF", "PHARMACY_MANAGER"}:
        orders.fail(403, "The pharmacy assignment has an unsupported role")
    from src.workforce_service import source_assignment_current
    if not source_assignment_current(db, "PHARMACY", assignment.id):
        orders.fail(403, "The managed pharmacy assignment is suspended, revoked, or expired")
    return PharmacyActor(user.id, assignment.id, assignment.department_id, assignment.assignment_role)


def queue_query(db, actor, search=None, priority=None, status=None, prescription_id=None):
    query = db.query(ClinicalOrder).join(
        MedicationOrderDetail, MedicationOrderDetail.order_id == ClinicalOrder.id,
    ).join(User, User.id == ClinicalOrder.patient_id).outerjoin(
        PharmacyDispenseWorkflow, PharmacyDispenseWorkflow.order_id == ClinicalOrder.id,
    ).filter(
        ClinicalOrder.order_type == "MEDICATION",
        ClinicalOrder.signed_at.is_not(None),
        ClinicalOrder.destination_department_id == actor.department_id,
    )
    if prescription_id is not None:
        query = query.filter(ClinicalOrder.id == prescription_id)
    if priority:
        query = query.filter(ClinicalOrder.priority == priority)
    if status:
        if status == "AWAITING_REVIEW":
            query = query.filter(PharmacyDispenseWorkflow.id.is_(None), ClinicalOrder.status != "CANCELLED")
        elif status == "PRESCRIPTION_CANCELLED":
            query = query.filter(ClinicalOrder.status == "CANCELLED")
        else:
            query = query.filter(PharmacyDispenseWorkflow.status == status, ClinicalOrder.status != "CANCELLED")
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(or_(
            User.mrn.ilike(term),
            MedicationOrderDetail.medication_display_name.ilike(term),
            MedicationOrderDetail.medication_identifier.ilike(term),
        ))
    return query


def readable(db, actor, order_id, lock=False):
    query = queue_query(db, actor, prescription_id=order_id)
    if lock:
        query = query.with_for_update().populate_existing()
    order = query.first()
    if order is None:
        orders.fail(404, "Prescription not found")
    return order


def workflow_for(db, order, lock=False, expected_department_id=None):
    query = db.query(PharmacyDispenseWorkflow).filter(PharmacyDispenseWorkflow.order_id == order.id)
    if lock:
        query = query.with_for_update().populate_existing()
    workflow = query.first()
    if (
        workflow is not None
        and expected_department_id is not None
        and workflow.pharmacy_department_id != expected_department_id
    ):
        orders.fail(409, "Pharmacy workflow department does not match the prescription destination")
    return workflow


def history(db, workflow):
    if workflow is None:
        return [], []
    events = db.query(PharmacyDispenseEvent).filter(
        PharmacyDispenseEvent.workflow_id == workflow.id
    ).order_by(PharmacyDispenseEvent.sequence).all()
    records = db.query(PharmacyDispenseRecord).filter(
        PharmacyDispenseRecord.workflow_id == workflow.id
    ).order_by(PharmacyDispenseRecord.id).all()
    return events, records


def allowed_actions(status):
    actions = sorted(REVIEW_TRANSITIONS.get(status, set()))
    if not inventory_gateway.is_configured():
        actions = [item for item in actions if item not in {"IN_PROGRESS", "PARTIALLY_DISPENSED", "COMPLETED"}]
    return actions


def projection(db, actor, order):
    detail = db.query(MedicationOrderDetail).filter(MedicationOrderDetail.order_id == order.id).first()
    patient = db.get(User, order.patient_id)
    doctor = db.get(Doctor, order.requested_by_doctor_id)
    prescriber = db.get(User, doctor.user_id) if doctor else None
    if detail is None or patient is None:
        raise HTTPException(503, "Prescription storage is incomplete")
    workflow = workflow_for(db, order, expected_department_id=actor.department_id)
    status = "PRESCRIPTION_CANCELLED" if order.status == "CANCELLED" else (workflow.status if workflow else "AWAITING_REVIEW")
    events, records = history(db, workflow)
    return {
        "prescription_id": order.id,
        "patient": {"id": patient.id, "mrn": patient.mrn, "full_name": patient.full_name},
        "prescriber": {"doctor_id": doctor.id if doctor else None, "full_name": prescriber.full_name if prescriber else "Unavailable"},
        "pharmacy_department_id": order.destination_department_id,
        "priority": order.priority,
        "prescription_status": order.status,
        "pharmacy_status": status,
        "version": workflow.version if workflow else 0,
        "medication": {
            name: getattr(detail, name) for name in (
                "medication_identifier_system medication_identifier medication_display_name dose dose_unit route "
                "frequency duration_value duration_unit quantity quantity_unit start_date instructions"
            ).split()
        },
        "allergy_warnings": detail.allergy_warning_snapshot or [],
        "inventory_ready": inventory_gateway.is_configured(),
        "allowed_actions": [] if order.status == "CANCELLED" else allowed_actions(status),
        "events": [{
            "sequence": row.sequence, "from_status": row.from_status, "to_status": row.to_status,
            "actor_user_id": row.actor_user_id, "reason": row.reason, "created_at": row.created_at,
        } for row in events],
        "dispensing_history": [{
            "quantity": row.quantity, "quantity_unit": row.quantity_unit,
            "inventory_transaction_reference": row.inventory_transaction_reference,
            "dispensed_by_user_id": row.dispensed_by_user_id, "created_at": row.created_at,
        } for row in records],
    }


def audit(db, actor, order, workflow, action):
    db.add(AuditLog(user_id=actor.user_id, action="Pharmacy " + action, status="Success", details={
        "prescription_id": order.id, "workflow_id": workflow.id,
        "patient_id": order.patient_id, "pharmacy_department_id": actor.department_id,
        "status": workflow.status, "version": workflow.version,
    }))


def transition(db, actor, order_id, data):
    order = readable(db, actor, order_id, lock=True)
    if order.status != "SIGNED":
        orders.fail(409, "Only a currently signed prescription can be processed")
    workflow = workflow_for(db, order, lock=True, expected_department_id=actor.department_id)
    source = workflow.status if workflow else "AWAITING_REVIEW"
    current_version = workflow.version if workflow else 0
    if current_version != data.expected_version:
        orders.fail(409, "This pharmacy workflow changed. Reload before retrying")
    if data.status not in REVIEW_TRANSITIONS.get(source, set()):
        orders.fail(409, f"Pharmacy workflow cannot move from {source} to {data.status}")
    if data.status in {"CLARIFICATION_REQUESTED", "REJECTED"} and not data.reason:
        orders.fail(422, "A reason is required")

    detail = db.query(MedicationOrderDetail).filter(MedicationOrderDetail.order_id == order.id).first()
    if detail is None:
        raise HTTPException(503, "Prescription storage is incomplete")
    if workflow is None:
        workflow = PharmacyDispenseWorkflow(
            order_id=order.id, pharmacy_department_id=actor.department_id,
            status=data.status, version=1, last_reason=data.reason,
        )
        db.add(workflow)
        db.flush()
    else:
        workflow.status = data.status
        workflow.version += 1
        workflow.last_reason = data.reason

    inventory_result = None
    if data.status == "IN_PROGRESS":
        inventory_gateway.verify_available(
            medication_identifier=detail.medication_identifier,
            quantity=detail.quantity,
            quantity_unit=detail.quantity_unit,
            department_id=actor.department_id,
        )
    elif data.status in {"PARTIALLY_DISPENSED", "COMPLETED"}:
        if data.quantity_unit.strip().lower() != detail.quantity_unit.strip().lower():
            orders.fail(422, "Dispensing unit must match the prescribed quantity unit")
        prior = db.query(func.coalesce(func.sum(PharmacyDispenseRecord.quantity), 0)).filter(
            PharmacyDispenseRecord.workflow_id == workflow.id
        ).scalar()
        total = Decimal(str(prior)) + data.quantity
        prescribed = Decimal(str(detail.quantity))
        if total > prescribed:
            orders.fail(409, "Dispensed quantity cannot exceed the prescribed quantity")
        if data.status == "PARTIALLY_DISPENSED" and total >= prescribed:
            orders.fail(422, "Use completed dispensing when the full quantity is supplied")
        if data.status == "COMPLETED" and total != prescribed:
            orders.fail(422, "Completed dispensing requires the full prescribed quantity")
        inventory_result = inventory_gateway.dispense(
            stock_item_identifier=data.stock_item_identifier,
            medication_identifier=detail.medication_identifier,
            quantity=data.quantity,
            quantity_unit=data.quantity_unit,
            department_id=actor.department_id,
        )
        if not isinstance(inventory_result, dict) or not str(
            inventory_result.get("transaction_reference", "")
        ).strip():
            raise HTTPException(503, "Inventory did not confirm an atomic dispensing transaction")

    event = PharmacyDispenseEvent(
        workflow_id=workflow.id, sequence=workflow.version, workflow_version=workflow.version,
        from_status=source, to_status=data.status, actor_user_id=actor.user_id,
        actor_assignment_id=actor.assignment_id, reason=data.reason,
    )
    db.add(event)
    db.flush()
    if inventory_result is not None:
        db.add(PharmacyDispenseRecord(
            workflow_id=workflow.id, event_id=event.id, quantity=data.quantity,
            quantity_unit=data.quantity_unit,
            inventory_transaction_reference=inventory_result["transaction_reference"],
            dispensed_by_user_id=actor.user_id,
        ))
    if data.status in {"CLARIFICATION_REQUESTED", "REJECTED"}:
        db.add(Notification(
            user_id=order.requested_by_user_id,
            title="Prescription pharmacy review updated",
            message="A prescription requires prescriber review in the pharmacy workflow.",
            type="PHARMACY_REVIEW",
        ))
    audit(db, actor, order, workflow, data.status.lower())
    db.flush()
    return order
