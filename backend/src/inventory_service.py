"""Department-scoped inventory rules. Storage is deliberately not installed yet."""
from dataclasses import dataclass
from datetime import date, timedelta, datetime, timezone
from decimal import Decimal
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import inspect

from src.inventory_models import (InventoryBase, InventoryLocation, InventoryStaffAssignment,
    InventoryItem, InventoryBatch, InventoryMovement, InventoryReservation, InventoryDiscrepancy)
from src.models import AuditLog, User


def fail(code, message):
    raise HTTPException(code, message)


def require_schema(db):
    try:
        installed = set(inspect(db.get_bind()).get_table_names(schema="public"))
    except Exception:
        fail(503, "Inventory storage readiness could not be verified")
    if not set(InventoryBase.metadata.tables).issubset(installed):
        fail(503, "Inventory storage is not installed")


@dataclass(frozen=True)
class Actor:
    user_id: int
    locations: dict[int, tuple[int, str]]  # location ID -> (department ID, assignment role)


def actor_for(db, token):
    user = db.get(User, token.user_id)
    if user is None or not user.password_hash or user.role != "department_admin":
        fail(403, "An eligible assigned inventory staff account is required")
    assignments = db.query(InventoryStaffAssignment).filter(
        InventoryStaffAssignment.user_id == user.id,
        InventoryStaffAssignment.is_active == 1,
    ).all()
    locations = {}
    from src.workforce_service import source_assignment_current
    for assignment in assignments:
        location = db.get(InventoryLocation, assignment.location_id)
        if (location is not None and location.is_active == 1
                and assignment.assignment_role in {"INVENTORY_STAFF", "INVENTORY_MANAGER"}
                and source_assignment_current(db, "INVENTORY", assignment.id)):
            locations[location.id] = (location.department_id, assignment.assignment_role)
    if not locations:
        fail(403, "An active storage-location assignment is required")
    return Actor(user.id, locations)


def location_for(db, actor, location_id, manager=False):
    location = db.get(InventoryLocation, location_id)
    assignment = actor.locations.get(location_id)
    if location is None or location.is_active != 1 or assignment is None or assignment[0] != location.department_id:
        fail(403, "Current storage-location assignment required")
    if manager and assignment[1] != "INVENTORY_MANAGER":
        fail(403, "Inventory manager assignment required")
    return location


def item_for(db, item_id):
    item = db.get(InventoryItem, item_id)
    if item is None:
        fail(404, "Inventory item not found")
    return item


def batch_for(db, actor, batch_id, lock=False):
    query = db.query(InventoryBatch).filter(InventoryBatch.id == batch_id)
    if lock:
        query = query.with_for_update().populate_existing()
    batch = query.first()
    if batch is None:
        fail(404, "Stock batch not found")
    location_for(db, actor, batch.location_id)
    return batch


def eligible(batch, today=None):
    """Unknown expiry is intentionally not treated as dispensable stock."""
    return batch.status == "AVAILABLE" and batch.expires_on is not None and batch.expires_on > (today or date.today())


def quantities(batch, today=None):
    on_hand = Decimal(str(batch.quantity_on_hand))
    reserved = Decimal(str(batch.quantity_reserved))
    available = on_hand - reserved if eligible(batch, today) else Decimal("0")
    return {"on_hand": on_hand, "reserved": reserved, "available": available}


def batch_projection(db, batch):
    item = item_for(db, batch.item_id)
    return {"id": batch.id, "item_id": item.id, "item_code": item.code, "item_name": item.name,
            "unit": item.unit, "location_id": batch.location_id, "lot_number": batch.lot_number,
            "expires_on": batch.expires_on, "manufactured_on": batch.manufactured_on,
            "status": batch.status, "version": batch.version, "eligible": eligible(batch),
            "quantity_received": batch.quantity_received, **quantities(batch)}


def audit(db, actor, action, **ids):
    db.add(AuditLog(user_id=actor.user_id, action="Inventory " + action,
                    status="Success", details=ids))


