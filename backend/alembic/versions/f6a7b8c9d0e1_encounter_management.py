"""Add outpatient encounters; strict model-shaped Phase 2A baseline required.

No existing rows are changed. All DDL and Alembic stamping are transactional.
Historical-baseline repair is deliberately out of scope.
"""
import json
import re
from pathlib import Path
from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None

# Frozen schema reflection: never reads application row values.
from sqlalchemy import inspect, text


def normalize_sql(value):
    if value is None:
        return None
    return re.sub(r"\s+", " ", str(value)).strip().replace("EXECUTE PROCEDURE", "EXECUTE FUNCTION")


def schema_signature(connection, table_names):
    inspector = inspect(connection)
    result = {"tables": {}}
    existing = set(inspector.get_table_names(schema="public"))
    for name in sorted(table_names):
        if name not in existing:
            raise RuntimeError(f"Required Phase 2A table public.{name} is missing")
        columns = []
        for column in inspector.get_columns(name, schema="public"):
            columns.append({
                "name": column["name"],
                "type": str(column["type"].compile(dialect=connection.dialect)),
                "nullable": column["nullable"],
                "default": normalize_sql(column.get("default")),
            })
        foreign_keys = [{
            "columns": fk["constrained_columns"], "table": fk["referred_table"],
            "target": fk["referred_columns"], "ondelete": fk.get("options", {}).get("ondelete"),
        } for fk in inspector.get_foreign_keys(name, schema="public")]
        indexes = [{
            "name": index["name"], "unique": bool(index["unique"]),
            "columns": index["column_names"], "expressions": index.get("expressions"),
            "where": normalize_sql(index.get("dialect_options", {}).get("postgresql_where")),
        } for index in inspector.get_indexes(name, schema="public")]
        result["tables"][name] = {
            "columns": sorted(columns, key=lambda item: item["name"]),
            "primary_key": inspector.get_pk_constraint(name, schema="public")["constrained_columns"],
            "foreign_keys": sorted(foreign_keys, key=lambda item: str(item["columns"])),
            "unique": sorted([sorted(item["column_names"]) for item in inspector.get_unique_constraints(name, schema="public")]),
            "checks": sorted([normalize_sql(item["sqltext"]) for item in inspector.get_check_constraints(name, schema="public")]),
            "indexes": sorted(indexes, key=lambda item: item["name"]),
        }
    result["enums"] = sorted([
        {"name": enum["name"], "labels": enum["labels"]}
        for enum in inspector.get_enums(schema="public")
    ], key=lambda item: item["name"])
    result["mrn_function"] = normalize_sql(connection.execute(text(
        "SELECT pg_get_functiondef(to_regprocedure('public.assign_and_protect_patient_mrn()'))"
    )).scalar_one())
    result["mrn_trigger"] = normalize_sql(connection.execute(text(
        "SELECT pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid='public.users'::regclass "
        "AND tgname='users_patient_mrn_guard' AND NOT tgisinternal"
    )).scalar_one())
    result["mrn_sequence"] = list(connection.execute(text(
        "SELECT increment_by,min_value,max_value,cache_size,cycle FROM pg_sequences "
        "WHERE schemaname='public' AND sequencename='patient_mrn_seq'"
    )).one())
    return result

