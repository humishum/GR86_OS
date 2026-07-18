from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import JobStatus, SessionManifest

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


class Catalog:
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

    def create_session(self, manifest: SessionManifest) -> None:
        with self._write_lock, self.connect() as connection:
            payload = manifest.model_dump_json()
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
                (
                    manifest.session_id,
                    manifest.name,
                    manifest.status,
                    manifest.created_at.isoformat(),
                    manifest.updated_at.isoformat(),
                    payload,
                ),
            )
            connection.executemany(
                "INSERT INTO chapters VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        manifest.session_id,
                        chapter.index,
                        chapter.fingerprint.path,
                        chapter.fingerprint.size_bytes,
                        chapter.fingerprint.modified_ns,
                        chapter.fingerprint.sha256,
                    )
                    for chapter in manifest.chapters
                ],
            )
            now = datetime.now(UTC).isoformat()
            connection.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?)",
                (manifest.session_id, "queued", "queued", 0.0, "Waiting to start", None, now),
            )

    def save_manifest(self, manifest: SessionManifest) -> None:
        manifest.updated_at = datetime.now(UTC)
        with self._write_lock, self.connect() as connection:
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

    def get_manifest(self, session_id: str) -> SessionManifest:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT manifest_json FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return SessionManifest.model_validate_json(row["manifest_json"])

    def list_manifests(self) -> list[SessionManifest]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT manifest_json FROM sessions ORDER BY created_at DESC"
            ).fetchall()
        return [SessionManifest.model_validate_json(row["manifest_json"]) for row in rows]

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