def check_key(db, key):
    transfer_key = sha256(key.encode()).hexdigest() + "o"
    if db.query(InventoryMovement).filter(
        InventoryMovement.request_key.in_((key, transfer_key))).first():
        fail(409, "Movement request already recorded; reload stock before retrying")


def event(db, actor, batch, kind, quantity, reason, reference, key, source=None, destination=None, related_movement_id=None):
    db.add(InventoryMovement(batch_id=batch.id, item_id=batch.item_id,
        source_location_id=source, destination_location_id=destination,
        movement_type=kind, quantity=quantity, actor_user_id=actor.user_id,
        request_key=key, reason=reason, reference=reference,
        resulting_version=batch.version, related_movement_id=related_movement_id))
    audit(db, actor, kind, batch_id=batch.id, item_id=batch.item_id,
          source_location_id=source, destination_location_id=destination, version=batch.version)


def create_item(db, actor, data):
    if not any(role == "INVENTORY_MANAGER" for _, role in actor.locations.values()):
        fail(403, "Inventory manager assignment required")
    if db.query(InventoryItem).filter(InventoryItem.code == data.code).first():
        fail(409, "Inventory item code already exists")
    item = InventoryItem(**data.model_dump(), created_by_user_id=actor.user_id)
    db.add(item)
    db.flush()
    audit(db, actor, "item created", item_id=item.id)
    return item


def receive(db, actor, data):
    location_for(db, actor, data.location_id)
    item = item_for(db, data.item_id)
    if item.is_active != 1:
        fail(409, "Inactive catalog item cannot receive stock")
    check_key(db, data.request_key)
    if db.query(InventoryBatch).filter(InventoryBatch.item_id == item.id,
          InventoryBatch.location_id == data.location_id,
          InventoryBatch.lot_number == data.lot_number).first():
        fail(409, "This lot already exists at the location; use a reviewed receipt workflow")
    batch = InventoryBatch(item_id=item.id, location_id=data.location_id,
        lot_number=data.lot_number, quantity_received=data.quantity,
        quantity_on_hand=data.quantity, quantity_reserved=Decimal("0"), version=1,
        unit_cost=data.unit_cost, currency=data.currency,
        manufactured_on=data.manufactured_on, expires_on=data.expires_on,
        supplier_reference=data.supplier_reference, receipt_reference=data.receipt_reference,
        status="AVAILABLE")
    db.add(batch)
    db.flush()
    event(db, actor, batch, "RECEIPT", data.quantity, data.reason, data.receipt_reference,
          data.request_key, destination=data.location_id)
    return batch


