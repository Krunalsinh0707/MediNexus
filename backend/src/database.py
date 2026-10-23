import os
import psycopg
from psycopg.rows import dict_row
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

# =========================
# Database Configuration
# =========================

DATABASE_URL = os.getenv("HMS_DATABASE_URL")
if DATABASE_URL:
    parsed_url = make_url(DATABASE_URL)
    if parsed_url.drivername != "postgresql+psycopg" or not parsed_url.database:
        raise RuntimeError("HMS_DATABASE_URL must be an explicit postgresql+psycopg database URL")
else:
    parsed_url = None


def require_database_url():
    if parsed_url is None:
        raise RuntimeError("Set HMS_DATABASE_URL explicitly before using the application database")
    return parsed_url

# =========================
# SQLAlchemy Engine
# =========================

engine = create_engine(DATABASE_URL, pool_size=10, max_overflow=20,
                       pool_pre_ping=True, echo=False) if DATABASE_URL else None
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ✅ SQLAlchemy Session Generator
def get_db():
    require_database_url()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ✅ ADD THIS (for Alembic compatibility)
def get_sqlalchemy_engine():
    require_database_url()
    return engine


# =========================
# Raw Database Connection Wrapper
# =========================

class PgCursorWrapper:
    """Wrapper around psycopg cursor to ensure full backward compatibility with raw MySQL queries"""
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query, vars=None):
        return self._cursor.execute(query, vars)

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size=None):
        return self._cursor.fetchmany(size)

    def close(self):
        return self._cursor.close()

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        # In PostgreSQL, lastrowid isn't directly present unless RETURNING is used, but return 0/None safely
        return getattr(self._cursor, "lastrowid", None)


class PgConnectionWrapper:
    """Wrapper over psycopg connection for seamless router backward compatibility"""
    def __init__(self, conn):
        self._conn = conn

    def cursor(self, dictionary=False, **kwargs):
        cur = self._conn.cursor(row_factory=dict_row if dictionary else None)
        return PgCursorWrapper(cur)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def get_db_connection():
    """Returns a PostgreSQL connection wrapped for backward compatibility"""
    try:
        url = require_database_url().set(drivername="postgresql").render_as_string(hide_password=False)
        conn = psycopg.connect(url)
        return PgConnectionWrapper(conn)
    except Exception:
        print("PostgreSQL connection is unavailable; check HMS_DATABASE_URL")
        return None


# =========================
# Database Initialization
# =========================

def require_current_schema():
    """Read-only readiness check; schema changes belong to Alembic/bootstrap."""
    from pathlib import Path
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from src.schema_registry import current_metadata, validated_module_ddl

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    heads = ScriptDirectory.from_config(config).get_heads()
    validated_module_ddl()
    with get_sqlalchemy_engine().connect() as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            inspector = inspect(connection)
            if not inspector.has_table("alembic_version", schema="public"):
                raise RuntimeError("Database is not initialized. Use the guarded fresh bootstrap or an assessed Alembic upgrade.")
            revisions = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all()
            if revisions != heads:
                raise RuntimeError("Database revision is not current. Run the approved Alembic upgrade before starting the API.")
            for table in current_metadata().sorted_tables:
                if not inspector.has_table(table.name, schema="public"):
                    raise RuntimeError(f"Database schema is incomplete: public.{table.name} is missing.")
                actual = {column["name"] for column in inspector.get_columns(table.name, schema="public")}
                if missing := set(table.columns.keys()) - actual:
                    raise RuntimeError(f"Database schema is incomplete: public.{table.name} is missing {sorted(missing)}.")
                indexes = {item["name"] for item in inspector.get_indexes(table.name, schema="public")}
                if missing := {index.name for index in table.indexes} - indexes:
                    raise RuntimeError(f"Database schema is incomplete: public.{table.name} indexes missing {sorted(missing)}.")


