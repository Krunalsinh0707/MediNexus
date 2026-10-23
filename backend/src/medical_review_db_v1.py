"""Frozen PostgreSQL guards for the first medical-review amendment revision.

Keep these definitions stable: the additive Alembic revision and fresh bootstrap
install the same objects inside their schema-creation transaction.
"""
from sqlalchemy import text


VALIDATE_INSERT_FUNCTION_SQL = """
CREATE FUNCTION public.validate_medical_review_revision_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE prior public.medical_review_revisions%ROWTYPE;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.doctor_reviews original
        WHERE original.id = NEW.original_review_id AND original.report_id = NEW.report_id
    ) THEN
        RAISE EXCEPTION 'Medical review amendment must reference the original review of the same report';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.doctors doctor
        JOIN public.users actor ON actor.id = doctor.user_id
        WHERE doctor.id = NEW.author_doctor_id AND actor.id = NEW.author_user_id
          AND doctor.status::text = 'Active'
          AND actor.role::text IN ('doctor', 'emergency_doctor')
          AND actor.password_hash IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Medical review amendment requires an active credentialed clinician';
    END IF;
    IF NEW.revision_number = 2 THEN
        IF NEW.previous_revision_id IS NOT NULL THEN
            RAISE EXCEPTION 'First amendment cannot reference another amendment';
        END IF;
    ELSE
        SELECT * INTO prior FROM public.medical_review_revisions
        WHERE id = NEW.previous_revision_id;
        IF NOT FOUND OR prior.report_id IS DISTINCT FROM NEW.report_id
           OR prior.original_review_id IS DISTINCT FROM NEW.original_review_id
           OR prior.revision_number IS DISTINCT FROM NEW.revision_number - 1 THEN
            RAISE EXCEPTION 'Medical review amendment must follow the immediately prior revision of this report';
        END IF;
    END IF;
    NEW.created_at := transaction_timestamp();
    NEW.signed_at := NEW.created_at;
    RETURN NEW;
END;
$$
"""

IMMUTABLE_FUNCTION_SQL = """
CREATE FUNCTION public.reject_medical_review_revision_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Signed medical review amendments cannot be updated, deleted, or truncated';
    RETURN NULL;
END;
$$
"""

TRIGGER_SQL = (
    "CREATE TRIGGER medical_review_revision_validate_insert "
    "BEFORE INSERT ON public.medical_review_revisions FOR EACH ROW "
    "EXECUTE PROCEDURE public.validate_medical_review_revision_insert()",
    "CREATE TRIGGER medical_review_revision_immutable_rows "
    "BEFORE UPDATE OR DELETE ON public.medical_review_revisions FOR EACH ROW "
    "EXECUTE PROCEDURE public.reject_medical_review_revision_change()",
    "CREATE TRIGGER medical_review_revision_immutable_truncate "
    "BEFORE TRUNCATE ON public.medical_review_revisions FOR EACH STATEMENT "
    "EXECUTE PROCEDURE public.reject_medical_review_revision_change()",
)


def install_medical_review_revision_guards(connection):
    for statement in (VALIDATE_INSERT_FUNCTION_SQL, IMMUTABLE_FUNCTION_SQL, *TRIGGER_SQL):
        connection.execute(text(statement))
