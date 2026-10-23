"""Revenue-cycle contracts; no automatic clinical event charges."""
from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func


class BillingBase(DeclarativeBase):
    pass


def ref(target, nullable=False):
    return Column(Integer, ForeignKey(target, ondelete="RESTRICT"), nullable=nullable, index=True)


class BillingStaffAssignment(BillingBase):
    __tablename__ = "billing_staff_assignments"
    id = Column(Integer, primary_key=True)
    user_id = ref("users.id")
    department_id = ref("departments.id")
    role = Column(String(24), nullable=False)
    is_active = Column(Integer, nullable=False, server_default=text("1"))
    __table_args__ = (
        UniqueConstraint("user_id", "department_id", name="uq_billing_staff_department"),
        CheckConstraint("role IN ('BILLING_STAFF','BILLING_MANAGER')", name="ck_billing_staff_role"),
        CheckConstraint("is_active IN (0,1)", name="ck_billing_staff_active"),
    )


class BillingTariff(BillingBase):
    __tablename__ = "billing_tariffs"
    id = Column(Integer, primary_key=True)
    department_id = ref("departments.id")
    service_code = Column(String(64), nullable=False)
    description = Column(String(255), nullable=False)
    unit_price = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(3), nullable=False)
    tax_required = Column(Integer, nullable=False, server_default=text("0"))
    approval_reference = Column(String(128), nullable=False)
    approved_by_user_id = ref("users.id")
    is_active = Column(Integer, nullable=False, server_default=text("1"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("department_id", "service_code", name="uq_billing_tariff_department_code"),
        CheckConstraint("unit_price >= 0", name="ck_billing_tariff_price"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_billing_tariff_currency"),
        CheckConstraint("tax_required IN (0,1) AND is_active IN (0,1)", name="ck_billing_tariff_flags"),
    )


class BillingInvoice(BillingBase):
    __tablename__ = "billing_invoices"
    id = Column(Integer, primary_key=True)
    invoice_number = Column(String(32), nullable=False, unique=True)
    creation_key = Column(String(100), nullable=False)
    patient_id = ref("users.id")
    department_id = ref("departments.id")
    appointment_id = ref("appointments.id", nullable=True)
    encounter_id = ref("encounters.id", nullable=True)
    admission_id = ref("inpatient_admissions.id", nullable=True)
    currency = Column(String(3), nullable=False)
    status = Column(String(16), nullable=False, server_default=text("'DRAFT'"))
    version = Column(Integer, nullable=False, server_default=text("1"))
    due_date = Column(Date)
    created_by_user_id = ref("users.id")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    issued_at = Column(DateTime(timezone=True))
    released_at = Column(DateTime(timezone=True))
    cancelled_at = Column(DateTime(timezone=True))
    cancellation_reason = Column(Text)
    __table_args__ = (
        UniqueConstraint("created_by_user_id", "creation_key", name="uq_billing_invoice_create_request"),
        CheckConstraint("status IN ('DRAFT','ISSUED','CANCELLED')", name="ck_billing_invoice_status"),
        CheckConstraint("currency ~ '^[A-Z]{3}$' AND version > 0", name="ck_billing_invoice_currency_version"),
        CheckConstraint("status <> 'ISSUED' OR issued_at IS NOT NULL", name="ck_billing_invoice_issue_time"),
        CheckConstraint("status <> 'CANCELLED' OR cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL AND length(btrim(cancellation_reason)) > 0", name="ck_billing_invoice_cancellation"),
        Index("ix_billing_invoice_department_created", "department_id", "created_at"),
        Index("ix_billing_invoice_patient_created", "patient_id", "created_at"),
    )


class BillingCharge(BillingBase):
    __tablename__ = "billing_charges"
    id = Column(Integer, primary_key=True)
    invoice_id = ref("billing_invoices.id")
    tariff_id = ref("billing_tariffs.id")
    description = Column(String(255), nullable=False)
    quantity = Column(Numeric(12, 3), nullable=False)
    unit_price = Column(Numeric(14, 2), nullable=False)
    line_total = Column(Numeric(14, 2), nullable=False)
    source_type = Column(String(24), nullable=False)
    source_id = Column(Integer)
    idempotency_key = Column(String(100), nullable=False)
    created_by_user_id = ref("users.id")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("invoice_id", "idempotency_key", name="uq_billing_charge_request"),
        Index("uq_billing_charge_source", "tariff_id", "source_type", "source_id", unique=True,
              postgresql_where=text("source_id IS NOT NULL")),
        CheckConstraint("quantity > 0 AND unit_price >= 0 AND line_total >= 0", name="ck_billing_charge_amounts"),
        CheckConstraint("source_type IN ('MANUAL','APPOINTMENT','ENCOUNTER','ADMISSION','CLINICAL_ORDER')", name="ck_billing_charge_source"),
        CheckConstraint("(source_type = 'MANUAL') = (source_id IS NULL)", name="ck_billing_charge_source_id"),
    )


class BillingAdjustment(BillingBase):
    __tablename__ = "billing_adjustments"
    id = Column(Integer, primary_key=True)
    invoice_id = ref("billing_invoices.id")
    amount = Column(Numeric(14, 2), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, server_default=text("'REQUESTED'"))
    requested_by_user_id = ref("users.id")
    decided_by_user_id = ref("users.id", nullable=True)
    requested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    decided_at = Column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_billing_adjustment_amount"),
        CheckConstraint("status IN ('REQUESTED','APPROVED','REJECTED')", name="ck_billing_adjustment_status"),
        CheckConstraint("(status = 'REQUESTED') = (decided_at IS NULL)", name="ck_billing_adjustment_decision"),
    )


