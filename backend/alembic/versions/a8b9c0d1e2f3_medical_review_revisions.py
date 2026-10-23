"""Add signed, immutable medical-review amendments without changing original reviews.

Requires the model-shaped Phase 2B head. Preflight is read-only; PostgreSQL DDL,
trigger creation, and Alembic stamping share the caller's transaction.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql

from src.medical_review_db_v1 import install_medical_review_revision_guards


revision = "a8b9c0d1e2f3"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None

TABLE = "medical_review_revisions"
INDEXES = (
    "uq_medical_review_revision_number",
    "uq_medical_review_revision_previous",
    "ix_medical_review_revisions_original_review_id",
    "ix_medical_review_revisions_author_user_id",
    "ix_medical_review_revisions_author_doctor_id",
)


def validate_baseline(connection):
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Medical review revision migration requires PostgreSQL")
    if int(connection.execute(text("SHOW server_version_num")).scalar_one()) < 100000:
        raise RuntimeError("Medical review revision migration requires PostgreSQL 10+")
    heads = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all()
    if heads != [down_revision]:
        raise RuntimeError("Medical review revision migration requires exactly f6a7b8c9d0e1; no DDL issued")
    if not connection.execute(text("SELECT current_schema() = 'public' AND pg_my_temp_schema() = 0")).scalar_one():
        raise RuntimeError("Medical review revision migration requires public as current schema; no DDL issued")
    if not connection.execute(text(
        "SELECT has_schema_privilege('public','USAGE') AND has_schema_privilege('public','CREATE')"
    )).scalar_one():
        raise RuntimeError("Medical review revision migration requires public schema USAGE and CREATE; no DDL issued")

    inspector = inspect(connection)
    required = {
        "users": {"id", "role", "password_hash"},
        "doctors": {"id", "user_id", "status"},
        "medical_reports": {"id", "patient_id", "doctor_id"},
        "doctor_reviews": {"id", "report_id", "doctor_id", "review_status", "clinical_notes",
                           "final_assessment", "reviewed_at"},
        "encounters": {"id", "patient_id", "doctor_id", "status"},
        "report_review_requests": {"id", "report_id", "patient_id", "doctor_id", "status"},
    }
    for table_name, names in required.items():
        if not inspector.has_table(table_name, schema="public"):
            raise RuntimeError(f"Required public.{table_name} is missing; no DDL issued")
        columns = {column["name"]: column for column in inspector.get_columns(table_name, schema="public")}
        if missing := names - columns.keys():
            raise RuntimeError(f"Required public.{table_name} columns missing: {sorted(missing)}; no DDL issued")
        for name in names & {"id", "user_id", "patient_id", "doctor_id", "report_id"}:
            if not isinstance(columns[name]["type"], sa.Integer):
                raise RuntimeError(f"Incompatible public.{table_name}.{name} type; no DDL issued")
    for table_name, column_name, expected_type in (
        ("doctor_reviews", "review_status", "review_status_enum"),
        ("doctors", "status", "doctor_status_enum"),
        ("users", "role", "user_role_enum"),
    ):
        column = next(item for item in inspector.get_columns(table_name, schema="public")
                      if item["name"] == column_name)
        if str(column["type"].compile(dialect=connection.dialect)) != expected_type:
            raise RuntimeError(f"Incompatible public.{table_name}.{column_name} type; no DDL issued")
    if inspector.get_pk_constraint("doctor_reviews", schema="public")["constrained_columns"] != ["id"]:
        raise RuntimeError("doctor_reviews.id must be its primary key; no DDL issued")

    unique = inspector.get_unique_constraints("doctor_reviews", schema="public")
    indexes = inspector.get_indexes("doctor_reviews", schema="public")
    if not any(set(item.get("column_names") or ()) == {"report_id"} for item in (*unique, *indexes)
               if item.get("unique", True)):
        raise RuntimeError("doctor_reviews.report_id must be unique; no DDL issued")
    links = inspector.get_foreign_keys("doctor_reviews", schema="public")
    if not any(item["constrained_columns"] == ["report_id"] and item["referred_table"] == "medical_reports"
               and item.get("referred_schema") in (None, "public") for item in links):
        raise RuntimeError("doctor_reviews must reference medical_reports; no DDL issued")
    enums = {item["name"]: item["labels"] for item in inspector.get_enums(schema="public")}
    for name, expected in {
        "review_status_enum": ["APPROVED", "MODIFIED", "REJECTED"],
        "doctor_status_enum": ["Active", "OnLeave", "Inactive"],
        "user_role_enum": ["user", "admin", "patient", "doctor", "department_admin",
                           "hospital_admin", "emergency_doctor"],
    }.items():
        if enums.get(name) != expected:
            raise RuntimeError(f"Unexpected public.{name} labels; no DDL issued")

    reserved = [TABLE, TABLE + "_id_seq", *INDEXES]
    collisions = connection.execute(text(
        "SELECT c.relname FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relname=ANY(:names) "
        "UNION SELECT t.typname FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace "
        "WHERE n.nspname='public' AND t.typname=ANY(:names)"
    ), {"names": reserved}).scalars().all()
    if collisions:
        raise RuntimeError(f"Medical review revision object names already exist: {sorted(collisions)}; no DDL issued")
    functions = connection.execute(text(
        "SELECT to_regprocedure('public.validate_medical_review_revision_insert()') IS NOT NULL "
        "OR to_regprocedure('public.reject_medical_review_revision_change()') IS NOT NULL"
    )).scalar_one()
    if functions:
        raise RuntimeError("Medical review revision guard functions already exist; no DDL issued")
    for name in ("medical_reports", "doctor_reviews", "users", "doctors"):
        if not connection.execute(text("SELECT has_table_privilege(:name, 'REFERENCES')"),
                                  {"name": "public." + name}).scalar_one():
            raise RuntimeError(f"REFERENCES privilege on public.{name} is required; no DDL issued")


def upgrade():
    connection = op.get_bind()
    validate_baseline(connection)
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("medical_reports.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("original_review_id", sa.Integer(), sa.ForeignKey("doctor_reviews.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("previous_revision_id", sa.Integer(), sa.ForeignKey(TABLE + ".id", ondelete="RESTRICT")),
        sa.Column("author_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("author_doctor_id", sa.Integer(), sa.ForeignKey("doctors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("review_status", postgresql.ENUM("APPROVED", "MODIFIED", "REJECTED",
                                                  name="review_status_enum", create_type=False), nullable=False),
        sa.Column("clinical_notes", sa.Text()),
        sa.Column("final_assessment", sa.Text()),
        sa.Column("corrected_parameters", sa.JSON()),
        sa.Column("amendment_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("signed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("revision_number >= 2", name="ck_medical_review_revision_number"),
        sa.CheckConstraint("length(btrim(amendment_reason)) > 0", name="ck_medical_review_revision_reason"),
        sa.CheckConstraint("(revision_number = 2 AND previous_revision_id IS NULL) OR "
                           "(revision_number > 2 AND previous_revision_id IS NOT NULL)",
                           name="ck_medical_review_revision_predecessor"),
        schema="public",
    )
    op.create_index(INDEXES[0], TABLE, ["report_id", "revision_number"], unique=True, schema="public")
    op.create_index(INDEXES[1], TABLE, ["previous_revision_id"], unique=True, schema="public")
    op.create_index(INDEXES[2], TABLE, ["original_review_id"], schema="public")
    op.create_index(INDEXES[3], TABLE, ["author_user_id"], schema="public")
    op.create_index(INDEXES[4], TABLE, ["author_doctor_id"], schema="public")
    install_medical_review_revision_guards(connection)


def downgrade():
    raise RuntimeError("Refusing to remove immutable medical review amendments; assess downgrade separately")
