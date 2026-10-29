from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .catalog import (
    IN_FLIGHT_STATUSES,
    Catalog,
    read_manifest_file,
    write_manifest_checkpoint,
)
from .config import Settings
from .migrations import load_manifest
from .models import (
    ArtifactCleanupResponse,
    CatalogBackupResponse,
    CatalogRepairResponse,
    SessionManifest,
)

# SQLite is runtime catalog authority. The session-dir file is the portable
# checkpoint and the recovery source when a catalog row is missing.
CATALOG_RUNTIME_AUTHORITY = "sqlite"
MANIFEST_CHECKPOINT_AUTHORITY = "session-dir-file"


def _load_sqlite_manifest(catalog: Catalog, session_id: str) -> SessionManifest | None:
    try:
        payload = catalog.raw_manifest_payload(session_id)
    except (KeyError, ValueError, json.JSONDecodeError):
        return None
    if payload is None:
        return None
    try:
        return load_manifest(payload)
    except (ValueError, TypeError):
        return None


def _payloads_differ(left: SessionManifest, right: SessionManifest) -> bool:
    left_dump = left.model_dump(mode="json")
    right_dump = right.model_dump(mode="json")
    left_dump.pop("updated_at", None)
    right_dump.pop("updated_at", None)
    return left_dump != right_dump


def repair_catalog(catalog: Catalog, settings: Settings) -> CatalogRepairResponse:
    """Reconcile SQLite rows and session-dir checkpoints.

    Repair rules:
    1. File-only valid manifests restore the SQLite row. The file is the recovery
       source when the catalog lost a session.
    2. SQLite-only valid sessions rewrite the missing checkpoint file.
    3. When both exist and differ, SQLite wins unless it is not in-flight and the
       file's updated_at is strictly newer (a restored session directory).
    4. In-flight SQLite statuses always win so a live import is not clobbered.
    """
    report = CatalogRepairResponse()
    sessions_root = settings.var_root / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)
    sqlite_ids = set(catalog.list_session_ids())
    file_ids: set[str] = set()
    for entry in sessions_root.iterdir():
        if entry.is_dir() and not entry.name.startswith("."):
            file_ids.add(entry.name)

    for session_id in sorted(sqlite_ids | file_ids):
        session_dir = sessions_root / session_id
        sqlite_manifest = (
            _load_sqlite_manifest(catalog, session_id) if session_id in sqlite_ids else None
        )
        try:
            file_manifest = read_manifest_file(session_dir)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            file_manifest = None
            if (session_dir / "manifest.json").is_file():
                report.unreadable.append(session_id)

        if sqlite_manifest is None and session_id in sqlite_ids:
            report.unreadable.append(session_id)

        if sqlite_manifest is not None and file_manifest is None:
            write_manifest_checkpoint(session_dir, sqlite_manifest)
            report.rewritten_files.append(session_id)
            continue
        if file_manifest is not None and sqlite_manifest is None:
            catalog.upsert_session(file_manifest, touch=False)
            report.restored_from_file.append(session_id)
            continue
        if sqlite_manifest is None or file_manifest is None:
            if session_dir.is_dir() and session_id not in sqlite_ids:
                report.orphan_directories.append(session_id)
            continue

        sqlite_in_flight = sqlite_manifest.status in IN_FLIGHT_STATUSES
        file_is_newer = file_manifest.updated_at > sqlite_manifest.updated_at
        if sqlite_in_flight or not file_is_newer:
            if _payloads_differ(sqlite_manifest, file_manifest):
                write_manifest_checkpoint(session_dir, sqlite_manifest)
                report.sqlite_won.append(session_id)
            continue
        catalog.upsert_session(file_manifest, touch=False)
        report.file_won.append(session_id)

    for session_id in sqlite_ids:
        if not (sessions_root / session_id).is_dir():
            report.missing_directories.append(session_id)
    return report


def archive_session(catalog: Catalog, settings: Settings, session_id: str) -> SessionManifest:
    manifest = catalog.get_manifest(session_id)
    if manifest.status in IN_FLIGHT_STATUSES:
        raise ValueError("Cannot archive a session while import is running")
    if manifest.status == "archived":
        raise ValueError("Session is already archived")
    manifest.archived_from_status = manifest.status
    manifest.archived_at = datetime.now(UTC)
    manifest.status = "archived"
    catalog.persist_manifest(manifest, settings.session_dir(session_id))
    return manifest


