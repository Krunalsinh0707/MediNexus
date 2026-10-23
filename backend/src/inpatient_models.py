"""ADT contracts; existing users and encounters remain authoritative."""
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func


class InpatientBase(DeclarativeBase):
    pass


def ref(target, nullable=False):
    return Column(Integer, ForeignKey(target, ondelete="RESTRICT"), nullable=nullable, index=True)


class Ward(InpatientBase):
    __tablename__ = "inpatient_wards"
    id = Column(Integer, primary_key=True)
    code = Column(String(32), nullable=False, unique=True)
    name = Column(String(100), nullable=False)
    department_id = ref("departments.id")
    is_active = Column(Integer, nullable=False, server_default=text("1"))
    __table_args__ = (CheckConstraint("is_active IN (0,1)", name="ck_ward_active"),)


class Room(InpatientBase):
    __tablename__ = "inpatient_rooms"
    id = Column(Integer, primary_key=True)
    ward_id = ref("inpatient_wards.id")
    code = Column(String(32), nullable=False)
    __table_args__ = (UniqueConstraint("ward_id", "code", name="uq_ward_room_code"),)


class Bed(InpatientBase):
    __tablename__ = "inpatient_beds"
    id = Column(Integer, primary_key=True)
    room_id = ref("inpatient_rooms.id")
    code = Column(String(32), nullable=False)
    maintenance_status = Column(String(16), nullable=False, server_default=text("'AVAILABLE'"))
    maintenance_reason = Column(Text)
    version = Column(Integer, nullable=False, server_default=text("1"))
    __table_args__ = (
        UniqueConstraint("room_id", "code", name="uq_room_bed_code"),
        CheckConstraint("maintenance_status IN ('AVAILABLE','BLOCKED','CLEANING')", name="ck_bed_maintenance_status"),
        CheckConstraint("version > 0", name="ck_bed_version"),
        CheckConstraint("maintenance_status = 'AVAILABLE' OR maintenance_reason IS NOT NULL AND length(btrim(maintenance_reason)) > 0", name="ck_bed_maintenance_reason"),
    )


class InpatientStaffAssignment(InpatientBase):
    __tablename__ = "inpatient_staff_assignments"
    id = Column(Integer, primary_key=True)
    user_id = ref("users.id")
    ward_id = ref("inpatient_wards.id")
    role = Column(String(24), nullable=False)
    is_active = Column(Integer, nullable=False, server_default=text("1"))
    __table_args__ = (
        UniqueConstraint("user_id", "ward_id", name="uq_inpatient_staff_ward"),
        CheckConstraint("role IN ('ADT_STAFF','WARD_MANAGER','NURSE','CHARGE_NURSE')", name="ck_inpatient_staff_role"),
        CheckConstraint("is_active IN (0,1)", name="ck_inpatient_staff_active"),
    )


class InpatientAdmission(InpatientBase):
    __tablename__ = "inpatient_admissions"
    id = Column(Integer, primary_key=True)
    patient_id = ref("users.id")
    source_encounter_id = ref("encounters.id")
    requested_by_user_id = ref("users.id")
    ward_id = ref("inpatient_wards.id")
    status = Column(String(16), nullable=False, server_default=text("'REQUESTED'"))
    version = Column(Integer, nullable=False, server_default=text("1"))
    request_reason = Column(Text, nullable=False)
    decision_reason = Column(Text)
    discharge_reason = Column(Text)
    requested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    admitted_at = Column(DateTime(timezone=True))
    planned_discharge_at = Column(DateTime(timezone=True))
    discharged_at = Column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('REQUESTED','REJECTED','ACTIVE','DISCHARGED')", name="ck_inpatient_admission_status"),
        CheckConstraint("version > 0", name="ck_inpatient_admission_version"),
        CheckConstraint("length(btrim(request_reason)) > 0", name="ck_inpatient_request_reason"),
        CheckConstraint("status <> 'REJECTED' OR decision_reason IS NOT NULL AND length(btrim(decision_reason)) > 0", name="ck_inpatient_rejection_reason"),
        CheckConstraint("status <> 'DISCHARGED' OR discharged_at IS NOT NULL AND discharge_reason IS NOT NULL AND length(btrim(discharge_reason)) > 0", name="ck_inpatient_discharge_reason"),
        Index("ix_inpatient_ward_status", "ward_id", "status"),
        Index("uq_open_inpatient_patient", "patient_id", unique=True,
              postgresql_where=text("status IN ('REQUESTED','ACTIVE')")),
    )


class BedAssignment(InpatientBase):
    __tablename__ = "inpatient_bed_assignments"
    id = Column(Integer, primary_key=True)
    admission_id = ref("inpatient_admissions.id")
    bed_id = ref("inpatient_beds.id")
    assigned_by_user_id = ref("users.id")
    assigned_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    released_at = Column(DateTime(timezone=True))
    released_by_user_id = ref("users.id", nullable=True)
    release_reason = Column(String(24))
    __table_args__ = (
        CheckConstraint("(released_at IS NULL) = (released_by_user_id IS NULL)", name="ck_bed_assignment_release_actor"),
        Index("uq_active_bed_assignment", "bed_id", unique=True, postgresql_where=text("released_at IS NULL")),
        Index("uq_active_admission_assignment", "admission_id", unique=True, postgresql_where=text("released_at IS NULL")),
    )


class BedReservation(InpatientBase):
    __tablename__ = "inpatient_bed_reservations"
    id = Column(Integer, primary_key=True)
    admission_id = ref("inpatient_admissions.id")
    bed_id = ref("inpatient_beds.id")
    reserved_by_user_id = ref("users.id")
    reserved_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    released_at = Column(DateTime(timezone=True))
    released_by_user_id = ref("users.id", nullable=True)
    __table_args__ = (
        Index("uq_active_bed_reservation", "bed_id", unique=True, postgresql_where=text("released_at IS NULL")),
        Index("uq_active_admission_reservation", "admission_id", unique=True, postgresql_where=text("released_at IS NULL")),
    )


class InpatientEvent(InpatientBase):
    __tablename__ = "inpatient_events"
    id = Column(Integer, primary_key=True)
    admission_id = ref("inpatient_admissions.id")
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(24), nullable=False)
    from_ward_id = ref("inpatient_wards.id", nullable=True)
    to_ward_id = ref("inpatient_wards.id", nullable=True)
    from_bed_id = ref("inpatient_beds.id", nullable=True)
    to_bed_id = ref("inpatient_beds.id", nullable=True)
    actor_user_id = ref("users.id")
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint("admission_id", "sequence", name="uq_inpatient_event_sequence"),)


class BedEvent(InpatientBase):
    __tablename__ = "inpatient_bed_events"
    id = Column(Integer, primary_key=True)
    bed_id = ref("inpatient_beds.id")
    bed_version = Column(Integer, nullable=False)
    event_type = Column(String(24), nullable=False)
    actor_user_id = ref("users.id")
    admission_id = ref("inpatient_admissions.id", nullable=True)
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint("bed_id", "bed_version", name="uq_inpatient_bed_event_version"),)
