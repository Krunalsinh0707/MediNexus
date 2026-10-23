"""Insurance and claims rules; no insurer integration or automatic accounting."""
import base64
import binascii
import hashlib
import hmac
import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import inspect

from src import billing_service as billing
from src.billing_models import BillingInvoice, BillingCharge, BillingPayment
from src.encounter_models import Encounter
from src.insurance_models import (InsuranceBase, InsurancePolicy, InsurancePolicyEvent,
    InsuranceEligibilityCheck, InsuranceClaim, InsuranceClaimLine,
    InsuranceClaimLineAmendment, InsuranceClaimEvent, InsuranceRemittance)
from src.models import User, Appointment, AuditLog


TRANSITIONS = {
    "DRAFT": {"READY_FOR_REVIEW", "CANCELLED"},
    "READY_FOR_REVIEW": {"SUBMITTED", "CANCELLED"},
    "SUBMITTED": {"ACKNOWLEDGED", "UNDER_REVIEW"},
    "ACKNOWLEDGED": {"UNDER_REVIEW"},
    "UNDER_REVIEW": {"APPROVED", "PARTIALLY_APPROVED", "DENIED"},
    "DENIED": {"READY_FOR_REVIEW"},
    "APPROVED": set(), "PARTIALLY_APPROVED": set(), "PAID": set(), "CANCELLED": set(),
}


def require_schema(db):
    billing.require_schema(db)
    try:
        available = set(inspect(db.get_bind()).get_table_names(schema="public"))
    except Exception:
        raise HTTPException(503, "Insurance storage is unavailable") from None
    if not set(InsuranceBase.metadata.tables).issubset(available):
        raise HTTPException(503, "Insurance storage is not installed; an approved migration is required")


def field_key():
    configured = os.getenv("HMS_INSURANCE_FIELD_KEY")
    try:
        if not configured or len(base64.urlsafe_b64decode(configured)) != 32:
            raise ValueError("missing key")
        return Fernet(configured.encode("ascii"))
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        raise HTTPException(503, "Insurance field encryption is not configured") from None


def secure_identifier(value):
    key = field_key()
    normalized = value.strip().upper()
    configured = os.environ["HMS_INSURANCE_FIELD_KEY"].encode("ascii")
    digest = hmac.new(configured, normalized.encode("utf-8"), hashlib.sha256).hexdigest()
    return key.encrypt(value.encode("utf-8")), digest, normalized[-4:]


def policy_status(row):
    if row.coverage_end and row.coverage_end < date.today():
        return "EXPIRED"
    return row.status


def policy_for(db, actor, policy_id, lock=False):
    query = db.query(InsurancePolicy).filter(InsurancePolicy.id == policy_id)
    if lock:
        query = query.with_for_update()
    row = query.first()
    if not row:
        raise HTTPException(404, "Policy not found")
    if actor.role in {"patient", "user"}:
        if row.patient_id != actor.user_id or row.released_at is None:
            raise HTTPException(404, "Policy not found")
    else:
        billing.staff(actor, row.department_id)
    return row


def claim_for(db, actor, claim_id, lock=False):
    query = db.query(InsuranceClaim).filter(InsuranceClaim.id == claim_id)
    if lock:
        query = query.with_for_update()
    row = query.first()
    if not row:
        raise HTTPException(404, "Claim not found")
    if actor.role in {"patient", "user"}:
        if row.patient_id != actor.user_id or row.released_at is None:
            raise HTTPException(404, "Claim not found")
    else:
        billing.staff(actor, row.department_id)
    return row


def version(row, expected):
    if row.version != expected:
        raise HTTPException(409, "Record changed. Reload before retrying")


def audit(db, actor, action, *, policy=None, claim=None):
    db.add(AuditLog(user_id=actor.user_id, action="insurance." + action.lower(),
        details={"policy_id": getattr(policy, "id", None), "claim_id": getattr(claim, "id", None),
                 "department_id": getattr(policy or claim, "department_id", None),
                 "version": getattr(policy or claim, "version", None)}))


