from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import race_review.catalog as catalog_module
import race_review.maintenance as maintenance_module
from race_review.catalog import Catalog, write_manifest_checkpoint
from race_review.config import Settings
from race_review.maintenance import (
    archive_session,
    backup_catalog,
    cleanup_artifacts,
    delete_session,
    repair_catalog,
    restore_session,
)
from race_review.models import ChapterManifest, SessionManifest, SourceFingerprint


def _manifest(session_id: str, path: Path, *, status: str = "ready") -> SessionManifest:
    now = datetime.now(UTC)
    return SessionManifest(
        session_id=session_id,
        name=session_id,
        created_at=now,
        updated_at=now,
        status=status,
        duration_seconds=4,
        chapters=[
            ChapterManifest(
                index=0,
                filename=path.name,
                fingerprint=SourceFingerprint(
                    path=str(path), size_bytes=4, modified_ns=1, sha256="f" * 64
                ),
                duration_seconds=4,
                timeline_start_seconds=0,
                timeline_end_seconds=4,
            )
        ],
        processing_versions={"race_review": "test", "analysis": "1", "manifest": "1"},
    )


def _settings(tmp_path: Path) -> Settings:
    settings = Settings(project_root=tmp_path, var_root=tmp_path / "var", media_roots=(tmp_path,))
    settings.ensure_directories()
    return settings


def test_sqlite_is_runtime_authority_and_repair_rewrites_missing_file(tmp_path: Path) -> None:
    source = tmp_path / "GX010001.MP4"
    source.write_bytes(b"test")
    settings = _settings(tmp_path)
    catalog = Catalog(settings.database_path)
    manifest = _manifest("sessone", source)
    catalog.create_session(manifest)
    session_dir = settings.session_dir(manifest.session_id)
    assert not (session_dir / "manifest.json").is_file()
    report = repair_catalog(catalog, settings)
    assert manifest.session_id in report.rewritten_files
    assert json.loads((session_dir / "manifest.json").read_text())["session_id"] == "sessone"


def test_file_only_manifest_restores_sqlite_row(tmp_path: Path) -> None:
    source = tmp_path / "GX010001.MP4"
    source.write_bytes(b"test")
    settings = _settings(tmp_path)
    catalog = Catalog(settings.database_path)
    manifest = _manifest("fileonly", source)
    write_manifest_checkpoint(settings.session_dir(manifest.session_id), manifest)
    report = repair_catalog(catalog, settings)
    assert manifest.session_id in report.restored_from_file
    assert catalog.get_manifest(manifest.session_id).name == "fileonly"


def test_newer_file_wins_unless_sqlite_is_in_flight(tmp_path: Path) -> None:
    source = tmp_path / "GX010001.MP4"
    source.write_bytes(b"test")
    settings = _settings(tmp_path)
    catalog = Catalog(settings.database_path)
    sqlite_manifest = _manifest("conflict", source, status="ready")
    catalog.create_session(sqlite_manifest)
    file_manifest = sqlite_manifest.model_copy(deep=True)
    file_manifest.name = "Restored backup"
    file_manifest.updated_at = sqlite_manifest.updated_at + timedelta(minutes=5)
    write_manifest_checkpoint(settings.session_dir(sqlite_manifest.session_id), file_manifest)
    report = repair_catalog(catalog, settings)
    assert sqlite_manifest.session_id in report.file_won
    assert catalog.get_manifest(sqlite_manifest.session_id).name == "Restored backup"

    inflight = _manifest("inflight", source, status="processing")
    catalog.create_session(inflight)
    newer = inflight.model_copy(deep=True)
    newer.name = "Should not win"
    newer.updated_at = inflight.updated_at + timedelta(minutes=5)
    write_manifest_checkpoint(settings.session_dir(inflight.session_id), newer)
    report = repair_catalog(catalog, settings)
    assert inflight.session_id in report.sqlite_won
    assert catalog.get_manifest(inflight.session_id).status == "processing"
    assert (
        json.loads((settings.session_dir(inflight.session_id) / "manifest.json").read_text())[
            "status"
        ]
        == "processing"
    )