NEW_TABLES = ('encounters', 'encounter_allergy_reviews', 'encounter_diagnoses', 'encounter_notes', 'encounter_vitals', 'patient_allergies')
CREATE_STATEMENTS = (
    "CREATE TABLE encounters (\n\tid SERIAL NOT NULL, \n\tpatient_id INTEGER NOT NULL, \n\tappointment_id INTEGER, \n\tdoctor_id INTEGER, \n\tdepartment_id INTEGER, \n\tcreated_by_user_id INTEGER NOT NULL, \n\tcreation_key VARCHAR(64) NOT NULL, \n\tcreation_fingerprint VARCHAR(64) NOT NULL, \n\tchief_complaint TEXT, \n\tstatus VARCHAR(24) DEFAULT 'CHECKED_IN' NOT NULL, \n\tversion INTEGER DEFAULT 1 NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tchecked_in_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE, \n\tcompleted_at TIMESTAMP WITH TIME ZONE, \n\tcancelled_at TIMESTAMP WITH TIME ZONE, \n\tcancellation_reason TEXT, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_encounter_creation_request UNIQUE (created_by_user_id, creation_key), \n\tCONSTRAINT ck_encounter_status CHECK (status IN ('CHECKED_IN','IN_PROGRESS','COMPLETED','CANCELLED')), \n\tCONSTRAINT ck_encounter_version CHECK (version > 0), \n\tCONSTRAINT ck_encounter_started CHECK (status NOT IN ('IN_PROGRESS','COMPLETED') OR (doctor_id IS NOT NULL AND started_at IS NOT NULL)), \n\tCONSTRAINT ck_encounter_completed CHECK ((status = 'COMPLETED') = (completed_at IS NOT NULL)), \n\tCONSTRAINT ck_encounter_cancelled CHECK ((status = 'CANCELLED') = (cancelled_at IS NOT NULL)), \n\tCONSTRAINT ck_encounter_cancel_reason CHECK (status <> 'CANCELLED' OR length(btrim(cancellation_reason)) > 0 AND cancellation_reason IS NOT NULL), \n\tFOREIGN KEY(patient_id) REFERENCES users (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(appointment_id) REFERENCES appointments (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(doctor_id) REFERENCES doctors (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE RESTRICT\n)",
    'CREATE INDEX ix_encounter_doctor_status ON encounters (doctor_id, status)',
    'CREATE INDEX ix_encounter_patient_created ON encounters (patient_id, created_at)',
    'CREATE UNIQUE INDEX ix_encounters_appointment_id ON encounters (appointment_id)',
    'CREATE INDEX ix_encounters_created_by_user_id ON encounters (created_by_user_id)',
    'CREATE INDEX ix_encounters_department_id ON encounters (department_id)',
    'CREATE INDEX ix_encounters_doctor_id ON encounters (doctor_id)',
    'CREATE INDEX ix_encounters_patient_id ON encounters (patient_id)',
    "CREATE TABLE encounter_allergy_reviews (\n\tid SERIAL NOT NULL, \n\tencounter_id INTEGER NOT NULL, \n\tencounter_version INTEGER NOT NULL, \n\toutcome VARCHAR(16) NOT NULL, \n\tsnapshot JSONB NOT NULL, \n\treviewed_by_user_id INTEGER NOT NULL, \n\treviewed_by_doctor_id INTEGER NOT NULL, \n\treviewed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_encounter_allergy_review_version UNIQUE (encounter_id, encounter_version), \n\tCONSTRAINT ck_allergy_review_outcome CHECK (outcome IN ('UNKNOWN','NO_KNOWN','RECORDED')), \n\tFOREIGN KEY(encounter_id) REFERENCES encounters (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(reviewed_by_user_id) REFERENCES users (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(reviewed_by_doctor_id) REFERENCES doctors (id) ON DELETE RESTRICT\n)",
    'CREATE INDEX ix_encounter_allergy_reviews_encounter_id ON encounter_allergy_reviews (encounter_id)',
    'CREATE INDEX ix_encounter_allergy_reviews_reviewed_by_doctor_id ON encounter_allergy_reviews (reviewed_by_doctor_id)',
    'CREATE INDEX ix_encounter_allergy_reviews_reviewed_by_user_id ON encounter_allergy_reviews (reviewed_by_user_id)',
    "CREATE TABLE encounter_diagnoses (\n\tid SERIAL NOT NULL, \n\tencounter_id INTEGER NOT NULL, \n\tprevious_id INTEGER, \n\trecorded_by_user_id INTEGER NOT NULL, \n\trecorded_by_doctor_id INTEGER NOT NULL, \n\tdescription TEXT NOT NULL, \n\tcoding_system VARCHAR(64), \n\tcode VARCHAR(64), \n\tstatus VARCHAR(24) DEFAULT 'PROVISIONAL' NOT NULL, \n\tis_primary BOOLEAN DEFAULT false NOT NULL, \n\treason TEXT, \n\trecorded_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_diagnosis_description CHECK (length(btrim(description)) > 0), \n\tCONSTRAINT ck_diagnosis_status CHECK (status IN ('PROVISIONAL','CONFIRMED','ENTERED_IN_ERROR')), \n\tCONSTRAINT ck_diagnosis_code_system CHECK ((code IS NULL) = (coding_system IS NULL)), \n\tCONSTRAINT ck_diagnosis_correction_reason CHECK (previous_id IS NULL OR (reason IS NOT NULL AND length(btrim(reason)) > 0)), \n\tFOREIGN KEY(encounter_id) REFERENCES encounters (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(previous_id) REFERENCES encounter_diagnoses (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(recorded_by_user_id) REFERENCES users (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(recorded_by_doctor_id) REFERENCES doctors (id) ON DELETE RESTRICT\n)",
    'CREATE INDEX ix_encounter_diagnoses_encounter_id ON encounter_diagnoses (encounter_id)',
    'CREATE UNIQUE INDEX ix_encounter_diagnoses_previous_id ON encounter_diagnoses (previous_id)',
    'CREATE INDEX ix_encounter_diagnoses_recorded_by_doctor_id ON encounter_diagnoses (recorded_by_doctor_id)',
    'CREATE INDEX ix_encounter_diagnoses_recorded_by_user_id ON encounter_diagnoses (recorded_by_user_id)',
    "CREATE TABLE encounter_notes (\n\tid SERIAL NOT NULL, \n\tencounter_id INTEGER NOT NULL, \n\trevision INTEGER NOT NULL, \n\tprevious_id INTEGER, \n\tkind VARCHAR(16) DEFAULT 'CONSULTATION' NOT NULL, \n\tsubjective TEXT DEFAULT '' NOT NULL, \n\tobjective TEXT DEFAULT '' NOT NULL, \n\tassessment TEXT DEFAULT '' NOT NULL, \n\tplan TEXT DEFAULT '' NOT NULL, \n\tpatient_summary TEXT DEFAULT '' NOT NULL, \n\treason TEXT, \n\tauthor_user_id INTEGER NOT NULL, \n\tauthor_doctor_id INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsigned_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_encounter_note_revision UNIQUE (encounter_id, revision), \n\tCONSTRAINT ck_note_revision CHECK (revision > 0), \n\tCONSTRAINT ck_note_kind CHECK (kind IN ('CONSULTATION','ADDENDUM')), \n\tCONSTRAINT ck_addendum_attribution CHECK (kind <> 'ADDENDUM' OR (signed_at IS NOT NULL AND reason IS NOT NULL AND length(btrim(reason)) > 0)), \n\tFOREIGN KEY(encounter_id) REFERENCES encounters (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(previous_id) REFERENCES encounter_notes (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(author_user_id) REFERENCES users (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(author_doctor_id) REFERENCES doctors (id) ON DELETE RESTRICT\n)",
    'CREATE INDEX ix_encounter_notes_author_doctor_id ON encounter_notes (author_doctor_id)',
    'CREATE INDEX ix_encounter_notes_author_user_id ON encounter_notes (author_user_id)',
    'CREATE INDEX ix_encounter_notes_encounter_id ON encounter_notes (encounter_id)',
    'CREATE UNIQUE INDEX ix_encounter_notes_previous_id ON encounter_notes (previous_id)',
    'CREATE TABLE encounter_vitals (\n\tid SERIAL NOT NULL, \n\tencounter_id INTEGER NOT NULL, \n\tprevious_id INTEGER, \n\trecorded_by_user_id INTEGER NOT NULL, \n\trecorded_by_doctor_id INTEGER NOT NULL, \n\tmeasured_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trecorded_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsystolic_mmhg NUMERIC(7, 2), \n\tdiastolic_mmhg NUMERIC(7, 2), \n\tpulse_bpm NUMERIC(7, 2), \n\trespiratory_rate_per_min NUMERIC(7, 2), \n\ttemperature_c NUMERIC(7, 2), \n\tspo2_percent NUMERIC(5, 2), \n\tweight_kg NUMERIC(7, 2), \n\theight_cm NUMERIC(7, 2), \n\treason TEXT, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_vitals_measurement CHECK (num_nonnulls(systolic_mmhg,diastolic_mmhg,pulse_bpm,respiratory_rate_per_min,temperature_c,spo2_percent,weight_kg,height_cm) > 0), \n\tCONSTRAINT ck_vitals_spo2 CHECK (spo2_percent BETWEEN 0 AND 100), \n\tCONSTRAINT ck_vitals_correction_reason CHECK (previous_id IS NULL OR (reason IS NOT NULL AND length(btrim(reason)) > 0)), \n\tFOREIGN KEY(encounter_id) REFERENCES encounters (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(previous_id) REFERENCES encounter_vitals (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(recorded_by_user_id) REFERENCES users (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(recorded_by_doctor_id) REFERENCES doctors (id) ON DELETE RESTRICT\n)',
    'CREATE INDEX ix_encounter_vitals_encounter_id ON encounter_vitals (encounter_id)',
    'CREATE UNIQUE INDEX ix_encounter_vitals_previous_id ON encounter_vitals (previous_id)',
    'CREATE INDEX ix_encounter_vitals_recorded_by_doctor_id ON encounter_vitals (recorded_by_doctor_id)',
    'CREATE INDEX ix_encounter_vitals_recorded_by_user_id ON encounter_vitals (recorded_by_user_id)',
    "CREATE TABLE patient_allergies (\n\tid SERIAL NOT NULL, \n\tpatient_id INTEGER NOT NULL, \n\tsource_encounter_id INTEGER NOT NULL, \n\tprevious_id INTEGER, \n\tsubstance VARCHAR(255) NOT NULL, \n\treaction TEXT, \n\tseverity VARCHAR(16) DEFAULT 'UNKNOWN' NOT NULL, \n\tstatus VARCHAR(24) DEFAULT 'ACTIVE' NOT NULL, \n\treason TEXT, \n\trecorded_by_user_id INTEGER NOT NULL, \n\trecorded_by_doctor_id INTEGER NOT NULL, \n\trecorded_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_allergy_substance CHECK (length(btrim(substance)) > 0), \n\tCONSTRAINT ck_allergy_severity CHECK (severity IN ('UNKNOWN','MILD','MODERATE','SEVERE')), \n\tCONSTRAINT ck_allergy_status CHECK (status IN ('ACTIVE','INACTIVE','ENTERED_IN_ERROR')), \n\tCONSTRAINT ck_allergy_correction_reason CHECK (previous_id IS NULL OR (reason IS NOT NULL AND length(btrim(reason)) > 0)), \n\tFOREIGN KEY(patient_id) REFERENCES users (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(source_encounter_id) REFERENCES encounters (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(previous_id) REFERENCES patient_allergies (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(recorded_by_user_id) REFERENCES users (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(recorded_by_doctor_id) REFERENCES doctors (id) ON DELETE RESTRICT\n)",
    'CREATE INDEX ix_patient_allergies_patient_id ON patient_allergies (patient_id)',
    'CREATE UNIQUE INDEX ix_patient_allergies_previous_id ON patient_allergies (previous_id)',
    'CREATE INDEX ix_patient_allergies_recorded_by_doctor_id ON patient_allergies (recorded_by_doctor_id)',
    'CREATE INDEX ix_patient_allergies_recorded_by_user_id ON patient_allergies (recorded_by_user_id)',
    'CREATE INDEX ix_patient_allergies_source_encounter_id ON patient_allergies (source_encounter_id)',
)


