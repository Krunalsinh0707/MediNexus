"""Inventory contracts installed by the additive module foundation."""
from sqlalchemy import (CheckConstraint, Column, Date, DateTime, ForeignKey, Integer,
                        Numeric, String, Text, UniqueConstraint, Index, text)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func


class InventoryBase(DeclarativeBase):
    pass


def ref(target, nullable=False):
    return Column(Integer, ForeignKey(target, ondelete="RESTRICT"), nullable=nullable, index=True)


class InventoryLocation(InventoryBase):
    __tablename__ = "inventory_locations"
    id = Column(Integer, primary_key=True)
    department_id = ref("departments.id")
    code = Column(String(40), nullable=False, unique=True)
    name = Column(String(150), nullable=False)
    kind = Column(String(24), nullable=False)
    is_active = Column(Integer, nullable=False, server_default=text("1"))
    __table_args__ = (
        CheckConstraint("kind IN ('WAREHOUSE','PHARMACY','LABORATORY','RADIOLOGY','WARD','OTHER')", name="ck_inventory_location_kind"),
        CheckConstraint("is_active IN (0,1)", name="ck_inventory_location_active"),
    )


class InventoryStaffAssignment(InventoryBase):
    __tablename__ = "inventory_staff_assignments"
    id = Column(Integer, primary_key=True)
    user_id = ref("users.id")
    location_id = ref("inventory_locations.id")
    assignment_role = Column(String(24), nullable=False)
    is_active = Column(Integer, nullable=False, server_default=text("1"))
    __table_args__ = (
        UniqueConstraint("user_id", "location_id", name="uq_inventory_staff_location"),
        CheckConstraint("assignment_role IN ('INVENTORY_STAFF','INVENTORY_MANAGER')", name="ck_inventory_staff_role"),
        CheckConstraint("is_active IN (0,1)", name="ck_inventory_staff_active"),
    )


class InventoryItem(InventoryBase):
    __tablename__ = "inventory_items"
    id = Column(Integer, primary_key=True)
    code = Column(String(128), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    category = Column(String(24), nullable=False)
    unit = Column(String(32), nullable=False)
    description = Column(Text)
    reorder_level = Column(Numeric(14, 3), nullable=False, server_default=text("0"))
    supplier_reference = Column(String(128))
    is_active = Column(Integer, nullable=False, server_default=text("1"))
    created_by_user_id = ref("users.id")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("category IN ('MEDICATION','SUPPLY')", name="ck_inventory_item_category"),
        CheckConstraint("reorder_level >= 0", name="ck_inventory_item_reorder"),
        CheckConstraint("is_active IN (0,1)", name="ck_inventory_item_active"),
    )


class InventoryBatch(InventoryBase):
    __tablename__ = "inventory_batches"
    id = Column(Integer, primary_key=True)
    item_id = ref("inventory_items.id")
    location_id = ref("inventory_locations.id")
    lot_number = Column(String(128), nullable=False)
    quantity_received = Column(Numeric(14, 3), nullable=False)
    quantity_on_hand = Column(Numeric(14, 3), nullable=False)
    quantity_reserved = Column(Numeric(14, 3), nullable=False, server_default=text("0"))
    unit_cost = Column(Numeric(14, 2))
    currency = Column(String(3))
    manufactured_on = Column(Date)
    expires_on = Column(Date)
    supplier_reference = Column(String(128))
    receipt_reference = Column(String(128))
    status = Column(String(24), nullable=False, server_default=text("'AVAILABLE'"))
    version = Column(Integer, nullable=False, server_default=text("1"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("item_id", "location_id", "lot_number", name="uq_inventory_batch_lot_location"),
        CheckConstraint("quantity_received > 0 AND quantity_on_hand >= 0 AND quantity_reserved >= 0 AND quantity_reserved <= quantity_on_hand", name="ck_inventory_batch_quantities"),
        CheckConstraint("version > 0", name="ck_inventory_batch_version"),
        CheckConstraint("status IN ('AVAILABLE','QUARANTINED','RECALLED')", name="ck_inventory_batch_status"),
        CheckConstraint("(unit_cost IS NULL) = (currency IS NULL)", name="ck_inventory_batch_cost_currency"),
        Index("ix_inventory_batch_location_expiry", "location_id", "expires_on"),
    )


class InventoryReservation(InventoryBase):
    __tablename__ = "inventory_reservations"
    id = Column(Integer, primary_key=True)
    batch_id = ref("inventory_batches.id")
    workflow_type = Column(String(32), nullable=False)
    workflow_reference = Column(String(128), nullable=False)
    quantity = Column(Numeric(14, 3), nullable=False)
    status = Column(String(16), nullable=False, server_default=text("'ACTIVE'"))
    created_by_user_id = ref("users.id")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at = Column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("batch_id", "workflow_type", "workflow_reference", name="uq_inventory_reservation_workflow"),
        CheckConstraint("quantity > 0 AND status IN ('ACTIVE','RELEASED','CONSUMED')", name="ck_inventory_reservation_state"),
    )


class InventoryMovement(InventoryBase):
    __tablename__ = "inventory_movements"
    id = Column(Integer, primary_key=True)
    batch_id = ref("inventory_batches.id")
    item_id = ref("inventory_items.id")
    source_location_id = ref("inventory_locations.id", nullable=True)
    destination_location_id = ref("inventory_locations.id", nullable=True)
    movement_type = Column(String(24), nullable=False)
    quantity = Column(Numeric(14, 3), nullable=False)
    actor_user_id = ref("users.id")
    request_key = Column(String(100), nullable=False, unique=True)
    reason = Column(Text, nullable=False)
    reference = Column(String(128), nullable=False)
    related_movement_id = ref("inventory_movements.id", nullable=True)
    resulting_version = Column(Integer, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("quantity > 0 AND resulting_version > 0", name="ck_inventory_movement_positive"),
        CheckConstraint("movement_type IN ('RECEIPT','TRANSFER_OUT','TRANSFER_IN','RESERVE','RELEASE','ISSUE','RETURN','DAMAGE','EXPIRY','QUARANTINE','RECALL','ADJUST_IN','ADJUST_OUT')", name="ck_inventory_movement_type"),
        Index("ix_inventory_movement_batch_time", "batch_id", "occurred_at"),
    )


class InventoryDiscrepancy(InventoryBase):
    __tablename__ = "inventory_discrepancies"
    id = Column(Integer, primary_key=True)
    batch_id = ref("inventory_batches.id")
    expected_version = Column(Integer, nullable=False)
    counted_quantity = Column(Numeric(14, 3), nullable=False)
    status = Column(String(16), nullable=False, server_default=text("'OPEN'"))
    reported_by_user_id = ref("users.id")
    reviewed_by_user_id = ref("users.id", nullable=True)
    reason = Column(Text, nullable=False)
    review_reason = Column(Text)
    reported_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("counted_quantity >= 0 AND expected_version > 0", name="ck_inventory_discrepancy_count"),
        CheckConstraint("status IN ('OPEN','APPROVED','REJECTED')", name="ck_inventory_discrepancy_status"),
    )