def policy_event(db, actor, row, action, reason=None, changed_fields=None):
    db.add(InsurancePolicyEvent(policy_id=row.id, sequence=row.version, action=action,
        actor_user_id=actor.user_id, reason=reason, changed_fields=changed_fields))
    audit(db, actor, action, policy=row)


def claim_event(db, actor, row, previous, source="INTERNAL_WORKFLOW", reference=None, reason=None, action=None):
    db.add(InsuranceClaimEvent(claim_id=row.id, sequence=row.version,
        action=action or row.status, from_status=previous, to_status=row.status, actor_user_id=actor.user_id,
        source=source, source_reference=reference, reason=reason,
        requested_total=row.requested_total, approved_amount=row.approved_amount,
        denied_amount=row.denied_amount, insurer_reference=row.insurer_reference))
    audit(db, actor, "claim_" + row.status.lower(), claim=row)


def policy_projection(db, actor, row):
    actions = []
    if actor.role == "department_admin":
        actions = ["update", "record_eligibility"]
        if (actor.department_roles.get(row.department_id) == "BILLING_MANAGER"
                and row.released_at is None and policy_status(row) not in {"UNVERIFIED", "PENDING"}):
            actions.append("release")
    result = {"id": row.id, "patient_id": row.patient_id,
        "department_id": row.department_id, "insurer_code": row.insurer_code,
        "insurer_name": row.insurer_name, "plan_code": row.plan_code,
        "member_identifier_masked": "••••" + row.member_last4,
        "policyholder_relationship": row.policyholder_relationship,
        "coverage_start": row.coverage_start, "coverage_end": row.coverage_end,
        "status": policy_status(row), "version": row.version,
        "last_checked_at": row.last_checked_at,
        "last_check_method": row.last_check_method or "NOT_CHECKED",
        "released_at": row.released_at,
        "benefits_status": "UNAVAILABLE_WITHOUT_TRUSTED_SOURCE",
        "real_time_eligibility": "INTEGRATION_UNAVAILABLE",
        "allowed_actions": actions}
    if actor.role not in {"patient", "user"}:
        result["checks"] = [{"id": c.id, "status": c.status,
            "method": c.method, "source_reference": c.source_reference,
            "checked_at": c.checked_at, "checked_by_user_id": c.checked_by_user_id,
            "reason": c.reason} for c in db.query(InsuranceEligibilityCheck).filter(
                InsuranceEligibilityCheck.policy_id == row.id).order_by(InsuranceEligibilityCheck.id).all()]
        result["history"] = [{"sequence": e.sequence, "action": e.action,
            "actor_user_id": e.actor_user_id, "occurred_at": e.occurred_at,
            "changed_fields": e.changed_fields, "reason": e.reason}
            for e in db.query(InsurancePolicyEvent).filter(
                InsurancePolicyEvent.policy_id == row.id).order_by(InsurancePolicyEvent.sequence).all()]
    return result


