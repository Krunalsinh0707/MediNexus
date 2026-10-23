"""Department-scoped LIS contracts built on signed shared clinical orders."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os

from fastapi import HTTPException
from sqlalchemy import func, inspect, or_

from src import clinical_order_service as orders
from src.clinical_order_models import (
    ClinicalOrder, LaboratoryOrderWorkflow, LaboratoryResultEvent,
    LaboratoryResultRevision, LaboratorySpecimen, LaboratorySpecimenEvent,
    LaboratoryStaffAssignment, LaboratoryWorkflowEvent,
)
from src.models import AuditLog, Department, Doctor, Encounter, Notification, User


LABORATORY_TABLES = (
    "laboratory_staff_assignments", "laboratory_order_workflows",
    "laboratory_workflow_events", "laboratory_specimens",
    "laboratory_specimen_events", "laboratory_result_revisions",
    "laboratory_result_events",
)
WORKFLOW_TRANSITIONS = {
    "AWAITING_REVIEW": {"ACCEPTED", "CLARIFICATION_REQUESTED", "REJECTED"},
    "CLARIFICATION_REQUESTED": {"ACCEPTED", "REJECTED"},
    "ACCEPTED": {"COLLECTION_PENDING"},
    "COLLECTION_PENDING": {"COLLECTED"},
    "COLLECTED": {"RECEIVED", "SPECIMEN_REJECTED"},
    "SPECIMEN_REJECTED": {"COLLECTION_PENDING"},
    "RECEIVED": {"PROCESSING"},
    "PROCESSING": set(), "RESULT_DRAFTED": set(), "RESULT_REJECTED": set(), "RESULT_VERIFIED": set(),
    "FINALIZED": set(), "REJECTED": set(),
}


@dataclass(frozen=True)
class LaboratoryActor:
    user_id: int
    assignment_id: int
    department_id: int
    assignment_role: str


class UnavailableReferenceRangeGateway:
    def find(self, **_kwargs):
        return None


reference_range_gateway = UnavailableReferenceRangeGateway()


def fail(status, detail):
    raise HTTPException(status, detail)


def require_laboratory_schema(db):
    orders.require_order_schema(db)
    try:
        inspector = inspect(db.get_bind())
        missing = [name for name in LABORATORY_TABLES if not inspector.has_table(name, schema="public")]
    except Exception as exc:
        raise HTTPException(503, "Laboratory storage readiness could not be verified") from exc
    if missing:
        raise HTTPException(503, "Laboratory storage is not installed")


def actor_for(db, token):
    user = db.get(User, token.user_id)
    if user is None or not user.password_hash:
        fail(401, "An eligible portal account is required")
    if user.role != "department_admin":
        fail(403, "An assigned laboratory staff account is required")
    code = os.getenv("HMS_LAB_DEPARTMENT_CODE", "LAB").strip().upper()
    assignment = db.query(LaboratoryStaffAssignment).join(
        Department, Department.id == LaboratoryStaffAssignment.department_id,
    ).filter(
        LaboratoryStaffAssignment.user_id == user.id,
        LaboratoryStaffAssignment.is_active == 1,
        func.upper(Department.code) == code,
    ).first()
    if assignment is None:
        fail(403, "No active assignment exists for the configured laboratory department")
    if assignment.assignment_role not in {"LAB_STAFF", "LAB_VERIFIER", "LAB_MANAGER"}:
        fail(403, "The laboratory assignment has an unsupported role")
    from src.workforce_service import source_assignment_current
    if not source_assignment_current(db, "LABORATORY", assignment.id):
        fail(403, "The managed laboratory assignment is suspended, revoked, or expired")
    return LaboratoryActor(user.id, assignment.id, assignment.department_id, assignment.assignment_role)


def queue_query(db, actor, search=None, priority=None, status=None, order_id=None, encounter_id=None):
    query = db.query(ClinicalOrder).join(User, User.id == ClinicalOrder.patient_id).outerjoin(
        LaboratoryOrderWorkflow, LaboratoryOrderWorkflow.order_id == ClinicalOrder.id,
    ).filter(
        ClinicalOrder.order_type == "LAB",
        ClinicalOrder.signed_at.is_not(None),
        ClinicalOrder.destination_department_id == actor.department_id,
    )
    if order_id is not None: query = query.filter(ClinicalOrder.id == order_id)
    if encounter_id is not None: query = query.filter(ClinicalOrder.encounter_id == encounter_id)
    if priority: query = query.filter(ClinicalOrder.priority == priority)
    if status:
        if status == "AWAITING_REVIEW":
            query = query.filter(LaboratoryOrderWorkflow.id.is_(None), ClinicalOrder.status != "CANCELLED")
        elif status == "ORDER_CANCELLED":
            query = query.filter(ClinicalOrder.status == "CANCELLED")
        else:
            query = query.filter(LaboratoryOrderWorkflow.status == status, ClinicalOrder.status != "CANCELLED")
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(or_(User.mrn.ilike(term), ClinicalOrder.display_name.ilike(term), ClinicalOrder.order_code.ilike(term)))
    return query


def readable(db, actor, order_id, lock=False):
    query = queue_query(db, actor, order_id=order_id)

    if lock:
        query = query.with_for_update(
            of=ClinicalOrder
        ).populate_existing()

    order = query.first()

    if order is None:
        fail(404, "Laboratory order not found")

    return order

def workflow_for(db, order, actor, lock=False):
    query = db.query(LaboratoryOrderWorkflow).filter(LaboratoryOrderWorkflow.order_id == order.id)
    if lock: query = query.with_for_update().populate_existing()
    workflow = query.first()
    if workflow and workflow.laboratory_department_id != actor.department_id:
        fail(409, "Laboratory workflow department does not match the order destination")
    return workflow


def latest_specimen(db, order_id, lock=False):
    query = db.query(LaboratorySpecimen).filter(LaboratorySpecimen.order_id == order_id).order_by(LaboratorySpecimen.id.desc())
    if lock: query = query.with_for_update().populate_existing()
    return query.first()


def _workflow_event(db, actor, workflow, source, target, reason=None):
    db.add(LaboratoryWorkflowEvent(
        workflow_id=workflow.id, sequence=workflow.version, workflow_version=workflow.version,
        from_status=source, to_status=target, actor_user_id=actor.user_id,
        actor_assignment_id=actor.assignment_id, reason=reason,
    ))


def _audit(db, actor, order, workflow, action):
    db.add(AuditLog(user_id=actor.user_id, action=f"Laboratory {action}", status="Success", details={
        "order_id": order.id, "patient_id": order.patient_id, "workflow_id": workflow.id,
        "laboratory_department_id": actor.department_id, "status": workflow.status,
        "version": workflow.version,
    }))


def transition_workflow(db, actor, order_id, data):
    order = readable(db, actor, order_id, lock=True)
    if order.status != "SIGNED": fail(409, "Only a currently signed laboratory order can be processed")
    workflow = workflow_for(db, order, actor, lock=True)
    source = workflow.status if workflow else "AWAITING_REVIEW"
    version = workflow.version if workflow else 0
    if version != data.expected_version: fail(409, "This laboratory workflow changed. Reload before retrying")
    if data.status not in WORKFLOW_TRANSITIONS.get(source, set()):
        fail(409, f"Laboratory workflow cannot move from {source} to {data.status}")
    if data.status in {"CLARIFICATION_REQUESTED", "REJECTED", "SPECIMEN_REJECTED"} and not data.reason:
        fail(422, "A reason is required")
    if workflow is None:
        workflow = LaboratoryOrderWorkflow(
            order_id=order.id, laboratory_department_id=actor.department_id,
            status=data.status, version=1, last_reason=data.reason,
        )
        db.add(workflow); db.flush()
    else:
        workflow.status = data.status; workflow.version += 1; workflow.last_reason = data.reason

    specimen = latest_specimen(db, order.id, lock=True)
    if data.status == "COLLECTED":
        if specimen and specimen.status != "REJECTED": fail(409, "An active specimen already exists for this order")
        specimen = LaboratorySpecimen(
            workflow_id=workflow.id, order_id=order.id, patient_id=order.patient_id,
            encounter_id=order.encounter_id, specimen_identifier=data.specimen_identifier,
            specimen_type=data.specimen_type, status="COLLECTED", version=1,
            collected_by_user_id=actor.user_id, collected_at=func.now(),
        )
        db.add(specimen); db.flush()
        db.add(LaboratorySpecimenEvent(specimen_id=specimen.id, sequence=1, from_status=None,
                                       to_status="COLLECTED", actor_user_id=actor.user_id))
    elif data.status in {"RECEIVED", "SPECIMEN_REJECTED"}:
        if specimen is None or specimen.status != "COLLECTED": fail(409, "A collected specimen is required")
        previous = specimen.status
        specimen.status = "RECEIVED" if data.status == "RECEIVED" else "REJECTED"
        specimen.version += 1
        specimen.received_by_user_id = actor.user_id
        specimen.received_at = func.now()
        specimen.rejection_reason = data.reason
        specimen.recollection_requested = 1 if data.recollection_requested else 0
        db.add(LaboratorySpecimenEvent(specimen_id=specimen.id, sequence=specimen.version,
                                       from_status=previous, to_status=specimen.status,
                                       actor_user_id=actor.user_id, reason=data.reason))
    elif data.status == "PROCESSING" and (specimen is None or specimen.status != "RECEIVED"):
        fail(409, "A received specimen is required before processing")

    _workflow_event(db, actor, workflow, source, data.status, data.reason)
    if data.status in {"CLARIFICATION_REQUESTED", "REJECTED", "SPECIMEN_REJECTED"}:
        db.add(Notification(user_id=order.requested_by_user_id, title="Laboratory order update",
                            message="A laboratory order requires clinician review.", type="LAB_REVIEW"))
    _audit(db, actor, order, workflow, data.status.lower())
    db.flush()
    return order


def _abnormality(value, range_data):
    if not range_data: return "NOT_ASSESSED"
    try: numeric = Decimal(value)
    except (InvalidOperation, TypeError): return "NOT_ASSESSED"
    low, high = range_data.get("low"), range_data.get("high")
    if low is not None and numeric < Decimal(str(low)): return "LOW"
    if high is not None and numeric > Decimal(str(high)): return "HIGH"
    return "NORMAL"


def _aggregate_result_status(db, order_id):
    revisions = db.query(LaboratoryResultRevision).filter(
        LaboratoryResultRevision.order_id == order_id,
    ).all()
    latest = {}
    for revision in revisions:
        prior = latest.get(revision.test_identifier)
        if prior is None or revision.revision_number > prior.revision_number:
            latest[revision.test_identifier] = revision
    statuses = {revision.status for revision in latest.values()}
    if not statuses or not statuses <= {"DRAFT", "VERIFIED", "FINALIZED", "REJECTED"}:
        fail(409, "Laboratory result state is incomplete. Reload before retrying")
    if "REJECTED" in statuses:
        return "RESULT_REJECTED"
    if "DRAFT" in statuses:
        return "RESULT_DRAFTED"
    if statuses == {"FINALIZED"}:
        return "FINALIZED"
    return "RESULT_VERIFIED"


def create_result(db, actor, order_id, data):
    order = readable(db, actor, order_id, lock=True)
    if order.status != "SIGNED": fail(409, "Only a currently signed laboratory order can receive results")
    workflow = workflow_for(db, order, actor, lock=True)
    if not workflow or workflow.status not in {"PROCESSING", "RESULT_DRAFTED", "RESULT_REJECTED", "RESULT_VERIFIED", "FINALIZED"}:
        fail(409, "Specimen processing must begin before result entry")
    if workflow.version != data.expected_workflow_version: fail(409, "This laboratory workflow changed. Reload before retrying")
    specimen = db.query(LaboratorySpecimen).filter(
        LaboratorySpecimen.id == data.specimen_id, LaboratorySpecimen.order_id == order.id,
        LaboratorySpecimen.patient_id == order.patient_id, LaboratorySpecimen.encounter_id == order.encounter_id,
        LaboratorySpecimen.status == "RECEIVED",
    ).with_for_update().populate_existing().first()
    if specimen is None: fail(422, "The received specimen does not belong to this order, patient, and encounter")
    previous = db.query(LaboratoryResultRevision).filter(
        LaboratoryResultRevision.order_id == order.id,
        LaboratoryResultRevision.test_identifier == data.test_identifier,
    ).order_by(LaboratoryResultRevision.revision_number.desc()).with_for_update().populate_existing().first()
    if previous and previous.status not in {"FINALIZED", "REJECTED"}: fail(409, "An unfinished result revision already exists for this test")
    if previous and not data.correction_reason: fail(422, "A correction reason is required after finalization or rejection")
    if not previous and data.correction_reason: fail(422, "A correction reason is valid only for a finalized or rejected result")
    patient = db.get(User, order.patient_id)
    approved_range = reference_range_gateway.find(
        test_identifier=data.test_identifier, patient=patient, result_unit=data.result_unit,
    )
    revision = LaboratoryResultRevision(
        workflow_id=workflow.id, order_id=order.id, specimen_id=specimen.id,
        test_identifier=data.test_identifier, test_name=data.test_name,
        revision_number=(previous.revision_number + 1 if previous else 1),
        previous_revision_id=previous.id if previous else None,
        result_value=data.result_value, result_unit=data.result_unit,
        reference_range_text=approved_range.get("display") if approved_range else None,
        reference_range_source=approved_range.get("source") if approved_range else None,
        abnormality_flag=_abnormality(data.result_value, approved_range), status="DRAFT", version=1,
        correction_reason=data.correction_reason, entered_by_user_id=actor.user_id,
    )
    db.add(revision); db.flush()
    db.add(LaboratoryResultEvent(result_revision_id=revision.id, sequence=1, result_version=1,
                                 from_status=None, to_status="DRAFT", actor_user_id=actor.user_id,
                                 reason=data.correction_reason))
    source = workflow.status; workflow.status = _aggregate_result_status(db, order.id); workflow.version += 1
    _workflow_event(db, actor, workflow, source, workflow.status, "correction" if previous else None)
    _audit(db, actor, order, workflow, "result drafted")
    db.flush()
    return order


def transition_result(db, actor, order_id, result_id, data):
    order = readable(db, actor, order_id, lock=True)
    if order.status != "SIGNED": fail(409, "Only a currently signed laboratory order can be finalized")
    workflow = workflow_for(db, order, actor, lock=True)
    if not workflow or workflow.version != data.expected_workflow_version:
        fail(409, "This laboratory workflow changed. Reload before retrying")
    result = db.query(LaboratoryResultRevision).filter(
        LaboratoryResultRevision.id == result_id, LaboratoryResultRevision.order_id == order.id,
    ).with_for_update().populate_existing().first()
    if result is None: fail(404, "Laboratory result revision not found")
    if result.version != data.expected_result_version: fail(409, "This result changed. Reload before retrying")
    targets_for = {"DRAFT": {"VERIFIED", "REJECTED"}, "VERIFIED": {"FINALIZED", "REJECTED"}}
    if data.status not in targets_for.get(result.status, set()): fail(409, f"Result cannot move from {result.status} to {data.status}")
    if actor.assignment_role not in {"LAB_VERIFIER", "LAB_MANAGER"}:
        fail(403, "A laboratory verifier assignment is required")
    source = result.status; result.status = data.status; result.version += 1
    if data.status == "VERIFIED": result.verified_by_user_id = actor.user_id; result.verified_at = func.now()
    elif data.status == "FINALIZED":
        result.finalized_by_user_id = actor.user_id; result.finalized_at = func.now()
        db.add(Notification(user_id=order.requested_by_user_id, title="Laboratory result available",
                            message="A finalized laboratory result is ready for clinical follow-up.", type="LAB_RESULT"))
    db.add(LaboratoryResultEvent(result_revision_id=result.id, sequence=result.version,
                                 result_version=result.version, from_status=source, to_status=data.status,
                                 actor_user_id=actor.user_id, reason=data.comment))
    workflow_source = workflow.status
    workflow.status = _aggregate_result_status(db, order.id)
    workflow.version += 1
    _workflow_event(db, actor, workflow, workflow_source, workflow.status, data.comment)
    _audit(db, actor, order, workflow, f"result {data.status.lower()}")
    db.flush()
    return order


def projection(db, actor, order):
    patient = db.get(User, order.patient_id); encounter = db.get(Encounter, order.encounter_id)
    doctor = db.get(Doctor, order.requested_by_doctor_id)
    prescriber = db.get(User, doctor.user_id) if doctor else None
    if patient is None or encounter is None: raise HTTPException(503, "Laboratory order relationships are incomplete")
    workflow = workflow_for(db, order, actor)
    specimens = db.query(LaboratorySpecimen).filter(LaboratorySpecimen.order_id == order.id).order_by(LaboratorySpecimen.id).all()
    results = db.query(LaboratoryResultRevision).filter(LaboratoryResultRevision.order_id == order.id).order_by(
        LaboratoryResultRevision.test_identifier, LaboratoryResultRevision.revision_number,
    ).all()
    events = [] if not workflow else db.query(LaboratoryWorkflowEvent).filter(
        LaboratoryWorkflowEvent.workflow_id == workflow.id).order_by(LaboratoryWorkflowEvent.sequence).all()
    specimen_items = []
    for row in specimens:
        specimen_events = db.query(LaboratorySpecimenEvent).filter(
            LaboratorySpecimenEvent.specimen_id == row.id,
        ).order_by(LaboratorySpecimenEvent.sequence).all()
        specimen_items.append({
            **{name: getattr(row, name) for name in "id specimen_identifier specimen_type status version collected_by_user_id collected_at received_by_user_id received_at rejection_reason recollection_requested".split()},
            "events": [{"sequence": event.sequence, "from_status": event.from_status,
                        "to_status": event.to_status, "actor_user_id": event.actor_user_id,
                        "reason": event.reason, "created_at": event.created_at} for event in specimen_events],
        })
    status = "ORDER_CANCELLED" if order.status == "CANCELLED" else (workflow.status if workflow else "AWAITING_REVIEW")
    return {
        "order_id": order.id, "patient": {"id": patient.id, "mrn": patient.mrn, "full_name": patient.full_name},
        "encounter": {"id": encounter.id, "status": encounter.status},
        "requesting_clinician": {"doctor_id": doctor.id if doctor else None, "full_name": prescriber.full_name if prescriber else "Unavailable"},
        "laboratory_department_id": order.destination_department_id, "test_code": order.order_code,
        "test_name": order.display_name, "priority": order.priority, "order_status": order.status,
        "laboratory_status": status, "version": workflow.version if workflow else 0,
        "allowed_actions": [] if order.status == "CANCELLED" else sorted(WORKFLOW_TRANSITIONS.get(status, set())),
        "specimens": specimen_items,
        "results": [{
            **{name: getattr(row, name) for name in "id specimen_id test_identifier test_name revision_number previous_revision_id result_value result_unit reference_range_text reference_range_source abnormality_flag status version correction_reason entered_by_user_id verified_by_user_id finalized_by_user_id entered_at verified_at finalized_at".split()},
            "allowed_actions": (
                ["VERIFIED", "REJECTED"] if row.status == "DRAFT" and actor.assignment_role in {"LAB_VERIFIER", "LAB_MANAGER"}
                else ["FINALIZED", "REJECTED"] if row.status == "VERIFIED" and actor.assignment_role in {"LAB_VERIFIER", "LAB_MANAGER"}
                else []
            ) if order.status != "CANCELLED" else [],
        } for row in results],
        "events": [{"sequence": row.sequence, "from_status": row.from_status, "to_status": row.to_status,
                    "actor_user_id": row.actor_user_id, "reason": row.reason, "created_at": row.created_at} for row in events],
    }


def finalized_results_for_reader(db, actor, order_id):
    if actor.role not in orders.CLINICAL_ROLES | orders.PATIENT_ROLES:
        fail(403, "Final laboratory results are available only to the patient or an authorized clinician")
    order = orders.readable(db, actor, order_id)
    if order.order_type != "LAB": fail(404, "Laboratory order not found")
    if order.signed_at is None or order.status == "CANCELLED":
        fail(404, "Released laboratory results are unavailable for this order")
    rows = db.query(LaboratoryResultRevision).join(
        LaboratorySpecimen, LaboratorySpecimen.id == LaboratoryResultRevision.specimen_id,
    ).filter(
        LaboratoryResultRevision.order_id == order.id,
        LaboratoryResultRevision.status == "FINALIZED",
        LaboratorySpecimen.order_id == order.id,
        LaboratorySpecimen.patient_id == order.patient_id,
        LaboratorySpecimen.encounter_id == order.encounter_id,
    ).order_by(LaboratoryResultRevision.test_identifier, LaboratoryResultRevision.revision_number.desc()).all()
    latest = {}
    for row in rows:
        latest.setdefault(row.test_identifier, row)
    response = {
        "order_id": order.id, "patient_id": order.patient_id, "encounter_id": order.encounter_id,
        "results": [{
            "test_identifier": row.test_identifier, "test_name": row.test_name,
            "revision_number": row.revision_number, "result_value": row.result_value,
            "result_unit": row.result_unit, "reference_range_text": row.reference_range_text,
            "reference_range_source": row.reference_range_source,
            "abnormality_flag": row.abnormality_flag, "finalized_at": row.finalized_at,
            "corrected": row.revision_number > 1,
        } for row in latest.values()],
    }
    if actor.role in orders.CLINICAL_ROLES:
        response["revision_history"] = [{
            "test_identifier": row.test_identifier, "test_name": row.test_name,
            "revision_number": row.revision_number, "result_value": row.result_value,
            "result_unit": row.result_unit, "abnormality_flag": row.abnormality_flag,
            "finalized_at": row.finalized_at,
        } for row in rows]
    return response