def test_archive_restore_and_confirmed_delete(tmp_path: Path) -> None:
    source = tmp_path / "GX010001.MP4"
    source.write_bytes(b"test")
    settings = _settings(tmp_path)
    catalog = Catalog(settings.database_path)
    manifest = _manifest("keepme", source)
    catalog.persist_manifest(manifest, settings.session_dir(manifest.session_id), touch=False)
    archived = archive_session(catalog, settings, manifest.session_id)
    assert archived.status == "archived"
    assert archived.archived_from_status == "ready"
    restored = restore_session(catalog, settings, manifest.session_id)
    assert restored.status == "ready"
    archive_session(catalog, settings, manifest.session_id)
    delete_session(catalog, settings, manifest.session_id, confirm_session_id=manifest.session_id)
    assert manifest.session_id not in catalog.list_session_ids()
    assert not settings.session_dir(manifest.session_id).exists()


def test_backup_and_cleanup_remove_regenerable_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "GX010001.MP4"
    source.write_bytes(b"test")
    settings = _settings(tmp_path)
    catalog = Catalog(settings.database_path)
    manifest = _manifest("readyone", source)
    session_dir = settings.session_dir(manifest.session_id)
    catalog.persist_manifest(manifest, session_dir, touch=False)
    export_dir = session_dir / "export"
    export_dir.mkdir(parents=True)
    (export_dir / "analysis_bundle.zip").write_bytes(b"zip")
    partial = session_dir / "media" / "proxy.partial.mp4"
    partial.parent.mkdir()
    partial.write_bytes(b"partial")
    orphan = settings.var_root / "sessions" / "orphan-dir"
    orphan.mkdir()
    (orphan / "junk.txt").write_text("no manifest")
    recoverable = settings.var_root / "sessions" / "file-only"
    recoverable.mkdir()
    write_manifest_checkpoint(recoverable, _manifest("file-only", source))

    backup = backup_catalog(catalog, settings)
    assert Path(backup.path).is_file()
    assert backup.size_bytes > 0

    dry = cleanup_artifacts(catalog, settings, dry_run=True)
    assert str(export_dir) in dry.removed_paths
    assert export_dir.is_dir()
    cleaned = cleanup_artifacts(catalog, settings, dry_run=False)
    assert not export_dir.exists()
    assert not partial.exists()
    assert orphan.exists()
    assert recoverable.exists()
    assert str(orphan.relative_to(settings.var_root)) in cleaned.skipped_paths
    assert str(recoverable.relative_to(settings.var_root)) in cleaned.skipped_paths


@pytest.mark.parametrize("status", ["queued", "processing", "cancelling"])
def test_cleanup_preserves_all_artifacts_for_in_flight_sessions(
    tmp_path: Path, status: str
) -> None:
    settings = _settings(tmp_path)
    catalog = Catalog(settings.database_path)
    manifest = _manifest("active", tmp_path / "source.mp4", status=status)
    session_dir = settings.session_dir(manifest.session_id)
    catalog.persist_manifest(manifest, session_dir)
    partial = session_dir / "media" / "proxy.partial.mp4"
    partial.parent.mkdir()
    partial.write_bytes(b"active transcode")
    export = session_dir / "export" / "analysis_bundle.zip"
    export.parent.mkdir()
    export.write_bytes(b"active download")

    for dry_run in (True, False):
        report = cleanup_artifacts(catalog, settings, dry_run=dry_run)
        assert report.skipped_paths == ["sessions/active"]
        assert report.removed_paths == []
        assert report.recovered_bytes == 0
        assert partial.read_bytes() == b"active transcode"
        assert export.read_bytes() == b"active download"


