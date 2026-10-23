"""Workforce records; existing users remain the only staff identities."""
from sqlalchemy import (CheckConstraint, Column, DateTime, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint, text)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func


class WorkforceBase(DeclarativeBase):
    pass


def ref(table, nullable=False):
    return Column(Integer, ForeignKey(table, ondelete="RESTRICT"), nullable=nullable, index=True)


class WorkforceAssignment(WorkforceBase):
    __tablename__ = "workforce_assignments"
    id = Column(Integer, primary_key=True)
    user_id = ref("users.id")
    department_id = ref("departments.id")
    ward_id = ref("inpatient_wards.id", nullable=True)
    location_id = ref("inventory_locations.id", nullable=True)
    source_module = Column(String(24), nullable=False)
    source_assignment_id = Column(Integer, nullable=False)
    assignment_role = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False, server_default=text("'ACTIVE'"))
    starts_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True))
    version = Column(Integer, nullable=False, server_default=text("1"))
    assigned_by_user_id = ref("users.id")
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("source_module IN ('DOCTOR','WARD','PHARMACY','LABORATORY','RADIOLOGY','BILLING','INVENTORY')", name="ck_workforce_assignment_source"),
        CheckConstraint("status IN ('ACTIVE','SUSPENDED','REVOKED')", name="ck_workforce_assignment_status"),
        CheckConstraint("expires_at IS NULL OR expires_at > starts_at", name="ck_workforce_assignment_dates"),
        CheckConstraint("version > 0", name="ck_workforce_assignment_version"),
        Index("ix_workforce_assignment_source", "source_module", "source_assignment_id"),
        Index("ix_workforce_assignment_staff", "user_id", "department_id", "status"),
        Index("uq_workforce_active_source", "source_module", "source_assignment_id", unique=True,
              postgresql_where=text("status = 'ACTIVE'")),
    )


class WorkforceAssignmentEvent(WorkforceBase):
    __tablename__ = "workforce_assignment_events"
    id = Column(Integer, primary_key=True)
    assignment_id = ref("workforce_assignments.id")
    version = Column(Integer, nullable=False)
    from_status = Column(String(16))
    to_status = Column(String(16), nullable=False)
    actor_user_id = ref("users.id")
    reason = Column(Text, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint("assignment_id", "version", name="uq_workforce_assignment_event_version"),)


class WorkforceShift(WorkforceBase):
    __tablename__ = "workforce_shifts"
    id = Column(Integer, primary_key=True)
    user_id = ref("users.id")
    department_id = ref("departments.id")
    ward_id = ref("inpatient_wards.id", nullable=True)
    title = Column(String(100), nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(16), nullable=False, server_default=text("'SCHEDULED'"))
    version = Column(Integer, nullable=False, server_default=text("1"))
    created_by_user_id = ref("users.id")
    change_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_workforce_shift_times"),
        CheckConstraint("status IN ('SCHEDULED','CANCELLED')", name="ck_workforce_shift_status"),
        CheckConstraint("version > 0", name="ck_workforce_shift_version"),
        Index("ix_workforce_shift_staff_time", "user_id", "starts_at", "ends_at"),
    )


class WorkforceShiftEvent(WorkforceBase):
    __tablename__ = "workforce_shift_events"
    id = Column(Integer, primary_key=True)
    shift_id = ref("workforce_shifts.id")
    version = Column(Integer, nullable=False)
    action = Column(String(16), nullable=False)
    actor_user_id = ref("users.id")
    reason = Column(Text, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint("shift_id", "version", name="uq_workforce_shift_event_version"),)


class WorkforceAttendance(WorkforceBase):
    __tablename__ = "workforce_attendance"
    id = Column(Integer, primary_key=True)
    shift_id = ref("workforce_shifts.id")
    user_id = ref("users.id")
    clocked_in_at = Column(DateTime(timezone=True), nullable=False)
    clocked_out_at = Column(DateTime(timezone=True))
    version = Column(Integer, nullable=False, server_default=text("1"))
    __table_args__ = (
        UniqueConstraint("shift_id", "user_id", name="uq_workforce_attendance_shift_staff"),
        CheckConstraint("clocked_out_at IS NULL OR clocked_out_at > clocked_in_at", name="ck_workforce_attendance_times"),
        CheckConstraint("version > 0", name="ck_workforce_attendance_version"),
    )


class WorkforceAttendanceEvent(WorkforceBase):
    __tablename__ = "workforce_attendance_events"
    id = Column(Integer, primary_key=True)
    attendance_id = ref("workforce_attendance.id")
    sequence = Column(Integer, nullable=False)
    action = Column(String(20), nullable=False)
    actor_user_id = ref("users.id")
    recorded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    effective_at = Column(DateTime(timezone=True), nullable=False)
    reason = Column(Text)
    __table_args__ = (UniqueConstraint("attendance_id", "sequence", name="uq_workforce_attendance_event_seq"),)


class WorkforceCorrectionRequest(WorkforceBase):
    __tablename__ = "workforce_correction_requests"
    id = Column(Integer, primary_key=True)
    attendance_id = ref("workforce_attendance.id")
    requested_by_user_id = ref("users.id")
    proposed_clock_out_at = Column(DateTime(timezone=True), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, server_default=text("'PENDING'"))
    reviewed_by_user_id = ref("users.id", nullable=True)
    reviewed_at = Column(DateTime(timezone=True))
    review_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','APPROVED','REJECTED')", name="ck_workforce_correction_status"),
        Index("uq_workforce_pending_correction", "attendance_id", unique=True,
              postgresql_where=text("status = 'PENDING'")),
    )
