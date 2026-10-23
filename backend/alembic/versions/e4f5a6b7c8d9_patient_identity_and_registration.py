"""add patient MRN and credential optionality

Revision ID: e4f5a6b7c8d9
Revises: d2e3f4a5b6c7
"""

from alembic import op
import sqlalchemy as sa

revision = "e4f5a6b7c8d9"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None

LEGACY_ROLE_LABELS = ("user", "admin")
CURRENT_ROLE_LABELS = (
    "user", "admin", "patient", "doctor", "department_admin",
    "hospital_admin", "emergency_doctor",
)
TEMP_ROLE_TYPE = "user_role_enum_phase2a"


def _reconcile_user_role_enum(connection):
    """Transactionally replace only the known historical users.role enum."""
    column = connection.execute(sa.text("""
        SELECT t.oid, t.typname, t.typtype, a.attnum
          FROM pg_catalog.pg_attribute AS a
          JOIN pg_catalog.pg_class AS c ON c.oid = a.attrelid
          JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
          JOIN pg_catalog.pg_type AS t ON t.oid = a.atttypid
         WHERE n.nspname = 'public' AND c.relname = 'users'
           AND a.attname = 'role' AND NOT a.attisdropped
    """)).one_or_none()
    if column is None or column.typtype != "e":
        actual_type = column.typname if column is not None else "missing users.role column"
        raise RuntimeError(
            f"Patient identity migration expected public.users.role to be a PostgreSQL enum; found {actual_type}."
        )

    labels = tuple(connection.execute(sa.text("""
        SELECT enumlabel FROM pg_catalog.pg_enum
         WHERE enumtypid = :type_oid ORDER BY enumsortorder
    """), {"type_oid": column.oid}).scalars())
    if column.typname == "user_role_enum" and labels == CURRENT_ROLE_LABELS:
        return
    if labels not in (LEGACY_ROLE_LABELS, CURRENT_ROLE_LABELS):
        raise RuntimeError(
            "Patient identity migration refused to alter users.role: "
            f"enum {column.typname!r} has unexpected labels {labels!r}; "
            f"expected legacy {LEGACY_ROLE_LABELS!r} or current {CURRENT_ROLE_LABELS!r}."
        )
    if column.typname not in ("role", "user_role_enum"):
        raise RuntimeError(
            f"Patient identity migration found unsupported users.role enum type {column.typname!r}."
        )

    if column.typname != "user_role_enum":
        target_type_exists = connection.execute(sa.text("""
            SELECT 1 FROM pg_catalog.pg_type AS t
              JOIN pg_catalog.pg_namespace AS n ON n.oid = t.typnamespace
             WHERE n.nspname = 'public' AND t.typname = 'user_role_enum'
        """)).scalar_one_or_none()
        if target_type_exists:
            raise RuntimeError(
                "Patient identity migration cannot normalize users.role: public.user_role_enum "
                "already exists separately from the historical role type. Inspect both types and "
                "their dependencies before retrying."
            )

    dependencies = connection.execute(sa.text("""
        SELECT pg_catalog.pg_describe_object(d.classid, d.objid, d.objsubid) AS object_description,
               d.classid = 'pg_class'::regclass
                   AND d.objid = 'public.users'::regclass
                   AND d.objsubid = :role_attnum
                   AND d.deptype = 'n' AS is_expected_column
          FROM pg_catalog.pg_depend AS d
         WHERE d.refclassid = 'pg_type'::regclass
           AND d.refobjid = :type_oid
           AND NOT (d.classid = 'pg_type'::regclass AND d.deptype = 'i')
    """), {"role_attnum": column.attnum, "type_oid": column.oid}).all()
    unexpected_dependencies = [row.object_description for row in dependencies if not row.is_expected_column]
    expected_column_dependencies = [row for row in dependencies if row.is_expected_column]
    if len(expected_column_dependencies) != 1 or unexpected_dependencies:
        found = [row.object_description for row in dependencies]
        raise RuntimeError(
            "Patient identity migration refused to replace the users.role enum because it has "
            f"unsupported dependencies: {found!r}. Expected only public.users.role."
        )

    temp_exists = connection.execute(sa.text("""
        SELECT 1 FROM pg_catalog.pg_type AS t
          JOIN pg_catalog.pg_namespace AS n ON n.oid = t.typnamespace
         WHERE n.nspname = 'public' AND t.typname = :type_name
    """), {"type_name": TEMP_ROLE_TYPE}).scalar_one_or_none()
    if temp_exists:
        raise RuntimeError(
            f"Patient identity migration found pre-existing temporary enum {TEMP_ROLE_TYPE!r}; "
            "inspect it manually before retrying."
        )

    labels_sql = ", ".join("'" + label.replace("'", "''") + "'" for label in CURRENT_ROLE_LABELS)
    op.execute(f"CREATE TYPE public.{TEMP_ROLE_TYPE} AS ENUM ({labels_sql})")
    op.execute(
        f"ALTER TABLE public.users ALTER COLUMN role TYPE public.{TEMP_ROLE_TYPE} "
        "USING role::text::public.user_role_enum_phase2a"
    )
    op.execute(f"DROP TYPE public.{column.typname}")
    op.execute(f"ALTER TYPE public.{TEMP_ROLE_TYPE} RENAME TO user_role_enum")