def apply_movement(db, actor, batch, data):
    """Caller must hold a batch row lock and commit all records in one transaction."""
    if batch.version != data.expected_version:
        fail(409, "Stock changed. Reload before retrying")
    check_key(db, data.request_key)
    location_for(db, actor, batch.location_id)
    item = item_for(db, batch.item_id)
    if item.is_active != 1:
        fail(409, "Inactive item cannot be moved")
    qty = Decimal(str(data.quantity))
    current = quantities(batch)
    kind = data.movement_type
    if kind in {"ADJUST_IN", "ADJUST_OUT", "QUARANTINE", "RECALL", "EXPIRY", "DAMAGE"}:
        location_for(db, actor, batch.location_id, manager=True)
    if kind in {"RESERVE", "ISSUE", "TRANSFER"} and (not eligible(batch) or current["available"] < qty):
        fail(409, "Eligible available stock is insufficient or expiry is unknown")
    if kind in {"DAMAGE", "EXPIRY", "ADJUST_OUT"} and current["available"] < qty:
        fail(409, "Unreserved stock is insufficient")
    if kind in {"RETURN", "ADJUST_IN"} and batch.status != "AVAILABLE":
        fail(409, "Quarantined or recalled stock cannot receive this movement")
    if kind == "RETURN" and not eligible(batch):
        fail(409, "Expired or unknown-expiry stock cannot be returned to available stock")
    if kind == "RETURN":
        issue = db.get(InventoryMovement, data.related_movement_id)
        if issue is None or issue.batch_id != batch.id or issue.movement_type != "ISSUE":
            fail(409, "Return must reference an issue from the same batch")
        prior_returns = db.query(InventoryMovement).filter(
            InventoryMovement.related_movement_id == issue.id,
            InventoryMovement.movement_type == "RETURN").all()
        already_returned = sum((Decimal(str(row.quantity)) for row in prior_returns), Decimal("0"))
        if already_returned + qty > Decimal(str(issue.quantity)):
            fail(409, "Returns cannot exceed the recorded issue quantity")
    if kind in {"QUARANTINE", "RECALL"}:
        if batch.status != "AVAILABLE" or qty != current["on_hand"]:
            fail(409, "Status change requires the complete available batch")
        batch.status = "QUARANTINED" if kind == "QUARANTINE" else "RECALLED"
    elif kind == "RESERVE":
        if db.query(InventoryReservation).filter(
            InventoryReservation.batch_id == batch.id,
            InventoryReservation.workflow_type == data.workflow_type,
            InventoryReservation.workflow_reference == data.workflow_reference).first():
            fail(409, "Workflow already has a reservation on this batch")
        db.add(InventoryReservation(batch_id=batch.id, workflow_type=data.workflow_type,
            workflow_reference=data.workflow_reference, quantity=qty,
            status="ACTIVE", created_by_user_id=actor.user_id))
        batch.quantity_reserved = current["reserved"] + qty
    elif kind == "RELEASE":
        reservation = db.query(InventoryReservation).filter(
            InventoryReservation.batch_id == batch.id,
            InventoryReservation.workflow_type == data.workflow_type,
            InventoryReservation.workflow_reference == data.workflow_reference).with_for_update().first()
        if reservation is None or reservation.status != "ACTIVE" or Decimal(str(reservation.quantity)) != qty:
            fail(409, "An active reservation with this exact quantity is required")
        reservation.status = "RELEASED"
        reservation.closed_at = datetime.now(timezone.utc)
        batch.quantity_reserved = current["reserved"] - qty
    elif kind in {"ISSUE", "TRANSFER", "DAMAGE", "EXPIRY", "ADJUST_OUT"}:
        batch.quantity_on_hand = current["on_hand"] - qty
    elif kind in {"RETURN", "ADJUST_IN"}:
        batch.quantity_on_hand = current["on_hand"] + qty
    else:
        fail(422, "Unsupported stock movement")

    if kind == "TRANSFER":
        destination = location_for(db, actor, data.destination_location_id)
        if destination.id == batch.location_id:
            fail(422, "Transfer destination must differ from source")
        target = db.query(InventoryBatch).filter(
            InventoryBatch.item_id == batch.item_id,
            InventoryBatch.location_id == destination.id,
            InventoryBatch.lot_number == batch.lot_number).with_for_update().first()
        if target is None:
            target = InventoryBatch(item_id=batch.item_id, location_id=destination.id,
                lot_number=batch.lot_number, quantity_received=qty, quantity_on_hand=qty,
                quantity_reserved=Decimal("0"), version=1, unit_cost=batch.unit_cost,
                currency=batch.currency, manufactured_on=batch.manufactured_on,
                expires_on=batch.expires_on, supplier_reference=batch.supplier_reference,
                receipt_reference=data.reference, status="AVAILABLE")
            db.add(target)
            db.flush()
        else:
            if (target.status != "AVAILABLE" or target.expires_on != batch.expires_on
                    or target.manufactured_on != batch.manufactured_on or target.unit_cost != batch.unit_cost
                    or target.currency != batch.currency):
                fail(409, "Destination lot details conflict with source")
            target.quantity_received = Decimal(str(target.quantity_received)) + qty
            target.quantity_on_hand = Decimal(str(target.quantity_on_hand)) + qty
            target.version += 1
    batch.version += 1
    if kind == "TRANSFER":
        keys = sha256(data.request_key.encode()).hexdigest()
        event(db, actor, batch, "TRANSFER_OUT", qty, data.reason, data.reference,
              keys + "o", source=batch.location_id, destination=destination.id)
        event(db, actor, target, "TRANSFER_IN", qty, data.reason, data.reference,
              keys + "i", source=batch.location_id, destination=destination.id)
    else:
        event(db, actor, batch, kind, qty, data.reason, data.reference,
              data.request_key, source=batch.location_id, related_movement_id=data.related_movement_id)
    return batch