def claim_projection(db, actor, row):
    lines = db.query(InsuranceClaimLine).filter(InsuranceClaimLine.claim_id == row.id).order_by(InsuranceClaimLine.id).all()
    remittances = db.query(InsuranceRemittance).filter(InsuranceRemittance.claim_id == row.id).order_by(InsuranceRemittance.id).all()
    reconciled = billing.money(sum((r.amount for r in remittances), Decimal(0)))
    transitions = []
    actions = []
    if actor.role == "department_admin":
        manager = actor.department_roles.get(row.department_id) == "BILLING_MANAGER"
        transitions = sorted(target for target in TRANSITIONS.get(row.status, set())
                             if manager or target not in {"SUBMITTED", "APPROVED", "PARTIALLY_APPROVED", "DENIED", "CANCELLED"})
        if manager and row.released_at is None and row.status not in {"DRAFT", "READY_FOR_REVIEW", "CANCELLED"}:
            actions.append("release")
        if manager and row.status in {"APPROVED", "PARTIALLY_APPROVED"} and row.approved_amount:
            actions.append("reconcile")
        if row.status in {"DRAFT", "DENIED"}:
            actions.append("correct")
    result = {"id": row.id, "claim_number": row.claim_number, "invoice_id": row.invoice_id,
        "policy_id": row.policy_id, "patient_id": row.patient_id,
        "department_id": row.department_id, "encounter_id": row.encounter_id,
        "currency": row.currency, "requested_total": str(row.requested_total),
        "approved_amount": str(row.approved_amount) if row.approved_amount is not None else None,
        "denied_amount": str(row.denied_amount) if row.denied_amount is not None else None,
        "patient_responsibility": str(row.patient_responsibility) if row.patient_responsibility is not None else None,
        "status": row.status, "version": row.version,
        "created_at": row.created_at, "submitted_at": row.submitted_at,
        "released_at": row.released_at,
        "decision_source": row.decision_source or "NONE",
        "payment_status": "MANUALLY_RECONCILED_UNVERIFIED" if reconciled else "NO_REMITTANCE_RECORDED",
        "manually_reconciled_amount": str(reconciled),
        "lines": [{"charge_id": x.charge_id, "billed_amount": str(x.billed_amount),
                   "requested_amount": str(x.requested_amount),
                   **({"review_reference": x.review_reference} if actor.role not in {"patient", "user"} else {})}
                   for x in lines],
        "allowed_transitions": transitions, "allowed_actions": actions}
    if actor.role not in {"patient", "user"}:
        result.update({"insurer_reference": row.insurer_reference,
            "decision_reason": row.decision_reason,
            "remittances": [{"id": r.id, "billing_payment_id": r.billing_payment_id,
                             "amount": str(r.amount), "source": r.source,
                             "source_reference": r.source_reference,
                             "reconciled_at": r.reconciled_at} for r in remittances],
            "history": [{"sequence": e.sequence, "from_status": e.from_status,
                         "to_status": e.to_status, "source": e.source,
                         "action": e.action, "requested_total": str(e.requested_total),
                         "actor_user_id": e.actor_user_id, "occurred_at": e.occurred_at,
                         "reason": e.reason} for e in db.query(InsuranceClaimEvent).filter(
                             InsuranceClaimEvent.claim_id == row.id).order_by(InsuranceClaimEvent.sequence).all()],
            "line_amendments": [{"charge_id": x.charge_id, "claim_version": x.claim_version,
                "from_amount": str(x.from_amount), "to_amount": str(x.to_amount),
                "from_review_reference": x.from_review_reference,
                "to_review_reference": x.to_review_reference,
                "reason": x.reason, "actor_user_id": x.actor_user_id,
                "amended_at": x.amended_at} for x in db.query(InsuranceClaimLineAmendment).filter(
                    InsuranceClaimLineAmendment.claim_id == row.id).order_by(InsuranceClaimLineAmendment.id).all()]})
    return result


def require_patient_relationship(db, patient_id, department_id):
    patient = db.query(User).filter(User.id == patient_id,
        User.role.in_(["patient", "user"])).first()
    if patient is None or not patient.mrn:
        raise HTTPException(422, "Registered patient with MRN required")
    linked = (db.query(BillingInvoice).filter(BillingInvoice.patient_id == patient_id,
            BillingInvoice.department_id == department_id).first()
        or db.query(Appointment).filter(Appointment.patient_id == patient_id,
            Appointment.department_id == department_id).first()
        or db.query(Encounter).filter(Encounter.patient_id == patient_id,
            Encounter.department_id == department_id).first())
    if linked is None or linked.patient_id != patient_id or linked.department_id != department_id:
        raise HTTPException(404, "No patient relationship in assigned department")


