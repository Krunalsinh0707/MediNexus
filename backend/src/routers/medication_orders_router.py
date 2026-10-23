"""Medication prescribing API; fulfillment and administration are out of scope."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src import clinical_order_service as orders
from src import medication_order_service as service
from src.auth import get_current_user
from src.clinical_order_models import ClinicalOrder
from src.database import get_db
from src.models import AuditLog
from src.schemas.medication_orders import (
    MedicationOrderCreate,
    MedicationOrderListResponse,
    MedicationOrderResponse,
    MedicationOrderTransition,
)


router = APIRouter(prefix="/medication-orders", tags=["Medication Orders"])


def medication_actor(db: Session = Depends(get_db), token=Depends(get_current_user)):
    service.require_medication_schema(db)
    return orders.actor_for(db, token)


def mutate(db, actor, action, *args):
    try:
        order = action(db, actor, *args)
        db.flush()
        result = service.projection(db, actor, order)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A conflicting medication order update was saved. Reload before retrying") from None
    except Exception:
        db.rollback()
        raise


@router.post("", response_model=MedicationOrderResponse, status_code=201)
def create(data: MedicationOrderCreate, db: Session = Depends(get_db), actor=Depends(medication_actor)):
    return mutate(db, actor, service.create_medication_order, data)


@router.get("", response_model=MedicationOrderListResponse)
def list_orders(
    patient_id: int | None = Query(default=None, gt=0),
    encounter_id: int | None = Query(default=None, gt=0),
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    db: Session = Depends(get_db),
    actor=Depends(medication_actor),
):
    if status and status not in orders.ALLOWED_TRANSITIONS:
        raise HTTPException(422, "Unknown medication order status")
    query = service.medication_query(db, actor, patient_id, encounter_id)
    if status:
        query = query.filter(ClinicalOrder.status == status)
    total = query.count()
    rows = query.order_by(ClinicalOrder.created_at.desc(), ClinicalOrder.id.desc()).offset(offset).limit(limit).all()
    items = [service.projection(db, actor, row) for row in rows]
    db.add(AuditLog(
        user_id=actor.user_id,
        action="Medication order list viewed",
        status="Success",
        details={"patient_id": patient_id, "encounter_id": encounter_id, "status": status, "result_count": len(items)},
    ))
    db.commit()
    return {"items": items, "total": total}


@router.get("/{order_id}", response_model=MedicationOrderResponse)
def get_order(order_id: int, db: Session = Depends(get_db), actor=Depends(medication_actor)):
    order = service.readable_medication(db, actor, order_id)
    result = service.projection(db, actor, order)
    orders.audit(db, actor, order, "medication prescription viewed")
    db.commit()
    return result


@router.post("/{order_id}/transitions", response_model=MedicationOrderResponse)
def transition(
    order_id: int,
    data: MedicationOrderTransition,
    db: Session = Depends(get_db),
    actor=Depends(medication_actor),
):
    return mutate(db, actor, service.transition_medication_order, order_id, data)