def init_db():
    """
    Explicit, backward-compatible entry point to seed an already migrated database.
    It no longer creates tables or conceals readiness failures.
    """
    require_current_schema()
    print("Seeding initialized PostgreSQL database...")
    try:
        from src.models import Department, ClinicalRoutingRule

        # Seed default departments if table is empty
        db = SessionLocal()
        try:
            dept_count = db.query(Department).count()
            if dept_count == 0:
                default_departments = [
                    ("Cardiology", "CARD", "Heart, vascular, and circulatory condition diagnostic and therapeutic care."),
                    ("Oncology", "ONCO", "Cancer detection, tumor assessment, and targeted oncological therapy."),
                    ("Orthopedics", "ORTHO", "Bone, joint, spine, and musculoskeletal system disorders."),
                    ("Neurology", "NEURO", "Brain, nervous system, stroke, and neuromuscular disorder care."),
                    ("Pulmonology", "PULMO", "Lungs, respiratory tract, and breathing conditions."),
                    ("Endocrinology", "ENDO", "Hormones, metabolism, diabetes, and endocrine gland disorders."),
                    ("Gastroenterology", "GASTRO", "Digestive system, liver, and gastrointestinal conditions."),
                    ("Hematology", "HEMA", "Blood disorders, CBC analysis, and bone marrow conditions."),
                    ("Nephrology", "NEPHRO", "Kidney diseases, renal function, and fluid balance."),
                    ("Dermatology", "DERM", "Skin, hair, nails, and cutaneous pathology."),
                    ("Pediatrics", "PEDI", "Infant, child, and adolescent specialized medical care."),
                    ("Gynecology", "GYNE", "Women's reproductive health and maternal care."),
                    ("General Medicine", "GENMED", "Comprehensive primary internal medicine and overall wellness."),
                    ("Emergency", "EMERG", "Critical care, urgent triage, and emergency medical response.")
                ]
                for name, code, desc in default_departments:
                    db.add(Department(name=name, code=code, description=desc))
                db.commit()
                print("Default medical departments seeded.")

            # Seed default clinical routing rules if table is empty
            rule_count = db.query(ClinicalRoutingRule).count()
            if rule_count == 0:
                dept_map = {d.code: d.id for d in db.query(Department).all()}
                default_rules = [
                    ("chest_pain", dept_map.get("EMERG", dept_map.get("CARD")), "EMERGENCY_REVIEW"),
                    ("shortness_of_breath", dept_map.get("EMERG", dept_map.get("PULMO")), "EMERGENCY_REVIEW"),
                    ("stroke", dept_map.get("EMERG", dept_map.get("NEURO")), "EMERGENCY_REVIEW"),
                    ("heart_attack", dept_map.get("CARD", dept_map.get("EMERG")), "EMERGENCY_REVIEW"),
                    ("cardiac", dept_map.get("CARD"), "HIGH_PRIORITY"),
                    ("hypertension", dept_map.get("CARD"), "MODERATE"),
                    ("diabetes", dept_map.get("ENDO"), "MODERATE"),
                    ("respiratory", dept_map.get("PULMO"), "MODERATE"),
                    ("orthopedic", dept_map.get("ORTHO"), "LOW_PRIORITY"),
                    ("dermatology", dept_map.get("DERM"), "LOW_PRIORITY"),
                    ("pediatric", dept_map.get("PEDI"), "LOW_PRIORITY"),
                    ("general", dept_map.get("GENMED"), "NORMAL"),
                    ("emergency", dept_map.get("EMERG"), "EMERGENCY_REVIEW"),
                ]
                for cat, dept_id, priority in default_rules:
                    if dept_id:
                        db.add(ClinicalRoutingRule(
                            category_or_indicator=cat,
                            department_id=dept_id,
                            priority=priority,
                            is_enabled=True,
                            version="1.0"
                        ))
                db.commit()
                print("Default clinical routing rules seeded.")
        finally:
            db.close()

        print("[OK] Database initialization complete.")
    except Exception as e:
        print(f"[ERROR] Database initialization error: {e}")
        raise


if __name__ == "__main__":
    init_db()
