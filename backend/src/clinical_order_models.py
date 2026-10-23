"""Clinical order and departmental workflow schema contracts.

The additive module revision and guarded fresh bootstrap install these tables.
The registry remains separate from the historical core model registry.
"""

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func


class ClinicalOrderBase(DeclarativeBase):
    """Separate registry combined by migration and bootstrap tooling."""


def reference(target, nullable=False, **kwargs):
    return Column(Integer, ForeignKey(target, ondelete="RESTRICT"), nullable=nullable, index=True, **kwargs)


class ClinicalOrder(ClinicalOrderBase):
    __tablename__ = "clinical_orders"

    id = Column(Integer, primary_key=True)
    patient_id = reference("users.id")
    encounter_id = reference("encounters.id")
    requested_by_user_id = reference("users.id")
    requested_by_doctor_id = reference("doctors.id")
    destination_department_id = reference("departments.id")
    order_type = Column(String(24), nullable=False)
    priority = Column(String(16), nullable=False, server_default=text("'ROUTINE'"))
    order_code = Column(String(64))
    display_name = Column(String(255), nullable=False)
    clinical_indication = Column(Text)
    status = Column(String(24), nullable=False, server_default=text("'DRAFT'"))
    version = Column(Integer, nullable=False, server_default=text("1"))
    cancellation_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    signed_at = Column(DateTime(timezone=True))
    accepted_at = Column(DateTime(timezone=True))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    cancelled_at = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("order_type IN ('LAB','IMAGING','MEDICATION','PROCEDURE','OTHER')", name="ck_clinical_order_type"),
        CheckConstraint("priority IN ('ROUTINE','URGENT','STAT')", name="ck_clinical_order_priority"),
        CheckConstraint("status IN ('DRAFT','SIGNED','ACCEPTED','IN_PROGRESS','COMPLETED','CANCELLED')", name="ck_clinical_order_status"),
        CheckConstraint("version > 0", name="ck_clinical_order_version"),
        CheckConstraint("length(btrim(display_name)) > 0", name="ck_clinical_order_display_name"),
        CheckConstraint("status NOT IN ('SIGNED','ACCEPTED','IN_PROGRESS','COMPLETED') OR signed_at IS NOT NULL", name="ck_clinical_order_signed"),
        CheckConstraint("status NOT IN ('ACCEPTED','IN_PROGRESS','COMPLETED') OR accepted_at IS NOT NULL", name="ck_clinical_order_accepted"),
        CheckConstraint("status NOT IN ('IN_PROGRESS','COMPLETED') OR started_at IS NOT NULL", name="ck_clinical_order_started"),
        CheckConstraint("(status = 'COMPLETED') = (completed_at IS NOT NULL)", name="ck_clinical_order_completed"),
        CheckConstraint("(status = 'CANCELLED') = (cancelled_at IS NOT NULL)", name="ck_clinical_order_cancelled"),
        CheckConstraint("status <> 'CANCELLED' OR cancellation_reason IS NOT NULL AND length(btrim(cancellation_reason)) > 0", name="ck_clinical_order_cancel_reason"),
        Index("ix_clinical_order_patient_created", "patient_id", "created_at"),
        Index("ix_clinical_order_department_status", "destination_department_id", "status"),
        Index("ix_clinical_order_encounter_created", "encounter_id", "created_at"),
    )


class ClinicalOrderEvent(ClinicalOrderBase):
    __tablename__ = "clinical_order_events"

    id = Column(Integer, primary_key=True)
    order_id = reference("clinical_orders.id")
    sequence = Column(Integer, nullable=False)
    order_version = Column(Integer, nullable=False)
    from_status = Column(String(24))
    to_status = Column(String(24), nullable=False)
    actor_user_id = reference("users.id")
    actor_doctor_id = reference("doctors.id", nullable=True)
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("order_id", "sequence", name="uq_clinical_order_event_sequence"),
        UniqueConstraint("order_id", "order_version", name="uq_clinical_order_event_version"),
        CheckConstraint("sequence > 0 AND order_version > 0", name="ck_clinical_order_event_numbers"),
        CheckConstraint("to_status IN ('DRAFT','SIGNED','ACCEPTED','IN_PROGRESS','COMPLETED','CANCELLED')", name="ck_clinical_order_event_target"),
        Index("ix_clinical_order_event_order_created", "order_id", "created_at"),
    )


