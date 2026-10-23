from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src import pharmacy_service as service
from src.auth import get_current_user
from src.database import get_db
from src.schemas.pharmacy import PharmacyQueueResponse, PharmacyTransition


router = APIRouter(prefix="/pharmacy", tags=["Pharmacy"])


def pharmacy_actor(db: Session = Depends(get_db), token=Depends(get_current_user)):
    service.require_pharmacy_schema(db)
    return service.actor_for(db, token)


@router.get("/prescriptions", response_model=PharmacyQueueResponse)
def queue(
    search: str | None = Query(default=None, max_length=255),
    prescription_id: int | None = Query(default=None, gt=0),
    priority: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    db: Session = Depends(get_db), actor=Depends(pharmacy_actor),
):
    if priority and priority not in {"ROUTINE", "URGENT", "STAT"}:
        raise HTTPException(422, "Unknown priority")
    if status and status not in set(service.REVIEW_TRANSITIONS) | {"PRESCRIPTION_CANCELLED"}:
        raise HTTPException(422, "Unknown pharmacy status")
    query = service.queue_query(db, actor, search, priority, status, prescription_id)
    total = query.count()
    rows = query.order_by(service.ClinicalOrder.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [service.projection(db, actor, row) for row in rows], "total": total}


@router.get("/prescriptions/{order_id}")
def detail(order_id: int, db: Session = Depends(get_db), actor=Depends(pharmacy_actor)):
    return service.projection(db, actor, service.readable(db, actor, order_id))


@router.post("/prescriptions/{order_id}/transitions")
def transition(order_id: int, data: PharmacyTransition, db: Session = Depends(get_db), actor=Depends(pharmacy_actor)):
    try:
        order = service.transition(db, actor, order_id, data)
        result = service.projection(db, actor, order)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A conflicting pharmacy update was saved. Reload before retrying") from None
    except Exception:
        db.rollback()
        raise
