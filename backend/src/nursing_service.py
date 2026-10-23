"""Ward-scoped nursing records. All persistence is migration-gated."""
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import inspect

from src import inpatient_service
from src.clinical_order_models import ClinicalOrder, MedicationOrderDetail, PharmacyDispenseRecord, PharmacyDispenseWorkflow
from src.inpatient_models import Bed, InpatientAdmission, InpatientStaffAssignment, Room
from src.models import AuditLog, Encounter, EncounterVitals, User
from src.nursing_models import NursingCarePlan, NursingNote, NursingObservation, NursingTask, NursingWorkflowEvent


TABLES = tuple(model.__tablename__ for model in
    (NursingObservation, NursingNote, NursingCarePlan, NursingTask, NursingWorkflowEvent))
MEASUREMENTS = ("systolic_mmhg", "diastolic_mmhg", "pulse_bpm", "respiratory_rate_per_min",
                "temperature_c", "spo2_percent", "weight_kg", "height_cm")
PLAN_TRANSITIONS = {"DRAFT": {"ACTIVE", "CANCELLED"}, "ACTIVE": {"COMPLETED", "CANCELLED"}}
TASK_TRANSITIONS = {"PENDING": {"IN_PROGRESS", "DONE", "CANCELLED"},
                    "IN_PROGRESS": {"DONE", "CANCELLED"}}


def fail(code, message):
    raise HTTPException(code, message)


def now():
    return datetime.now(timezone.utc)


def require_schema(db):
    inpatient_service.require_schema(db)
    try:
        inspector = inspect(db.get_bind())
        missing = [name for name in (*TABLES, "encounter_vitals") if not inspector.has_table(name, schema="public")]
    except Exception as exc:
        raise HTTPException(503, "Nursing storage readiness could not be verified") from exc
    if missing:
        fail(503, "Nursing storage is not installed")


@dataclass(frozen=True)
class NurseActor:
    user_id: int
    ward_ids: frozenset[int]


def actor_for(db, token):
    user = db.get(User, token.user_id)
    # Current seven-role enum has no nurse label. An explicit nursing ward
    # assignment on a credentialed department account is the authority.
    if user is None or not user.password_hash:
        fail(401, "An eligible staff account is required")
    if user.role != "department_admin":
        fail(403, "An active nursing assignment is required")
    rows = db.query(InpatientStaffAssignment).filter(
        InpatientStaffAssignment.user_id == user.id,
        InpatientStaffAssignment.is_active == 1,
        InpatientStaffAssignment.role.in_(("NURSE", "CHARGE_NURSE")),
    ).all()
    if not rows:
        fail(403, "An active nursing assignment is required")
    from src.workforce_service import source_assignment_current
    wards = frozenset(row.ward_id for row in rows if source_assignment_current(db, "WARD", getattr(row, "id", None)))
    if not wards:
        fail(403, "No current nursing assignment is available")
    return NurseActor(user.id, wards)


def admission_for(db, actor, admission_id, *, lock=False, write=False):
    query = db.query(InpatientAdmission).filter(InpatientAdmission.id == admission_id)
    if lock:
        query = query.with_for_update().populate_existing()
    row = query.first()
    if row is None or row.ward_id not in actor.ward_ids:
        fail(404, "Inpatient admission not found")
    encounter = db.get(Encounter, row.source_encounter_id)
    patient = db.get(User, row.patient_id)
    if encounter is None or encounter.patient_id != row.patient_id or patient is None or not patient.mrn:
        fail(409, "Admission patient and encounter linkage is incomplete")
    if write and row.status != "ACTIVE":
        fail(409, "Nursing writes require an active admission")
    return row


def audit(db, actor, admission, action, item_id=None):
    db.add(AuditLog(user_id=actor.user_id, action="Nursing " + action, status="Success",
        details={"admission_id": admission.id, "patient_id": admission.patient_id,
                 "encounter_id": admission.source_encounter_id, "item_id": item_id}))


def warning_flags(row):
    flags = []
    def flagged(name, predicate, message):
        value = getattr(row, name, None)
        if value is not None and predicate(float(value)):
            flags.append(message)
    flagged("spo2_percent", lambda x: x < 92, "Low oxygen saturation: verify measurement and follow local escalation policy")
    flagged("temperature_c", lambda x: x < 35 or x >= 38, "Temperature outside typical range: verify measurement")
    flagged("pulse_bpm", lambda x: x < 50 or x > 120, "Pulse outside typical range: verify measurement")
    flagged("respiratory_rate_per_min", lambda x: x < 10 or x > 30, "Respiratory rate outside typical range: verify measurement")
    flagged("systolic_mmhg", lambda x: x < 90 or x >= 180, "Systolic pressure outside typical range: verify measurement")
    return flags