class MedicationOrderDetail(ClinicalOrderBase):
    """Structured prescription data; fulfillment remains a separate workflow."""

    __tablename__ = "medication_order_details"

    id = Column(Integer, primary_key=True)
    order_id = reference("clinical_orders.id", unique=True)
    medication_identifier_system = Column(String(64), nullable=False, server_default=text("'LOCAL'"))
    medication_identifier = Column(String(128), nullable=False)
    medication_display_name = Column(String(255), nullable=False)
    dose = Column(Numeric(12, 4), nullable=False)
    dose_unit = Column(String(32), nullable=False)
    route = Column(String(64), nullable=False)
    frequency = Column(String(128), nullable=False)
    duration_value = Column(Integer)
    duration_unit = Column(String(16))
    quantity = Column(Numeric(12, 3), nullable=False)
    quantity_unit = Column(String(64), nullable=False)
    start_date = Column(Date, nullable=False)
    instructions = Column(Text)
    allergy_review_id = reference("encounter_allergy_reviews.id")
    allergy_warning_snapshot = Column(JSON, nullable=False, server_default=text("'[]'::jsonb"))
    allergy_acknowledged_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("dose > 0", name="ck_medication_order_dose_positive"),
        CheckConstraint("quantity > 0", name="ck_medication_order_quantity_positive"),
        CheckConstraint("duration_value IS NULL OR duration_value > 0", name="ck_medication_order_duration_positive"),
        CheckConstraint(
            "(duration_value IS NULL) = (duration_unit IS NULL)",
            name="ck_medication_order_duration_pair",
        ),
        CheckConstraint(
            "duration_unit IS NULL OR duration_unit IN ('DAYS','WEEKS','MONTHS','DOSES')",
            name="ck_medication_order_duration_unit",
        ),
        CheckConstraint("length(btrim(medication_identifier)) > 0", name="ck_medication_order_identifier"),
        CheckConstraint("length(btrim(medication_display_name)) > 0", name="ck_medication_order_display_name"),
        CheckConstraint("length(btrim(dose_unit)) > 0", name="ck_medication_order_dose_unit"),
        CheckConstraint("length(btrim(route)) > 0", name="ck_medication_order_route"),
        CheckConstraint("length(btrim(frequency)) > 0", name="ck_medication_order_frequency"),
        CheckConstraint("length(btrim(quantity_unit)) > 0", name="ck_medication_order_quantity_unit"),
        Index("ix_medication_order_start_date", "start_date"),
    )


class PharmacyStaffAssignment(ClinicalOrderBase):
    __tablename__ = "pharmacy_staff_assignments"

    id = Column(Integer, primary_key=True)
    user_id = reference("users.id")
    department_id = reference("departments.id")
    assignment_role = Column(String(24), nullable=False, server_default=text("'PHARMACY_STAFF'"))
    is_active = Column(Integer, nullable=False, server_default=text("1"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "department_id", name="uq_pharmacy_staff_user_department"),
        CheckConstraint("assignment_role IN ('PHARMACY_STAFF','PHARMACY_MANAGER')", name="ck_pharmacy_staff_role"),
        CheckConstraint("is_active IN (0,1)", name="ck_pharmacy_staff_active"),
    )


