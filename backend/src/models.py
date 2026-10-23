from sqlalchemy import Column, Integer, String, Float, JSON, DateTime, ForeignKey, Enum, Text, Boolean, Date, text, Index, CheckConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import datetime

from src.model_base import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=True)
    mobile_no = Column(String(20), nullable=True)
    blood_group = Column(String(5), nullable=True)
    password_hash = Column(String(255), nullable=True)
    full_name = Column(String(255), nullable=False)
    mrn = Column(String(32), nullable=True)
    date_of_birth = Column(Date, nullable=True)
    role = Column(Enum('user', 'admin', 'patient', 'doctor', 'department_admin', 'hospital_admin', 'emergency_doctor', name='user_role_enum'), default='patient')
    email_verified = Column(Integer, default=1)
    mobile_verified = Column(Integer, default=1)
    profile_data = Column(JSON, nullable=True, default={}, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "password_hash IS NULL OR (email IS NOT NULL AND mobile_no IS NOT NULL)",
            name="ck_users_credentialed_accounts_have_contacts",
        ),
        Index("uq_users_credentialed_email_normalized", text("lower(btrim(email))"), unique=True,
              postgresql_where=text("password_hash IS NOT NULL AND email IS NOT NULL")),
        Index("uq_users_credentialed_mobile_normalized",
              text("regexp_replace(mobile_no, '[^0-9]', '', 'g')"), unique=True,
              postgresql_where=text("password_hash IS NOT NULL AND mobile_no IS NOT NULL")),
        Index("uq_users_mrn", "mrn", unique=True),
    )

    patient_reports = relationship("PatientReport", back_populates="user")
    cbc_reports = relationship("CbcReport", back_populates="user")
    heart_reports = relationship("HeartReport", back_populates="user")
    hypertension_reports = relationship("HypertensionReport", back_populates="user")
    doctor_profile = relationship("Doctor", back_populates="user", uselist=False)

class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    code = Column(String(32), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    head_doctor_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    doctors = relationship("Doctor", back_populates="department")

class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    specialization = Column(String(150), nullable=False)
    qualification = Column(String(150), nullable=False)
    license_number = Column(String(64), nullable=True)
    experience_years = Column(Integer, default=0)
    availability = Column(JSON, nullable=True)
    status = Column(Enum('Active', 'OnLeave', 'Inactive', name='doctor_status_enum'), default='Active')
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="doctor_profile")
    department = relationship("Department", back_populates="doctors")
    appointments = relationship("Appointment", back_populates="doctor")

class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    appointment_date = Column(DateTime, nullable=False)
    time_slot = Column(String(32), nullable=True)
    status = Column(Enum('REQUESTED', 'CONFIRMED', 'REJECTED', 'CANCELLED', 'COMPLETED', 'NO_SHOW', name='appointment_status_enum'), default='REQUESTED')
    reason = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    doctor = relationship("Doctor", back_populates="appointments")

class MedicalReport(Base):
    __tablename__ = "medical_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    report_source = Column(Enum('hospital', 'existing_upload', name='report_source_enum'), default='existing_upload')
    report_title = Column(String(255), nullable=False)
    report_type = Column(String(100), nullable=True)
    report_date = Column(DateTime, server_default=func.now())
    status = Column(Enum('UPLOADED', 'OCR_EXTRACTED', 'VALIDATED', 'AI_PRE_ANALYZED', 'DOCTOR_REVIEWED', 'FINALIZED', name='medical_report_status_enum'), default='UPLOADED')
    original_filename = Column(String(255), nullable=True)
    file_path = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    extractions = relationship("ReportExtraction", back_populates="report", uselist=False)
    ai_analysis = relationship("AIAnalysis", back_populates="report", uselist=False)
    doctor_review = relationship("DoctorReview", back_populates="report", uselist=False)

