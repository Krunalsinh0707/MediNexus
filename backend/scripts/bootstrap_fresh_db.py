"""Create the current model schema in an explicitly selected empty PostgreSQL DB.

This is a fresh-install path, not a repair or upgrade tool. It intentionally
requires HMS_FRESH_DATABASE_URL and never reads the application's HMS_DATABASE_URL.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

# Support direct invocation as ``python scripts/bootstrap_fresh_db.py`` from
# the backend directory, where Python otherwise places only ``scripts/`` first.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from src.schema_registry import current_metadata, validated_module_ddl
from src.patient_identity_db import install_patient_identity_database_objects
from src.medical_review_db_v1 import install_medical_review_revision_guards


ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
OBJECTS_QUERY = text(
    """
    -- Relations cover tables, indexes, sequences, views, partitions, foreign
    -- tables, and other relation-backed objects, including user-created types
    -- attached to a table.
    SELECT n.nspname, c.relname, c.relkind::text AS kind
      FROM pg_catalog.pg_class AS c
      JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND n.nspname NOT LIKE 'pg_toast%'
    UNION ALL
    SELECT n.nspname, p.proname, 'routine'::text
      FROM pg_catalog.pg_proc AS p
      JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND n.nspname NOT LIKE 'pg_toast%'
    UNION ALL
    -- Exclude only automatically-created array types and composite row types
    -- owned by a relation. Include standalone composite and base types.
    SELECT n.nspname, t.typname, 'type'::text
      FROM pg_catalog.pg_type AS t
      JOIN pg_catalog.pg_namespace AS n ON n.oid = t.typnamespace
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND n.nspname NOT LIKE 'pg_toast%'
       AND t.typrelid = 0
       AND (t.typtype <> 'b' OR t.typelem = 0)
    UNION ALL
    SELECT n.nspname, o.oprname, 'operator'::text
      FROM pg_catalog.pg_operator AS o
      JOIN pg_catalog.pg_namespace AS n ON n.oid = o.oprnamespace
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND n.nspname NOT LIKE 'pg_toast%'
    UNION ALL
    SELECT n.nspname, c.conname, 'conversion'::text
      FROM pg_catalog.pg_conversion AS c
      JOIN pg_catalog.pg_namespace AS n ON n.oid = c.connamespace
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND n.nspname NOT LIKE 'pg_toast%'
    UNION ALL
    SELECT n.nspname, c.collname, 'collation'::text
      FROM pg_catalog.pg_collation AS c
      JOIN pg_catalog.pg_namespace AS n ON n.oid = c.collnamespace
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND n.nspname NOT LIKE 'pg_toast%'
    UNION ALL
    SELECT n.nspname, o.opcname, 'operator class'::text
      FROM pg_catalog.pg_opclass AS o
      JOIN pg_catalog.pg_namespace AS n ON n.oid = o.opcnamespace
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND n.nspname NOT LIKE 'pg_toast%'
    UNION ALL
    SELECT n.nspname, o.opfname, 'operator family'::text
      FROM pg_catalog.pg_opfamily AS o
      JOIN pg_catalog.pg_namespace AS n ON n.oid = o.opfnamespace
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND n.nspname NOT LIKE 'pg_toast%'
    UNION ALL
    SELECT n.nspname, d.dictname, 'text search dictionary'::text
      FROM pg_catalog.pg_ts_dict AS d
      JOIN pg_catalog.pg_namespace AS n ON n.oid = d.dictnamespace
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND n.nspname NOT LIKE 'pg_toast%'
    UNION ALL
    SELECT n.nspname, c.cfgname, 'text search configuration'::text
      FROM pg_catalog.pg_ts_config AS c
      JOIN pg_catalog.pg_namespace AS n ON n.oid = c.cfgnamespace
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND n.nspname NOT LIKE 'pg_toast%'
    UNION ALL
    SELECT n.nspname, p.prsname, 'text search parser'::text
      FROM pg_catalog.pg_ts_parser AS p
      JOIN pg_catalog.pg_namespace AS n ON n.oid = p.prsnamespace
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND n.nspname NOT LIKE 'pg_toast%'
    UNION ALL
    SELECT n.nspname, t.tmplname, 'text search template'::text
      FROM pg_catalog.pg_ts_template AS t
      JOIN pg_catalog.pg_namespace AS n ON n.oid = t.tmplnamespace
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND n.nspname NOT LIKE 'pg_toast%'
    UNION ALL
    SELECT n.nspname, s.stxname, 'extended statistics'::text
      FROM pg_catalog.pg_statistic_ext AS s
      JOIN pg_catalog.pg_namespace AS n ON n.oid = s.stxnamespace
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND n.nspname NOT LIKE 'pg_toast%'
    UNION ALL
    SELECT n.nspname, e.extname, 'extension'::text
      FROM pg_catalog.pg_extension AS e
      JOIN pg_catalog.pg_namespace AS n ON n.oid = e.extnamespace
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND n.nspname NOT LIKE 'pg_toast%'
    UNION ALL
    SELECT 'database', l.oid::text, 'large object'::text
      FROM pg_catalog.pg_largeobject_metadata AS l
    UNION ALL
    SELECT 'database', p.pubname, 'publication'::text
      FROM pg_catalog.pg_publication AS p
    UNION ALL
    SELECT 'database', s.subname, 'subscription'::text
      FROM pg_catalog.pg_subscription AS s
    UNION ALL
    SELECT 'database', e.evtname, 'event trigger'::text
      FROM pg_catalog.pg_event_trigger AS e
    UNION ALL
    SELECT 'database', l.lanname, 'procedural language'::text
      FROM pg_catalog.pg_language AS l
     WHERE l.lanname NOT IN ('internal', 'c', 'sql', 'plpgsql')
    UNION ALL
    SELECT 'database', w.fdwname, 'foreign data wrapper'::text
      FROM pg_catalog.pg_foreign_data_wrapper AS w
    UNION ALL
    SELECT 'database', s.srvname, 'foreign server'::text
      FROM pg_catalog.pg_foreign_server AS s
    UNION ALL
    SELECT 'database', a.amname, 'access method'::text
      FROM pg_catalog.pg_am AS a
     WHERE a.amname NOT IN ('heap', 'btree', 'hash', 'gist', 'gin', 'spgist', 'brin')
    """
)


class UnsafeDatabase(RuntimeError):
    """Raised when the selected database is not demonstrably fresh."""


def require_fresh_postgres_url(value: str | None) -> str:
    if not value:
        raise UnsafeDatabase("Set HMS_FRESH_DATABASE_URL to the dedicated fresh-install database.")
    url = make_url(value)
    if not url.drivername.startswith("postgresql"):
        raise UnsafeDatabase("Fresh bootstrap is supported only for PostgreSQL URLs.")
    if not url.database:
        raise UnsafeDatabase("The PostgreSQL URL must name an explicit database.")
    if url.database.casefold() == "health_analyzer":
        raise UnsafeDatabase("The legacy health_analyzer database is not a fresh-install target.")
    return value


def assert_target_database(connection, expected_name: str) -> None:
    """Check the actual connection and privileges before any schema DDL."""
    if connection.dialect.name != "postgresql":
        raise UnsafeDatabase("Fresh bootstrap requires PostgreSQL.")
    actual = connection.execute(text("SELECT current_database()")).scalar_one()
    if actual != expected_name or actual.casefold() == "health_analyzer":
        raise UnsafeDatabase("Connected database does not match the authorized fresh-install target.")
    version = int(connection.execute(text("SHOW server_version_num")).scalar_one())
    if version < 100000:
        raise UnsafeDatabase("Fresh bootstrap requires PostgreSQL 10+.")
    if connection.execute(text("SELECT current_schema()")).scalar_one() != "public":
        raise UnsafeDatabase("Fresh bootstrap requires public as the current schema.")
    if not connection.execute(text(
        "SELECT has_database_privilege(current_database(), 'CONNECT') "
        "AND has_schema_privilege('public', 'USAGE') "
        "AND has_schema_privilege('public', 'CREATE')"
    )).scalar_one():
        raise UnsafeDatabase("Database CONNECT and public schema USAGE/CREATE privileges are required.")


def assert_database_empty(connection) -> None:
    """Reject user-created objects in any non-system schema or database catalog."""
    schemas = connection.execute(
        text(
            "SELECT nspname FROM pg_catalog.pg_namespace "
            "WHERE nspname NOT IN ('pg_catalog', 'information_schema') "
            "AND nspname NOT LIKE 'pg_toast%' AND nspname <> 'public'"
        )
    ).fetchall()
    if schemas:
        raise UnsafeDatabase(f"Target database has non-default schemas: {schemas!r}")

    objects = connection.execute(OBJECTS_QUERY).fetchall()
    if objects:
        names = ", ".join(f"{schema}.{name} ({kind})" for schema, name, kind in objects[:8])
        raise UnsafeDatabase(f"Target database is not empty; found: {names}")

    # Defense in depth: explicitly check the marker even if catalog filtering changes.
    inspector = connection.dialect.identifier_preparer
    version_table = inspector.quote("alembic_version")
    exists = connection.execute(
        text("SELECT to_regclass(:qualified_name)"),
        {"qualified_name": f"public.{version_table}"},
    ).scalar_one()
    if exists is not None:
        raise UnsafeDatabase("Target database already has public.alembic_version.")


def bootstrap(database_url: str) -> str:
    """Atomically create current models and stamp the single current Alembic head."""
    database_url = require_fresh_postgres_url(database_url)
    validated_module_ddl()
    metadata = current_metadata()
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            with connection.begin():
                assert_target_database(connection, make_url(database_url).database)
                assert_database_empty(connection)
                metadata.create_all(connection)
                install_patient_identity_database_objects(connection)
                install_medical_review_revision_guards(connection)

                config = Config(str(ALEMBIC_INI))
                scripts = ScriptDirectory.from_config(config)
                heads = scripts.get_heads()
                if len(heads) != 1:
                    raise RuntimeError(f"Expected one Alembic head, found {heads!r}")
                MigrationContext.configure(connection).stamp(scripts, heads[0])
                return heads[0]
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-empty",
        action="store_true",
        help="Confirm this is a dedicated, authorized empty PostgreSQL database.",
    )
    args = parser.parse_args()
    if not args.confirm_empty:
        raise SystemExit("Refusing to continue without --confirm-empty.")

    database_url = require_fresh_postgres_url(os.environ.get("HMS_FRESH_DATABASE_URL"))
    head = bootstrap(database_url)
    print(f"Fresh schema created and stamped at Alembic head {head}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
