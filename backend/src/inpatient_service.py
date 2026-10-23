"""Source-level ADT rules. Routers own commit and rollback; schema use is gated."""
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import inspect

from src import encounter_service
from src.inpatient_models import (Bed, BedAssignment, BedEvent, BedReservation, InpatientAdmission,
    InpatientEvent, InpatientStaffAssignment, Room, Ward)
from src.models import AuditLog, Department, Doctor, Encounter, User


TABLES = tuple(model.__tablename__ for model in (
    Ward, Room, Bed, InpatientStaffAssignment, InpatientAdmission,
    BedAssignment, BedReservation, InpatientEvent, BedEvent,
))


def fail(code, message):
    raise HTTPException(code, message)


def require_schema(db):
    try:
        inspector = inspect(db.get_bind())
        missing = [name for name in TABLES if not inspector.has_table(name, schema="public")]
    except Exception as exc:
        raise HTTPException(503, "Inpatient storage readiness could not be verified") from exc
    if missing:
        fail(503, "Inpatient storage is not installed")


@dataclass(frozen=True)
class Actor:
    user_id: int
    role: str
    doctor_id: int | None
    ward_ids: frozenset[int]


def actor_for(db, token):
    user = db.get(User, token.user_id)
    if not user or not user.password_hash:
        fail(401, "An eligible portal account is required")
    doctor_id = None
    if user.role in encounter_service.CLINICAL_ROLES:
        doctor = db.query(Doctor).filter(Doctor.user_id == user.id, Doctor.status == "Active").first()
        if doctor is None:
            fail(403, "An active clinician profile is required")
        doctor_id = doctor.id
    if user.role not in encounter_service.CLINICAL_ROLES | {"admin", "hospital_admin", "department_admin"}:
        fail(403, "Inpatient access is restricted to authorized staff")
    assignments = db.query(InpatientStaffAssignment).filter(
        InpatientStaffAssignment.user_id == user.id,
        InpatientStaffAssignment.is_active == 1,
        InpatientStaffAssignment.role.in_(("ADT_STAFF", "WARD_MANAGER")),
    ).all()
    from src.workforce_service import source_assignment_current
    return Actor(user.id, user.role, doctor_id, frozenset(
        row.ward_id for row in assignments if source_assignment_current(db, "WARD", row.id)))


def ward_for(db, ward_id, active=True):
    ward = db.get(Ward, ward_id)
    if ward is None or (active and ward.is_active != 1):
        fail(422, "Select an active ward")
    if db.get(Department, ward.department_id) is None:
        fail(409, "Ward is not linked to an existing department")
    return ward


def require_ward(actor, ward_id):
    if ward_id not in actor.ward_ids:
        fail(403, "An active assignment to this ward is required")


def bed_for(db, ward_id, bed_id, lock=False):
    query = db.query(Bed).join(Room, Room.id == Bed.room_id).filter(Bed.id == bed_id, Room.ward_id == ward_id)
    if lock:
        query = query.with_for_update().populate_existing()
    bed = query.first()
    if bed is None:
        fail(422, "Bed does not belong to the selected ward")
    return bed


def active_assignment(db, *, admission_id=None, bed_id=None, lock=False):
    query = db.query(BedAssignment).filter(BedAssignment.released_at.is_(None))
    if admission_id is not None:
        query = query.filter(BedAssignment.admission_id == admission_id)
    if bed_id is not None:
        query = query.filter(BedAssignment.bed_id == bed_id)
    if lock:
        query = query.with_for_update().populate_existing()
    return query.first()


def active_reservation(db, bed_id, lock=False):
    query = db.query(BedReservation).filter(BedReservation.bed_id == bed_id, BedReservation.released_at.is_(None))
    if lock:
        query = query.with_for_update().populate_existing()
    return query.first()


def available(db, bed, admission_id=None):
    if bed.maintenance_status != "AVAILABLE":
        fail(409, "Bed is blocked or being cleaned")
    if active_assignment(db, bed_id=bed.id, lock=True):
        fail(409, "Bed is already occupied")
    reservation = active_reservation(db, bed.id, lock=True)
    if reservation and reservation.admission_id != admission_id:
        fail(409, "Bed is reserved for another admission")
    return reservation