def restore_session(catalog: Catalog, settings: Settings, session_id: str) -> SessionManifest:
    manifest = catalog.get_manifest(session_id)
    if manifest.status != "archived":
        raise ValueError("Only archived sessions can be restored")
    manifest.status = manifest.archived_from_status or "ready"
    manifest.archived_from_status = None
    manifest.archived_at = None
    catalog.persist_manifest(manifest, settings.session_dir(session_id))
    return manifest


def delete_session(
    catalog: Catalog,
    settings: Settings,
    session_id: str,
    *,
    confirm_session_id: str,
    running: set[str] | None = None,
) -> None:
    if confirm_session_id != session_id:
        raise ValueError("confirm_session_id must match the session id")
    manifest = catalog.get_manifest(session_id)
    if manifest.status != "archived":
        raise ValueError("Archive the session before deleting it")
    if running and session_id in running:
        raise ValueError("Cannot delete a session while import is running")
    session_dir = settings.session_dir(session_id)
    manifest_path = session_dir / "manifest.json"
    if manifest_path.is_file():
        manifest_path.unlink()
    catalog.delete_session(session_id)
    if session_dir.is_dir():
        shutil.rmtree(session_dir)


def backup_catalog(catalog: Catalog, settings: Settings) -> CatalogBackupResponse:
    backup_dir = settings.var_root / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"catalog-{stamp}.sqlite3"
    with catalog.connect() as source:
        source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        with sqlite3.connect(destination) as replica:
            source.backup(replica)
    return CatalogBackupResponse(
        path=str(destination),
        created_at=datetime.now(UTC),
        size_bytes=destination.stat().st_size,
    )


def _remove_path(path: Path, *, dry_run: bool) -> int:
    size = 0
    if path.is_file():
        size = path.stat().st_size
        if not dry_run:
            path.unlink()
        return size
    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_file():
                size += child.stat().st_size
        if not dry_run:
            shutil.rmtree(path)
    return size


def cleanup_artifacts(
    catalog: Catalog, settings: Settings, *, dry_run: bool = False
) -> ArtifactCleanupResponse:
    """Remove regenerable export copies and partial files from idle sessions.

    Unregistered directories and unreadable manifests are kept for recovery.
    Reserve database writes while checking statuses and removing files so an
    import cannot transition to processing in the middle of cleanup.
    """
    report = ArtifactCleanupResponse(dry_run=dry_run)
    sessions_root = settings.var_root / "sessions"
    if not sessions_root.is_dir():
        return report
    with catalog.write_transaction() as connection:
        rows = connection.execute("SELECT id, status, manifest_json FROM sessions").fetchall()
        sessions = {row["id"]: row for row in rows}
        for entry in sorted(sessions_root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            relative = str(entry.relative_to(settings.var_root))
            row = sessions.get(entry.name)
            if entry.is_symlink() or row is None or row["status"] in IN_FLIGHT_STATUSES:
                report.skipped_paths.append(relative)
                continue
            try:
                manifest = load_manifest(json.loads(row["manifest_json"]))
                checkpoint = read_manifest_file(entry)
            except (OSError, ValueError, TypeError):
                report.skipped_paths.append(relative)
                continue
            if manifest.status in IN_FLIGHT_STATUSES or (
                checkpoint is not None and checkpoint.status in IN_FLIGHT_STATUSES
            ):
                report.skipped_paths.append(relative)
                continue
            export_dir = entry / "export"
            if export_dir.exists():
                report.recovered_bytes += _remove_path(export_dir, dry_run=dry_run)
                report.removed_paths.append(str(export_dir))
            for leftover in entry.rglob("*"):
                if leftover == export_dir or export_dir in leftover.parents:
                    continue
                if leftover.name.endswith(".partial") or ".partial." in leftover.name:
                    report.recovered_bytes += _remove_path(leftover, dry_run=dry_run)
                    report.removed_paths.append(str(leftover))
    return report
