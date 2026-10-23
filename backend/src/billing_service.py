"""Billing rules. Storage is deliberately unavailable until an approved migration exists."""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import inspect

from src.billing_models import (BillingBase, BillingStaffAssignment, BillingTariff,
    BillingInvoice, BillingCharge, BillingAdjustment, BillingPayment,
    BillingRefundRequest, BillingEvent)
from src.models import User, Department, Appointment, AuditLog
from src.encounter_models import Encounter
from src.inpatient_models import InpatientAdmission, Ward
from src.clinical_order_models import ClinicalOrder

CENT = Decimal("0.01")


def money(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def require_schema(db):
    try:
        present = set(inspect(db.get_bind()).get_table_names(schema="public"))
    except Exception:
        raise HTTPException(503, "Billing storage is unavailable") from None
    if not (set(BillingBase.metadata.tables) | {"users", "departments", "appointments", "encounters", "audit_logs"}).issubset(present):
        raise HTTPException(503, "Billing storage is not installed; an approved migration is required")


def require_linked_table(db, table):
    try:
        available = set(inspect(db.get_bind()).get_table_names(schema="public"))
    except Exception:
        raise HTTPException(503, "Linked clinical storage is unavailable") from None
    if table not in available:
        raise HTTPException(503, f"{table} storage is not installed")


def active_insurance_claim_exists(db, invoice_id):
    try:
        installed = "insurance_claims" in set(inspect(db.get_bind()).get_table_names(schema="public"))
    except Exception:
        raise HTTPException(503, "Cannot verify insurance claim links") from None
    if not installed:
        return False
    from src.insurance_models import InsuranceClaim
    return db.query(InsuranceClaim).filter(InsuranceClaim.invoice_id == invoice_id,
        InsuranceClaim.status != "CANCELLED").first() is not None


@dataclass(frozen=True)
class Actor:
    user_id: int
    role: str
    department_roles: dict[int, str]

    @property
    def departments(self):
        return set(self.department_roles)


def actor_for(db, token):
    if token.role in {"patient", "user"}:
        return Actor(token.user_id, token.role, {})
    if token.role != "department_admin":
        raise HTTPException(403, "A billing assignment is required")
    assignments = db.query(BillingStaffAssignment).filter(
        BillingStaffAssignment.user_id == token.user_id,
        BillingStaffAssignment.is_active == 1).all()
    from src.workforce_service import source_assignment_current
    roles = {a.department_id: a.role for a in assignments
             if source_assignment_current(db, "BILLING", a.id)}
    if not roles:
        raise HTTPException(403, "An active billing assignment is required")
    return Actor(token.user_id, token.role, roles)


def staff(actor, department_id, manager=False):
    role = actor.department_roles.get(department_id)
    if role is None or manager and role != "BILLING_MANAGER":
        raise HTTPException(403, "Current department billing assignment required")


def patient_scope(actor, patient_id):
    if actor.role in {"patient", "user"} and actor.user_id != patient_id:
        raise HTTPException(404, "Invoice not found")


def invoice_for(db, actor, invoice_id, lock=False):
    query = db.query(BillingInvoice).filter(BillingInvoice.id == invoice_id)
    if lock:
        query = query.with_for_update()
    row = query.first()
    if row is None:
        raise HTTPException(404, "Invoice not found")
    if actor.role in {"patient", "user"}:
        patient_scope(actor, row.patient_id)
        if row.released_at is None or row.status != "ISSUED":
            raise HTTPException(404, "Invoice not found")
    else:
        staff(actor, row.department_id)
    return row


def check_version(row, expected):
    if row.version != expected:
        raise HTTPException(409, "Invoice changed. Reload before retrying")


def event(db, row, actor, kind, entity_id=None, reason=None):
    db.add(BillingEvent(invoice_id=row.id, sequence=row.version, event_type=kind,
                        entity_id=entity_id, actor_user_id=actor.user_id, reason=reason))
    db.add(AuditLog(user_id=actor.user_id, action=f"billing.{kind.lower()}",
                    details={"invoice_id": row.id, "department_id": row.department_id,
                             "version": row.version, "entity_id": entity_id}))


def amounts(db, row):
    charges = db.query(BillingCharge).filter(BillingCharge.invoice_id == row.id).order_by(BillingCharge.id).all()
    adjustments = db.query(BillingAdjustment).filter(BillingAdjustment.invoice_id == row.id).order_by(BillingAdjustment.id).all()
    payments = db.query(BillingPayment).filter(BillingPayment.invoice_id == row.id).order_by(BillingPayment.id).all()
    refunds = db.query(BillingRefundRequest).filter(BillingRefundRequest.invoice_id == row.id).order_by(BillingRefundRequest.id).all()
    subtotal = money(sum((c.line_total for c in charges), Decimal(0)))
    credits = money(sum((a.amount for a in adjustments if a.status == "APPROVED"), Decimal(0)))
    total = subtotal - credits
    paid = money(sum((p.amount for p in payments if p.status == "MANUALLY_RECORDED"), Decimal(0)))
    return charges, adjustments, payments, refunds, subtotal, credits, total, paid


def projection(db, actor, row):
    charges, adjustments, payments, refunds, subtotal, credits, total, paid = amounts(db, row)
    balance = total - paid
    status = row.status
    if status == "ISSUED":
        if balance == 0 and paid > 0:
            status = "PAID"  # Based on manually recorded payments; no settlement assertion.
        elif row.due_date and row.due_date < date.today():
            status = "OVERDUE"
        elif paid > 0:
            status = "PARTIALLY_PAID"
    patient = db.query(User).filter(User.id == row.patient_id).first()
    actions = []
    if actor.role == "department_admin":
        actions = (["add_charge"] if row.status == "DRAFT" else
                   ["record_payment", "request_adjustment", "request_refund"] if row.status == "ISSUED" else [])
        if actor.department_roles.get(row.department_id) == "BILLING_MANAGER":
            if row.status == "DRAFT": actions.extend(["issue", "cancel"])
            if row.status == "ISSUED": actions.extend(["cancel", "decide_adjustment", "reverse_payment"])
    tax_configuration_required = bool(charges and db.query(BillingTariff).filter(
        BillingTariff.id.in_([c.tariff_id for c in charges]), BillingTariff.tax_required == 1).first())
    result = {"id": row.id, "invoice_number": row.invoice_number,
        "patient": {"id": row.patient_id, "mrn": patient.mrn if patient else None,
                    "full_name": patient.full_name if patient else None},
        "department_id": row.department_id, "appointment_id": row.appointment_id,
        "encounter_id": row.encounter_id, "admission_id": row.admission_id,
        "currency": row.currency, "status": status, "version": row.version,
        "created_at": row.created_at, "issued_at": row.issued_at,
        "due_date": row.due_date, "subtotal": str(subtotal),
        "approved_adjustments": str(credits), "tax": None if tax_configuration_required else "0.00",
        "tax_status": "CONFIGURATION_REQUIRED" if tax_configuration_required else "NOT_APPLICABLE",
        "total": None if tax_configuration_required else str(total),
        "manually_recorded_payments": str(paid),
        "outstanding": None if tax_configuration_required else str(balance),
        "payment_evidence": "MANUALLY_RECORDED_ONLY",
        "allowed_actions": actions,
        "charges": [{"id": c.id, "description": c.description, "quantity": str(c.quantity),
                     "unit_price": str(c.unit_price), "line_total": str(c.line_total),
                     "source_type": c.source_type, "source_id": c.source_id} for c in charges],
        "payments": [{"id": p.id, "amount": str(p.amount), "method": p.method,
                      "reference": p.reference, "status": p.status, "recorded_at": p.recorded_at}
                     for p in payments],
        "adjustments": [{"id": a.id, "amount": str(a.amount), "status": a.status,
                         "reason": a.reason} for a in adjustments],
        "refund_requests": [{"id": r.id, "payment_id": r.payment_id,
                             "amount": str(r.amount), "status": r.status} for r in refunds]}
    if actor.role not in {"patient", "user"}:
        result["history"] = [{"sequence": e.sequence, "action": e.event_type,
                              "actor_user_id": e.actor_user_id, "created_at": e.created_at,
                              "reason": e.reason} for e in db.query(BillingEvent).filter(
                              BillingEvent.invoice_id == row.id).order_by(BillingEvent.sequence).all()]
    return result


def validate_links(db, patient_id, department_id, data):
    patient = db.query(User).filter(User.id == patient_id, User.role.in_(["patient", "user"])).first()
    if patient is None or not patient.mrn:
        raise HTTPException(422, "Existing registered patient with MRN required")
    if not db.query(Department).filter(Department.id == department_id).first():
        raise HTTPException(422, "Unknown department")
    verified = False
    if data.appointment_id:
        a = db.query(Appointment).filter(Appointment.id == data.appointment_id,
            Appointment.patient_id == patient_id, Appointment.department_id == department_id).first()
        if a is None or a.patient_id != patient_id or a.department_id != department_id:
            raise HTTPException(422, "Appointment does not match patient and department")
        verified = True
    if data.encounter_id:
        e = db.query(Encounter).filter(Encounter.id == data.encounter_id,
            Encounter.patient_id == patient_id, Encounter.department_id == department_id).first()
        if e is None or e.patient_id != patient_id or e.department_id != department_id or data.appointment_id and e.appointment_id != data.appointment_id:
            raise HTTPException(422, "Encounter does not match patient, department, or appointment")
        verified = True
    if data.admission_id:
        require_linked_table(db, "inpatient_admissions")
        admission = db.query(InpatientAdmission).join(Ward, Ward.id == InpatientAdmission.ward_id).filter(
            InpatientAdmission.id == data.admission_id, InpatientAdmission.patient_id == patient_id,
            Ward.department_id == department_id).first()
        if admission is None or admission.patient_id != patient_id or data.encounter_id and admission.source_encounter_id != data.encounter_id:
            raise HTTPException(422, "Admission does not match patient, department, or encounter")
        verified = True
    if not verified:
        raise HTTPException(422, "A verified appointment, encounter, or admission is required")


def create_invoice(db, actor, data):
    staff(actor, data.department_id)
    existing = db.query(BillingInvoice).filter(BillingInvoice.created_by_user_id == actor.user_id,
                                               BillingInvoice.creation_key == data.creation_key).first()
    if existing:
        if any(getattr(existing, key) != getattr(data, key) for key in
               ("patient_id", "department_id", "appointment_id", "encounter_id", "admission_id", "currency")):
            raise HTTPException(409, "Creation key already used for another invoice")
        return existing
    validate_links(db, data.patient_id, data.department_id, data)
    row = BillingInvoice(invoice_number="INV-" + uuid4().hex.upper(),
        created_by_user_id=actor.user_id, **data.model_dump())
    db.add(row)
    db.flush()
    event(db, row, actor, "CREATED")
    return row


def validate_source(db, row, data):
    if data.source_type == "MANUAL":
        return
    if data.source_type == "CLINICAL_ORDER":
        require_linked_table(db, "clinical_orders")
    if data.source_type == "ADMISSION":
        require_linked_table(db, "inpatient_admissions")
    source = {"APPOINTMENT": (Appointment, "patient_id", "department_id"),
              "ENCOUNTER": (Encounter, "patient_id", "department_id"),
              "CLINICAL_ORDER": (ClinicalOrder, "patient_id", "destination_department_id")}.get(data.source_type)
    if source:
        model, patient_col, department_col = source
        item = db.query(model).filter(model.id == data.source_id,
            getattr(model, patient_col) == row.patient_id,
            getattr(model, department_col) == row.department_id).first()
    else:
        item = db.query(InpatientAdmission).join(Ward, Ward.id == InpatientAdmission.ward_id).filter(
            InpatientAdmission.id == data.source_id, InpatientAdmission.patient_id == row.patient_id,
            Ward.department_id == row.department_id).first()
    if item is None or item.patient_id != row.patient_id or source and getattr(item, department_col) != row.department_id:
        raise HTTPException(422, "Charge source does not match patient and department")


def add_charge(db, actor, row, data):
    staff(actor, row.department_id)
    existing = db.query(BillingCharge).filter(BillingCharge.invoice_id == row.id,
        BillingCharge.idempotency_key == data.idempotency_key).first()
    if existing:
        if (existing.tariff_id, existing.quantity, existing.source_type, existing.source_id) != (
                data.tariff_id, data.quantity, data.source_type, data.source_id):
            raise HTTPException(409, "Charge key already used with different details")
        return
    check_version(row, data.expected_version)
    if row.status != "DRAFT":
        raise HTTPException(409, "Issued invoices cannot be edited; request an adjustment")
    tariff = db.query(BillingTariff).filter(BillingTariff.id == data.tariff_id,
        BillingTariff.department_id == row.department_id, BillingTariff.is_active == 1).first()
    if tariff is None or tariff.currency != row.currency:
        raise HTTPException(422, "An active, matching-currency tariff is required")
    validate_source(db, row, data)
    if data.source_id and db.query(BillingCharge).filter(
        BillingCharge.tariff_id == tariff.id, BillingCharge.source_type == data.source_type,
        BillingCharge.source_id == data.source_id).first():
        raise HTTPException(409, "This source was already charged at this tariff")
    line_total = money(data.quantity * tariff.unit_price)
    if line_total > Decimal("999999999999.99"):
        raise HTTPException(422, "Charge exceeds supported monetary range")
    charge = BillingCharge(invoice_id=row.id, tariff_id=tariff.id, description=tariff.description,
        quantity=data.quantity, unit_price=tariff.unit_price,
        line_total=line_total, source_type=data.source_type,
        source_id=data.source_id, idempotency_key=data.idempotency_key,
        created_by_user_id=actor.user_id)
    db.add(charge)
    db.flush()
    row.version += 1
    event(db, row, actor, "CHARGE_ADDED", charge.id)


def issue(db, actor, row, data):
    staff(actor, row.department_id, manager=True)
    check_version(row, data.expected_version)
    if row.status != "DRAFT":
        raise HTTPException(409, "Only a draft invoice may be issued")
    charges = db.query(BillingCharge).filter(BillingCharge.invoice_id == row.id).all()
    if not charges:
        raise HTTPException(422, "At least one tariff-backed charge is required")
    if data.due_date < date.today():
        raise HTTPException(422, "Due date cannot precede issue date")
    if db.query(BillingTariff).filter(BillingTariff.id.in_([c.tariff_id for c in charges]),
                                      BillingTariff.tax_required == 1).first():
        raise HTTPException(503, "Tax calculation has not been configured")
    row.status = "ISSUED"
    row.issued_at = row.released_at = datetime.now(timezone.utc)
    row.due_date = data.due_date
    row.version += 1
    event(db, row, actor, "ISSUED")


def cancel(db, actor, row, data):
    staff(actor, row.department_id, manager=True)
    check_version(row, data.expected_version)
    if row.status not in {"DRAFT", "ISSUED"}:
        raise HTTPException(409, "Invoice is already cancelled")
    if db.query(BillingPayment).filter(BillingPayment.invoice_id == row.id,
                                       BillingPayment.status == "MANUALLY_RECORDED").first():
        raise HTTPException(409, "Reverse recorded payments before cancellation")
    if active_insurance_claim_exists(db, row.id):
        raise HTTPException(409, "Invoice has an active insurer claim")
    row.status = "CANCELLED"
    row.cancelled_at = datetime.now(timezone.utc)
    row.cancellation_reason = data.reason
    row.version += 1
    event(db, row, actor, "CANCELLED", reason=data.reason)


def request_adjustment(db, actor, row, data):
    staff(actor, row.department_id)
    check_version(row, data.expected_version)
    if row.status != "ISSUED":
        raise HTTPException(409, "Adjustments require an issued invoice")
    item = BillingAdjustment(invoice_id=row.id, amount=data.amount, reason=data.reason,
                             requested_by_user_id=actor.user_id, status="REQUESTED")
    db.add(item)
    db.flush()
    row.version += 1
    event(db, row, actor, "ADJUSTMENT_REQUESTED", item.id)


def decide_adjustment(db, actor, row, adjustment_id, data):
    staff(actor, row.department_id, manager=True)
    check_version(row, data.expected_version)
    if row.status != "ISSUED":
        raise HTTPException(409, "Invoice is no longer issued")
    item = db.query(BillingAdjustment).filter(BillingAdjustment.id == adjustment_id,
        BillingAdjustment.invoice_id == row.id).first()
    if item is None or item.status != "REQUESTED":
        raise HTTPException(409, "Adjustment is not pending")
    if data.approve:
        _, _, _, _, subtotal, credits, _, paid = amounts(db, row)
        if item.amount > subtotal - credits - paid:
            raise HTTPException(409, "Adjustment exceeds unpaid balance")
        if active_insurance_claim_exists(db, row.id):
            raise HTTPException(409, "Resolve the active insurer claim before approving an invoice adjustment")
    item.status = "APPROVED" if data.approve else "REJECTED"
    item.decided_by_user_id = actor.user_id
    item.decided_at = datetime.now(timezone.utc)
    row.version += 1
    event(db, row, actor, "ADJUSTMENT_" + item.status, item.id, data.reason)


def record_payment(db, actor, row, data):
    staff(actor, row.department_id)
    existing = db.query(BillingPayment).filter(BillingPayment.invoice_id == row.id,
        BillingPayment.idempotency_key == data.idempotency_key).first()
    if existing:
        if (existing.amount, existing.currency, existing.method, existing.reference) != (
                data.amount, data.currency, data.method, data.reference):
            raise HTTPException(409, "Payment key already used with different details")
        return
    check_version(row, data.expected_version)
    if row.status != "ISSUED" or row.currency != data.currency:
        raise HTTPException(409, "An issued invoice with matching currency is required")
    if db.query(BillingPayment).filter(BillingPayment.method == data.method,
        BillingPayment.reference == data.reference, BillingPayment.currency == data.currency).first():
        raise HTTPException(409, "Payment reference already recorded")
    _, _, _, _, _, _, total, paid = amounts(db, row)
    if data.amount > total - paid:
        raise HTTPException(409, "Payment exceeds outstanding balance")
    payment = BillingPayment(invoice_id=row.id, amount=data.amount, currency=data.currency,
        method=data.method, reference=data.reference, idempotency_key=data.idempotency_key,
        recorded_by_user_id=actor.user_id, status="MANUALLY_RECORDED")
    db.add(payment)
    db.flush()
    row.version += 1
    event(db, row, actor, "MANUAL_PAYMENT_RECORDED", payment.id)


def reverse_payment(db, actor, row, payment_id, data):
    staff(actor, row.department_id, manager=True)
    check_version(row, data.expected_version)
    payment = db.query(BillingPayment).filter(BillingPayment.id == payment_id,
        BillingPayment.invoice_id == row.id).first()
    if payment is None or payment.status != "MANUALLY_RECORDED":
        raise HTTPException(409, "Active manual payment not found")
    if db.query(BillingRefundRequest).filter(BillingRefundRequest.payment_id == payment_id).first():
        raise HTTPException(409, "A refund request exists for this payment")
    try:
        insurance_tables = set(inspect(db.get_bind()).get_table_names(schema="public"))
    except Exception:
        raise HTTPException(503, "Cannot verify claim remittance links before reversal") from None
    if "insurance_remittances" in insurance_tables:
        from src.insurance_models import InsuranceRemittance
        if db.query(InsuranceRemittance).filter(InsuranceRemittance.billing_payment_id == payment_id).first():
            raise HTTPException(409, "Payment is linked to an insurer claim; correct the claim before reversal")
    payment.status = "REVERSED"
    payment.reversed_at = datetime.now(timezone.utc)
    payment.reversed_by_user_id = actor.user_id
    payment.reversal_reason = data.reason
    row.version += 1
    event(db, row, actor, "MANUAL_PAYMENT_REVERSED", payment.id, data.reason)


def request_refund(db, actor, row, data):
    staff(actor, row.department_id)
    check_version(row, data.expected_version)
    payment = db.query(BillingPayment).filter(BillingPayment.id == data.payment_id,
        BillingPayment.invoice_id == row.id, BillingPayment.status == "MANUALLY_RECORDED").first()
    if payment is None or data.amount > payment.amount:
        raise HTTPException(422, "Refund request must reference an active payment and valid amount")
    if db.query(BillingRefundRequest).filter(BillingRefundRequest.payment_id == payment.id).first():
        raise HTTPException(409, "Refund already requested for this payment")
    request = BillingRefundRequest(invoice_id=row.id, payment_id=payment.id,
        amount=data.amount, reason=data.reason, requested_by_user_id=actor.user_id)
    db.add(request)
    db.flush()
    row.version += 1
    event(db, row, actor, "REFUND_REQUESTED", request.id)