class PharmacyDispenseWorkflow(ClinicalOrderBase):
    __tablename__ = "pharmacy_dispense_workflows"

    id = Column(Integer, primary_key=True)
    order_id = reference("clinical_orders.id", unique=True)
    pharmacy_department_id = reference("departments.id")
    status = Column(String(32), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    last_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('ACCEPTED','CLARIFICATION_REQUESTED','REJECTED','IN_PROGRESS','PARTIALLY_DISPENSED','COMPLETED')",
            name="ck_pharmacy_workflow_status",
        ),
        CheckConstraint("version > 0", name="ck_pharmacy_workflow_version"),
        CheckConstraint(
            "status NOT IN ('CLARIFICATION_REQUESTED','REJECTED') OR last_reason IS NOT NULL AND length(btrim(last_reason)) > 0",
            name="ck_pharmacy_workflow_reason",
        ),
        Index("ix_pharmacy_workflow_department_status", "pharmacy_department_id", "status"),
    )


class PharmacyDispenseEvent(ClinicalOrderBase):
    __tablename__ = "pharmacy_dispense_events"

    id = Column(Integer, primary_key=True)
    workflow_id = reference("pharmacy_dispense_workflows.id")
    sequence = Column(Integer, nullable=False)
    workflow_version = Column(Integer, nullable=False)
    from_status = Column(String(32), nullable=False)
    to_status = Column(String(32), nullable=False)
    actor_user_id = reference("users.id")
    actor_assignment_id = reference("pharmacy_staff_assignments.id")
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("workflow_id", "sequence", name="uq_pharmacy_event_sequence"),
        UniqueConstraint("workflow_id", "workflow_version", name="uq_pharmacy_event_version"),
        CheckConstraint("sequence > 0 AND workflow_version > 0", name="ck_pharmacy_event_numbers"),
    )


class PharmacyDispenseRecord(ClinicalOrderBase):
    __tablename__ = "pharmacy_dispense_records"

    id = Column(Integer, primary_key=True)
    workflow_id = reference("pharmacy_dispense_workflows.id")
    event_id = reference("pharmacy_dispense_events.id", unique=True)
    quantity = Column(Numeric(12, 3), nullable=False)
    quantity_unit = Column(String(64), nullable=False)
    inventory_transaction_reference = Column(String(255), nullable=False, unique=True)
    dispensed_by_user_id = reference("users.id")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_pharmacy_dispense_quantity"),
        CheckConstraint("length(btrim(quantity_unit)) > 0", name="ck_pharmacy_dispense_unit"),
        CheckConstraint("length(btrim(inventory_transaction_reference)) > 0", name="ck_pharmacy_inventory_reference"),
        Index("ix_pharmacy_dispense_workflow_created", "workflow_id", "created_at"),
    )


class LaboratoryStaffAssignment(ClinicalOrderBase):
    __tablename__ = "laboratory_staff_assignments"

    id = Column(Integer, primary_key=True)
    user_id = reference("users.id")
    department_id = reference("departments.id")
    assignment_role = Column(String(24), nullable=False, server_default=text("'LAB_STAFF'"))
    is_active = Column(Integer, nullable=False, server_default=text("1"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "department_id", name="uq_lab_staff_user_department"),
        CheckConstraint("assignment_role IN ('LAB_STAFF','LAB_VERIFIER','LAB_MANAGER')", name="ck_lab_staff_role"),
        CheckConstraint("is_active IN (0,1)", name="ck_lab_staff_active"),
    )


class LaboratoryOrderWorkflow(ClinicalOrderBase):
    __tablename__ = "laboratory_order_workflows"

    id = Column(Integer, primary_key=True)
    order_id = reference("clinical_orders.id", unique=True)
    laboratory_department_id = reference("departments.id")
    status = Column(String(32), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    last_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('ACCEPTED','CLARIFICATION_REQUESTED','REJECTED','COLLECTION_PENDING','COLLECTED','RECEIVED','SPECIMEN_REJECTED','PROCESSING','RESULT_DRAFTED','RESULT_REJECTED','RESULT_VERIFIED','FINALIZED')",
            name="ck_lab_workflow_status",
        ),
        CheckConstraint("version > 0", name="ck_lab_workflow_version"),
        CheckConstraint(
            "status NOT IN ('CLARIFICATION_REQUESTED','REJECTED','SPECIMEN_REJECTED') OR last_reason IS NOT NULL AND length(btrim(last_reason)) > 0",
            name="ck_lab_workflow_reason",
        ),
        Index("ix_lab_workflow_department_status", "laboratory_department_id", "status"),
    )


