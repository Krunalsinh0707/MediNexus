"""Insurance contracts installed by the additive module foundation."""
from sqlalchemy import (CheckConstraint, Column, Date, DateTime, ForeignKey, Index,
                        Integer, LargeBinary, Numeric, String, Text, UniqueConstraint, text)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func


class InsuranceBase(DeclarativeBase):
    pass


def ref(target, nullable=False):
    return Column(Integer, ForeignKey(target, ondelete="RESTRICT"), nullable=nullable, index=True)


class InsurancePolicy(InsuranceBase):
    __tablename__ = "insurance_policies"
    id = Column(Integer, primary_key=True)
    patient_id = ref("users.id")
    department_id = ref("departments.id")
    insurer_code = Column(String(64), nullable=False)
    insurer_name = Column(String(255), nullable=False)
    plan_code = Column(String(64), nullable=False)
    member_identifier_ciphertext = Column(LargeBinary, nullable=False)
    member_identifier_digest = Column(String(64), nullable=False)
    member_last4 = Column(String(4), nullable=False)
    policyholder_relationship = Column(String(24), nullable=False)
    coverage_start = Column(Date, nullable=False)
    coverage_end = Column(Date, nullable=True)
    status = Column(String(24), nullable=False, server_default=text("'UNVERIFIED'"))
    version = Column(Integer, nullable=False, server_default=text("1"))
    last_checked_at = Column(DateTime(timezone=True))
    last_checked_by_user_id = ref("users.id", nullable=True)
    last_check_method = Column(String(24))
    released_at = Column(DateTime(timezone=True))
    created_by_user_id = ref("users.id")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("patient_id", "insurer_code", "plan_code", "member_identifier_digest",
                         name="uq_insurance_policy_member"),
        CheckConstraint("coverage_end IS NULL OR coverage_end >= coverage_start", name="ck_policy_dates"),
        CheckConstraint("status IN ('UNVERIFIED','PENDING','VERIFIED','INELIGIBLE','FAILED')", name="ck_policy_status"),
        CheckConstraint("policyholder_relationship IN ('SELF','SPOUSE','CHILD','PARENT','OTHER')", name="ck_policy_relationship"),
        CheckConstraint("version > 0", name="ck_policy_version"),
        Index("ix_insurance_patient_department", "patient_id", "department_id"),
    )


class InsurancePolicyEvent(InsuranceBase):
    __tablename__ = "insurance_policy_events"
    id = Column(Integer, primary_key=True)
    policy_id = ref("insurance_policies.id")
    sequence = Column(Integer, nullable=False)
    action = Column(String(32), nullable=False)
    actor_user_id = ref("users.id")
    reason = Column(Text)
    changed_fields = Column(String(255))
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint("policy_id", "sequence", name="uq_policy_event_sequence"),)


class InsuranceEligibilityCheck(InsuranceBase):
    __tablename__ = "insurance_eligibility_checks"
    id = Column(Integer, primary_key=True)
    policy_id = ref("insurance_policies.id")
    status = Column(String(24), nullable=False)
    method = Column(String(24), nullable=False)
    source_reference = Column(String(128), nullable=False)
    checked_by_user_id = ref("users.id")
    checked_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    reason = Column(Text)
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','VERIFIED','INELIGIBLE','FAILED')", name="ck_eligibility_status"),
        CheckConstraint("method IN ('MANUAL_STAFF_ENTRY','EXTERNAL_VERIFIED')", name="ck_eligibility_method"),
    )


