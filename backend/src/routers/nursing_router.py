"""Nursing station: authenticated, ward-scoped, and schema-gated."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src import nursing_service as service
from src.auth import get_current_user
from src.database import get_db
from src.inpatient_models import InpatientAdmission
from src.schemas.nursing import NoteWrite, ObservationWrite, PlanWrite, TaskWrite, Transition


router = APIRouter(prefix="/nursing", tags=["Nursing"])


def nursing_actor(db: Session = Depends(get_db), token=Depends(get_current_user)):
    service.require_schema(db)
    return service.actor_for(db, token)


def mutate(db, actor, admission_id, operation, *args):
    try:
        operation(db, actor, admission_id, *args)
        db.flush()
        result = service.workspace(db, actor, admission_id)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A nursing record changed. Reload before retrying") from None
    except Exception:
        db.rollback()
        raise


@router.get("/census")
def census(ward_id: int | None = Query(None, gt=0), limit: int = Query(50, ge=1, le=100),
           offset: int = Query(0, ge=0, le=10000),
           db: Session = Depends(get_db), actor=Depends(nursing_actor)):
    if ward_id is not None and ward_id not in actor.ward_ids:
        raise HTTPException(403, "A current nursing assignment to this ward is required")
    allowed = {ward_id} if ward_id else actor.ward_ids
    query = db.query(InpatientAdmission).filter(InpatientAdmission.status == "ACTIVE",
        InpatientAdmission.ward_id.in_(allowed))
    total = query.count()
    rows = query.order_by(InpatientAdmission.id.desc()).offset(offset).limit(limit).all()
    return {"items": [service.census_item(db, row) for row in rows], "total": total}


@router.get("/admissions/{admission_id}")
def workspace(admission_id: int, db: Session = Depends(get_db), actor=Depends(nursing_actor)):
    return service.workspace(db, actor, admission_id)


@router.post("/admissions/{admission_id}/observations", status_code=201)
def observation(admission_id: int, data: ObservationWrite,
                db: Session = Depends(get_db), actor=Depends(nursing_actor)):
    return mutate(db, actor, admission_id, service.record_observation, data)


@router.post("/admissions/{admission_id}/notes", status_code=201)
def note(admission_id: int, data: NoteWrite,
         db: Session = Depends(get_db), actor=Depends(nursing_actor)):
    return mutate(db, actor, admission_id, service.add_note, data)


@router.post("/admissions/{admission_id}/plans", status_code=201)
def plan(admission_id: int, data: PlanWrite,
         db: Session = Depends(get_db), actor=Depends(nursing_actor)):
    return mutate(db, actor, admission_id, service.add_plan, data)


@router.post("/admissions/{admission_id}/plans/{plan_id}/transitions")
def plan_transition(admission_id: int, plan_id: int, data: Transition,
                    db: Session = Depends(get_db), actor=Depends(nursing_actor)):
    return mutate(db, actor, admission_id, service.transition_plan, plan_id, data)


@router.post("/admissions/{admission_id}/plans/{plan_id}/tasks", status_code=201)
def task(admission_id: int, plan_id: int, data: TaskWrite,
         db: Session = Depends(get_db), actor=Depends(nursing_actor)):
    return mutate(db, actor, admission_id, service.add_task, plan_id, data)


@router.post("/admissions/{admission_id}/tasks/{task_id}/transitions")
def task_transition(admission_id: int, task_id: int, data: Transition,
                    db: Session = Depends(get_db), actor=Depends(nursing_actor)):
    return mutate(db, actor, admission_id, service.transition_task, task_id, data)