class LaboratoryWorkflowEvent(ClinicalOrderBase):
    __tablename__ = "laboratory_workflow_events"

    id = Column(Integer, primary_key=True)
    workflow_id = reference("laboratory_order_workflows.id")
    sequence = Column(Integer, nullable=False)
    workflow_version = Column(Integer, nullable=False)
    from_status = Column(String(32), nullable=False)
    to_status = Column(String(32), nullable=False)
    actor_user_id = reference("users.id")
    actor_assignment_id = reference("laboratory_staff_assignments.id")
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("workflow_id", "sequence", name="uq_lab_workflow_event_sequence"),
        UniqueConstraint("workflow_id", "workflow_version", name="uq_lab_workflow_event_version"),
        CheckConstraint("sequence > 0 AND workflow_version > 0", name="ck_lab_workflow_event_numbers"),
    )


class LaboratorySpecimen(ClinicalOrderBase):
    __tablename__ = "laboratory_specimens"

    id = Column(Integer, primary_key=True)
    workflow_id = reference("laboratory_order_workflows.id")
    order_id = reference("clinical_orders.id")
    patient_id = reference("users.id")
    encounter_id = reference("encounters.id")
    specimen_identifier = Column(String(128), nullable=False, unique=True)
    specimen_type = Column(String(128), nullable=False)
    status = Column(String(24), nullable=False, server_default=text("'COLLECTED'"))
    version = Column(Integer, nullable=False, server_default=text("1"))
    collected_by_user_id = reference("users.id")
    collected_at = Column(DateTime(timezone=True), nullable=False)
    received_by_user_id = reference("users.id", nullable=True)
    received_at = Column(DateTime(timezone=True))
    rejection_reason = Column(Text)
    recollection_requested = Column(Integer, nullable=False, server_default=text("0"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('COLLECTED','RECEIVED','REJECTED')", name="ck_lab_specimen_status"),
        CheckConstraint("version > 0", name="ck_lab_specimen_version"),
        CheckConstraint("status <> 'REJECTED' OR rejection_reason IS NOT NULL AND length(btrim(rejection_reason)) > 0", name="ck_lab_specimen_rejection"),
        CheckConstraint("recollection_requested IN (0,1)", name="ck_lab_specimen_recollection"),
        Index("ix_lab_specimen_order_created", "order_id", "created_at"),
    )


class LaboratorySpecimenEvent(ClinicalOrderBase):
    __tablename__ = "laboratory_specimen_events"

    id = Column(Integer, primary_key=True)
    specimen_id = reference("laboratory_specimens.id")
    sequence = Column(Integer, nullable=False)
    from_status = Column(String(24))
    to_status = Column(String(24), nullable=False)
    actor_user_id = reference("users.id")
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("specimen_id", "sequence", name="uq_lab_specimen_event_sequence"),)