def observation_view(row, source):
    return {"id": row.id, "source": source, "previous_id": row.previous_id,
        "measured_at": row.measured_at, "recorded_at": row.recorded_at,
        "recorded_by_user_id": row.recorded_by_user_id,
        "correction_reason": getattr(row, "correction_reason", getattr(row, "reason", None)),
        "measurements": {name: getattr(row, name) for name in MEASUREMENTS},
        "review_flags": warning_flags(row), "units": {"temperature_c": "°C", "systolic_mmhg": "mmHg",
            "diastolic_mmhg": "mmHg", "pulse_bpm": "beats/min", "respiratory_rate_per_min": "breaths/min",
            "spo2_percent": "%", "weight_kg": "kg", "height_cm": "cm"}}


def record_observation(db, actor, admission_id, data):
    admission = admission_for(db, actor, admission_id, lock=True, write=True)
    if data.previous_id is not None:
        previous = db.query(NursingObservation).filter(NursingObservation.id == data.previous_id).with_for_update().populate_existing().first()
        if previous is None or (previous.admission_id, previous.patient_id, previous.encounter_id) != (
                admission.id, admission.patient_id, admission.source_encounter_id):
            fail(404, "Prior nursing observation not found for this admission")
        if db.query(NursingObservation.id).filter(NursingObservation.previous_id == previous.id).first():
            fail(409, "This observation was already corrected; reload the history")
    fields = {name: getattr(data, name) for name in MEASUREMENTS}
    row = NursingObservation(admission_id=admission.id, patient_id=admission.patient_id,
        encounter_id=admission.source_encounter_id, recorded_by_user_id=actor.user_id,
        measured_at=data.measured_at, previous_id=data.previous_id,
        correction_reason=data.correction_reason, **fields)
    db.add(row)
    db.flush()
    audit(db, actor, admission, "observation corrected" if data.previous_id else "observation recorded", row.id)
    return row


def add_note(db, actor, admission_id, data):
    admission = admission_for(db, actor, admission_id, lock=True, write=True)
    row = NursingNote(admission_id=admission.id, patient_id=admission.patient_id,
        encounter_id=admission.source_encounter_id, author_user_id=actor.user_id,
        kind=data.kind, content=data.content)
    db.add(row); db.flush()
    audit(db, actor, admission, "note finalized", row.id)
    return row


def add_plan(db, actor, admission_id, data):
    admission = admission_for(db, actor, admission_id, lock=True, write=True)
    row = NursingCarePlan(admission_id=admission.id, patient_id=admission.patient_id,
        encounter_id=admission.source_encounter_id, created_by_user_id=actor.user_id,
        goal=data.goal, intervention=data.intervention, status="DRAFT", version=1)
    db.add(row); db.flush()
    db.add(NursingWorkflowEvent(admission_id=admission.id, patient_id=admission.patient_id,
        encounter_id=admission.source_encounter_id, plan_id=row.id, sequence=1,
        from_status=None, to_status="DRAFT", actor_user_id=actor.user_id))
    audit(db, actor, admission, "care plan created", row.id)
    return row


def plan_for(db, admission, plan_id, *, lock=False):
    query = db.query(NursingCarePlan).filter(NursingCarePlan.id == plan_id)
    if lock: query = query.with_for_update().populate_existing()
    row = query.first()
    if row is None or (row.admission_id, row.patient_id, row.encounter_id) != (
            admission.id, admission.patient_id, admission.source_encounter_id):
        fail(404, "Care plan not found for this admission")
    return row


def transition_plan(db, actor, admission_id, plan_id, data):
    admission = admission_for(db, actor, admission_id, lock=True, write=True)
    plan = plan_for(db, admission, plan_id, lock=True)
    if plan.version != data.expected_version: fail(409, "Care plan changed. Reload before retrying")
    if data.status not in PLAN_TRANSITIONS.get(plan.status, set()):
        fail(409, "Invalid care plan transition")
    if data.status == "CANCELLED" and not data.reason: fail(422, "Cancellation requires a reason")
    if data.status in ("COMPLETED", "CANCELLED") and db.query(NursingTask.id).filter(
            NursingTask.plan_id == plan.id, NursingTask.status.in_(("PENDING", "IN_PROGRESS"))).first():
        fail(409, "Complete or cancel pending tasks before closing the plan")
    previous = plan.status
    plan.status = data.status; plan.version += 1
    if data.status in ("COMPLETED", "CANCELLED"): plan.finalized_at = now()
    db.add(NursingWorkflowEvent(admission_id=admission.id, patient_id=admission.patient_id,
        encounter_id=admission.source_encounter_id, plan_id=plan.id, sequence=plan.version,
        from_status=previous, to_status=plan.status, actor_user_id=actor.user_id, reason=data.reason))
    audit(db, actor, admission, "care plan status changed", plan.id)
    return plan