def event(db, admission, actor, kind, *, previous_ward=None, previous_bed=None, next_ward=None, next_bed=None, reason=None):
    db.add(InpatientEvent(admission_id=admission.id, sequence=admission.version, event_type=kind,
        from_ward_id=previous_ward, from_bed_id=previous_bed, to_ward_id=next_ward,
        to_bed_id=next_bed, actor_user_id=actor.user_id, reason=reason))
    db.add(AuditLog(user_id=actor.user_id, action="Inpatient " + kind.lower(), status="Success", details={
        "admission_id": admission.id, "patient_id": admission.patient_id, "version": admission.version,
        "from_ward_id": previous_ward, "to_ward_id": next_ward,
        "from_bed_id": previous_bed, "to_bed_id": next_bed,
    }))


def bed_event(db, bed, actor, kind, admission_id=None, reason=None):
    bed.version += 1
    db.add(BedEvent(bed_id=bed.id, bed_version=bed.version, event_type=kind,
        actor_user_id=actor.user_id, admission_id=admission_id, reason=reason))


def request_admission(db, actor, data):
    if actor.role not in encounter_service.CLINICAL_ROLES or actor.doctor_id is None:
        fail(403, "An assigned active clinician must request admission")
    # Match encounter writes: lock the patient before the encounter.
    patient = db.query(User).filter(User.id == data.patient_id).with_for_update().populate_existing().first()
    if patient is None or patient.role not in encounter_service.PATIENT_ROLES or not patient.mrn:
        fail(422, "Select a registered patient with an MRN")
    encounter = db.query(Encounter).filter(Encounter.id == data.source_encounter_id).with_for_update().populate_existing().first()
    if encounter is None or encounter.patient_id != data.patient_id:
        fail(404, "Patient visit not found")
    encounter_service.assigned_clinician(actor, encounter)
    if encounter.status != "IN_PROGRESS":
        fail(409, "Admission request requires an active assigned visit")
    ward_for(db, data.ward_id)
    prior = db.query(InpatientAdmission).filter(InpatientAdmission.patient_id == data.patient_id,
        InpatientAdmission.status.in_(("REQUESTED", "ACTIVE"))).first()
    if prior:
        fail(409, "Patient already has an open admission request or stay")
    admission = InpatientAdmission(patient_id=patient.id, source_encounter_id=encounter.id,
        requested_by_user_id=actor.user_id, ward_id=data.ward_id, status="REQUESTED",
        version=1, request_reason=data.reason)
    db.add(admission)
    db.flush()
    event(db, admission, actor, "REQUESTED", next_ward=data.ward_id)
    return admission


def admission_for(db, actor, admission_id, lock=False):
    query = db.query(InpatientAdmission).filter(InpatientAdmission.id == admission_id)
    if lock:
        query = query.with_for_update().populate_existing()
    admission = query.first()
    if admission is None:
        fail(404, "Admission not found")
    if admission.ward_id not in actor.ward_ids:
        if actor.doctor_id is None:
            fail(404, "Admission not found")
        encounter = db.get(Encounter, admission.source_encounter_id)
        if encounter is None or encounter.doctor_id != actor.doctor_id or encounter.status != "IN_PROGRESS":
            fail(404, "Admission not found")
    return admission


def staff_admission(db, actor, admission_id, expected):
    admission = admission_for(db, actor, admission_id, lock=True)
    require_ward(actor, admission.ward_id)
    if admission.version != expected:
        fail(409, "Admission changed. Reload before retrying")
    return admission


def decide(db, actor, admission_id, data):
    admission = staff_admission(db, actor, admission_id, data.expected_version)
    if admission.status != "REQUESTED":
        fail(409, "Only a pending admission can be decided")
    if data.decision == "REJECT":
        reservation = db.query(BedReservation).filter(BedReservation.admission_id == admission.id,
            BedReservation.released_at.is_(None)).with_for_update().populate_existing().first()
        if reservation:
            reserved_bed = db.query(Bed).filter(Bed.id == reservation.bed_id).with_for_update().populate_existing().first()
            if reserved_bed is None:
                fail(409, "Reserved bed is missing")
            reservation.released_at = encounter_service.now()
            reservation.released_by_user_id = actor.user_id
            bed_event(db, reserved_bed, actor, "RESERVATION_RELEASED", admission.id)
        admission.status = "REJECTED"
        admission.decision_reason = data.reason
        admission.version += 1
        event(db, admission, actor, "REJECTED", previous_ward=admission.ward_id, reason=data.reason)
        return admission
    ward_for(db, admission.ward_id)
    bed = bed_for(db, admission.ward_id, data.bed_id, lock=True)
    reservation = available(db, bed, admission.id)
    if reservation:
        reservation.released_at = encounter_service.now()
        reservation.released_by_user_id = actor.user_id
    db.add(BedAssignment(admission_id=admission.id, bed_id=bed.id, assigned_by_user_id=actor.user_id))
    bed_event(db, bed, actor, "ASSIGNED", admission.id)
    admission.status = "ACTIVE"
    admission.admitted_at = encounter_service.now()
    admission.version += 1
    event(db, admission, actor, "ADMITTED", next_ward=admission.ward_id, next_bed=bed.id)
    return admission