def validate_baseline(connection):
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Encounter migration requires PostgreSQL")
    version = connection.execute(text("SHOW server_version_num")).scalar_one()
    if int(version) < 100000:
        raise RuntimeError("Encounter migration requires PostgreSQL 10+")
    revision_rows = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all()
    if revision_rows != [down_revision]:
        raise RuntimeError("Encounter migration requires exactly the Phase 2A Alembic revision")
    if not connection.execute(text("SELECT has_schema_privilege('public','USAGE') AND has_schema_privilege('public','CREATE')")).scalar_one():
        raise RuntimeError("Encounter migration requires public schema USAGE and CREATE")
    if not connection.execute(text("SELECT current_schema() = 'public' AND pg_my_temp_schema() = 0")).scalar_one():
        raise RuntimeError("Encounter migration requires public as the current schema and no temporary schema")
    for table in ("users", "appointments", "doctors", "departments"):
        if not connection.execute(text("SELECT has_table_privilege(:table, 'REFERENCES')"), {"table": "public." + table}).scalar_one():
            raise RuntimeError(f"Encounter migration requires REFERENCES on public.{table}")
    reserved_names = set(NEW_TABLES) | {name + "_id_seq" for name in NEW_TABLES}
    reserved_names.update(re.match(r"CREATE (?:UNIQUE )?INDEX (\w+)", statement).group(1)
                          for statement in CREATE_STATEMENTS if "INDEX " in statement[:20])
    collisions = connection.execute(text(
        "SELECT c.relname FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relname=ANY(:names) "
        "UNION SELECT t.typname FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace "
        "WHERE n.nspname='public' AND t.typname=ANY(:names)"
    ), {"names": sorted(reserved_names)}).scalars().all()
    if collisions:
        raise RuntimeError(f"Encounter tables already exist before their revision: {sorted(collisions)}. No DDL issued.")
    expected = json.loads((Path(__file__).resolve().parents[1] / "baselines" / "e4f5a6b7c8d9.json").read_text(encoding="utf-8"))
    inspector = inspect(connection)
    for name in expected["tables"]:
        if not inspector.has_table(name, schema="public"):
            raise RuntimeError(f"Required Phase 2A table public.{name} is missing. No DDL issued.")
        columns = {column["name"] for column in inspector.get_columns(name, schema="public")}
        required = {column["name"] for column in expected["tables"][name]["columns"]}
        if missing := required - columns:
            raise RuntimeError(f"Required Phase 2A columns missing in public.{name}: {sorted(missing)}. No DDL issued.")
        for foreign_key in inspector.get_foreign_keys(name, schema="public"):
            if foreign_key.get("referred_schema") not in (None, "public"):
                raise RuntimeError(f"Unsupported cross-schema dependency in public.{name}. No DDL issued.")
    actual = schema_signature(connection, expected["tables"])
    differences = ["public." + name for name in expected["tables"] if actual["tables"][name] != expected["tables"][name]]
    differences.extend(key for key in ("enums", "mrn_function", "mrn_trigger", "mrn_sequence") if actual[key] != expected[key])
    if differences:
        raise RuntimeError("Encounter migration refused incompatible Phase 2A baseline: " + ", ".join(differences) + ". No DDL issued; assess schema drift separately.")


def upgrade():
    connection = op.get_bind()
    validate_baseline(connection)
    for statement in CREATE_STATEMENTS:
        op.execute(text(statement))


def downgrade():
    connection = op.get_bind()
    op.execute("LOCK TABLE " + ", ".join("public." + name for name in NEW_TABLES) + " IN ACCESS EXCLUSIVE MODE")
    for name in NEW_TABLES:
        if connection.execute(text("SELECT EXISTS (SELECT 1 FROM public." + name + ")")).scalar_one():
            raise RuntimeError("Refusing encounter downgrade: clinical data exists. No tables were dropped.")
    for name in reversed(NEW_TABLES):
        op.drop_table(name, schema="public")