class BillingPayment(BillingBase):
    __tablename__ = "billing_payments"
    id = Column(Integer, primary_key=True)
    invoice_id = ref("billing_invoices.id")
    amount = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(3), nullable=False)
    method = Column(String(24), nullable=False)
    reference = Column(String(128), nullable=False)
    idempotency_key = Column(String(100), nullable=False)
    status = Column(String(24), nullable=False, server_default=text("'MANUALLY_RECORDED'"))
    recorded_by_user_id = ref("users.id")
    recorded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    reversed_by_user_id = ref("users.id", nullable=True)
    reversed_at = Column(DateTime(timezone=True))
    reversal_reason = Column(Text)
    __table_args__ = (
        UniqueConstraint("invoice_id", "idempotency_key", name="uq_billing_payment_request"),
        UniqueConstraint("method", "reference", "currency", name="uq_billing_payment_reference"),
        CheckConstraint("amount > 0", name="ck_billing_payment_amount"),
        CheckConstraint("method IN ('CASH','BANK_TRANSFER','CHEQUE','OTHER')", name="ck_billing_payment_method"),
        CheckConstraint("status IN ('MANUALLY_RECORDED','REVERSED')", name="ck_billing_payment_status"),
        CheckConstraint("status <> 'REVERSED' OR reversed_at IS NOT NULL AND reversed_by_user_id IS NOT NULL AND reversal_reason IS NOT NULL", name="ck_billing_payment_reversal"),
    )


class BillingRefundRequest(BillingBase):
    __tablename__ = "billing_refund_requests"
    id = Column(Integer, primary_key=True)
    invoice_id = ref("billing_invoices.id")
    payment_id = ref("billing_payments.id")
    amount = Column(Numeric(14, 2), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, server_default=text("'REQUESTED'"))
    requested_by_user_id = ref("users.id")
    requested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_billing_refund_amount"),
        CheckConstraint("status = 'REQUESTED'", name="ck_billing_refund_request_only"),
        Index("uq_open_billing_refund_payment", "payment_id", unique=True),
    )


class BillingEvent(BillingBase):
    __tablename__ = "billing_events"
    id = Column(Integer, primary_key=True)
    invoice_id = ref("billing_invoices.id")
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(32), nullable=False)
    entity_id = Column(Integer)
    actor_user_id = ref("users.id")
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint("invoice_id", "sequence", name="uq_billing_event_sequence"),)