class InsuranceClaim(InsuranceBase):
    __tablename__ = "insurance_claims"
    id = Column(Integer, primary_key=True)
    claim_number = Column(String(40), nullable=False, unique=True)
    creation_key = Column(String(100), nullable=False)
    creation_fingerprint = Column(String(64), nullable=False)
    invoice_id = ref("billing_invoices.id")
    policy_id = ref("insurance_policies.id")
    patient_id = ref("users.id")
    department_id = ref("departments.id")
    encounter_id = ref("encounters.id", nullable=True)
    currency = Column(String(3), nullable=False)
    requested_total = Column(Numeric(14, 2), nullable=False)
    approved_amount = Column(Numeric(14, 2), nullable=True)
    denied_amount = Column(Numeric(14, 2), nullable=True)
    patient_responsibility = Column(Numeric(14, 2), nullable=True)
    status = Column(String(24), nullable=False, server_default=text("'DRAFT'"))
    version = Column(Integer, nullable=False, server_default=text("1"))
    insurer_reference = Column(String(128))
    decision_source = Column(String(24))
    decision_reason = Column(Text)
    created_by_user_id = ref("users.id")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    submitted_at = Column(DateTime(timezone=True))
    released_at = Column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("invoice_id", "policy_id", name="uq_claim_invoice_policy"),
        UniqueConstraint("created_by_user_id", "creation_key", name="uq_claim_create_request"),
        CheckConstraint("status IN ('DRAFT','READY_FOR_REVIEW','SUBMITTED','ACKNOWLEDGED','UNDER_REVIEW','APPROVED','PARTIALLY_APPROVED','DENIED','PAID','CANCELLED')", name="ck_claim_status"),
        CheckConstraint("requested_total > 0 AND version > 0", name="ck_claim_total_version"),
        CheckConstraint("approved_amount IS NULL OR approved_amount >= 0", name="ck_claim_approved_amount"),
        CheckConstraint("denied_amount IS NULL OR denied_amount >= 0", name="ck_claim_denied_amount"),
        CheckConstraint("patient_responsibility IS NULL OR patient_responsibility >= 0", name="ck_claim_patient_responsibility"),
        Index("ix_claim_department_status", "department_id", "status"),
        Index("ix_claim_patient_created", "patient_id", "created_at"),
    )


class InsuranceClaimLine(InsuranceBase):
    __tablename__ = "insurance_claim_lines"
    id = Column(Integer, primary_key=True)
    claim_id = ref("insurance_claims.id")
    charge_id = ref("billing_charges.id")
    billed_amount = Column(Numeric(14, 2), nullable=False)
    requested_amount = Column(Numeric(14, 2), nullable=False)
    review_reference = Column(String(128), nullable=False)
    __table_args__ = (
        UniqueConstraint("charge_id", name="uq_claim_charge_once"),
        CheckConstraint("requested_amount > 0 AND requested_amount <= billed_amount", name="ck_claim_line_amount"),
    )


class InsuranceClaimLineAmendment(InsuranceBase):
    __tablename__ = "insurance_claim_line_amendments"
    id = Column(Integer, primary_key=True)
    claim_id = ref("insurance_claims.id")
    charge_id = ref("billing_charges.id")
    claim_version = Column(Integer, nullable=False)
    from_amount = Column(Numeric(14, 2), nullable=False)
    to_amount = Column(Numeric(14, 2), nullable=False)
    from_review_reference = Column(String(128), nullable=False)
    to_review_reference = Column(String(128), nullable=False)
    reason = Column(Text, nullable=False)
    actor_user_id = ref("users.id")
    amended_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("claim_id", "charge_id", "claim_version", name="uq_claim_line_amendment_version"),
        CheckConstraint("from_amount > 0 AND to_amount > 0 AND claim_version > 1", name="ck_claim_amendment_amounts"),
    )


class InsuranceClaimEvent(InsuranceBase):
    __tablename__ = "insurance_claim_events"
    id = Column(Integer, primary_key=True)
    claim_id = ref("insurance_claims.id")
    sequence = Column(Integer, nullable=False)
    action = Column(String(32), nullable=False)
    from_status = Column(String(24))
    to_status = Column(String(24), nullable=False)
    actor_user_id = ref("users.id")
    source = Column(String(24), nullable=False)
    source_reference = Column(String(128))
    reason = Column(Text)
    requested_total = Column(Numeric(14, 2), nullable=False)
    approved_amount = Column(Numeric(14, 2))
    denied_amount = Column(Numeric(14, 2))
    insurer_reference = Column(String(128))
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint("claim_id", "sequence", name="uq_claim_event_sequence"),)


class InsuranceRemittance(InsuranceBase):
    __tablename__ = "insurance_remittances"
    id = Column(Integer, primary_key=True)
    claim_id = ref("insurance_claims.id")
    billing_payment_id = ref("billing_payments.id")
    amount = Column(Numeric(14, 2), nullable=False)
    source = Column(String(24), nullable=False, server_default=text("'MANUAL_RECONCILIATION'"))
    source_reference = Column(String(128), nullable=False)
    reconciled_by_user_id = ref("users.id")
    reconciled_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("billing_payment_id", name="uq_insurer_remittance_payment"),
        CheckConstraint("amount > 0", name="ck_remittance_amount"),
        CheckConstraint("source = 'MANUAL_RECONCILIATION'", name="ck_remittance_source"),
    )