def transfer(db, actor, admission_id, data):
    admission = staff_admission(db, actor, admission_id, data.expected_version)
    if admission.status != "ACTIVE":
        fail(409, "Only active inpatients can be transferred")
    require_ward(actor, data.ward_id)
    ward_for(db, data.ward_id)
    current = active_assignment(db, admission_id=admission.id, lock=True)
    if current is None or current.bed_id == data.bed_id:
        fail(409, "Select a different bed for this active admission")
    # Lock both beds in stable ID order before checking target occupancy.
    old_bed, new_bed = None, None
    for bed_id in sorted((current.bed_id, data.bed_id)):
        row = db.query(Bed).filter(Bed.id == bed_id).with_for_update().populate_existing().first()
        if row is None:
            fail(422, "Bed not found")
        if bed_id == current.bed_id:
            old_bed = row
        else:
            new_bed = row
    # The target room/ward relationship is checked independently of client input.
    bed_for(db, data.ward_id, new_bed.id)
    reservation = available(db, new_bed, admission.id)
    if reservation:
        reservation.released_at = encounter_service.now()
        reservation.released_by_user_id = actor.user_id
    previous_ward = admission.ward_id
    current.released_at = encounter_service.now()
    current.released_by_user_id = actor.user_id
    current.release_reason = "TRANSFER"
    old_bed.maintenance_status = "CLEANING"
    old_bed.maintenance_reason = "Cleaning required after transfer"
    bed_event(db, old_bed, actor, "RELEASED", admission.id)
    db.add(BedAssignment(admission_id=admission.id, bed_id=new_bed.id, assigned_by_user_id=actor.user_id))
    bed_event(db, new_bed, actor, "ASSIGNED", admission.id)
    admission.ward_id = data.ward_id
    admission.version += 1
    event(db, admission, actor, "TRANSFERRED", previous_ward=previous_ward,
        previous_bed=old_bed.id, next_ward=data.ward_id, next_bed=new_bed.id, reason=data.reason)
    return admission


def discharge(db, actor, admission_id, data):
    admission = staff_admission(db, actor, admission_id, data.expected_version)
    if admission.status != "ACTIVE":
        fail(409, "Only an active inpatient can be discharged")
    current = active_assignment(db, admission_id=admission.id, lock=True)
    if current is None:
        fail(409, "Active admission has no current bed assignment")
    bed = db.query(Bed).filter(Bed.id == current.bed_id).with_for_update().populate_existing().first()
    if bed is None:
        fail(409, "Assigned bed is missing")
    current.released_at = encounter_service.now()
    current.released_by_user_id = actor.user_id
    current.release_reason = "DISCHARGE"
    bed.maintenance_status = "CLEANING"
    bed.maintenance_reason = "Cleaning required after discharge"
    bed_event(db, bed, actor, "RELEASED", admission.id)
    admission.status = "DISCHARGED"
    admission.discharge_reason = data.reason
    admission.discharged_at = encounter_service.now()
    admission.version += 1
    event(db, admission, actor, "DISCHARGED", previous_ward=admission.ward_id,
        previous_bed=bed.id, reason=data.reason)
    return admission


def plan_discharge(db, actor, admission_id, data):
    admission = staff_admission(db, actor, admission_id, data.expected_version)
    if admission.status != "ACTIVE":
        fail(409, "Only an active inpatient can have a discharge plan")
    admission.planned_discharge_at = data.planned_at
    admission.version += 1
    event(db, admission, actor, "DISCHARGE_PLANNED", previous_ward=admission.ward_id,
        reason=data.reason)
    return admission


def bed_status(db, actor, bed_id, data):
    bed = db.query(Bed).filter(Bed.id == bed_id).with_for_update().populate_existing().first()
    if bed is None:
        fail(404, "Bed not found")
    room = db.get(Room, bed.room_id)
    if room is None:
        fail(409, "Bed room is missing")
    require_ward(actor, room.ward_id)
    if bed.version != data.expected_version:
        fail(409, "Bed changed. Reload before retrying")
    if active_assignment(db, bed_id=bed.id, lock=True) or active_reservation(db, bed.id, lock=True):
        fail(409, "Occupied or reserved bed cannot change maintenance status")
    if bed.maintenance_status == data.status:
        fail(409, "Bed already has this status")
    bed.maintenance_status = data.status
    bed.maintenance_reason = data.reason if data.status != "AVAILABLE" else None
    bed_event(db, bed, actor, data.status, reason=data.reason)
    db.add(AuditLog(user_id=actor.user_id, action="Inpatient bed status", status="Success",
        details={"bed_id": bed.id, "ward_id": room.ward_id, "status": data.status, "version": bed.version}))
    return bed