class LaboratoryResultRevision(ClinicalOrderBase):
    __tablename__ = "laboratory_result_revisions"

    id = Column(Integer, primary_key=True)
    workflow_id = reference("laboratory_order_workflows.id")
    order_id = reference("clinical_orders.id")
    specimen_id = reference("laboratory_specimens.id")
    test_identifier = Column(String(128), nullable=False)
    test_name = Column(String(255), nullable=False)
    revision_number = Column(Integer, nullable=False)
    previous_revision_id = reference("laboratory_result_revisions.id", nullable=True)
    result_value = Column(String(255), nullable=False)
    result_unit = Column(String(64))
    reference_range_text = Column(String(255))
    reference_range_source = Column(String(255))
    abnormality_flag = Column(String(24), nullable=False, server_default=text("'NOT_ASSESSED'"))
    status = Column(String(16), nullable=False, server_default=text("'DRAFT'"))
    version = Column(Integer, nullable=False, server_default=text("1"))
    correction_reason = Column(Text)
    entered_by_user_id = reference("users.id")
    verified_by_user_id = reference("users.id", nullable=True)
    finalized_by_user_id = reference("users.id", nullable=True)
    entered_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    verified_at = Column(DateTime(timezone=True))
    finalized_at = Column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("order_id", "test_identifier", "revision_number", name="uq_lab_result_test_revision"),
        CheckConstraint("revision_number > 0 AND version > 0", name="ck_lab_result_versions"),
        CheckConstraint("status IN ('DRAFT','REJECTED','VERIFIED','FINALIZED')", name="ck_lab_result_status"),
        CheckConstraint("abnormality_flag IN ('LOW','NORMAL','HIGH','ABNORMAL','NOT_ASSESSED')", name="ck_lab_result_abnormality"),
        CheckConstraint("revision_number = 1 OR correction_reason IS NOT NULL AND length(btrim(correction_reason)) > 0", name="ck_lab_result_correction_reason"),
        Index("ix_lab_result_order_status", "order_id", "status"),
    )


class LaboratoryResultEvent(ClinicalOrderBase):
    __tablename__ = "laboratory_result_events"

    id = Column(Integer, primary_key=True)
    result_revision_id = reference("laboratory_result_revisions.id")
    sequence = Column(Integer, nullable=False)
    result_version = Column(Integer, nullable=False)
    from_status = Column(String(16))
    to_status = Column(String(16), nullable=False)
    actor_user_id = reference("users.id")
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("result_revision_id", "sequence", name="uq_lab_result_event_sequence"),
        UniqueConstraint("result_revision_id", "result_version", name="uq_lab_result_event_version"),
    )


class ImagingOrderDetail(ClinicalOrderBase):
    __tablename__ = "imaging_order_details"
    id = Column(Integer, primary_key=True)
    order_id = reference("clinical_orders.id", unique=True)
    modality = Column(String(32), nullable=False)
    body_region = Column(String(128), nullable=False)
    requested_procedure = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("length(btrim(modality)) > 0", name="ck_imaging_modality"),
        CheckConstraint("length(btrim(body_region)) > 0", name="ck_imaging_body_region"),
    )


class RadiologyStaffAssignment(ClinicalOrderBase):
    __tablename__ = "radiology_staff_assignments"
    id = Column(Integer, primary_key=True)
    user_id = reference("users.id")
    department_id = reference("departments.id")
    assignment_role = Column(String(24), nullable=False, server_default=text("'RAD_STAFF'"))
    is_active = Column(Integer, nullable=False, server_default=text("1"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("user_id", "department_id", name="uq_radiology_staff_user_department"),
        CheckConstraint("assignment_role IN ('RAD_STAFF','RADIOLOGIST','RAD_MANAGER')", name="ck_radiology_staff_role"),
        CheckConstraint("is_active IN (0,1)", name="ck_radiology_staff_active"),
    )


class RadiologyWorkflow(ClinicalOrderBase):
    __tablename__ = "radiology_workflows"
    id = Column(Integer, primary_key=True)
    order_id = reference("clinical_orders.id", unique=True)
    department_id = reference("departments.id")
    status = Column(String(40), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    scheduled_at = Column(DateTime(timezone=True))
    last_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        CheckConstraint("status IN ('ACCEPTED','CLARIFICATION_REQUESTED','REJECTED','SCHEDULED','READY_FOR_IMAGING','ACQUISITION_IN_PROGRESS','ACQUISITION_COMPLETED','INTERPRETATION_IN_PROGRESS','REPORT_DRAFT','REPORT_VERIFIED','REPORT_FINALIZED','CANCELLED')", name="ck_radiology_workflow_status"),
        CheckConstraint("version > 0", name="ck_radiology_workflow_version"),
        CheckConstraint("status NOT IN ('CLARIFICATION_REQUESTED','REJECTED','CANCELLED') OR last_reason IS NOT NULL AND length(btrim(last_reason)) > 0", name="ck_radiology_workflow_reason"),
        Index("ix_radiology_workflow_department_status", "department_id", "status"),
    )


class RadiologyWorkflowEvent(ClinicalOrderBase):
    __tablename__ = "radiology_workflow_events"
    id = Column(Integer, primary_key=True)
    workflow_id = reference("radiology_workflows.id")
    sequence = Column(Integer, nullable=False)
    workflow_version = Column(Integer, nullable=False)
    from_status = Column(String(40), nullable=False)
    to_status = Column(String(40), nullable=False)
    actor_user_id = reference("users.id")
    actor_assignment_id = reference("radiology_staff_assignments.id")
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("workflow_id", "sequence", name="uq_radiology_event_sequence"),
        UniqueConstraint("workflow_id", "workflow_version", name="uq_radiology_event_version"),
    )