def create_policy(db, actor, data):
    billing.staff(actor, data.department_id)
    require_patient_relationship(db, data.patient_id, data.department_id)
    ciphertext, digest, last4 = secure_identifier(data.member_identifier)
    if db.query(InsurancePolicy).filter(InsurancePolicy.patient_id == data.patient_id,
        InsurancePolicy.insurer_code == data.insurer_code,
        InsurancePolicy.plan_code == data.plan_code,
        InsurancePolicy.member_identifier_digest == digest).first():
        raise HTTPException(409, "Policy already recorded for this patient")
    row = InsurancePolicy(**data.model_dump(exclude={"member_identifier"}),
        member_identifier_ciphertext=ciphertext, member_identifier_digest=digest,
        member_last4=last4, status="UNVERIFIED", created_by_user_id=actor.user_id)
    db.add(row)
    db.flush()
    policy_event(db, actor, row, "CREATED")
    return row


def update_policy(db, actor, row, data):
    billing.staff(actor, row.department_id)
    version(row, data.expected_version)
    if db.query(InsuranceClaim).filter(InsuranceClaim.policy_id == row.id).first():
        raise HTTPException(409, "A policy already used for a claim cannot be rewritten")
    changed = [name for name in ("insurer_name", "plan_code", "policyholder_relationship", "coverage_start", "coverage_end")
               if getattr(row, name) != getattr(data, name)]
    if not changed:
        raise HTTPException(422, "No policy fields changed")
    for name in changed:
        setattr(row, name, getattr(data, name))
    row.status = "UNVERIFIED"
    row.released_at = None
    row.last_checked_at = row.last_checked_by_user_id = row.last_check_method = None
    row.version += 1
    policy_event(db, actor, row, "UPDATED_REVERIFY", data.reason, ",".join(changed))


def record_eligibility(db, actor, row, data):
    billing.staff(actor, row.department_id)
    version(row, data.expected_version)
    if data.method != "MANUAL_STAFF_ENTRY":
        raise HTTPException(503, "Live insurer eligibility integration is unavailable")
    if policy_status(row) == "EXPIRED" and data.status == "VERIFIED":
        raise HTTPException(422, "Expired policy cannot be marked eligible")
    now = datetime.now(timezone.utc)
    check = InsuranceEligibilityCheck(policy_id=row.id, status=data.status,
        method="MANUAL_STAFF_ENTRY", source_reference=data.source_reference,
        checked_by_user_id=actor.user_id, checked_at=now, reason=data.reason)
    db.add(check)
    db.flush()
    row.status = data.status
    row.last_checked_at = now
    row.last_checked_by_user_id = actor.user_id
    row.last_check_method = "MANUAL_STAFF_ENTRY"
    row.released_at = None  # A fresh check needs a fresh explicit release.
    row.version += 1
    policy_event(db, actor, row, "ELIGIBILITY_" + data.status)


def release_policy(db, actor, row, data):
    billing.staff(actor, row.department_id, manager=True)
    version(row, data.expected_version)
    if row.released_at is not None:
        raise HTTPException(409, "Policy is already released")
    if policy_status(row) in {"UNVERIFIED", "PENDING"}:
        raise HTTPException(409, "Only a completed eligibility check may be released")
    row.released_at = datetime.now(timezone.utc)
    row.version += 1
    policy_event(db, actor, row, "RELEASED")