def reserve(db, actor, bed_id, data):
    admission = admission_for(db, actor, data.admission_id, lock=True)
    require_ward(actor, admission.ward_id)
    if admission.status != "REQUESTED":
        fail(409, "Only pending admissions can reserve a bed")
    bed = bed_for(db, admission.ward_id, bed_id, lock=True)
    if bed.version != data.expected_bed_version:
        fail(409, "Bed changed. Reload before retrying")
    if active_reservation(db, bed.id, lock=True):
        fail(409, "Bed is already reserved")
    if db.query(BedReservation).filter(BedReservation.admission_id == admission.id,
        BedReservation.released_at.is_(None)).first():
        fail(409, "Admission already has an active bed reservation")
    available(db, bed, admission.id)
    db.add(BedReservation(admission_id=admission.id, bed_id=bed.id, reserved_by_user_id=actor.user_id))
    bed_event(db, bed, actor, "RESERVED", admission.id)
    return bed


def release_reservation(db, actor, bed_id, data):
    bed = db.query(Bed).filter(Bed.id == bed_id).with_for_update().populate_existing().first()
    if bed is None:
        fail(404, "Bed not found")
    room = db.get(Room, bed.room_id)
    if room is None:
        fail(409, "Bed room is missing")
    require_ward(actor, room.ward_id)
    if bed.version != data.expected_bed_version:
        fail(409, "Bed changed. Reload before retrying")
    reservation = active_reservation(db, bed.id, lock=True)
    if reservation is None:
        fail(409, "Bed has no active reservation")
    reservation.released_at = encounter_service.now()
    reservation.released_by_user_id = actor.user_id
    bed_event(db, bed, actor, "RESERVATION_RELEASED", reservation.admission_id, data.reason)
    return bed


def bed_view(db, bed, room):
    assignment = active_assignment(db, bed_id=bed.id)
    reservation = active_reservation(db, bed.id)
    status = "OCCUPIED" if assignment else "RESERVED" if reservation else bed.maintenance_status
    return {"id": bed.id, "code": bed.code, "room_id": room.id, "room_code": room.code,
        "ward_id": room.ward_id, "status": status, "version": bed.version,
        "maintenance_reason": bed.maintenance_reason,
        "admission_id": assignment.admission_id if assignment else None,
        "reserved_for_admission_id": reservation.admission_id if reservation else None}


def admission_view(db, actor, admission):
    patient = db.get(User, admission.patient_id)
    assignment = active_assignment(db, admission_id=admission.id)
    bed = db.get(Bed, assignment.bed_id) if assignment else None
    room = db.get(Room, bed.room_id) if bed else None
    events = db.query(InpatientEvent).filter(InpatientEvent.admission_id == admission.id).order_by(InpatientEvent.sequence).all()
    return {"id": admission.id, "patient_id": admission.patient_id,
        "patient_name": patient.full_name if patient else "Unavailable", "mrn": patient.mrn if patient else None,
        "source_encounter_id": admission.source_encounter_id, "status": admission.status,
        "version": admission.version, "ward_id": admission.ward_id,
        "room_id": room.id if room else None, "room_code": room.code if room else None,
        "bed_id": bed.id if bed else None, "bed_code": bed.code if bed else None,
        "requested_at": admission.requested_at, "admitted_at": admission.admitted_at,
        "planned_discharge_at": admission.planned_discharge_at,
        "discharged_at": admission.discharged_at,
        "allowed_actions": (["ADMIT", "REJECT"] if admission.status == "REQUESTED" else
            ["TRANSFER", "PLAN_DISCHARGE", "DISCHARGE"] if admission.status == "ACTIVE" else [])
            if admission.ward_id in actor.ward_ids else [],
        "events": [{"sequence": row.sequence, "event_type": row.event_type,
            "from_ward_id": row.from_ward_id, "to_ward_id": row.to_ward_id,
            "from_bed_id": row.from_bed_id, "to_bed_id": row.to_bed_id,
            "actor_user_id": row.actor_user_id, "reason": row.reason,
            "created_at": row.created_at} for row in events]}
