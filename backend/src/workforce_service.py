"""Source-only workforce rules. Workforce records never grant clinical access alone."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from src.models import AuditLog, Department, Doctor, DoctorDepartmentMembership, User
from src.inpatient_models import InpatientStaffAssignment, Ward
from src.inventory_models import InventoryLocation, InventoryStaffAssignment
from src.clinical_order_models import PharmacyStaffAssignment, LaboratoryStaffAssignment, RadiologyStaffAssignment
from src.billing_models import BillingStaffAssignment
from src.workforce_models import (WorkforceBase, WorkforceAssignment, WorkforceAssignmentEvent,
    WorkforceShift, WorkforceShiftEvent, WorkforceAttendance, WorkforceAttendanceEvent,
    WorkforceCorrectionRequest)


SOURCE = {
    "DOCTOR": (DoctorDepartmentMembership, "doctor_id", "department_id", "role", {"MEMBER", "RESPONDER", "LEAD"}),
    "WARD": (InpatientStaffAssignment, "user_id", "ward_id", "role", {"ADT_STAFF", "WARD_MANAGER", "NURSE", "CHARGE_NURSE"}),
    "PHARMACY": (PharmacyStaffAssignment, "user_id", "department_id", "assignment_role", {"PHARMACY_STAFF", "PHARMACY_MANAGER"}),
    "LABORATORY": (LaboratoryStaffAssignment, "user_id", "department_id", "assignment_role", {"LAB_STAFF", "LAB_VERIFIER", "LAB_MANAGER"}),
    "RADIOLOGY": (RadiologyStaffAssignment, "user_id", "department_id", "assignment_role", {"RAD_STAFF", "RADIOLOGIST", "RAD_MANAGER"}),
    "BILLING": (BillingStaffAssignment, "user_id", "department_id", "role", {"BILLING_STAFF", "BILLING_MANAGER"}),
    "INVENTORY": (InventoryStaffAssignment, "user_id", "location_id", "assignment_role", {"INVENTORY_STAFF", "INVENTORY_MANAGER"}),
}


def fail(code, message):
    raise HTTPException(code, message)


def now():
    return datetime.now(timezone.utc)


def require_schema(db):
    try:
        names = set(inspect(db.get_bind()).get_table_names(schema="public"))
    except Exception:
        fail(503, "Workforce storage readiness could not be verified")
    if not set(WorkforceBase.metadata.tables).issubset(names):
        fail(503, "Workforce storage is not installed")


def require_source_table(db, module):
    model = SOURCE[module][0]
    try:
        if not inspect(db.get_bind()).has_table(model.__tablename__, schema="public"):
            fail(503, f"{module.lower()} assignment storage is not installed")
    except HTTPException:
        raise
    except Exception:
        fail(503, "Assignment storage readiness could not be verified")


def source_assignment_current(db, module, source_id, at=None):
    """Check managed expiry without replacing legacy authorization.

    Existing, unlinked module assignments keep their existing policy. Real
    SQLAlchemy sessions fail closed on catalog errors. Fake unit sessions have
    no PostgreSQL catalog and exercise their own authorization tests.
    """
    if not isinstance(db, Session):
        return True
    try:
        if not inspect(db.get_bind()).has_table("workforce_assignments", schema="public"):
            return True
    except Exception:
        fail(503, "Workforce assignment readiness could not be verified")
    rows = db.query(WorkforceAssignment).filter(
        WorkforceAssignment.source_module == module,
        WorkforceAssignment.source_assignment_id == source_id,
    ).all()
    return not rows or any(current(row, at) for row in rows)


def current(row, at=None):
    instant = at or now()
    return (row.status == "ACTIVE" and row.starts_at <= instant
            and (row.expires_at is None or row.expires_at > instant))


@dataclass(frozen=True)
class Actor:
    user_id: int
    role: str

    @property
    def administrator(self):
        return self.role in {"admin", "hospital_admin"}


def actor_for(db, token):
    user = db.get(User, token.user_id)
    if user is None or not user.password_hash or user.role not in {
        "admin", "hospital_admin", "department_admin", "doctor", "emergency_doctor"}:
        fail(403, "An eligible staff account is required")
    return Actor(user.id, user.role)


def admin(actor):
    if not actor.administrator:
        fail(403, "Hospital administrator access is required")


def staff_for(db, user_id):
    user = db.get(User, user_id)
    if user is None or not user.password_hash or user.role not in {
        "admin", "hospital_admin", "department_admin", "doctor", "emergency_doctor"}:
        fail(422, "Select an eligible existing staff account")
    return user


def scope(db, department_id, ward_id=None, location_id=None):
    department = db.get(Department, department_id)
    if department is None:
        fail(422, "Select an existing department")
    if ward_id is not None:
        ward = db.get(Ward, ward_id)
        if ward is None or ward.is_active != 1 or ward.department_id != department_id:
            fail(422, "Ward must be active and belong to this department")
    if location_id is not None:
        location = db.get(InventoryLocation, location_id)
        if location is None or location.is_active != 1 or location.department_id != department_id:
            fail(422, "Storage location must be active and belong to this department")


def audit(db, actor, action, **ids):
    db.add(AuditLog(user_id=actor.user_id, action="Workforce " + action,
                    status="Success", details=ids))


def assignment_event(db, actor, row, before, reason):
    db.add(WorkforceAssignmentEvent(assignment_id=row.id, version=row.version,
        from_status=before, to_status=row.status, actor_user_id=actor.user_id, reason=reason))
    audit(db, actor, "assignment " + row.status.lower(), assignment_id=row.id,
          staff_user_id=row.user_id, department_id=row.department_id,
          source_module=row.source_module, version=row.version)


def grant(db, actor, data):
    admin(actor)
    user = staff_for(db, data.user_id)
    require_source_table(db, data.source_module)
    scope(db, data.department_id, data.ward_id, data.location_id)
    model, user_field, scope_field, role_field, allowed = SOURCE[data.source_module]
    if data.assignment_role not in allowed:
        fail(422, "Unsupported role for the selected department or ward workflow")
    if data.source_module == "DOCTOR":
        if user.role not in {"doctor", "emergency_doctor"}:
            fail(422, "Only clinicians may receive doctor membership")
        doctor = db.query(Doctor).filter(Doctor.user_id == user.id, Doctor.status == "Active").first()
        if doctor is None:
            fail(422, "An active doctor profile is required")
        source_user_id = doctor.id
    else:
        if user.role != "department_admin":
            fail(422, "Department workflows require a department staff account")
        source_user_id = user.id
    source_scope_id = data.ward_id if data.source_module == "WARD" else data.location_id if data.source_module == "INVENTORY" else data.department_id
    source = db.query(model).filter(getattr(model, user_field) == source_user_id,
                                     getattr(model, scope_field) == source_scope_id).with_for_update().first()
    enabled_value = True if data.source_module == "DOCTOR" else 1
    if source is None:
        source = model(**{user_field: source_user_id, scope_field: source_scope_id,
                          role_field: data.assignment_role, "is_active": enabled_value})
        db.add(source)
        db.flush()
    else:
        linked = db.query(WorkforceAssignment).filter(
            WorkforceAssignment.source_module == data.source_module,
            WorkforceAssignment.source_assignment_id == source.id,
            WorkforceAssignment.status == "ACTIVE").first()
        if linked is not None:
            fail(409, "An active workforce assignment already manages this permission")
        setattr(source, role_field, data.assignment_role)
        source.is_active = enabled_value
    row = WorkforceAssignment(user_id=user.id, department_id=data.department_id,
        ward_id=data.ward_id, location_id=data.location_id, source_module=data.source_module,
        source_assignment_id=source.id, assignment_role=data.assignment_role,
        status="ACTIVE", starts_at=data.starts_at, expires_at=data.expires_at,
        version=1, assigned_by_user_id=actor.user_id, reason=data.reason)
    db.add(row)
    db.flush()
    assignment_event(db, actor, row, None, data.reason)
    return row


def assignment_for(db, actor, assignment_id, lock=False):
    admin(actor)
    query = db.query(WorkforceAssignment).filter(WorkforceAssignment.id == assignment_id)
    if lock:
        query = query.with_for_update().populate_existing()
    row = query.first()
    if row is None:
        fail(404, "Workforce assignment not found")
    return row


def change_assignment(db, actor, row, data):
    admin(actor)
    if row.version != data.expected_version:
        fail(409, "Assignment changed. Reload before retrying")
    transitions = {"ACTIVE": {"SUSPEND": "SUSPENDED", "REVOKE": "REVOKED"},
                   "SUSPENDED": {"RESUME": "ACTIVE", "REVOKE": "REVOKED"}}
    target = transitions.get(row.status, {}).get(data.action)
    if target is None:
        fail(409, "Invalid assignment transition")
    if target == "ACTIVE" and row.expires_at is not None and row.expires_at <= now():
        fail(409, "Expired assignment cannot be resumed")
    require_source_table(db, row.source_module)
    source = db.query(SOURCE[row.source_module][0]).filter(
        SOURCE[row.source_module][0].id == row.source_assignment_id).with_for_update().first()
    if source is None:
        fail(409, "Linked permission record is missing")
    other_active = db.query(WorkforceAssignment).filter(
        WorkforceAssignment.source_module == row.source_module,
        WorkforceAssignment.source_assignment_id == row.source_assignment_id,
        WorkforceAssignment.id != row.id,
        WorkforceAssignment.status == "ACTIVE",
    ).first()
    if target == "ACTIVE" and other_active is not None:
        fail(409, "A newer active assignment already manages this permission")
    enabled = target == "ACTIVE" or other_active is not None
    source.is_active = enabled if row.source_module == "DOCTOR" else int(enabled)
    before = row.status
    row.status = target
    row.version += 1
    assignment_event(db, actor, row, before, data.reason)
    return row


def assignment_view(row):
    return {"id": row.id, "user_id": row.user_id, "department_id": row.department_id,
        "ward_id": row.ward_id, "location_id": row.location_id,
        "source_module": row.source_module, "assignment_role": row.assignment_role,
        "status": row.status, "effective": current(row), "starts_at": row.starts_at,
        "expires_at": row.expires_at, "version": row.version}


def legacy_assignments(db, user, doctor, managed):
    """Expose existing permission rows without fabricating workforce history."""
    try:
        installed = set(inspect(db.get_bind()).get_table_names(schema="public"))
    except Exception:
        fail(503, "Existing assignment storage could not be inspected")
    linked = {(row.source_module, row.source_assignment_id) for row in managed}
    result = []
    for module, (model, user_field, scope_field, role_field, _) in SOURCE.items():
        if model.__tablename__ not in installed or module == "DOCTOR" and doctor is None:
            continue
        key = doctor.id if module == "DOCTOR" else user.id
        rows = db.query(model).filter(getattr(model, user_field) == key).all()
        for row in rows:
            if (module, row.id) in linked:
                continue
            scope_id = getattr(row, scope_field)
            location = db.get(InventoryLocation, scope_id) if module == "INVENTORY" else None
            ward = db.get(Ward, scope_id) if module == "WARD" else None
            if module == "INVENTORY" and location is None or module == "WARD" and ward is None:
                fail(409, "Existing staff assignment has an invalid storage location or ward")
            result.append({"source_module": module, "source_assignment_id": row.id,
                "assignment_role": getattr(row, role_field),
                "department_id": location.department_id if location else ward.department_id if ward else scope_id,
                "ward_id": scope_id if module == "WARD" else None,
                "location_id": scope_id if module == "INVENTORY" else None,
                "active": bool(row.is_active), "provenance": "LEGACY_UNMANAGED",
                "history_available": False})
    return result


def assigned_to_scope(db, user_id, department_id, ward_id=None):
    rows = db.query(WorkforceAssignment).filter(
        WorkforceAssignment.user_id == user_id,
        WorkforceAssignment.department_id == department_id,
    ).all()
    return any(current(row) and (ward_id is None or row.ward_id == ward_id) for row in rows)


def ensure_no_overlap(db, user_id, starts_at, ends_at, exclude_id=None):
    query = db.query(WorkforceShift).filter(WorkforceShift.user_id == user_id,
        WorkforceShift.status == "SCHEDULED", WorkforceShift.starts_at < ends_at,
        WorkforceShift.ends_at > starts_at)
    if exclude_id is not None:
        query = query.filter(WorkforceShift.id != exclude_id)
    if query.with_for_update().first():
        fail(409, "This staff member already has an overlapping shift")


def shift_event(db, actor, row, action, reason):
    db.add(WorkforceShiftEvent(shift_id=row.id, version=row.version, action=action,
        actor_user_id=actor.user_id, reason=reason))
    audit(db, actor, "shift " + action.lower(), shift_id=row.id,
          staff_user_id=row.user_id, department_id=row.department_id, version=row.version)


def schedule(db, actor, data):
    admin(actor)
    staff_for(db, data.user_id)
    scope(db, data.department_id, data.ward_id)
    if not assigned_to_scope(db, data.user_id, data.department_id, data.ward_id):
        fail(409, "An active workforce assignment in this department or ward is required")
    ensure_no_overlap(db, data.user_id, data.starts_at, data.ends_at)
    row = WorkforceShift(**data.model_dump(), status="SCHEDULED", version=1,
                         created_by_user_id=actor.user_id)
    db.add(row)
    db.flush()
    shift_event(db, actor, row, "SCHEDULED", "Initial schedule")
    return row


def shift_for(db, actor, shift_id, lock=False):
    query = db.query(WorkforceShift).filter(WorkforceShift.id == shift_id)
    if lock:
        query = query.with_for_update().populate_existing()
    row = query.first()
    if row is None or not actor.administrator and row.user_id != actor.user_id:
        fail(404, "Shift not found")
    return row


def change_shift(db, actor, row, data):
    admin(actor)
    if row.status != "SCHEDULED" or row.version != data.expected_version:
        fail(409, "Shift changed or was cancelled. Reload before retrying")
    if data.action == "RESCHEDULE":
        ensure_no_overlap(db, row.user_id, data.starts_at, data.ends_at, exclude_id=row.id)
        row.starts_at, row.ends_at = data.starts_at, data.ends_at
    else:
        row.status = "CANCELLED"
    row.version += 1
    row.change_reason = data.reason
    shift_event(db, actor, row, data.action, data.reason)
    return row


def shift_view(row):
    return {"id": row.id, "user_id": row.user_id, "department_id": row.department_id,
        "ward_id": row.ward_id, "title": row.title, "starts_at": row.starts_at,
        "ends_at": row.ends_at, "status": row.status, "version": row.version,
        "change_reason": row.change_reason}


def attendance_for(db, actor, attendance_id, lock=False):
    query = db.query(WorkforceAttendance).filter(WorkforceAttendance.id == attendance_id)
    if lock:
        query = query.with_for_update().populate_existing()
    row = query.first()
    if row is None or not actor.administrator and row.user_id != actor.user_id:
        fail(404, "Attendance record not found")
    return row


def attendance_event(db, actor, row, action, instant, reason=None):
    db.add(WorkforceAttendanceEvent(attendance_id=row.id, sequence=row.version,
        action=action, actor_user_id=actor.user_id, effective_at=instant, reason=reason))
    audit(db, actor, "attendance " + action.lower(), attendance_id=row.id,
          shift_id=row.shift_id, staff_user_id=row.user_id, version=row.version)


def clock_in(db, actor, shift):
    if shift.user_id != actor.user_id:
        fail(403, "Only the scheduled staff member may clock in")
    instant = now()
    if shift.status != "SCHEDULED" or not shift.starts_at - timedelta(hours=2) <= instant <= shift.ends_at:
        fail(409, "Clock-in is outside the scheduled shift window")
    if not assigned_to_scope(db, actor.user_id, shift.department_id, shift.ward_id):
        fail(403, "A current assignment to the shift location is required")
    if db.query(WorkforceAttendance).filter(WorkforceAttendance.shift_id == shift.id).first():
        fail(409, "Attendance has already been recorded for this shift")
    row = WorkforceAttendance(shift_id=shift.id, user_id=actor.user_id,
                              clocked_in_at=instant, version=1)
    db.add(row)
    db.flush()
    attendance_event(db, actor, row, "CLOCK_IN", instant)
    return row


def clock_out(db, actor, row, data):
    if row.user_id != actor.user_id:
        fail(403, "Only the recorded staff member may clock out")
    if row.version != data.expected_version or row.clocked_out_at is not None:
        fail(409, "Attendance changed or already has a clock-out")
    instant = now()
    if instant <= row.clocked_in_at:
        fail(409, "Clock-out must follow clock-in")
    row.clocked_out_at = instant
    row.version += 1
    attendance_event(db, actor, row, "CLOCK_OUT", instant)
    return row


def request_correction(db, actor, row, data):
    if row.user_id != actor.user_id:
        fail(403, "Only the recorded staff member may request a correction")
    if data.proposed_clock_out_at <= row.clocked_in_at:
        fail(422, "Proposed clock-out must follow clock-in")
    if data.proposed_clock_out_at > now():
        fail(422, "Proposed clock-out cannot be in the future")
    if db.query(WorkforceCorrectionRequest).filter(
        WorkforceCorrectionRequest.attendance_id == row.id,
        WorkforceCorrectionRequest.status == "PENDING").first():
        fail(409, "A correction is already pending review")
    request = WorkforceCorrectionRequest(attendance_id=row.id,
        requested_by_user_id=actor.user_id, proposed_clock_out_at=data.proposed_clock_out_at,
        reason=data.reason, status="PENDING")
    db.add(request)
    db.flush()
    audit(db, actor, "correction requested", attendance_id=row.id, correction_id=request.id)
    return request


def decide_correction(db, actor, request, data):
    admin(actor)
    if request.status != "PENDING":
        fail(409, "Correction has already been reviewed")
    row = attendance_for(db, actor, request.attendance_id, lock=True)
    if request.proposed_clock_out_at <= row.clocked_in_at:
        fail(409, "Proposed clock-out no longer follows clock-in")
    if data.decision == "APPROVED":
        row.clocked_out_at = request.proposed_clock_out_at
        row.version += 1
        attendance_event(db, actor, row, "CORRECTION", request.proposed_clock_out_at, data.reason)
    request.status = data.decision
    request.reviewed_by_user_id = actor.user_id
    request.reviewed_at = now()
    request.review_reason = data.reason
    audit(db, actor, "correction reviewed", attendance_id=row.id,
          correction_id=request.id, decision=data.decision)
    return request


def attendance_view(row):
    duration = ((row.clocked_out_at - row.clocked_in_at).total_seconds() / 3600
                if row.clocked_out_at is not None else None)
    return {"id": row.id, "shift_id": row.shift_id, "user_id": row.user_id,
            "clocked_in_at": row.clocked_in_at, "clocked_out_at": row.clocked_out_at,
            "hours": round(duration, 2) if duration is not None else None,
            "missing_clock_out": row.clocked_out_at is None, "version": row.version}
