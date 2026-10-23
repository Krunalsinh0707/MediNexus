"""Migration-gated workforce directory, assignments, shifts and attendance."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, inspect, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src import workforce_service as service
from src.auth import get_current_user
from src.database import get_db
from src.models import Department, Doctor, User
from src.models import DoctorDepartmentMembership
from src.inpatient_models import Ward
from src.inventory_models import InventoryLocation
from src.workforce_models import (WorkforceAssignment, WorkforceAssignmentEvent,
    WorkforceShift, WorkforceShiftEvent, WorkforceAttendance, WorkforceAttendanceEvent,
    WorkforceCorrectionRequest)
from src.schemas.workforce import (AssignmentCreate, AssignmentChange, ShiftCreate,
    ShiftChange, ClockOut, CorrectionCreate, CorrectionDecision)

router = APIRouter(prefix="/workforce", tags=["Hospital Workforce"])
STAFF_ROLES = ("admin", "hospital_admin", "department_admin", "doctor", "emergency_doctor")


def workforce_actor(db: Session = Depends(get_db), token=Depends(get_current_user)):
    service.require_schema(db)
    return service.actor_for(db, token)


def save(db, operation):
    try:
        result = operation()
        db.flush()
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Conflicting workforce update; reload before retrying") from None
    except Exception:
        db.rollback()
        raise


def staff_view(db, user, include_legacy=False):
    doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first() if user.role in {"doctor", "emergency_doctor"} else None
    assignments = db.query(WorkforceAssignment).filter(
        WorkforceAssignment.user_id == user.id).order_by(WorkforceAssignment.id.desc()).all()
    return {"user_id": user.id, "staff_identifier": f"STAFF-{user.id:06d}",
        "name": user.full_name, "role": user.role,
        "eligible_account": bool(user.password_hash),
        "active": bool(user.password_hash) and (user.role not in {"doctor", "emergency_doctor"}
            or doctor is not None and doctor.status == "Active"),
        "doctor_profile_id": doctor.id if doctor else None,
        "assignments": [service.assignment_view(row) for row in assignments],
        "legacy_assignments": service.legacy_assignments(db, user, doctor, assignments) if include_legacy else []}


@router.get("/departments")
def departments(db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    service.admin(actor)
    rows = db.query(Department).order_by(Department.name).all()
    return {"items": [{"id": row.id, "code": row.code, "name": row.name} for row in rows]}


@router.get("/wards")
def wards(db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    service.admin(actor)
    service.require_source_table(db, "WARD")
    rows = db.query(Ward).filter(Ward.is_active == 1).order_by(Ward.name).all()
    return {"items": [{"id": row.id, "department_id": row.department_id,
        "code": row.code, "name": row.name} for row in rows]}


@router.get("/locations")
def locations(db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    service.admin(actor)
    service.require_source_table(db, "INVENTORY")
    rows = db.query(InventoryLocation).filter(InventoryLocation.is_active == 1).all()
    return {"items": [{"id": row.id, "department_id": row.department_id,
        "code": row.code, "name": row.name} for row in rows]}


@router.get("/staff")
def staff(search: str | None = Query(None, max_length=100),
          role: str | None = None, department_id: int | None = Query(None, gt=0),
          active: bool | None = None, limit: int = Query(50, ge=1, le=100),
          offset: int = Query(0, ge=0), db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    service.admin(actor)
    query = db.query(User).outerjoin(Doctor, Doctor.user_id == User.id).filter(User.role.in_(STAFF_ROLES))
    if role:
        if role not in STAFF_ROLES:
            raise HTTPException(422, "Unknown staff role")
        query = query.filter(User.role == role)
    if search:
        term = search.strip().removeprefix("STAFF-")
        conditions = [User.full_name.ilike(f"%{search.strip()}%"),
                      cast(User.id, String).ilike(f"%{term}%")]
        if term.isdigit():
            conditions.append(User.id == int(term))
        query = query.filter(or_(*conditions))
    if department_id is not None:
        managed_ids = db.query(WorkforceAssignment.user_id).filter(
            WorkforceAssignment.department_id == department_id,
            WorkforceAssignment.status == "ACTIVE",
            WorkforceAssignment.starts_at <= service.now(),
            or_(WorkforceAssignment.expires_at.is_(None), WorkforceAssignment.expires_at > service.now()),
        )
        matches = [User.id.in_(managed_ids), User.id.in_(db.query(Doctor.user_id).filter(
            Doctor.department_id == department_id, Doctor.status == "Active"))]
        try:
            installed = set(inspect(db.get_bind()).get_table_names(schema="public"))
        except Exception:
            raise HTTPException(503, "Existing department assignments could not be inspected") from None
        def unmanaged(module, model):
            return ~db.query(WorkforceAssignment.id).filter(
                WorkforceAssignment.source_module == module,
                WorkforceAssignment.source_assignment_id == model.id,
            ).exists()
        if DoctorDepartmentMembership.__tablename__ in installed:
            matches.append(User.id.in_(db.query(Doctor.user_id).join(
                DoctorDepartmentMembership, DoctorDepartmentMembership.doctor_id == Doctor.id,
            ).filter(DoctorDepartmentMembership.department_id == department_id,
                     DoctorDepartmentMembership.is_active == True,
                     unmanaged("DOCTOR", DoctorDepartmentMembership))))
        for module, (model, _, _, _, _) in service.SOURCE.items():
            if module == "DOCTOR" or model.__tablename__ not in installed:
                continue
            if module == "WARD":
                matches.append(User.id.in_(db.query(model.user_id).join(
                    Ward, Ward.id == model.ward_id).filter(
                    Ward.department_id == department_id, model.is_active == 1,
                    unmanaged(module, model))))
            elif module == "INVENTORY":
                matches.append(User.id.in_(db.query(model.user_id).join(
                    InventoryLocation, InventoryLocation.id == model.location_id).filter(
                    InventoryLocation.department_id == department_id, model.is_active == 1,
                    unmanaged(module, model))))
            else:
                matches.append(User.id.in_(db.query(model.user_id).filter(
                    model.department_id == department_id, model.is_active == 1,
                    unmanaged(module, model))))
        query = query.filter(or_(*matches))
    eligible = User.password_hash.is_not(None) & or_(
        User.role.notin_(("doctor", "emergency_doctor")), Doctor.status == "Active")
    if active is not None:
        query = query.filter(eligible if active else ~eligible)
    rows = query.order_by(User.id).offset(offset).limit(limit).all()
    views = [staff_view(db, row) for row in rows]
    return {"items": views, "limit": limit, "offset": offset}


@router.get("/staff/{user_id}")
def staff_detail(user_id: int, db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    service.admin(actor)
    user = db.get(User, user_id)
    if user is None or user.role not in STAFF_ROLES:
        raise HTTPException(404, "Staff account not found")
    return staff_view(db, user, include_legacy=True)


@router.get("/assignments")
def assignments(user_id: int | None = Query(None, gt=0),
                db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    service.admin(actor)
    query = db.query(WorkforceAssignment)
    if user_id is not None:
        query = query.filter(WorkforceAssignment.user_id == user_id)
    rows = query.order_by(WorkforceAssignment.id.desc()).limit(100).all()
    return {"items": [service.assignment_view(row) for row in rows]}


@router.post("/assignments", status_code=201)
def create_assignment(data: AssignmentCreate,
                      db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    return save(db, lambda: service.assignment_view(service.grant(db, actor, data)))


@router.post("/assignments/{assignment_id}/change")
def change_assignment(assignment_id: int, data: AssignmentChange,
                      db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    return save(db, lambda: service.assignment_view(service.change_assignment(
        db, actor, service.assignment_for(db, actor, assignment_id, lock=True), data)))


@router.get("/assignments/{assignment_id}/events")
def assignment_events(assignment_id: int, db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    service.assignment_for(db, actor, assignment_id)
    rows = db.query(WorkforceAssignmentEvent).filter(
        WorkforceAssignmentEvent.assignment_id == assignment_id).order_by(WorkforceAssignmentEvent.version).all()
    return {"items": [{"version": row.version, "from_status": row.from_status,
        "to_status": row.to_status, "actor_user_id": row.actor_user_id,
        "reason": row.reason, "occurred_at": row.occurred_at} for row in rows]}


@router.get("/shifts")
def shifts(user_id: int | None = Query(None, gt=0),
           db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    if not actor.administrator:
        if user_id is not None and user_id != actor.user_id:
            raise HTTPException(403, "Only your shifts are visible")
        user_id = actor.user_id
    query = db.query(WorkforceShift)
    if user_id is not None:
        query = query.filter(WorkforceShift.user_id == user_id)
    rows = query.order_by(WorkforceShift.starts_at.desc()).limit(100).all()
    return {"items": [service.shift_view(row) for row in rows]}


@router.post("/shifts", status_code=201)
def create_shift(data: ShiftCreate, db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    return save(db, lambda: service.shift_view(service.schedule(db, actor, data)))


@router.post("/shifts/{shift_id}/change")
def change_shift(shift_id: int, data: ShiftChange,
                 db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    return save(db, lambda: service.shift_view(service.change_shift(
        db, actor, service.shift_for(db, actor, shift_id, lock=True), data)))


@router.get("/shifts/{shift_id}/events")
def shift_events(shift_id: int, db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    service.shift_for(db, actor, shift_id)
    rows = db.query(WorkforceShiftEvent).filter(
        WorkforceShiftEvent.shift_id == shift_id).order_by(WorkforceShiftEvent.version).all()
    return {"items": [{"version": row.version, "action": row.action,
        "actor_user_id": row.actor_user_id, "reason": row.reason,
        "occurred_at": row.occurred_at} for row in rows]}


@router.get("/attendance")
def attendance(user_id: int | None = Query(None, gt=0),
               db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    if not actor.administrator:
        if user_id is not None and user_id != actor.user_id:
            raise HTTPException(403, "Only your attendance is visible")
        user_id = actor.user_id
    query = db.query(WorkforceAttendance)
    if user_id is not None:
        query = query.filter(WorkforceAttendance.user_id == user_id)
    rows = query.order_by(WorkforceAttendance.id.desc()).limit(100).all()
    views = [service.attendance_view(row) for row in rows]
    return {"items": views, "recorded_hours": round(sum(row["hours"] or 0 for row in views), 2),
            "missing_clock_outs": sum(row["missing_clock_out"] for row in views)}


@router.post("/shifts/{shift_id}/clock-in", status_code=201)
def clock_in(shift_id: int, db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    return save(db, lambda: service.attendance_view(service.clock_in(
        db, actor, service.shift_for(db, actor, shift_id, lock=True))))


@router.post("/attendance/{attendance_id}/clock-out")
def clock_out(attendance_id: int, data: ClockOut,
              db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    return save(db, lambda: service.attendance_view(service.clock_out(
        db, actor, service.attendance_for(db, actor, attendance_id, lock=True), data)))


@router.post("/attendance/{attendance_id}/corrections", status_code=201)
def correction(attendance_id: int, data: CorrectionCreate,
               db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    def operation():
        row = service.attendance_for(db, actor, attendance_id, lock=True)
        request = service.request_correction(db, actor, row, data)
        return {"id": request.id, "attendance_id": row.id, "status": request.status}
    return save(db, operation)


@router.get("/attendance/{attendance_id}/events")
def attendance_events(attendance_id: int, db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    service.attendance_for(db, actor, attendance_id)
    rows = db.query(WorkforceAttendanceEvent).filter(
        WorkforceAttendanceEvent.attendance_id == attendance_id).order_by(WorkforceAttendanceEvent.sequence).all()
    return {"items": [{"sequence": row.sequence, "action": row.action,
        "actor_user_id": row.actor_user_id, "effective_at": row.effective_at,
        "recorded_at": row.recorded_at, "reason": row.reason} for row in rows]}


@router.get("/corrections")
def corrections(db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    query = db.query(WorkforceCorrectionRequest)
    if not actor.administrator:
        query = query.filter(WorkforceCorrectionRequest.requested_by_user_id == actor.user_id)
    rows = query.order_by(WorkforceCorrectionRequest.id.desc()).limit(100).all()
    return {"items": [{"id": row.id, "attendance_id": row.attendance_id,
        "requested_by_user_id": row.requested_by_user_id,
        "proposed_clock_out_at": row.proposed_clock_out_at,
        "status": row.status, "reason": row.reason,
        "review_reason": row.review_reason} for row in rows]}


@router.post("/corrections/{correction_id}/decision")
def decision(correction_id: int, data: CorrectionDecision,
             db: Session = Depends(get_db), actor=Depends(workforce_actor)):
    service.admin(actor)
    def operation():
        row = db.query(WorkforceCorrectionRequest).filter(
            WorkforceCorrectionRequest.id == correction_id).with_for_update().first()
        if row is None:
            raise HTTPException(404, "Correction request not found")
        service.decide_correction(db, actor, row, data)
        return {"id": row.id, "attendance_id": row.attendance_id, "status": row.status}
    return save(db, operation)
