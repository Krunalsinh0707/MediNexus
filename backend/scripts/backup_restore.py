"""Guarded PostgreSQL and uploaded-file backup/restore for MediNexus.

Credentials are read only from environment variables and are passed to
PostgreSQL tools through their environment, never command-line arguments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from scripts.bootstrap_fresh_db import UnsafeDatabase, assert_database_empty

FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
DUMP_NAME = "database.dump"
UPLOAD_ARCHIVE_NAME = "uploads.tar.gz"
FORBIDDEN_RESTORE_DATABASES = {"health_analyzer"}


class RecoveryError(RuntimeError):
    pass


def require_postgres_url(value: str | None, variable: str) -> URL:
    if not value:
        raise RecoveryError(f"Set {variable} to an explicitly authorized PostgreSQL database.")
    url = make_url(value)
    if not url.drivername.startswith("postgresql") or not url.database:
        raise RecoveryError(f"{variable} must be an explicit PostgreSQL database URL.")
    return url


def pg_environment(url: URL) -> dict[str, str]:
    env = os.environ.copy()
    values = {
        "PGHOST": url.host or "localhost",
        "PGPORT": str(url.port or 5432),
        "PGUSER": url.username or "",
        "PGPASSWORD": url.password or "",
        "PGDATABASE": url.database or "",
    }
    env.update(values)
    return env


def run_postgres_tool(arguments: list[str], url: URL) -> None:
    configured_bin = os.getenv("HMS_PG_BIN_DIR")
    executable = None
    if configured_bin:
        candidate = Path(configured_bin) / (arguments[0] + (".exe" if os.name == "nt" else ""))
        if candidate.is_file():
            executable = str(candidate)
    executable = executable or shutil.which(arguments[0])
    if not executable:
        raise RecoveryError(f"Required PostgreSQL tool is unavailable: {arguments[0]}")
    command = [executable, *arguments[1:]]
    result = subprocess.run(
        command,
        env=pg_environment(url),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        message = (result.stderr or result.stdout or "PostgreSQL tool failed").strip()
        if url.password:
            message = message.replace(url.password, "[REDACTED]")
        raise RecoveryError(f"{arguments[0]} failed with exit code {result.returncode}: {message}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def upload_entries(upload_root: Path) -> list[dict]:
    if not upload_root.exists():
        return []
    if not upload_root.is_dir():
        raise RecoveryError(f"Upload root is not a directory: {upload_root}")
    entries = []
    for path in sorted(upload_root.rglob("*")):
        if path.is_symlink():
            raise RecoveryError(f"Refusing symlink in upload root: {path.relative_to(upload_root)}")
        if path.is_file():
            entries.append({
                "path": path.relative_to(upload_root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    return entries


def create_upload_archive(upload_root: Path, destination: Path, entries: list[dict]) -> None:
    with tarfile.open(destination, "w:gz") as archive:
        for entry in entries:
            archive.add(upload_root / entry["path"], arcname=entry["path"], recursive=False)


def database_fingerprint(url: URL) -> dict:
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            row = connection.execute(text(
                "SELECT current_database(), current_user, current_setting('server_version_num')"
            )).one()
            revisions = connection.execute(
                text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
            ).scalars().all()
            return {
                "database": row[0],
                "role": row[1],
                "server_version_num": int(row[2]),
                "alembic_revisions": list(revisions),
            }
    finally:
        engine.dispose()


def verify_backup(backup_dir: Path) -> dict:
    manifest_path = backup_dir / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecoveryError("Backup manifest is missing or invalid.") from exc
    if manifest.get("format_version") != FORMAT_VERSION:
        raise RecoveryError("Unsupported backup manifest format.")
    for name in (DUMP_NAME, UPLOAD_ARCHIVE_NAME):
        path = backup_dir / name
        expected = manifest.get("artifacts", {}).get(name, {}).get("sha256")
        if not path.is_file() or not expected or sha256_file(path) != expected:
            raise RecoveryError(f"Backup artifact checksum failed: {name}")

    expected_uploads = {row["path"]: row for row in manifest.get("uploads", [])}
    seen = set()
    with tarfile.open(backup_dir / UPLOAD_ARCHIVE_NAME, "r:gz") as archive:
        for member in archive.getmembers():
            member_path = Path(member.name)
            if member.issym() or member.islnk() or member_path.is_absolute() or ".." in member_path.parts:
                raise RecoveryError(f"Unsafe upload archive member: {member.name}")
            if not member.isfile():
                continue
            expected = expected_uploads.get(member.name)
            extracted = archive.extractfile(member)
            if expected is None or extracted is None:
                raise RecoveryError(f"Unexpected upload archive member: {member.name}")
            content = extracted.read()
            if len(content) != expected["size"] or hashlib.sha256(content).hexdigest() != expected["sha256"]:
                raise RecoveryError(f"Uploaded-file checksum failed: {member.name}")
            seen.add(member.name)
    if seen != set(expected_uploads):
        raise RecoveryError("Upload archive does not match its file manifest.")
    return manifest


def extract_verified_uploads(archive_path: Path, destination: Path) -> None:
    """Extract regular files only, without relying on version-specific tar filters."""
    destination = destination.resolve()
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            member_path = Path(member.name)
            if not member.isfile():
                if member.isdir():
                    continue
                raise RecoveryError(f"Unsafe upload archive member: {member.name}")
            target = (destination / member_path).resolve()
            if destination != target and destination not in target.parents:
                raise RecoveryError(f"Unsafe upload archive member: {member.name}")
            source = archive.extractfile(member)
            if source is None:
                raise RecoveryError(f"Cannot read upload archive member: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _remove_expired_backups(root: Path, keep: int, current: Path) -> None:
    if keep < 1:
        raise RecoveryError("HMS_BACKUP_RETENTION_COUNT must be at least 1.")
    candidates = sorted(
        (p for p in root.glob("medinexus-*") if p.is_dir() and p != current),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in candidates[max(0, keep - 1):]:
        try:
            verify_backup(path)
        except RecoveryError:
            # Never delete an unverified directory automatically.
            continue
        resolved = path.resolve()
        if root.resolve() not in resolved.parents:
            raise RecoveryError("Refusing to remove a backup outside the configured root.")
        shutil.rmtree(resolved)


def create_backup(url: URL, upload_root: Path, backup_root: Path, retention_count: int) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    staging = Path(tempfile.mkdtemp(prefix=".incomplete-", dir=backup_root))
    final = backup_root / f"medinexus-{backup_id}"
    try:
        fingerprint = database_fingerprint(url)
        entries = upload_entries(upload_root)
        run_postgres_tool(
            ["pg_dump", "--format=custom", "--no-owner", "--no-privileges", "--file", str(staging / DUMP_NAME)],
            url,
        )
        create_upload_archive(upload_root, staging / UPLOAD_ARCHIVE_NAME, entries)
        manifest = {
            "format_version": FORMAT_VERSION,
            "backup_id": backup_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "database": fingerprint,
            "uploads": entries,
            "artifacts": {
                DUMP_NAME: {"sha256": sha256_file(staging / DUMP_NAME)},
                UPLOAD_ARCHIVE_NAME: {"sha256": sha256_file(staging / UPLOAD_ARCHIVE_NAME)},
            },
        }
        (staging / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        verify_backup(staging)
        staging.rename(final)
        for path in final.rglob("*"):
            if path.is_file():
                path.chmod(0o600)
        _remove_expired_backups(backup_root, retention_count, final)
        return final
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def assert_restore_target(url: URL) -> dict:
    if (url.database or "").lower() in FORBIDDEN_RESTORE_DATABASES:
        raise RecoveryError(f"Refusing protected restore target: {url.database}")
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            identity = connection.execute(text(
                "SELECT current_database(), current_user, current_setting('server_version_num'), "
                "has_database_privilege(current_user, current_database(), 'CONNECT'), "
                "has_schema_privilege(current_user, 'public', 'USAGE'), "
                "has_schema_privilege(current_user, 'public', 'CREATE')"
            )).one()
            if identity[0] != url.database or int(identity[2]) < 100000:
                raise RecoveryError("Restore target identity or PostgreSQL version check failed.")
            if not all(identity[3:]):
                raise RecoveryError("Restore role lacks CONNECT or public schema USAGE/CREATE.")
            assert_database_empty(connection)
            return {"database": identity[0], "role": identity[1], "server_version_num": int(identity[2])}
    except UnsafeDatabase as exc:
        raise RecoveryError(str(exc)) from exc
    finally:
        engine.dispose()


def restore_backup(backup_dir: Path, url: URL, upload_target: Path) -> dict:
    manifest = verify_backup(backup_dir)
    identity = assert_restore_target(url)
    if upload_target.exists() and (not upload_target.is_dir() or any(upload_target.iterdir())):
        raise RecoveryError("Restore upload target must be absent or an empty directory.")
    upload_target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=upload_target.parent))
    try:
        extract_verified_uploads(backup_dir / UPLOAD_ARCHIVE_NAME, staging)
        restored_entries = upload_entries(staging)
        if restored_entries != manifest.get("uploads", []):
            raise RecoveryError("Restored uploaded files do not match the manifest.")

        run_postgres_tool(
            ["pg_restore", "--exit-on-error", "--single-transaction", "--no-owner", "--no-privileges", str(backup_dir / DUMP_NAME)],
            url,
        )
        actual = database_fingerprint(url)
        if actual["alembic_revisions"] != manifest["database"]["alembic_revisions"]:
            raise RecoveryError("Restored Alembic revision does not match the backup manifest.")
        if upload_target.exists():
            upload_target.rmdir()
        staging.rename(upload_target)
        return {"target": identity, "database": actual, "upload_count": len(restored_entries)}
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("backup")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("backup_dir", type=Path)
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("backup_dir", type=Path)
    restore_parser.add_argument("--confirm-empty", action="store_true")
    args = parser.parse_args()

    if args.command == "verify":
        manifest = verify_backup(args.backup_dir.resolve())
        print(f"Backup {manifest['backup_id']} passed manifest and checksum verification.")
        return 0

    upload_root = Path(os.getenv("HMS_UPLOAD_ROOT", BACKEND_ROOT / "uploads")).resolve()
    if args.command == "backup":
        url = require_postgres_url(os.getenv("HMS_BACKUP_DATABASE_URL"), "HMS_BACKUP_DATABASE_URL")
        backup_root = Path(os.getenv("HMS_BACKUP_ROOT", BACKEND_ROOT / "backups")).resolve()
        retention = int(os.getenv("HMS_BACKUP_RETENTION_COUNT", "7"))
        destination = create_backup(url, upload_root, backup_root, retention)
        print(f"Verified backup created: {destination.name}")
        return 0

    if not args.confirm_empty:
        raise RecoveryError("Refusing restore without --confirm-empty.")
    url = require_postgres_url(os.getenv("HMS_RESTORE_DATABASE_URL"), "HMS_RESTORE_DATABASE_URL")
    target = Path(os.environ.get("HMS_RESTORE_UPLOAD_ROOT", "")).resolve() if os.environ.get("HMS_RESTORE_UPLOAD_ROOT") else None
    if target is None:
        raise RecoveryError("Set HMS_RESTORE_UPLOAD_ROOT to an isolated empty directory.")
    result = restore_backup(args.backup_dir.resolve(), url, target)
    print(f"Restore verified for {result['target']['database']} with {result['upload_count']} uploaded files.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RecoveryError as exc:
        raise SystemExit(f"Recovery refused: {exc}")