class ReportExtraction(Base):
    __tablename__ = "report_extractions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("medical_reports.id", ondelete="CASCADE"), nullable=False, unique=True)
    ocr_raw_text = Column(Text, nullable=True)
    extracted_json = Column(JSON, nullable=True)
    validation_status = Column(Enum('VALID', 'NEEDS_REVIEW', 'FAILED', name='extraction_validation_status_enum'), default='VALID')
    confidence_score = Column(Float, default=1.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    report = relationship("MedicalReport", back_populates="extractions")

class AIAnalysis(Base):
    __tablename__ = "ai_analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("medical_reports.id", ondelete="CASCADE"), nullable=False, unique=True)
    department_slug = Column(String(64), nullable=True)
    model_name = Column(String(100), nullable=False)
    model_version = Column(String(32), default="1.0")
    prediction = Column(String(100), nullable=False)
    probability = Column(Float, nullable=True)
    risk_level = Column(Enum('LOW', 'MODERATE', 'HIGH', 'CRITICAL', name='ai_risk_level_enum'), default='LOW')
    important_factors = Column(JSON, nullable=True)
    explanation = Column(Text, nullable=True)
    requires_doctor_review = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    report = relationship("MedicalReport", back_populates="ai_analysis")

class DoctorReview(Base):
    __tablename__ = "doctor_reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("medical_reports.id", ondelete="CASCADE"), nullable=False, unique=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    review_status = Column(Enum('APPROVED', 'MODIFIED', 'REJECTED', name='review_status_enum'), default='APPROVED')
    clinical_notes = Column(Text, nullable=True)
    final_assessment = Column(Text, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), server_default=func.now())

    report = relationship("MedicalReport", back_populates="doctor_review")


class MedicalReviewRevision(Base):
    """Signed, append-only amendment; DoctorReview remains the original review."""
    __tablename__ = "medical_review_revisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("medical_reports.id", ondelete="RESTRICT"), nullable=False)
    original_review_id = Column(Integer, ForeignKey("doctor_reviews.id", ondelete="RESTRICT"), nullable=False)
    revision_number = Column(Integer, nullable=False)
    previous_revision_id = Column(Integer, ForeignKey("medical_review_revisions.id", ondelete="RESTRICT"), nullable=True)
    author_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    author_doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="RESTRICT"), nullable=False)
    review_status = Column(Enum('APPROVED', 'MODIFIED', 'REJECTED', name='review_status_enum'), nullable=False)
    clinical_notes = Column(Text, nullable=True)
    final_assessment = Column(Text, nullable=True)
    corrected_parameters = Column(JSON, nullable=True)
    amendment_reason = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    signed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("revision_number >= 2", name="ck_medical_review_revision_number"),
        CheckConstraint("length(btrim(amendment_reason)) > 0", name="ck_medical_review_revision_reason"),
        CheckConstraint("(revision_number = 2 AND previous_revision_id IS NULL) OR "
                        "(revision_number > 2 AND previous_revision_id IS NOT NULL)",
                        name="ck_medical_review_revision_predecessor"),
        Index("uq_medical_review_revision_number", "report_id", "revision_number", unique=True),
        Index("uq_medical_review_revision_previous", "previous_revision_id", unique=True),
        Index("ix_medical_review_revisions_original_review_id", "original_review_id"),
        Index("ix_medical_review_revisions_author_user_id", "author_user_id"),
        Index("ix_medical_review_revisions_author_doctor_id", "author_doctor_id"),
    )

class MedicalRecord(Base):
    __tablename__ = "medical_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    summary = Column(Text, nullable=True)
    medical_history_json = Column(JSON, nullable=True)
    allergies = Column(Text, nullable=True)
    current_medications = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class EmergencyRequest(Base):
    __tablename__ = "emergency_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    severity = Column(Enum('LOW', 'MEDIUM', 'HIGH', 'CRITICAL', name='emergency_severity_enum'), default='HIGH')
    status = Column(Enum('REQUESTED', 'ACKNOWLEDGED', 'ASSIGNED', 'IN_REVIEW', 'IN_TREATMENT', 'RESOLVED', 'CANCELLED', name='emergency_status_enum'), default='REQUESTED')
    symptoms = Column(Text, nullable=True)
    location = Column(String(255), nullable=True)
    contact_phone = Column(String(32), nullable=True)
    assigned_doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime, nullable=True)

class PatientDoctorMessage(Base):
    __tablename__ = "patient_doctor_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="CASCADE"), nullable=True)
    patient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    type = Column(String(64), default="INFO")
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class PatientReport(Base):
    __tablename__ = "patient_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    glucose = Column(Float(precision=2), nullable=True)
    blood_pressure = Column(Float(precision=2), nullable=True)
    skin_thickness = Column(Float(precision=2), nullable=True)
    insulin = Column(Float(precision=2), nullable=True)
    bmi = Column(Float(precision=2), nullable=True)
    diabetes_pedigree_function = Column(Float(precision=4), nullable=True)
    age = Column(Integer, nullable=True)
    
    diabetes_prediction = Column(String(64), nullable=True)
    hypertension_prediction = Column(String(64), nullable=True)
    heart_disease_prediction = Column(String(64), nullable=True)
    risk_level = Column(String(64), nullable=True)
    probability = Column(Float, nullable=True)
    
    abnormal_count = Column(Integer, nullable=True)
    abnormal_json = Column(JSON, nullable=True)
    conditions_json = Column(JSON, nullable=True)
    specialists_json = Column(JSON, nullable=True)
    source = Column(String(32), nullable=True)

    user = relationship("User", back_populates="patient_reports")