def _assert_no_credential_collisions(connection):
    checks = (
        ("email", "lower(btrim(email))", "email"),
        ("mobile_no", "regexp_replace(mobile_no, '[^0-9]', '', 'g')", "phone"),
    )
    conflicts = []
    for column, expression, label in checks:
        rows = connection.execute(sa.text(f"""
            SELECT array_agg(id ORDER BY id) AS user_ids
              FROM users
             WHERE password_hash IS NOT NULL AND {column} IS NOT NULL
             GROUP BY {expression}
            HAVING count(*) > 1
             ORDER BY min(id)
             LIMIT 20
        """)).fetchall()
        conflicts.extend(f"{label} collision among user IDs {row.user_ids}" for row in rows)
    if conflicts:
        raise RuntimeError(
            "Patient identity migration aborted: normalized contact collisions exist among "
            "credentialed accounts. Resolve these accounts manually; no accounts were changed. "
            + "; ".join(conflicts)
        )


def _preflight_identity_schema(connection):
    """Require the known model-shaped d2 users table before any DDL."""
    columns = connection.execute(sa.text("""
        SELECT column_name, data_type, character_maximum_length, is_nullable
          FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'users'
    """)).all()
    actual = {row.column_name: (row.data_type, row.character_maximum_length, row.is_nullable) for row in columns}
    expected = {
        "id": ("integer", None, "NO"),
        "email": ("character varying", 255, "NO"),
        "mobile_no": ("character varying", 20, "NO"),
        "blood_group": ("character varying", 5, "NO"),
        "password_hash": ("character varying", 255, "NO"),
        "full_name": ("character varying", 255, "NO"),
        "role": ("USER-DEFINED", None, "YES"),
    }
    mismatches = {
        name: {"expected": spec, "actual": actual.get(name)}
        for name, spec in expected.items()
        if actual.get(name) != spec
    }
    if mismatches:
        raise RuntimeError(
            "Patient identity migration requires the model-shaped d2 public.users schema; "
            f"incompatible or missing columns: {mismatches!r}. No schema changes were made."
        )

    added_columns = {"mrn", "date_of_birth"}.intersection(actual)
    if added_columns:
        raise RuntimeError(
            "Patient identity migration found Phase 2A columns before its Alembic revision: "
            f"{sorted(added_columns)!r}. Resolve the migration state manually; no data was changed."
        )

    unique_columns = connection.execute(sa.text("""
        SELECT array_agg(a.attname::text ORDER BY a.attname::text)
          FROM pg_catalog.pg_constraint AS c
          JOIN LATERAL unnest(c.conkey) AS key(attnum) ON true
          JOIN pg_catalog.pg_attribute AS a
            ON a.attrelid = c.conrelid AND a.attnum = key.attnum
         WHERE c.conrelid = 'public.users'::regclass AND c.contype = 'u'
         GROUP BY c.oid
    """)).scalars().all()
    if not {("email",), ("mobile_no",)}.issubset({tuple(row) for row in unique_columns}):
        raise RuntimeError(
            "Patient identity migration expected historical unique constraints on users.email "
            "and users.mobile_no. Inspect the current constraints before retrying; no schema changes were made."
        )

    existing_objects = connection.execute(sa.text("""
        SELECT 'sequence ' || c.relname AS object_name
          FROM pg_catalog.pg_class AS c
          JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind = 'S' AND c.relname = 'patient_mrn_seq'
        UNION ALL
        SELECT 'index ' || c.relname
          FROM pg_catalog.pg_class AS c
          JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind = 'i'
           AND c.relname IN ('uq_users_credentialed_email_normalized',
                             'uq_users_credentialed_mobile_normalized', 'uq_users_mrn')
        UNION ALL
        SELECT 'constraint ' || conname
          FROM pg_catalog.pg_constraint
         WHERE conrelid = 'public.users'::regclass
           AND conname = 'ck_users_credentialed_accounts_have_contacts'
        UNION ALL
        SELECT 'function assign_and_protect_patient_mrn'
          FROM pg_catalog.pg_proc AS p
          JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public' AND p.proname = 'assign_and_protect_patient_mrn'
        UNION ALL
        SELECT 'trigger users_patient_mrn_guard'
          FROM pg_catalog.pg_trigger
         WHERE tgrelid = 'public.users'::regclass AND tgname = 'users_patient_mrn_guard'
           AND NOT tgisinternal
    """)).scalars().all()
    if existing_objects:
        raise RuntimeError(
            "Patient identity migration found Phase 2A database objects while the d2 revision is active: "
            f"{list(existing_objects)!r}. Inspect the migration state; no schema changes were made."
        )


