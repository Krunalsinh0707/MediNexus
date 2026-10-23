from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src import laboratory_service as service
from src.auth import get_current_user
from src.database import get_db
from src.schemas.laboratory import (
    LaboratoryQueueResponse, LaboratoryResultCreate, LaboratoryResultTransition,
    LaboratoryWorkflowTransition,
)


router = APIRouter(prefix="/laboratory", tags=["Laboratory"])


def laboratory_actor(db: Session = Depends(get_db), token=Depends(get_current_user)):
    service.require_laboratory_schema(db)
    return service.actor_for(db, token)


def laboratory_reader(db: Session = Depends(get_db), token=Depends(get_current_user)):
    service.require_laboratory_schema(db)
    return service.orders.actor_for(db, token)


def mutate(db, callback, *args):
    try:
        order = callback(db, *args)
        result = service.projection(db, args[0], order)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A conflicting laboratory update was saved. Reload before retrying") from None
    except Exception:
        db.rollback()
        raise


@router.get("/orders", response_model=LaboratoryQueueResponse)
def queue(
    search: str | None = Query(default=None, max_length=255),
    order_id: int | None = Query(default=None, gt=0), encounter_id: int | None = Query(default=None, gt=0),
    priority: str | None = None, status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0, le=10000),
    db: Session = Depends(get_db), actor=Depends(laboratory_actor),
):
    if priority and priority not in {"ROUTINE", "URGENT", "STAT"}: raise HTTPException(422, "Unknown priority")
    valid = set(service.WORKFLOW_TRANSITIONS) | {"ORDER_CANCELLED"}
    if status and status not in valid: raise HTTPException(422, "Unknown laboratory status")
    query = service.queue_query(db, actor, search, priority, status, order_id, encounter_id)
    total = query.count()
    rows = query.order_by(service.ClinicalOrder.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [service.projection(db, actor, row) for row in rows], "total": total}


@router.get("/orders/{order_id}")
def detail(order_id: int, db: Session = Depends(get_db), actor=Depends(laboratory_actor)):
    return service.projection(db, actor, service.readable(db, actor, order_id))


@router.get("/orders/{order_id}/final-results")
def final_results(order_id: int, db: Session = Depends(get_db), actor=Depends(laboratory_reader)):
    return service.finalized_results_for_reader(db, actor, order_id)


@router.post("/orders/{order_id}/transitions")
def transition(order_id: int, data: LaboratoryWorkflowTransition, db: Session = Depends(get_db), actor=Depends(laboratory_actor)):
    return mutate(db, service.transition_workflow, actor, order_id, data)


@router.post("/orders/{order_id}/results", status_code=201)
def create_result(order_id: int, data: LaboratoryResultCreate, db: Session = Depends(get_db), actor=Depends(laboratory_actor)):
    return mutate(db, service.create_result, actor, order_id, data)


@router.post("/orders/{order_id}/results/{result_id}/transitions")
def transition_result(order_id: int, result_id: int, data: LaboratoryResultTransition,
                      db: Session = Depends(get_db), actor=Depends(laboratory_actor)):
    return mutate(db, service.transition_result, actor, order_id, result_id, data)
