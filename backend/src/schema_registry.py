"""Combined schema view for migration tooling; ORM registries remain separate."""

import hashlib
import json
from pathlib import Path

from sqlalchemy import MetaData
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from src.models import Base
from src.clinical_order_models import ClinicalOrderBase
from src.inpatient_models import InpatientBase
from src.nursing_models import NursingObservation  # registers nursing tables on InpatientBase
from src.billing_models import BillingBase
from src.insurance_models import InsuranceBase
from src.inventory_models import InventoryBase
from src.workforce_models import WorkforceBase


MODULE_REGISTRIES = (
    ClinicalOrderBase, InpatientBase, BillingBase, InsuranceBase,
    InventoryBase, WorkforceBase,
)
MODULE_SNAPSHOT_SHA256 = "b54b4d99d05251fcd4094b87578537e9819eb3dbfd844bad7ff58cf53dde79e8"
MODULE_SNAPSHOT = Path(__file__).resolve().parents[1] / "alembic" / "baselines" / "module_schema_v1.json"


def current_metadata():
    """Copy all table definitions into one metadata for cross-registry FKs."""
    metadata = MetaData()
    for registry in (Base, *MODULE_REGISTRIES):
        for table in registry.metadata.tables.values():
            table.to_metadata(metadata)
    return metadata


def module_tables(metadata):
    existing = set(Base.metadata.tables)
    return [table for table in metadata.sorted_tables if table.key not in existing]


def module_ddl():
    """Canonical PostgreSQL DDL used to verify the frozen migration snapshot."""
    dialect = postgresql.dialect()
    tables = module_tables(current_metadata())
    statements = [_canonical_table_ddl(str(CreateTable(table).compile(dialect=dialect)).strip())
                  for table in tables]
    statements.extend(str(CreateIndex(index).compile(dialect=dialect)).strip()
                      for table in tables for index in sorted(table.indexes, key=lambda item: item.name))
    return statements


def _canonical_table_ddl(statement):
    """Sort independently declared constraints; SQLAlchemy stores them in a set."""
    lines = statement.splitlines()
    clauses = [line.strip().removesuffix(",") for line in lines[1:-1] if line.strip()]
    constraint_prefixes = ("CONSTRAINT ", "FOREIGN KEY(", "PRIMARY KEY (", "UNIQUE (")
    columns = [part for part in clauses if not part.startswith(constraint_prefixes)]
    constraints = sorted(part for part in clauses if part.startswith(constraint_prefixes))
    return lines[0] + "\n\t" + ", \n\t".join((*columns, *constraints)) + "\n)"


def validated_module_ddl():
    """Never stamp a fresh schema or upgrade using drifted module definitions."""
    statements = json.loads(MODULE_SNAPSHOT.read_text(encoding="utf-8"))
    serialized = json.dumps(statements, indent=2).encode("utf-8")
    if hashlib.sha256(serialized).hexdigest() != MODULE_SNAPSHOT_SHA256:
        raise RuntimeError("Frozen module migration snapshot changed; no schema operation is safe")
    if statements != module_ddl():
        raise RuntimeError("Module ORM metadata differs from the frozen migration; no schema operation is safe")
    return statements