def upgrade():
    connection = op.get_bind()
    # Fail closed on schema drift and collisions before the first DDL statement.
    _preflight_identity_schema(connection)
    _assert_no_credential_collisions(connection)
    # CREATE TYPE / ALTER TABLE / DROP TYPE / RENAME are transactional on the
    # supported PostgreSQL 10+ baseline. Avoid ALTER TYPE ADD VALUE, which
    # PostgreSQL 10 rejects inside a transaction block. Alembic runs the entire
    # revision in one transaction; any later error rolls back enum and table DDL.
    _reconcile_user_role_enum(connection)

    op.add_column("users", sa.Column("mrn", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("date_of_birth", sa.Date(), nullable=True))

    # Replace the historical all-user unique constraints with credential-only
    # normalized uniqueness, allowing staff records to omit portal contacts.
    rows = connection.execute(sa.text("""
        SELECT conname FROM pg_catalog.pg_constraint
         WHERE conrelid = 'users'::regclass AND contype = 'u'
           AND (SELECT array_agg(a.attname ORDER BY a.attname)
                  FROM unnest(conkey) AS key(attnum)
                  JOIN pg_attribute AS a ON a.attrelid = conrelid AND a.attnum = key.attnum)
               IN (ARRAY['email']::name[], ARRAY['mobile_no']::name[])
    """)).fetchall()
    for row in rows:
        op.drop_constraint(row.conname, "users", type_="unique")

    op.alter_column("users", "email", existing_type=sa.String(255), nullable=True)
    op.alter_column("users", "mobile_no", existing_type=sa.String(20), nullable=True)
    op.alter_column("users", "blood_group", existing_type=sa.String(5), nullable=True)
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=True)
    op.create_check_constraint(
        "ck_users_credentialed_accounts_have_contacts",
        "users",
        "password_hash IS NULL OR (email IS NOT NULL AND mobile_no IS NOT NULL)",
    )

    op.execute(sa.text("CREATE SEQUENCE patient_mrn_seq START WITH 1 INCREMENT BY 1"))
    op.execute(sa.text("""
        WITH numbered AS (
            SELECT id, row_number() OVER (ORDER BY id) AS sequence_no
              FROM users WHERE role::text IN ('user', 'patient')
        )
        UPDATE users AS u
           SET mrn = 'HMS-' || lpad(numbered.sequence_no::text, 8, '0')
          FROM numbered WHERE u.id = numbered.id
    """))
    max_mrn = connection.execute(sa.text("""
        SELECT coalesce(max(substring(mrn from 5)::bigint), 0) FROM users
    """)).scalar_one()
    if max_mrn:
        op.execute(sa.text("SELECT setval('patient_mrn_seq', :value, true)").bindparams(value=max_mrn))
    else:
        op.execute(sa.text("SELECT setval('patient_mrn_seq', 1, false)"))

    op.create_index(
        "uq_users_credentialed_email_normalized", "users", [sa.text("lower(btrim(email))")],
        unique=True, postgresql_where=sa.text("password_hash IS NOT NULL AND email IS NOT NULL")
    )
    op.create_index(
        "uq_users_credentialed_mobile_normalized", "users",
        [sa.text("regexp_replace(mobile_no, '[^0-9]', '', 'g')")], unique=True,
        postgresql_where=sa.text("password_hash IS NOT NULL AND mobile_no IS NOT NULL")
    )
    op.create_index("uq_users_mrn", "users", ["mrn"], unique=True)

    op.execute(sa.text("""
        CREATE FUNCTION assign_and_protect_patient_mrn() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF OLD.mrn IS NOT NULL AND NEW.mrn IS DISTINCT FROM OLD.mrn THEN
                    RAISE EXCEPTION 'patient MRN is immutable';
                END IF;
                IF OLD.mrn IS NULL AND NEW.role::text IN ('user', 'patient') THEN
                    NEW.mrn := 'HMS-' || lpad(nextval('patient_mrn_seq')::text, 8, '0');
                ELSIF OLD.mrn IS NULL AND NEW.mrn IS NOT NULL THEN
                    RAISE EXCEPTION 'MRN is reserved for patient records';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.role::text IN ('user', 'patient') THEN
                IF NEW.mrn IS NOT NULL THEN
                    RAISE EXCEPTION 'patient MRN is database generated';
                END IF;
                NEW.mrn := 'HMS-' || lpad(nextval('patient_mrn_seq')::text, 8, '0');
            ELSIF NEW.mrn IS NOT NULL THEN
                RAISE EXCEPTION 'MRN is reserved for patient records';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER users_patient_mrn_guard
        BEFORE INSERT OR UPDATE OF mrn, role ON users
        FOR EACH ROW EXECUTE PROCEDURE assign_and_protect_patient_mrn()
    """))


