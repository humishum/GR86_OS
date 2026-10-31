from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .migrations import load_manifest
from .models import JobStatus, SessionManifest
from .storage import atomic_json

logger = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    manifest_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chapters (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    chapter_index INTEGER NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    modified_ns INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    PRIMARY KEY (session_id, chapter_index)
);

CREATE TABLE IF NOT EXISTS jobs (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    progress REAL NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    error TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edits (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    edit_type TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, edit_type)
);
"""

# Session statuses that must not be clobbered by a newer session-dir file.
IN_FLIGHT_STATUSES = frozenset({"queued", "processing", "cancelling"})


class Catalog:
    """SQLite is the runtime catalog authority for session identity, jobs, and edits.

    Each session directory's manifest.json is a portable checkpoint. Writes always
    go to SQLite first, then the file is rewritten from the same in-memory object
    so a crash can leave a missing file (repairable) but not a file that is newer
    than SQLite with different contents. See `repair_catalog` for reconciliation.
    """

    def __init__(self, path: Path):
        self.path = path
        self._write_lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def write_transaction(self) -> Iterator[sqlite3.Connection]:
        """Reserve writes before checking state for filesystem maintenance.

        BEGIN IMMEDIATE also blocks writers using another catalog connection,
        such as a CLI import, until maintenance has finished removing files.
        """
        with self._write_lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            yield connection

    def _chapter_rows(self, manifest: SessionManifest) -> list[tuple[object, ...]]:
        return [
            (
                manifest.session_id,
                chapter.index,
                chapter.fingerprint.path,
                chapter.fingerprint.size_bytes,
                chapter.fingerprint.modified_ns,
                chapter.fingerprint.sha256,
            )
            for chapter in manifest.chapters
        ]

    def _insert_session(self, connection: sqlite3.Connection, manifest: SessionManifest) -> None:
        connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
            (
                manifest.session_id,
                manifest.name,
                manifest.status,
                manifest.created_at.isoformat(),
                manifest.updated_at.isoformat(),
                manifest.model_dump_json(),
            ),
        )
        connection.executemany(
            "INSERT INTO chapters VALUES (?, ?, ?, ?, ?, ?)", self._chapter_rows(manifest)
        )
        now = datetime.now(UTC).isoformat()
        connection.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                manifest.session_id,
                manifest.status,
                manifest.status,
                0.0,
                "Waiting to start" if manifest.status == "queued" else manifest.status,
                None,
                now,
            ),
        )

    def _update_session(self, connection: sqlite3.Connection, manifest: SessionManifest) -> None:
        cursor = connection.execute(
            "UPDATE sessions SET name=?, status=?, updated_at=?, manifest_json=? WHERE id=?",
            (
                manifest.name,
                manifest.status,
                manifest.updated_at.isoformat(),
                manifest.model_dump_json(),
                manifest.session_id,
            ),
        )
        if cursor.rowcount != 1:
            raise KeyError(manifest.session_id)
        connection.execute("DELETE FROM chapters WHERE session_id=?", (manifest.session_id,))
        connection.executemany(
            "INSERT INTO chapters VALUES (?, ?, ?, ?, ?, ?)", self._chapter_rows(manifest)
        )

    def create_session(self, manifest: SessionManifest) -> None:
        with self._write_lock, self.connect() as connection:
            self._insert_session(connection, manifest)

    def save_manifest(self, manifest: SessionManifest, *, touch: bool = True) -> None:
        if touch:
            manifest.updated_at = datetime.now(UTC)
        with self._write_lock, self.connect() as connection:
            self._update_session(connection, manifest)

    def upsert_session(self, manifest: SessionManifest, *, touch: bool = False) -> None:
        with self._write_lock, self.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sessions WHERE id=?", (manifest.session_id,)
            ).fetchone()
            if exists:
                self._update_session(connection, manifest)
            else:
                self._insert_session(connection, manifest)

    def persist_manifest(
        self, manifest: SessionManifest, session_dir: Path, *, touch: bool = True
    ) -> None:
        """Write SQLite first (runtime authority), then the session-dir checkpoint."""
        with self._write_lock:
            if touch:
                manifest.updated_at = datetime.now(UTC)
            self.upsert_session(manifest, touch=False)
            write_manifest_checkpoint(session_dir, manifest)

    def delete_session(self, session_id: str) -> None:
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            if cursor.rowcount != 1:
                raise KeyError(session_id)

    def raw_manifest_payload(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT manifest_json FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["manifest_json"])
        if not isinstance(payload, dict):
            raise ValueError(f"Catalog row for {session_id} is not a JSON object")
        return payload

    def list_session_ids(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute("SELECT id FROM sessions ORDER BY created_at DESC").fetchall()
        return [row["id"] for row in rows]

    def get_manifest(self, session_id: str) -> SessionManifest:
        payload = self.raw_manifest_payload(session_id)
        if payload is None:
            raise KeyError(session_id)
        return load_manifest(payload)

    def list_manifests(self) -> list[SessionManifest]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, manifest_json FROM sessions ORDER BY created_at DESC"
            ).fetchall()
        manifests: list[SessionManifest] = []
        for row in rows:
            try:
                manifests.append(load_manifest(json.loads(row["manifest_json"])))
            except (TypeError, ValueError, json.JSONDecodeError):
                logger.warning("Skipping unreadable catalog row %s", row["id"])
        return manifests

    def set_job(
        self,
        session_id: str,
        *,
        status: str,
        stage: str,
        progress: float,
        message: str = "",
        error: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        progress = min(1.0, max(0.0, progress))
        with self._write_lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET status=excluded.status,
                    stage=excluded.stage, progress=excluded.progress,
                    message=excluded.message, error=excluded.error,
                    updated_at=excluded.updated_at""",
                (session_id, status, stage, progress, message, error, now),
            )

    def get_job(self, session_id: str) -> JobStatus:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE session_id=?", (session_id,)
            ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return JobStatus(**dict(row))

    def save_edit(self, session_id: str, edit_type: str, value: Any) -> None:
        now = datetime.now(UTC).isoformat()
        with self._write_lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO edits VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id, edit_type) DO UPDATE SET
                    value_json=excluded.value_json, updated_at=excluded.updated_at""",
                (session_id, edit_type, json.dumps(value, separators=(",", ":")), now),
            )

    def get_edit(self, session_id: str, edit_type: str) -> Any | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM edits WHERE session_id=? AND edit_type=?",
                (session_id, edit_type),
            ).fetchone()
        return None if row is None else json.loads(row["value_json"])


def write_manifest_checkpoint(session_dir: Path, manifest: SessionManifest) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(session_dir / "manifest.json", manifest.model_dump(mode="json"))


def read_manifest_file(session_dir: Path) -> SessionManifest | None:
    path = session_dir / "manifest.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return load_manifest(payload)