class CbcReport(Base):
    __tablename__ = "cbc_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    cbc_json = Column(JSON, nullable=True)
    interpretation_json = Column(JSON, nullable=True)
    probability = Column(Float, nullable=True)
    source = Column(String(32), nullable=True)

    user = relationship("User", back_populates="cbc_reports")

class HeartReport(Base):
    __tablename__ = "heart_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    age = Column(Integer, nullable=True)
    sex = Column(Integer, nullable=True)
    cp = Column(Integer, nullable=True)
    trestbps = Column(Integer, nullable=True)
    chol = Column(Integer, nullable=True)
    fbs = Column(Integer, nullable=True)
    restecg = Column(Integer, nullable=True)
    thalach = Column(Integer, nullable=True)
    exang = Column(Integer, nullable=True)
    oldpeak = Column(Float, nullable=True)
    slope = Column(Integer, nullable=True)
    ca = Column(Integer, nullable=True)
    thal = Column(Integer, nullable=True)

    prediction = Column(String(64), nullable=True)
    probability = Column(Float, nullable=True)

    user = relationship("User", back_populates="heart_reports")

class HypertensionReport(Base):
    __tablename__ = "hypertension_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    age = Column(Integer, nullable=True)
    sex = Column(Integer, nullable=True)
    bmi = Column(Float, nullable=True)
    heart_rate = Column(Integer, nullable=True)
    activity_level = Column(Integer, nullable=True)
    smoker = Column(Integer, nullable=True)
    family_history = Column(Integer, nullable=True)

    prediction = Column(String(64), nullable=True)
    probability = Column(Float, nullable=True)

    user = relationship("User", back_populates="hypertension_reports")

class VerificationCode(Base):
    __tablename__ = "verification_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_type = Column(Enum('email', 'mobile', name='verification_target_enum'), nullable=False)
    target_value = Column(String(255), nullable=False)
    code = Column(String(6), nullable=False)
    is_verified = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ModelRegistry(Base):
    __tablename__ = "model_registry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String(64), unique=True, nullable=False)
    version = Column(String(32), nullable=False, default="1.0.0")
    algorithm = Column(String(64), nullable=False)
    accuracy = Column(Float, nullable=True)
    precision = Column(Float, nullable=True)
    recall = Column(Float, nullable=True)
    f1_score = Column(Float, nullable=True)
    auc_roc = Column(Float, nullable=True)
    status = Column(Enum('Active', 'Training', 'Deprecated', 'Idle', name='model_status_enum'), default='Active')
    inference_count = Column(Integer, default=0)
    last_trained = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(255), nullable=False)
    details = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    status = Column(String(32), default="Success")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), default="New Health Conversation")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False)
    sender = Column(Enum('user', 'assistant', name='chat_sender_enum'), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class PasswordResetOTP(Base):
    __tablename__ = "password_reset_otp"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), index=True, nullable=False)
    otp = Column(String(255), nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    verified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)

# ==========================================
# New Clinical Chat Subsystem Models
# ==========================================

class ClinicalConversation(Base):
    __tablename__ = "clinical_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), default="Clinical Conversation")
    status = Column(
        Enum('OPEN', 'AWAITING_DOCTOR', 'DOCTOR_RESPONDED', 'ESCALATED', 'RESOLVED', name='clinical_conversation_status_enum'),
        default='OPEN',
        index=True
    )
    urgency = Column(
        Enum('NORMAL', 'LOW_PRIORITY', 'MODERATE', 'HIGH_PRIORITY', 'EMERGENCY_REVIEW', name='clinical_urgency_enum'),
        default='NORMAL',
        index=True
    )
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True, index=True)
    escalation_status = Column(
        Enum('NONE', 'PENDING_ACK', 'ACKNOWLEDGED', 'RESOLVED', name='escalation_status_enum'),
        default='NONE',
        index=True
    )
    source_legacy_id = Column(Integer, nullable=True)
    workflow_state = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    patient = relationship("User", foreign_keys=[patient_id])
    department = relationship("Department", foreign_keys=[department_id])
    assigned_doctor = relationship("Doctor", foreign_keys=[assigned_doctor_id])

    messages = relationship("ClinicalMessage", back_populates="conversation", cascade="all, delete-orphan")
    assignments = relationship("ClinicalAssignment", back_populates="conversation", cascade="all, delete-orphan")
    alerts = relationship("ClinicalAlert", back_populates="conversation", cascade="all, delete-orphan")
    events = relationship("ClinicalEvent", back_populates="conversation", cascade="all, delete-orphan")
    ai_analyses = relationship("ClinicalAIAnalysis", back_populates="conversation", cascade="all, delete-orphan")

