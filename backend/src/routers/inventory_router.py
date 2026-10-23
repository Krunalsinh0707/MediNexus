"""Inventory endpoints remain unavailable until an approved schema is installed."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src import inventory_service as service
from src.auth import get_current_user
from src.database import get_db
from src.inventory_models import InventoryBatch, InventoryDiscrepancy, InventoryItem, InventoryLocation, InventoryMovement
from src.schemas.inventory import ItemCreate, Receipt, Movement, CountReport, CountDecision

router = APIRouter(prefix="/inventory", tags=["Hospital Inventory"])


def inventory_actor(db: Session = Depends(get_db), token=Depends(get_current_user)):
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
        raise HTTPException(409, "Conflicting inventory update; reload before retrying") from None
    except Exception:
        db.rollback()
        raise


@router.get("/locations")
def locations(db: Session = Depends(get_db), actor=Depends(inventory_actor)):
    rows = db.query(InventoryLocation).filter(InventoryLocation.id.in_(actor.locations)).all()
    return {"items": [{"id": row.id, "code": row.code, "name": row.name,
                      "department_id": row.department_id,
                      "assignment_role": actor.locations[row.id][1]} for row in rows]}


@router.get("/items")
def items(search: str | None = Query(None, max_length=128),
          category: str | None = Query(None, pattern="^(MEDICATION|SUPPLY)$"),
          limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
          db: Session = Depends(get_db), actor=Depends(inventory_actor)):
    query = db.query(InventoryItem)
    if search:
        query = query.filter(InventoryItem.code.ilike(f"%{search.strip()}%") | InventoryItem.name.ilike(f"%{search.strip()}%"))
    if category:
        query = query.filter(InventoryItem.category == category)
    rows = query.order_by(InventoryItem.id.desc()).offset(offset).limit(limit).all()
    return {"items": [{"id": row.id, "code": row.code, "name": row.name,
        "category": row.category, "unit": row.unit, "description": row.description,
        "reorder_level": row.reorder_level, "supplier_reference": row.supplier_reference,
        "is_active": bool(row.is_active)} for row in rows], "limit": limit, "offset": offset}


@router.post("/items", status_code=201)
def create_item(data: ItemCreate, db: Session = Depends(get_db), actor=Depends(inventory_actor)):
    def operation():
        row = service.create_item(db, actor, data)
        return {"id": row.id, "code": row.code, "name": row.name, "unit": row.unit}
    return save(db, operation)


@router.get("/items/{item_id}")
def item_detail(item_id: int, db: Session = Depends(get_db), actor=Depends(inventory_actor)):
    row = service.item_for(db, item_id)
    return {"id": row.id, "code": row.code, "name": row.name,
        "category": row.category, "unit": row.unit, "description": row.description,
        "reorder_level": row.reorder_level, "supplier_reference": row.supplier_reference,
        "is_active": bool(row.is_active)}


@router.get("/batches")
def batches(location_id: int = Query(..., gt=0), item_id: int | None = Query(None, gt=0),
            limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
            db: Session = Depends(get_db), actor=Depends(inventory_actor)):
    service.location_for(db, actor, location_id)
    query = db.query(InventoryBatch).filter(InventoryBatch.location_id == location_id)
    if item_id is not None:
        query = query.filter(InventoryBatch.item_id == item_id)
    rows = query.order_by(InventoryBatch.id.desc()).offset(offset).limit(limit).all()
    return {"items": [service.batch_projection(db, row) for row in rows], "limit": limit, "offset": offset}


@router.post("/receipts", status_code=201)
def receipt(data: Receipt, db: Session = Depends(get_db), actor=Depends(inventory_actor)):
    def operation():
        row = service.receive(db, actor, data)
        return service.batch_projection(db, row)
    return save(db, operation)


@router.get("/batches/{batch_id}")
def batch_detail(batch_id: int, db: Session = Depends(get_db), actor=Depends(inventory_actor)):
    return service.batch_projection(db, service.batch_for(db, actor, batch_id))


@router.post("/batches/{batch_id}/movements")
def movement(batch_id: int, data: Movement, db: Session = Depends(get_db), actor=Depends(inventory_actor)):
    def operation():
        batch = service.batch_for(db, actor, batch_id, lock=True)
        return service.batch_projection(db, service.apply_movement(db, actor, batch, data))
    return save(db, operation)


@router.get("/movements")
def movements(location_id: int = Query(..., gt=0), limit: int = Query(50, ge=1, le=100),
              db: Session = Depends(get_db), actor=Depends(inventory_actor)):
    service.location_for(db, actor, location_id)
    rows = db.query(InventoryMovement).filter(
        (InventoryMovement.source_location_id == location_id) |
        (InventoryMovement.destination_location_id == location_id)
    ).order_by(InventoryMovement.id.desc()).limit(limit).all()
    return {"items": [{"id": row.id, "batch_id": row.batch_id, "item_id": row.item_id,
        "movement_type": row.movement_type, "quantity": row.quantity,
        "source_location_id": row.source_location_id,
        "destination_location_id": row.destination_location_id,
        "related_movement_id": row.related_movement_id,
        "actor_user_id": row.actor_user_id, "occurred_at": row.occurred_at,
        "reason": row.reason, "reference": row.reference} for row in rows]}


@router.get("/reports/stock")
def stock(location_id: int = Query(..., gt=0), db: Session = Depends(get_db), actor=Depends(inventory_actor)):
    return service.stock_report(db, actor, location_id)


@router.get("/discrepancies")
def discrepancies(location_id: int = Query(..., gt=0),
                  db: Session = Depends(get_db), actor=Depends(inventory_actor)):
    service.location_for(db, actor, location_id)
    rows = db.query(InventoryDiscrepancy).join(
        InventoryBatch, InventoryBatch.id == InventoryDiscrepancy.batch_id
    ).filter(InventoryBatch.location_id == location_id).order_by(InventoryDiscrepancy.id.desc()).limit(50).all()
    return {"items": [{"id": row.id, "batch_id": row.batch_id, "status": row.status,
        "expected_version": row.expected_version, "counted_quantity": row.counted_quantity,
        "reason": row.reason, "review_reason": row.review_reason,
        "reported_at": row.reported_at} for row in rows]}


@router.post("/batches/{batch_id}/counts", status_code=201)
def count(batch_id: int, data: CountReport,
          db: Session = Depends(get_db), actor=Depends(inventory_actor)):
    def operation():
        batch = service.batch_for(db, actor, batch_id, lock=True)
        row = service.report_count(db, actor, batch, data)
        return {"id": row.id, "status": row.status, "batch_id": row.batch_id}
    return save(db, operation)


@router.post("/discrepancies/{discrepancy_id}/decision")
def decide(discrepancy_id: int, data: CountDecision,
           db: Session = Depends(get_db), actor=Depends(inventory_actor)):
    def operation():
        row = db.query(InventoryDiscrepancy).filter(
            InventoryDiscrepancy.id == discrepancy_id).with_for_update().first()
        if row is None:
            raise HTTPException(404, "Stock discrepancy not found")
        service.decide_count(db, actor, row, data)
        return {"id": row.id, "status": row.status, "batch_id": row.batch_id}
    return save(db, operation)