def create_claim(db, actor, data):
    fingerprint = hashlib.sha256(json.dumps({"invoice_id": data.invoice_id, "policy_id": data.policy_id,
        "lines": sorted([(x.charge_id, str(billing.money(x.requested_amount)), x.review_reference) for x in data.lines])},
        sort_keys=True).encode()).hexdigest()
    existing = db.query(InsuranceClaim).filter(InsuranceClaim.created_by_user_id == actor.user_id,
        InsuranceClaim.creation_key == data.creation_key).first()
    if existing:
        billing.staff(actor, existing.department_id)
        if existing.creation_fingerprint != fingerprint:
            raise HTTPException(409, "Claim key already used for different records")
        return existing
    invoice = db.query(BillingInvoice).filter(BillingInvoice.id == data.invoice_id).with_for_update().first()
    if invoice is None:
        raise HTTPException(404, "Invoice not found")
    billing.staff(actor, invoice.department_id)
    if invoice.status != "ISSUED" or invoice.released_at is None or invoice.issued_at is None:
        raise HTTPException(409, "An issued, released invoice is required")
    policy = db.query(InsurancePolicy).filter(InsurancePolicy.id == data.policy_id).first()
    if (policy is None or policy.patient_id != invoice.patient_id or
            policy.department_id != invoice.department_id):
        raise HTTPException(422, "Policy does not match invoice patient and department")
    if policy_status(policy) != "VERIFIED" or not policy.last_checked_at:
        raise HTTPException(422, "A current manually verified policy is required; payment is not guaranteed")
    issue_date = invoice.issued_at.date()
    if issue_date < policy.coverage_start or policy.coverage_end and issue_date > policy.coverage_end:
        raise HTTPException(422, "Invoice issue date falls outside policy dates")
    _, _, _, _, _, _, invoice_total, paid = billing.amounts(db, invoice)
    requested = billing.money(sum((line.requested_amount for line in data.lines), Decimal(0)))
    if requested > Decimal("999999999999.99"):
        raise HTTPException(422, "Claim total exceeds supported monetary range")
    if requested > invoice_total - paid:
        raise HTTPException(422, "Requested claim exceeds unpaid invoice total")
    charges = db.query(BillingCharge).filter(BillingCharge.invoice_id == invoice.id,
        BillingCharge.id.in_([line.charge_id for line in data.lines])).all()
    by_id = {charge.id: charge for charge in charges}
    if len(by_id) != len(data.lines):
        raise HTTPException(422, "All claim lines must belong to the invoice")
    for line in data.lines:
        charge = by_id[line.charge_id]
        if line.requested_amount > charge.line_total:
            raise HTTPException(422, "Claim line exceeds billed charge")
        if db.query(InsuranceClaimLine).filter(InsuranceClaimLine.charge_id == line.charge_id).first():
            raise HTTPException(409, "Invoice charge already assigned to another claim")
    row = InsuranceClaim(claim_number="CLM-" + uuid4().hex.upper(),
        creation_key=data.creation_key, creation_fingerprint=fingerprint,
        invoice_id=invoice.id, policy_id=policy.id,
        patient_id=invoice.patient_id, department_id=invoice.department_id,
        encounter_id=invoice.encounter_id, currency=invoice.currency,
        requested_total=requested, status="DRAFT", version=1,
        created_by_user_id=actor.user_id)
    db.add(row)
    db.flush()
    for line in data.lines:
        db.add(InsuranceClaimLine(claim_id=row.id, charge_id=line.charge_id,
            billed_amount=by_id[line.charge_id].line_total,
            requested_amount=line.requested_amount,
            review_reference=line.review_reference))
    claim_event(db, actor, row, None)
    return row