def downgrade():
    # This downgrade is intentionally data-safe: refuse rather than truncate or
    # discard staff-only patients when restoring the old required fields.
    connection = op.get_bind()
    staff_only = connection.execute(sa.text(
        "SELECT id FROM users WHERE password_hash IS NULL OR email IS NULL OR mobile_no IS NULL LIMIT 1"
    )).scalar()
    if staff_only is not None:
        raise RuntimeError(
            f"Cannot downgrade patient identity migration: user ID {staff_only} has no complete portal credentials."
        )
    op.execute("DROP TRIGGER IF EXISTS users_patient_mrn_guard ON users")
    op.execute("DROP FUNCTION IF EXISTS assign_and_protect_patient_mrn()")
    op.drop_index("uq_users_mrn", table_name="users")
    op.drop_index("uq_users_credentialed_mobile_normalized", table_name="users")
    op.drop_index("uq_users_credentialed_email_normalized", table_name="users")
    op.drop_constraint("ck_users_credentialed_accounts_have_contacts", "users", type_="check")
    op.create_unique_constraint("users_email_key", "users", ["email"])
    op.create_unique_constraint("users_mobile_no_key", "users", ["mobile_no"])
    op.alter_column("users", "email", existing_type=sa.String(255), nullable=False)
    op.alter_column("users", "mobile_no", existing_type=sa.String(20), nullable=False)
    op.alter_column("users", "blood_group", existing_type=sa.String(5), nullable=False)
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=False)
    op.drop_column("users", "date_of_birth")
    op.drop_column("users", "mrn")
    op.execute("DROP SEQUENCE IF EXISTS patient_mrn_seq")
