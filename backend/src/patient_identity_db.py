"""PostgreSQL objects for database generated and immutable patient MRNs."""

MRN_SEQUENCE_DDL = "CREATE SEQUENCE patient_mrn_seq START WITH 1 INCREMENT BY 1"
MRN_FUNCTION_DDL = """
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
"""
MRN_TRIGGER_DDL = """
CREATE TRIGGER users_patient_mrn_guard
BEFORE INSERT OR UPDATE OF mrn, role ON users
FOR EACH ROW EXECUTE PROCEDURE assign_and_protect_patient_mrn()
"""


def install_patient_identity_database_objects(connection):
    """Install trigger-backed MRN generation for a fresh metadata schema."""
    connection.exec_driver_sql(MRN_SEQUENCE_DDL)
    connection.exec_driver_sql(MRN_FUNCTION_DDL)
    connection.exec_driver_sql(MRN_TRIGGER_DDL)