class ImagingStudy(ClinicalOrderBase):
    __tablename__ = "imaging_studies"
    id = Column(Integer, primary_key=True)
    workflow_id = reference("radiology_workflows.id", unique=True)
    order_id = reference("clinical_orders.id", unique=True)
    patient_id = reference("users.id")
    encounter_id = reference("encounters.id")
    study_identifier = Column(String(128), nullable=False, unique=True)
    modality = Column(String(32), nullable=False)
    body_region = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    acquisition_started_at = Column(DateTime(timezone=True))
    acquisition_completed_at = Column(DateTime(timezone=True))
    acquired_by_user_id = reference("users.id")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("status IN ('ACQUISITION_IN_PROGRESS','ACQUISITION_COMPLETED')", name="ck_imaging_study_status"),
        CheckConstraint("version > 0", name="ck_imaging_study_version"),
    )


class RadiologyReportRevision(ClinicalOrderBase):
    __tablename__ = "radiology_report_revisions"
    id = Column(Integer, primary_key=True)
    workflow_id = reference("radiology_workflows.id")
    study_id = reference("imaging_studies.id")
    order_id = reference("clinical_orders.id")
    revision_number = Column(Integer, nullable=False)
    previous_revision_id = reference("radiology_report_revisions.id", nullable=True)
    findings = Column(Text, nullable=False)
    impression = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, server_default=text("'DRAFT'"))
    version = Column(Integer, nullable=False, server_default=text("1"))
    amendment_reason = Column(Text)
    authored_by_user_id = reference("users.id")
    verified_by_user_id = reference("users.id", nullable=True)
    finalized_by_user_id = reference("users.id", nullable=True)
    authored_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    verified_at = Column(DateTime(timezone=True))
    finalized_at = Column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("order_id", "revision_number", name="uq_radiology_report_revision"),
        CheckConstraint("revision_number > 0 AND version > 0", name="ck_radiology_report_versions"),
        CheckConstraint("status IN ('DRAFT','VERIFIED','FINALIZED','REJECTED')", name="ck_radiology_report_status"),
        CheckConstraint("revision_number = 1 OR amendment_reason IS NOT NULL AND length(btrim(amendment_reason)) > 0", name="ck_radiology_amendment_reason"),
    )


class RadiologyReportEvent(ClinicalOrderBase):
    __tablename__ = "radiology_report_events"
    id = Column(Integer, primary_key=True)
    report_revision_id = reference("radiology_report_revisions.id")
    sequence = Column(Integer, nullable=False)
    report_version = Column(Integer, nullable=False)
    from_status = Column(String(16))
    to_status = Column(String(16), nullable=False)
    actor_user_id = reference("users.id")
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("report_revision_id", "sequence", name="uq_radiology_report_event_sequence"),
        UniqueConstraint("report_revision_id", "report_version", name="uq_radiology_report_event_version"),
    )
