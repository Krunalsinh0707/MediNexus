"""Install the existing departmental model contracts in one additive revision.

The DDL is frozen in module_schema_v1.json. PostgreSQL DDL and Alembic's
revision update are transactional. This revision refuses a drifted or partial
baseline and never modifies existing clinical rows. Downgrade is intentionally
unsupported because dropping these tables would destroy clinical history.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

from src.models import Base
from src.schema_registry import current_metadata, module_tables, validated_module_ddl


revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def validate_baseline(connection):
    """All inspection is read-only and finishes before the first DDL statement."""
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Module foundation requires PostgreSQL; no DDL issued")
    if int(connection.execute(text("SHOW server_version_num")).scalar_one()) < 100000:
        raise RuntimeError("Module foundation requires PostgreSQL 10+; no DDL issued")
    if connection.execute(text("SELECT current_schema()")).scalar_one() != "public":
        raise RuntimeError("Module foundation requires public as the current schema; no DDL issued")
    inspector = inspect(connection)
    if not inspector.has_table("alembic_version", schema="public"):
        raise RuntimeError("Alembic baseline marker is missing; no DDL issued")
    heads = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all()
    if heads != [down_revision]:
        raise RuntimeError(f"Expected exactly {down_revision}, found {heads!r}; no DDL issued")
    if not connection.execute(text(
        "SELECT has_schema_privilege('public', 'USAGE') AND has_schema_privilege('public', 'CREATE')"
    )).scalar_one():
        raise RuntimeError("public schema USAGE and CREATE privileges are required; no DDL issued")

    # The historical Alembic chain is not a general-purpose repair path.
    # Require the already assessed, model-shaped application baseline.
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name, schema="public"):
            raise RuntimeError(f"Required public.{table.name} is missing; no DDL issued")
        actual = {column["name"]: column for column in inspector.get_columns(table.name, schema="public")}
        if missing := {column.name for column in table.columns} - set(actual):
            raise RuntimeError(f"Required public.{table.name} columns missing: {sorted(missing)}; no DDL issued")
        indexes = {item["name"] for item in inspector.get_indexes(table.name, schema="public")}
        if missing := {index.name for index in table.indexes} - indexes:
            raise RuntimeError(f"Required public.{table.name} indexes missing: {sorted(missing)}; no DDL issued")

    expected_enums = {column.type.name: column.type.enums for table in Base.metadata.tables.values()
                      for column in table.columns if isinstance(column.type, sa.Enum)}
    actual_enums = {item["name"]: item["labels"] for item in inspector.get_enums(schema="public")}
    for name, labels in expected_enums.items():
        if actual_enums.get(name) != labels:
            raise RuntimeError(f"Unexpected public.{name} labels; no DDL issued")

    metadata = current_metadata()
    module = module_tables(metadata)
    reserved = {table.name for table in module}
    reserved.update(index.name for table in module for index in table.indexes)
    reserved.update(constraint.name for table in module for constraint in table.constraints
                    if constraint.name)
    collisions = connection.execute(text(
        "SELECT c.relname FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relname=ANY(:names) "
        "UNION SELECT t.typname FROM pg_catalog.pg_type t "
        "JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace "
        "WHERE n.nspname='public' AND t.typname=ANY(:names)"
    ), {"names": sorted(reserved)}).scalars().all()
    if collisions:
        raise RuntimeError(f"Module object names already exist: {sorted(collisions)}; no DDL issued")

    # The new FKs all target core integer primary keys. A column with the
    # right name but a drifted type/key is not a safe baseline for this DDL.
    core_targets = {(fk.column.table.name, fk.column.name) for table in module
                    for fk in table.foreign_keys if fk.column.table.name in Base.metadata.tables}
    for target, column in sorted(core_targets):
        actual_columns = {item["name"]: item for item in inspector.get_columns(target, schema="public")}
        actual_type = actual_columns[column].get("type")
        expected_type = Base.metadata.tables[target].columns[column].type
        if actual_type is None or type(actual_type.as_generic()) is not type(expected_type.as_generic()):
            raise RuntimeError(f"Required public.{target}.{column} type differs from the model; no DDL issued")
        primary_key = inspector.get_pk_constraint(target, schema="public").get("constrained_columns")
        if primary_key != [column]:
            raise RuntimeError(f"Required public.{target}.{column} primary key differs from the model; no DDL issued")

    # PostgreSQL must be able to create every FK to the preserved core tables.
    for target in sorted({name for name, _ in core_targets}):
        if not connection.execute(text("SELECT has_table_privilege(:name, 'REFERENCES')"),
                                  {"name": "public." + target}).scalar_one():
            raise RuntimeError(f"REFERENCES privilege on public.{target} is required; no DDL issued")


def upgrade():
    statements = validated_module_ddl()
    connection = op.get_bind()
    validate_baseline(connection)
    for statement in statements:
        connection.exec_driver_sql(statement)


def downgrade():
    raise RuntimeError("Module foundation downgrade would destroy clinical and financial history")
