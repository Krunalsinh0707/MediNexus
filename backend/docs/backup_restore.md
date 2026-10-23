# MediNexus backup and restore

The recovery utility creates one verified backup set containing:

- A PostgreSQL custom-format dump.
- A compressed archive of `HMS_UPLOAD_ROOT` with its directory structure.
- A JSON manifest containing the backup time, database identity, PostgreSQL
  version, Alembic revision, file sizes, and SHA-256 checksums.

Database credentials are read from environment variables and passed to
PostgreSQL tools through `PG*` environment variables. They are not written to
the manifest or command line.

## Prerequisites

- Matching PostgreSQL `pg_dump` and `pg_restore` client tools must be on
  `PATH`, or `HMS_PG_BIN_DIR` must identify their directory.
- The application must be in a maintenance/read-only window while the backup
  is created. This prevents database report metadata and uploaded files from
  changing at different points in the coordinated backup.
- `HMS_UPLOAD_ROOT` must be the private directory used by the backend.
- `HMS_BACKUP_ROOT` must be outside the application source tree and readable
  only by the backup operator and recovery service account.
- The database role needs enough read access for `pg_dump`, including every
  application table and sequence.

## Create and verify a backup in PowerShell

Set the URLs in the current PowerShell process without writing them to source
or command history. The examples below intentionally omit credentials.

```powershell
$env:HMS_BACKUP_DATABASE_URL = '<set securely for the intended source>'
$env:HMS_UPLOAD_ROOT = 'D:\secure\medinexus\uploads'
$env:HMS_BACKUP_ROOT = 'E:\medinexus-backups'
$env:HMS_BACKUP_RETENTION_COUNT = '7'
$env:HMS_PG_BIN_DIR = 'C:\Program Files\PostgreSQL\18\bin'

Set-Location 'D:\PROJECTS\MediNexus\backend'
.\venv\Scripts\python.exe -m scripts.backup_restore backup
.\venv\Scripts\python.exe -m scripts.backup_restore verify 'E:\medinexus-backups\medinexus-<backup-id>'
```

Retention runs only after the new backup passes manifest, archive, and checksum
verification. `HMS_BACKUP_RETENTION_COUNT` must be at least one.

## Restore safety requirements

Provision a dedicated disposable or recovery database. The restore command
refuses:

- A target named `health_analyzer`.
- A non-PostgreSQL URL or URL without an explicit database.
- PostgreSQL versions older than 10.
- A database with user-created objects, non-default schemas, large objects, or
  an Alembic version table.
- A role without database `CONNECT` and public-schema `USAGE` and `CREATE`.
- A missing, invalid, or checksum-mismatched backup.
- A file destination that is not demonstrably empty.

`pg_restore` uses `--single-transaction` and `--exit-on-error`, so a database
restore failure rolls back database changes. Database and filesystem changes
cannot share one transaction. Uploaded files are extracted and verified in a
temporary sibling directory before the database restore; they are moved into
the final empty destination only after the restored Alembic revision matches
the manifest.

## Restore into an isolated target

```powershell
$env:HMS_RESTORE_DATABASE_URL = '<set securely for the authorized empty target>'
$env:HMS_RESTORE_UPLOAD_ROOT = 'D:\medinexus-restore-validation\uploads'
$env:HMS_PG_BIN_DIR = 'C:\Program Files\PostgreSQL\18\bin'

Set-Location 'D:\PROJECTS\MediNexus\backend'
.\venv\Scripts\python.exe -m scripts.backup_restore restore 'E:\medinexus-backups\medinexus-<backup-id>' --confirm-empty
```

After restoration, start the application only with its database and upload
configuration explicitly pointed at the isolated recovery targets. Verify:

1. `alembic_version` matches the manifest.
2. Synthetic patients, reports, reviews, appointments, encounters, and chat
   relationships remain intact.
3. Every representative report metadata row resolves to its restored file.
4. Authenticated patient and authorized clinician reads work.
5. No production/shared services are configured in that process.

Do not redirect the normal application configuration to the recovery database.
Do not delete the backup used for a recovery drill until the drill report and
checksum evidence have been retained.

New report uploads store paths relative to `HMS_UPLOAD_ROOT`. Legacy records
may contain paths such as `uploads/reports/...`; validate those values during a
restore drill and keep the recovery application's working directory compatible.
Do not rewrite legacy report paths without a separate reviewed data migration.

## Current validation boundary

Unit tests cover credential isolation, manifest creation, checksums, tamper
rejection, protected-target refusal, and non-empty file-target refusal. A full
recovery is complete only after `pg_dump` and `pg_restore` have run against
separate authorized PostgreSQL databases with synthetic records and the
application read checks above have passed.