def add_task(db, actor, admission_id, plan_id, data):
    admission = admission_for(db, actor, admission_id, lock=True, write=True)
    plan = plan_for(db, admission, plan_id, lock=True)
    if plan.status != "ACTIVE": fail(409, "Tasks require an active care plan")
    task = NursingTask(plan_id=plan.id, admission_id=admission.id, patient_id=admission.patient_id,
        encounter_id=admission.source_encounter_id, description=data.description,
        status="PENDING", version=1, created_by_user_id=actor.user_id)
    db.add(task); db.flush()
    db.add(NursingWorkflowEvent(admission_id=admission.id, patient_id=admission.patient_id,
        encounter_id=admission.source_encounter_id, task_id=task.id, sequence=1,
        from_status=None, to_status="PENDING", actor_user_id=actor.user_id))
    audit(db, actor, admission, "task created", task.id)
    return task


def transition_task(db, actor, admission_id, task_id, data):
    admission = admission_for(db, actor, admission_id, lock=True, write=True)
    task = db.query(NursingTask).filter(NursingTask.id == task_id).with_for_update().populate_existing().first()
    if task is None or (task.admission_id, task.patient_id, task.encounter_id) != (
            admission.id, admission.patient_id, admission.source_encounter_id):
        fail(404, "Task not found for this admission")
    plan = plan_for(db, admission, task.plan_id, lock=True)
    if plan.status != "ACTIVE": fail(409, "Only an active care plan can have task updates")
    if task.version != data.expected_version: fail(409, "Task changed. Reload before retrying")
    if data.status not in TASK_TRANSITIONS.get(task.status, set()): fail(409, "Invalid task transition")
    if data.status == "CANCELLED" and not data.reason: fail(422, "Cancellation requires a reason")
    previous = task.status
    task.status = data.status; task.version += 1
    if data.status == "DONE":
        task.completed_at = now(); task.completed_by_user_id = actor.user_id
    db.add(NursingWorkflowEvent(admission_id=admission.id, patient_id=admission.patient_id,
        encounter_id=admission.source_encounter_id, task_id=task.id, sequence=task.version,
        from_status=previous, to_status=task.status, actor_user_id=actor.user_id, reason=data.reason))
    audit(db, actor, admission, "task status changed", task.id)
    return task


def location(db, admission):
    assignment = inpatient_service.active_assignment(db, admission_id=admission.id)
    bed = db.get(Bed, assignment.bed_id) if assignment else None
    room = db.get(Room, bed.room_id) if bed else None
    if admission.status == "ACTIVE" and (bed is None or room is None or room.ward_id != admission.ward_id):
        fail(409, "Active admission bed and ward linkage is incomplete")
    return {"room_id": room.id if room else None, "room_code": room.code if room else None,
            "bed_id": bed.id if bed else None, "bed_code": bed.code if bed else None}


def census_item(db, admission):
    patient = db.get(User, admission.patient_id)
    encounter = db.get(Encounter, admission.source_encounter_id)
    if patient is None or encounter is None or encounter.patient_id != admission.patient_id or not patient.mrn:
        fail(409, "Admission patient and encounter linkage is incomplete")
    return {"admission_id": admission.id, "patient_id": patient.id, "patient_name": patient.full_name,
        "mrn": patient.mrn, "encounter_id": encounter.id, "encounter_status": encounter.status,
        "admission_status": admission.status, "ward_id": admission.ward_id, **location(db, admission)}


def order_context(db, admission):
    try:
        inspector = inspect(db.get_bind())
        orders_ready = all(inspector.has_table(name, schema="public") for name in
                           ("clinical_orders", "clinical_order_events"))
        medication_ready = inspector.has_table("medication_order_details", schema="public") if orders_ready else False
        pharmacy_ready = all(inspector.has_table(name, schema="public") for name in
                             ("pharmacy_dispense_workflows", "pharmacy_dispense_records")) if medication_ready else False
    except Exception as exc:
        raise HTTPException(503, "Clinical order storage readiness could not be verified") from exc
    if not orders_ready:
        return {"orders_available": False, "medication_details_available": False,
                "pharmacy_available": False, "administration_available": False, "orders": []}
    rows = db.query(ClinicalOrder).filter(ClinicalOrder.patient_id == admission.patient_id,
        ClinicalOrder.encounter_id == admission.source_encounter_id,
        ClinicalOrder.signed_at.is_not(None)).order_by(ClinicalOrder.created_at.desc()).all()
    result = []
    for order in rows:
        item = {"id": order.id, "order_type": order.order_type, "display_name": order.display_name,
                "status": order.status, "priority": order.priority, "signed_at": order.signed_at,
                "prescription_status": order.status if order.order_type == "MEDICATION" else None,
                "pharmacy_status": "UNAVAILABLE" if order.order_type == "MEDICATION" else None,
                "administration_status": "UNAVAILABLE" if order.order_type == "MEDICATION" else None}
        if order.order_type == "MEDICATION" and medication_ready:
            detail = db.query(MedicationOrderDetail).filter(MedicationOrderDetail.order_id == order.id).first()
            if detail is None: fail(503, "Signed medication order details are incomplete")
            item["medication"] = {key: getattr(detail, key) for key in
                ("medication_identifier", "medication_display_name", "dose", "dose_unit", "route", "frequency")}
            if pharmacy_ready:
                workflow = db.query(PharmacyDispenseWorkflow).filter(PharmacyDispenseWorkflow.order_id == order.id).first()
                item["pharmacy_status"] = workflow.status if workflow else "AWAITING_REVIEW"
                item["dispense_record_count"] = db.query(PharmacyDispenseRecord).filter(
                    PharmacyDispenseRecord.workflow_id == workflow.id).count() if workflow else 0
        result.append(item)
    return {"orders_available": True, "medication_details_available": medication_ready,
            "pharmacy_available": pharmacy_ready, "administration_available": False, "orders": result}