class ClinicalMessage(Base):
    __tablename__ = "clinical_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("clinical_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_type = Column(
        Enum('patient', 'doctor', 'assistant', 'system', name='clinical_sender_type_enum'),
        nullable=False
    )
    sender_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    body = Column(Text, nullable=False)
    redaction_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    conversation = relationship("ClinicalConversation", back_populates="messages")
    sender_user = relationship("User", foreign_keys=[sender_user_id])

class ClinicalAssignment(Base):
    __tablename__ = "clinical_assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("clinical_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reason = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())
    unassigned_at = Column(DateTime(timezone=True), nullable=True)

    conversation = relationship("ClinicalConversation", back_populates="assignments")
    department = relationship("Department")
    doctor = relationship("Doctor")
    assigned_by = relationship("User", foreign_keys=[assigned_by_user_id])

class ClinicalAlert(Base):
    __tablename__ = "clinical_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("clinical_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(
        Enum('TRIGGERED', 'ACKNOWLEDGED', 'RESOLVED', 'DISMISSED', name='clinical_alert_status_enum'),
        default='TRIGGERED',
        index=True
    )
    reason = Column(Text, nullable=False)
    urgency = Column(
        Enum('NORMAL', 'LOW_PRIORITY', 'MODERATE', 'HIGH_PRIORITY', 'EMERGENCY_REVIEW', name='clinical_urgency_enum'),
        nullable=False
    )
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True, index=True)
    dedupe_key = Column(String(100), nullable=True, index=True)
    escalated_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    conversation = relationship("ClinicalConversation", back_populates="alerts")
    department = relationship("Department")
    assigned_doctor = relationship("Doctor")
    acknowledged_by = relationship("User", foreign_keys=[acknowledged_by_user_id])

class ClinicalEvent(Base):
    __tablename__ = "clinical_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("clinical_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    event_type = Column(String(64), nullable=False, index=True)
    state_before = Column(JSON, nullable=True)
    state_after = Column(JSON, nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    conversation = relationship("ClinicalConversation", back_populates="events")
    actor = relationship("User", foreign_keys=[actor_user_id])

class ClinicalAIAnalysis(Base):
    __tablename__ = "clinical_ai_analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("clinical_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("clinical_messages.id", ondelete="SET NULL"), nullable=True)
    category = Column(String(100), nullable=True)
    confidence = Column(Float, nullable=True)
    evidence_codes = Column(JSON, nullable=True)
    model_rule_version = Column(String(64), default="1.0")
    human_review_required = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("ClinicalConversation", back_populates="ai_analyses")
    message = relationship("ClinicalMessage", foreign_keys=[message_id])

class DoctorDepartmentMembership(Base):
    __tablename__ = "doctor_department_memberships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False, index=True)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(
        Enum('MEMBER', 'RESPONDER', 'LEAD', name='doctor_dept_role_enum'),
        default='MEMBER'
    )
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    doctor = relationship("Doctor")
    department = relationship("Department")

class ClinicalRoutingRule(Base):
    __tablename__ = "clinical_routing_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category_or_indicator = Column(String(100), nullable=False, index=True)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True)
    priority = Column(
        Enum('NORMAL', 'LOW_PRIORITY', 'MODERATE', 'HIGH_PRIORITY', 'EMERGENCY_REVIEW', name='clinical_urgency_enum'),
        default='NORMAL'
    )
    is_enabled = Column(Boolean, default=True, index=True)
    version = Column(String(32), default="1.0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    department = relationship("Department")

class ReportReviewRequest(Base):
    __tablename__ = "report_review_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("medical_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(
        Enum('PENDING', 'IN_REVIEW', 'COMPLETED', 'CANCELLED', name='report_review_request_status_enum'),
        default='PENDING',
        nullable=False,
        server_default=text("'PENDING'::report_review_request_status_enum"),
        index=True
    )
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    report = relationship("MedicalReport", foreign_keys=[report_id])
    patient = relationship("User", foreign_keys=[patient_id])
    doctor = relationship("Doctor", foreign_keys=[doctor_id])


# Register additive encounter tables in the same metadata used by fresh bootstrap.
from src.encounter_models import (  # noqa: E402,F401
    Encounter, EncounterNote, EncounterVitals, EncounterDiagnosis,
    PatientAllergy, EncounterAllergyReview,
)