def correct_claim(db, actor, row, data):
    billing.staff(actor, row.department_id)
    version(row, data.expected_version)
    if row.status not in {"DRAFT", "DENIED"}:
        raise HTTPException(409, "Only draft or denied claims may be corrected")
    invoice = db.query(BillingInvoice).filter(BillingInvoice.id == row.invoice_id).with_for_update().first()
    if (invoice is None or invoice.status != "ISSUED" or invoice.patient_id != row.patient_id
            or invoice.department_id != row.department_id):
        raise HTTPException(409, "Linked invoice is no longer valid")
    current = db.query(InsuranceClaimLine).filter(InsuranceClaimLine.claim_id == row.id).all()
    by_charge = {line.charge_id: line for line in current}
    if set(by_charge) != {line.charge_id for line in data.lines}:
        raise HTTPException(422, "Correction must retain the original invoice charges")
    total = billing.money(sum((line.requested_amount for line in data.lines), Decimal(0)))
    if total > Decimal("999999999999.99"):
        raise HTTPException(422, "Corrected claim exceeds supported monetary range")
    _, _, _, _, _, _, invoice_total, paid = billing.amounts(db, invoice)
    if total > invoice_total - paid:
        raise HTTPException(422, "Corrected claim exceeds unpaid invoice total")
    changed = []
    for line in data.lines:
        previous = by_charge[line.charge_id]
        if line.requested_amount > previous.billed_amount:
            raise HTTPException(422, "Corrected line exceeds billed amount")
        if line.requested_amount != previous.requested_amount or line.review_reference != previous.review_reference:
            changed.append((previous, line))
    if not changed:
        raise HTTPException(422, "Correction must change a requested amount")
    previous_status = row.status
    row.version += 1
    for previous, line in changed:
        db.add(InsuranceClaimLineAmendment(claim_id=row.id, charge_id=previous.charge_id,
            claim_version=row.version, from_amount=previous.requested_amount,
            to_amount=line.requested_amount,
            from_review_reference=previous.review_reference,
            to_review_reference=line.review_reference,
            reason=data.reason, actor_user_id=actor.user_id))
        previous.requested_amount = line.requested_amount
        previous.review_reference = line.review_reference
    row.requested_total = total
    if row.status == "DENIED":
        row.status = "DRAFT"
        row.approved_amount = row.denied_amount = row.patient_responsibility = None
        row.decision_reason = row.decision_source = row.insurer_reference = None
    claim_event(db, actor, row, previous_status, reason=data.reason, action="CORRECTED")


def transition_claim(db, actor, row, data):
    billing.staff(actor, row.department_id)
    version(row, data.expected_version)
    target = data.to_status
    if target not in TRANSITIONS.get(row.status, set()):
        raise HTTPException(409, "Invalid claim transition")
    if target not in {"CANCELLED"}:
        invoice = db.query(BillingInvoice).filter(BillingInvoice.id == row.invoice_id).first()
        if (invoice is None or invoice.status != "ISSUED" or invoice.patient_id != row.patient_id
                or invoice.department_id != row.department_id):
            raise HTTPException(409, "Linked invoice is no longer issued for this patient and department")
    if target in {"SUBMITTED", "APPROVED", "PARTIALLY_APPROVED", "DENIED", "CANCELLED"}:
        billing.staff(actor, row.department_id, manager=True)
    if target in {"CANCELLED"} or row.status == "DENIED":
        if not data.reason:
            raise HTTPException(422, "Cancellation or resubmission requires a reason")
    if target in {"SUBMITTED", "ACKNOWLEDGED", "UNDER_REVIEW", "APPROVED", "PARTIALLY_APPROVED", "DENIED"} and not data.source_reference:
        raise HTTPException(422, "A real manual evidence reference is required")
    if target in {"APPROVED", "PARTIALLY_APPROVED", "DENIED"}:
        if data.approved_amount is None or data.denied_amount is None:
            raise HTTPException(422, "Adjudication amounts are required")
        if billing.money(data.approved_amount + data.denied_amount) != row.requested_total:
            raise HTTPException(422, "Approved and denied amounts must equal claim total")
        if target == "APPROVED" and data.denied_amount != 0 or target == "DENIED" and data.approved_amount != 0 or target == "PARTIALLY_APPROVED" and (data.approved_amount <= 0 or data.denied_amount <= 0):
            raise HTTPException(422, "Adjudication amounts do not match decision status")
        if target in {"DENIED", "PARTIALLY_APPROVED"} and not data.reason:
            raise HTTPException(422, "A reason is required for the denied amount")
        if data.patient_responsibility is not None and data.patient_responsibility > data.denied_amount:
            raise HTTPException(422, "Patient responsibility exceeds denied amount")
    elif any(value is not None for value in (data.approved_amount, data.denied_amount, data.patient_responsibility)):
        raise HTTPException(422, "Adjudication amounts require an actual decision")
    previous = row.status
    if previous == "DENIED" and target == "READY_FOR_REVIEW":
        # The prior decision remains in append-only events.
        row.approved_amount = row.denied_amount = row.patient_responsibility = None
        row.decision_reason = row.decision_source = None
        row.insurer_reference = None
    if target in {"APPROVED", "PARTIALLY_APPROVED", "DENIED"}:
        row.approved_amount = data.approved_amount
        row.denied_amount = data.denied_amount
        row.patient_responsibility = data.patient_responsibility
        row.decision_reason = data.reason
        row.decision_source = "MANUAL_STAFF_ENTRY"
    if target == "SUBMITTED":
        row.submitted_at = datetime.now(timezone.utc)
    if data.insurer_reference:
        if target not in {"ACKNOWLEDGED", "UNDER_REVIEW", "APPROVED", "PARTIALLY_APPROVED", "DENIED"}:
            raise HTTPException(422, "Insurer reference cannot be attached to this transition")
        row.insurer_reference = data.insurer_reference
    row.status = target
    row.version += 1
    claim_event(db, actor, row, previous,
        source="MANUAL_STAFF_ENTRY" if data.source_reference else "INTERNAL_WORKFLOW",
        reference=data.source_reference, reason=data.reason)


