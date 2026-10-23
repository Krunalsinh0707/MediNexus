# Module database foundation (not yet applied)

Revision `b9c0d1e2f3a4` descends from `a8b9c0d1e2f3`. It adds 65 tables for
clinical orders, medication, pharmacy, laboratory, radiology, inpatient,
nursing, billing, insurance, inventory, and workforce. The 38 core tables
(users, doctors, departments, appointments, encounters, reports, notifications,
chat, and audit) remain owned by the historical revisions. The migration uses
a frozen PostgreSQL DDL snapshot and refuses a missing or incompatible core
baseline before its first DDL statement. Its downgrade refuses to drop records.

The API and Alembic now require an explicit `HMS_DATABASE_URL`. The raw
psycopg connection and SQLAlchemy engine derive from that same URL. Docker
Compose requires its own deployment URL and no longer provisions a database.
Existing `DATABASE_URL` and `DB_*` settings are not used by the application.

## Later initialization of the already provisioned `medinexus` database

Run these commands from `backend` in a PowerShell session only after an
authorized operator confirms that `medinexus` is dedicated to this project.
Enter the URL securely; do not put a password in source, shell history, or logs.

```powershell
$secureUrl = Read-Host 'HMS_DATABASE_URL for medinexus' -AsSecureString
$env:HMS_DATABASE_URL = [System.Net.NetworkCredential]::new('', $secureUrl).Password
Remove-Variable secureUrl
@'
import os
from sqlalchemy.engine import make_url
url = make_url(os.environ['HMS_DATABASE_URL'])
assert url.drivername == 'postgresql+psycopg' and url.database == 'medinexus'
print('Configured target: medinexus')
'@ | .\venv\Scripts\python.exe -
$env:HMS_FRESH_DATABASE_URL = $env:HMS_DATABASE_URL
.\venv\Scripts\python.exe -m scripts.bootstrap_fresh_db --confirm-empty
Remove-Item Env:\HMS_FRESH_DATABASE_URL
```

The bootstrap verifies the connected database name, PostgreSQL 10+ version,
public schema, and effective privileges, then aborts if **any** user-created
object or Alembic marker exists. It explicitly refuses `health_analyzer`.
It creates the complete current schema, installs the
existing identity and review guards, and stamps the single current head in one
transaction. A failure must leave the target empty; this still needs a real
PostgreSQL rollback test. Do not run bootstrap on a populated database.

For a populated, model-shaped database already at `a8b9c0d1e2f3`, a separate
assessed `alembic upgrade b9c0d1e2f3a4` path is available. Its preflight
rejects a missing core table/column, unexpected revision, or existing module
object. The historical Alembic baseline is **not** repaired by this revision.
Do not run `alembic upgrade head` on an unversioned or historically drifted
database. Confirm the actual database state and test the upgrade on an isolated
copy first.

Pharmacy dispensing remains unavailable until an atomic inventory gateway
has been implemented and verified. Insurance requires
`HMS_INSURANCE_FIELD_KEY`; billing requires approved tariffs and tax handling
where configured. Staff assignments and department/ward data must be created
through authorized workflows before those modules can serve users.