@pytest.mark.parametrize("registered", [False, True])
@pytest.mark.parametrize("failure", ["invalid-json", "future-schema", "unreadable"])
def test_cleanup_preserves_unreadable_sessions_before_removing_any_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registered: bool, failure: str
) -> None:
    settings = _settings(tmp_path)
    catalog = Catalog(settings.database_path)
    manifest = _manifest("recoverable", tmp_path / "source.mp4")
    session_dir = settings.session_dir(manifest.session_id)
    if registered:
        catalog.persist_manifest(manifest, session_dir)
    else:
        write_manifest_checkpoint(session_dir, manifest)
    checkpoint = session_dir / "manifest.json"
    if failure == "invalid-json":
        checkpoint.write_text("{interrupted write")
    elif failure == "future-schema":
        payload = manifest.model_dump(mode="json")
        payload["schema_version"] = 2
        checkpoint.write_text(json.dumps(payload))
    else:

        def unreadable(_directory: Path) -> None:
            raise PermissionError("checkpoint is unreadable")

        monkeypatch.setattr(maintenance_module, "read_manifest_file", unreadable)
    files = {
        "telemetry/derived.parquet": b"recoverable telemetry",
        "export/analysis_bundle.zip": b"recoverable export",
        "media/proxy.partial.mp4": b"recoverable partial",
    }
    for relative, contents in files.items():
        path = session_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    for dry_run in (True, False):
        report = cleanup_artifacts(catalog, settings, dry_run=dry_run)
        assert report.skipped_paths == ["sessions/recoverable"]
        assert report.removed_paths == []
        assert report.recovered_bytes == 0
        assert checkpoint.exists()
        for relative, contents in files.items():
            assert (session_dir / relative).read_bytes() == contents


def test_cleanup_reserves_writes_until_file_removal_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    catalog = Catalog(settings.database_path)
    importing_catalog = Catalog(settings.database_path)
    manifest = _manifest("session", tmp_path / "source.mp4")
    session_dir = settings.session_dir(manifest.session_id)
    catalog.persist_manifest(manifest, session_dir)
    export = session_dir / "export"
    export.mkdir()
    (export / "stale.zip").write_bytes(b"stale")
    removing = threading.Event()
    release_removal = threading.Event()
    starting_import = threading.Event()
    remove_path = maintenance_module._remove_path

    def gated_remove(path: Path, *, dry_run: bool) -> int:
        removing.set()
        assert release_removal.wait(5)
        return remove_path(path, dry_run=dry_run)

    def start_import() -> Path:
        starting_import.set()
        manifest.status = "processing"
        importing_catalog.persist_manifest(manifest, session_dir)
        partial = session_dir / "media" / "proxy.partial.mp4"
        partial.parent.mkdir()
        partial.write_bytes(b"new transcode")
        return partial

    monkeypatch.setattr(maintenance_module, "_remove_path", gated_remove)
    with ThreadPoolExecutor(max_workers=2) as pool:
        cleanup = pool.submit(cleanup_artifacts, catalog, settings)
        try:
            assert removing.wait(5)
            importing = pool.submit(start_import)
            assert starting_import.wait(5)
            with pytest.raises(TimeoutError):
                importing.result(timeout=0.2)
            assert catalog.get_manifest(manifest.session_id).status == "ready"
        finally:
            release_removal.set()
        report = cleanup.result(timeout=5)
        partial = importing.result(timeout=5)
    assert report.removed_paths == [str(export)]
    assert partial.read_bytes() == b"new transcode"
    assert catalog.get_manifest(manifest.session_id).status == "processing"


def test_concurrent_manifest_writes_keep_sqlite_and_checkpoint_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    catalog = Catalog(settings.database_path)
    older = _manifest("session", tmp_path / "source.mp4")
    older.name = "older"
    newer = older.model_copy(deep=True)
    newer.name = "newer"
    session_dir = settings.session_dir(older.session_id)
    checkpoint_pending = threading.Event()
    release_checkpoint = threading.Event()
    newer_started = threading.Event()
    write_checkpoint = catalog_module.write_manifest_checkpoint

    def gated_checkpoint(directory: Path, manifest: SessionManifest) -> None:
        if manifest.name == "older":
            checkpoint_pending.set()
            assert release_checkpoint.wait(5)
        write_checkpoint(directory, manifest)

    def save_newer() -> None:
        newer_started.set()
        catalog.persist_manifest(newer, session_dir)

    monkeypatch.setattr(catalog_module, "write_manifest_checkpoint", gated_checkpoint)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(catalog.persist_manifest, older, session_dir)
        try:
            assert checkpoint_pending.wait(5)
            second = pool.submit(save_newer)
            assert newer_started.wait(5)
            with pytest.raises(TimeoutError):
                second.result(timeout=0.2)
            assert catalog.get_manifest(older.session_id).name == "older"
        finally:
            release_checkpoint.set()
        first.result(timeout=5)
        second.result(timeout=5)
    stored = catalog.get_manifest(older.session_id).model_dump(mode="json")
    assert stored["name"] == "newer"
    assert json.loads((session_dir / "manifest.json").read_text()) == stored