def report_count(db, actor, batch, data):
    location_for(db, actor, batch.location_id)
    if batch.version != data.expected_version:
        fail(409, "Stock changed. Reload before recording a count")
    record = InventoryDiscrepancy(batch_id=batch.id, expected_version=batch.version,
        counted_quantity=data.counted_quantity, status="OPEN",
        reported_by_user_id=actor.user_id, reason=data.reason)
    db.add(record)
    db.flush()
    audit(db, actor, "count reported", batch_id=batch.id, discrepancy_id=record.id)
    return record


def decide_count(db, actor, record, data):
    batch = batch_for(db, actor, record.batch_id, lock=True)
    location_for(db, actor, batch.location_id, manager=True)
    if record.status != "OPEN" or record.expected_version != batch.version or data.expected_version != batch.version:
        fail(409, "Count is stale or already reviewed")
    check_key(db, data.request_key)
    if data.decision == "APPROVED":
        delta = Decimal(str(record.counted_quantity)) - Decimal(str(batch.quantity_on_hand))
        if delta < 0 and Decimal(str(batch.quantity_reserved)) > Decimal(str(record.counted_quantity)):
            fail(409, "Count is below already reserved stock")
        if delta:
            batch.quantity_on_hand = Decimal(str(record.counted_quantity))
            batch.version += 1
            event(db, actor, batch, "ADJUST_IN" if delta > 0 else "ADJUST_OUT", abs(delta),
                  data.reason, f"COUNT-{record.id}", data.request_key, source=batch.location_id)
    record.status = data.decision
    record.reviewed_by_user_id = actor.user_id
    record.review_reason = data.reason
    record.reviewed_at = datetime.now(timezone.utc)
    audit(db, actor, "count reviewed", batch_id=batch.id, discrepancy_id=record.id,
          decision=data.decision)
    return record


def stock_report(db, actor, location_id, expiring_days=30):
    location_for(db, actor, location_id)
    rows = db.query(InventoryBatch).filter(InventoryBatch.location_id == location_id).all()
    catalog = db.query(InventoryItem).filter(InventoryItem.is_active == 1).all()
    items = {item.id: item for item in catalog}
    summary = {item.id: {"item_id": item.id, "code": item.code,
        "name": item.name, "unit": item.unit, "on_hand": Decimal("0"),
        "reserved": Decimal("0"), "available": Decimal("0"),
        "reorder_level": Decimal(str(item.reorder_level))} for item in catalog}
    today = date.today()
    for batch in rows:
        item = items.get(batch.item_id) or item_for(db, batch.item_id)
        entry = summary.setdefault(item.id, {"item_id": item.id, "code": item.code,
            "name": item.name, "unit": item.unit, "on_hand": Decimal("0"),
            "reserved": Decimal("0"), "available": Decimal("0"),
            "reorder_level": Decimal(str(item.reorder_level))})
        for key, value in quantities(batch, today).items():
            entry[key] += value
    for entry in summary.values():
        entry["low_stock"] = entry["available"] <= entry["reorder_level"]
    return {"items": list(summary.values()), "expiring": [batch_projection(db, b) for b in rows
            if b.expires_on is not None and b.expires_on <= today + timedelta(days=expiring_days)],
            "quarantined": [batch_projection(db, b) for b in rows if b.status in {"QUARANTINED", "RECALLED"}]}


class InventoryGatewayContract:
    """An explicit, deliberately unconnected pharmacy integration boundary."""
    def is_configured(self):
        return False

    def verify_available(self, *, catalog_item_id=None, **_kwargs):
        if catalog_item_id is None:
            fail(503, "A verified medication-to-catalog identifier is required")
        fail(503, "Inventory stock verification requires installed storage and validation")

    def reserve(self, **_kwargs):
        fail(503, "Inventory reservation transaction is unavailable")

    def dispense(self, **_kwargs):
        fail(503, "Atomic pharmacy stock movement is unavailable")