def workspace(db, actor, admission_id):
    admission = admission_for(db, actor, admission_id)
    census = census_item(db, admission)
    nurse_rows = db.query(NursingObservation).filter(
        NursingObservation.admission_id == admission.id).order_by(NursingObservation.measured_at.desc(), NursingObservation.id.desc()).all()
    clinician_rows = db.query(EncounterVitals).filter(
        EncounterVitals.encounter_id == admission.source_encounter_id).order_by(EncounterVitals.measured_at.desc(), EncounterVitals.id.desc()).all()
    notes = db.query(NursingNote).filter(NursingNote.admission_id == admission.id).order_by(NursingNote.id.desc()).all()
    plans = db.query(NursingCarePlan).filter(NursingCarePlan.admission_id == admission.id).order_by(NursingCarePlan.id.desc()).all()
    tasks = db.query(NursingTask).filter(NursingTask.admission_id == admission.id).order_by(NursingTask.id).all()
    events = db.query(NursingWorkflowEvent).filter(NursingWorkflowEvent.admission_id == admission.id).order_by(NursingWorkflowEvent.id).all()
    for row in (*nurse_rows, *notes, *plans, *tasks, *events):
        if (row.admission_id, row.patient_id, row.encounter_id) != (
                admission.id, admission.patient_id, admission.source_encounter_id):
            fail(409, "Nursing record patient and encounter linkage is inconsistent")
    for row in clinician_rows:
        if row.encounter_id != admission.source_encounter_id:
            fail(409, "Clinician observation encounter linkage is inconsistent")
    plan_ids = {row.id for row in plans}
    if any(task.plan_id not in plan_ids for task in tasks):
        fail(409, "Nursing task is linked to a plan outside this admission")
    task_ids = {row.id for row in tasks}
    if any((event.plan_id is not None and event.plan_id not in plan_ids) or
           (event.task_id is not None and event.task_id not in task_ids) for event in events):
        fail(409, "Nursing history is linked outside this admission")
    observations = [observation_view(row, "NURSING") for row in nurse_rows] + [
        observation_view(row, "CLINICIAN") for row in clinician_rows]
    observations.sort(key=lambda row: row["measured_at"], reverse=True)
    return {**census,
        "observations": observations,
        "notes": [{"id": row.id, "kind": row.kind, "content": row.content,
                   "author_user_id": row.author_user_id, "created_at": row.created_at} for row in notes],
        "plans": [{"id": row.id, "goal": row.goal, "intervention": row.intervention,
                   "status": row.status, "version": row.version, "created_by_user_id": row.created_by_user_id,
                   "created_at": row.created_at, "finalized_at": row.finalized_at,
                   "allowed_actions": sorted(PLAN_TRANSITIONS.get(row.status, set())) if admission.status == "ACTIVE" else [],
                   "tasks": [{"id": task.id, "description": task.description, "status": task.status,
                              "version": task.version, "completed_at": task.completed_at,
                              "completed_by_user_id": task.completed_by_user_id,
                              "allowed_actions": sorted(TASK_TRANSITIONS.get(task.status, set()))
                                if admission.status == "ACTIVE" and row.status == "ACTIVE" else []}
                             for task in tasks if task.plan_id == row.id]} for row in plans],
        "workflow_history": [{"id": row.id, "plan_id": row.plan_id, "task_id": row.task_id,
                              "from_status": row.from_status, "to_status": row.to_status,
                              "actor_user_id": row.actor_user_id, "reason": row.reason,
                              "created_at": row.created_at} for row in events],
        "can_record": admission.status == "ACTIVE", **order_context(db, admission)}