def release_claim(db, actor, row, data):
    billing.staff(actor, row.department_id, manager=True)
    version(row, data.expected_version)
    if row.released_at is not None:
        raise HTTPException(409, "Claim is already released")
    if row.status in {"DRAFT", "READY_FOR_REVIEW", "CANCELLED"}:
        raise HTTPException(409, "Claim is not ready for patient release")
    row.released_at = datetime.now(timezone.utc)
    row.version += 1
    claim_event(db, actor, row, row.status, action="RELEASED")


def reconcile_remittance(db, actor, row, data):
    billing.staff(actor, row.department_id, manager=True)
    version(row, data.expected_version)
    if row.status not in {"APPROVED", "PARTIALLY_APPROVED"} or not row.approved_amount:
        raise HTTPException(409, "A positive adjudicated amount is required")
    # Billing reversals lock the invoice first. Hold that lock through the
    # remittance insert so a concurrent reversal cannot race reconciliation.
    invoice = db.query(BillingInvoice).filter(BillingInvoice.id == row.invoice_id).with_for_update().first()
    if (invoice is None or invoice.status != "ISSUED" or invoice.patient_id != row.patient_id
            or invoice.department_id != row.department_id):
        raise HTTPException(409, "Linked invoice is no longer available for reconciliation")
    payment = db.query(BillingPayment).filter(BillingPayment.id == data.billing_payment_id,
        BillingPayment.invoice_id == row.invoice_id,
        BillingPayment.status == "MANUALLY_RECORDED").first()
    if (payment is None or payment.invoice_id != row.invoice_id
            or payment.status != "MANUALLY_RECORDED" or payment.currency != row.currency
            or payment.recorded_at is None or row.created_at is None
            or payment.recorded_at < row.created_at):
        raise HTTPException(422, "Active matching-currency billing payment required")
    if db.query(InsuranceRemittance).filter(InsuranceRemittance.billing_payment_id == payment.id).first():
        raise HTTPException(409, "Billing payment already reconciled to an insurer claim")
    existing = db.query(InsuranceRemittance).filter(InsuranceRemittance.claim_id == row.id).all()
    amount = billing.money(payment.amount)
    previous_total = billing.money(sum((r.amount for r in existing), Decimal(0)))
    if amount + previous_total > row.approved_amount:
        raise HTTPException(409, "Remittance exceeds approved insurer amount")
    remittance = InsuranceRemittance(claim_id=row.id, billing_payment_id=payment.id,
        amount=amount, source="MANUAL_RECONCILIATION",
        source_reference=data.source_reference, reconciled_by_user_id=actor.user_id)
    db.add(remittance)
    db.flush()
    previous = row.status
    if previous_total + amount == row.approved_amount:
        row.status = "PAID"
    row.version += 1
    claim_event(db, actor, row, previous, source="MANUAL_RECONCILIATION",
                reference=data.source_reference)
