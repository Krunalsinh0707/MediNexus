"""Migration-gated admission and bed operations."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src import inpatient_service as service
from src.auth import get_current_user
from src.database import get_db
from src.inpatient_models import Bed, BedEvent, InpatientAdmission, Room, Ward
from src.models import Encounter
from src.schemas.inpatient import (AdmissionDecision, AdmissionRequest, BedReleaseRequest,
    BedReservationRequest, BedStatusRequest, DischargePlanRequest, DischargeRequest, TransferRequest)


router = APIRouter(prefix="/inpatient", tags=["Inpatient"])


def inpatient_actor(db: Session = Depends(get_db), token=Depends(get_current_user)):
    service.require_schema(db)
    return service.actor_for(db, token)


def mutate(db, actor, action, *args, bed_result=False):
    try:
        row = action(db, actor, *args)
        db.flush()
        if bed_result:
            room = db.get(Room, row.room_id)
            result = service.bed_view(db, row, room)
        else:
            result = service.admission_view(db, actor, row)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A conflicting inpatient or bed update was saved. Reload before retrying") from None
    except Exception:
        db.rollback()
        raise


@router.get("/wards")
def wards(db: Session = Depends(get_db), actor=Depends(inpatient_actor)):
    if actor.doctor_id is not None:
        rows = db.query(Ward).filter(Ward.is_active == 1).order_by(Ward.name).all()
    elif actor.ward_ids:
        rows = db.query(Ward).filter(Ward.id.in_(actor.ward_ids), Ward.is_active == 1).order_by(Ward.name).all()
    else:
        return {"items": []}
    return {"items": [{"id": row.id, "code": row.code, "name": row.name,
        "department_id": row.department_id} for row in rows]}


@router.get("/beds")
def beds(ward_id: int | None = Query(None, gt=0), status: str | None = None,
         db: Session = Depends(get_db), actor=Depends(inpatient_actor)):
    if ward_id is not None:
        service.require_ward(actor, ward_id)
    if status and status not in {"AVAILABLE", "OCCUPIED", "RESERVED", "BLOCKED", "CLEANING"}:
        raise HTTPException(422, "Unknown bed status")
    allowed = {ward_id} if ward_id else actor.ward_ids
    if not allowed:
        return {"items": []}
    rows = db.query(Bed, Room).join(Room, Room.id == Bed.room_id).filter(Room.ward_id.in_(allowed)).order_by(Room.ward_id, Room.code, Bed.code).all()
    items = [service.bed_view(db, bed, room) for bed, room in rows]
    return {"items": [item for item in items if not status or item["status"] == status]}


@router.get("/rooms")
def rooms(ward_id: int | None = Query(None, gt=0),
          db: Session = Depends(get_db), actor=Depends(inpatient_actor)):
    if ward_id is not None:
        service.require_ward(actor, ward_id)
    allowed = {ward_id} if ward_id else actor.ward_ids
    if not allowed:
        return {"items": []}
    rows = db.query(Room).filter(Room.ward_id.in_(allowed)).order_by(Room.ward_id, Room.code).all()
    return {"items": [{"id": row.id, "ward_id": row.ward_id, "code": row.code} for row in rows]}


@router.get("/beds/{bed_id}/history")
def bed_history(bed_id: int, db: Session = Depends(get_db), actor=Depends(inpatient_actor)):
    bed = db.get(Bed, bed_id)
    if bed is None:
        raise HTTPException(404, "Bed not found")
    room = db.get(Room, bed.room_id)
    if room is None or room.ward_id not in actor.ward_ids:
        raise HTTPException(404, "Bed not found")
    events = db.query(BedEvent).filter(BedEvent.bed_id == bed_id).order_by(BedEvent.bed_version).all()
    return {"bed": service.bed_view(db, bed, room), "events": [
        {"version": row.bed_version, "event_type": row.event_type, "actor_user_id": row.actor_user_id,
         "admission_id": row.admission_id, "reason": row.reason, "created_at": row.created_at}
        for row in events]}


@router.post("/beds/{bed_id}/status")
def bed_status(bed_id: int, data: BedStatusRequest, db: Session = Depends(get_db), actor=Depends(inpatient_actor)):
    return mutate(db, actor, service.bed_status, bed_id, data, bed_result=True)


@router.post("/beds/{bed_id}/reservations")
def reserve(bed_id: int, data: BedReservationRequest, db: Session = Depends(get_db), actor=Depends(inpatient_actor)):
    return mutate(db, actor, service.reserve, bed_id, data, bed_result=True)


@router.post("/beds/{bed_id}/reservations/release")
def release_reservation(bed_id: int, data: BedReleaseRequest,
                        db: Session = Depends(get_db), actor=Depends(inpatient_actor)):
    return mutate(db, actor, service.release_reservation, bed_id, data, bed_result=True)


@router.get("/admissions")
def admissions(status: str | None = None, patient_id: int | None = Query(None, gt=0),
               ward_id: int | None = Query(None, gt=0),
               limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=10000),
               db: Session = Depends(get_db), actor=Depends(inpatient_actor)):
    if status and status not in {"REQUESTED", "REJECTED", "ACTIVE", "DISCHARGED"}:
        raise HTTPException(422, "Unknown admission status")
    if ward_id is not None and ward_id not in actor.ward_ids:
        raise HTTPException(403, "An active assignment to this ward is required")
    query = db.query(InpatientAdmission)
    conditions = []
    if actor.ward_ids:
        conditions.append(InpatientAdmission.ward_id.in_(actor.ward_ids))
    if actor.doctor_id:
        conditions.append(InpatientAdmission.source_encounter_id.in_(
            db.query(Encounter.id).filter(Encounter.doctor_id == actor.doctor_id,
                Encounter.status == "IN_PROGRESS")))
    if not conditions:
        return {"items": [], "total": 0}
    query = query.filter(or_(*conditions))
    if status:
        query = query.filter(InpatientAdmission.status == status)
    if ward_id:
        query = query.filter(InpatientAdmission.ward_id == ward_id)
    if patient_id:
        query = query.filter(InpatientAdmission.patient_id == patient_id)
    total = query.count()
    rows = query.order_by(InpatientAdmission.id.desc()).offset(offset).limit(limit).all()
    return {"items": [service.admission_view(db, actor, row) for row in rows], "total": total}


@router.get("/admissions/{admission_id}")
def admission(admission_id: int, db: Session = Depends(get_db), actor=Depends(inpatient_actor)):
    return service.admission_view(db, actor, service.admission_for(db, actor, admission_id))


@router.post("/admissions", status_code=201)
def request_admission(data: AdmissionRequest, db: Session = Depends(get_db), actor=Depends(inpatient_actor)):
    return mutate(db, actor, service.request_admission, data)


@router.post("/admissions/{admission_id}/decisions")
def decision(admission_id: int, data: AdmissionDecision,
             db: Session = Depends(get_db), actor=Depends(inpatient_actor)):
    return mutate(db, actor, service.decide, admission_id, data)


@router.post("/admissions/{admission_id}/transfers")
def transfer(admission_id: int, data: TransferRequest,
             db: Session = Depends(get_db), actor=Depends(inpatient_actor)):
    return mutate(db, actor, service.transfer, admission_id, data)


@router.post("/admissions/{admission_id}/discharge")
def discharge(admission_id: int, data: DischargeRequest,
              db: Session = Depends(get_db), actor=Depends(inpatient_actor)):
    return mutate(db, actor, service.discharge, admission_id, data)


@router.post("/admissions/{admission_id}/discharge-plan")
def plan_discharge(admission_id: int, data: DischargePlanRequest,
                   db: Session = Depends(get_db), actor=Depends(inpatient_actor)):
    return mutate(db, actor, service.plan_discharge, admission_id, data)
