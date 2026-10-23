"""Hospital-wide clinical order API; storage remains migration-gated."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src import clinical_order_service as service
from src.auth import get_current_user
from src.database import get_db
from src.models import AuditLog
from src.schemas.clinical_orders import (
    ClinicalOrderCreate,
    ClinicalOrderListResponse,
    ClinicalOrderResponse,
    ClinicalOrderTransition,
)


router = APIRouter(prefix="/clinical-orders", tags=["Clinical Orders"])


def order_actor(db: Session = Depends(get_db), token=Depends(get_current_user)):
    service.require_order_schema(db)
    return service.actor_for(db, token)


def mutate(db, actor, action, *args):
    try:
        order = action(db, actor, *args)
        db.flush()
        result = service.projection(db, actor, order)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A conflicting order update was saved. Reload before retrying") from None
    except Exception:
        db.rollback()
        raise


@router.post("", response_model=ClinicalOrderResponse, status_code=201)
def create_order(data: ClinicalOrderCreate, db: Session = Depends(get_db), actor=Depends(order_actor)):
    return mutate(db, actor, service.create_order, data)


@router.get("", response_model=ClinicalOrderListResponse)
def list_orders(
    patient_id: int | None = Query(default=None, gt=0),
    encounter_id: int | None = Query(default=None, gt=0),
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    db: Session = Depends(get_db),
    actor=Depends(order_actor),
):
    if status and status not in service.ALLOWED_TRANSITIONS:
        raise HTTPException(422, "Unknown clinical order status")
    query = service.readable_query(db, actor, patient_id=patient_id, encounter_id=encounter_id)
    if status:
        from src.clinical_order_models import ClinicalOrder
        query = query.filter(ClinicalOrder.status == status)
    total = query.count()
    rows = query.order_by(service.ClinicalOrder.created_at.desc(), service.ClinicalOrder.id.desc()).offset(offset).limit(limit).all()
    items = [service.projection(db, actor, row) for row in rows]
    db.add(AuditLog(
        user_id=actor.user_id,
        action="Clinical order list viewed",
        status="Success",
        details={"patient_id": patient_id, "encounter_id": encounter_id, "status": status, "result_count": len(items)},
    ))
    db.commit()
    return {"items": items, "total": total}


@router.get("/{order_id}", response_model=ClinicalOrderResponse)
def get_order(order_id: int, db: Session = Depends(get_db), actor=Depends(order_actor)):
    order = service.readable(db, actor, order_id)
    result = service.projection(db, actor, order)
    service.audit(db, actor, order, "viewed")
    db.commit()
    return result


@router.post("/{order_id}/transitions", response_model=ClinicalOrderResponse)
def transition_order(
    order_id: int,
    data: ClinicalOrderTransition,
    db: Session = Depends(get_db),
    actor=Depends(order_actor),
):
    return mutate(db, actor, service.transition_order, order_id, data)
