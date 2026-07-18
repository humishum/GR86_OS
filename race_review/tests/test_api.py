from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
import pytest
from fastapi import FastAPI

from race_review.api import create_app
from race_review.catalog import Catalog
from race_review.config import Settings
from race_review.models import ChapterManifest, SessionManifest, SourceFingerprint


def ready_app(tmp_path: Path) -> tuple[FastAPI, SessionManifest]:
    media = tmp_path / "media"
    media.mkdir()
    source = media / "GX010001.MP4"
    source.write_bytes(b"source")
    settings = Settings(project_root=tmp_path, var_root=tmp_path / "var", media_roots=(media,))
    settings.ensure_directories()
    now = datetime.now(UTC)
    session = SessionManifest(
        session_id="ready123",
        name="Synthetic",
        created_at=now,
        updated_at=now,
        status="ready",
        duration_seconds=4,
        coordinate_origin={"latitude": 34, "longitude": -118, "altitude_m": 10},
        chapters=[
            ChapterManifest(
                index=0,
                filename=source.name,
                fingerprint=SourceFingerprint(
                    path=str(source),
                    size_bytes=source.stat().st_size,
                    modified_ns=source.stat().st_mtime_ns,
                    sha256="0" * 64,
                ),
                duration_seconds=4,
                timeline_start_seconds=0,
                timeline_end_seconds=4,
            )
        ],
        processing_versions={"race_review": "test"},
        artifacts={
            "derived_telemetry": "telemetry/derived.parquet",
            "laps": "analysis/laps.json",
            "corners": "analysis/corners.json",
            "proxy": "media/proxy.mp4",
        },
    )
    directory = settings.session_dir(session.session_id)
    (directory / "telemetry").mkdir(parents=True)
    (directory / "analysis").mkdir()
    (directory / "media").mkdir()
    (directory / "media" / "proxy.mp4").write_bytes(b"0123456789")
    pd.DataFrame(
        {
            "timestamp": [0.0, 1.0, 2.0, 3.0, 4.0],
            "latitude": [34.0] * 5,
            "longitude": [-118.0] * 5,
            "speed_mps": [0.0, 10.0, 20.0, 10.0, 0.0],
            "longitudinal_g": [0.0] * 5,
            "lateral_g": [0.0] * 5,
            "distance_m": [0.0, 10.0, 30.0, 40.0, 40.0],
            "lap_number": [0] * 5,
            "lap_distance_m": [0.0, 10.0, 30.0, 40.0, 40.0],
            "valid": [True] * 5,
            "east_smooth_m": [0.0] * 5,
            "north_smooth_m": [0.0] * 5,
        }
    ).to_parquet(directory / "telemetry" / "derived.parquet", index=False)
    (directory / "analysis" / "laps.json").write_text("[]")
    (directory / "analysis" / "corners.json").write_text("[]")
    Catalog(settings.database_path).create_session(session)
    return create_app(settings), session


@pytest.mark.anyio
async def test_health_session_and_time_window(tmp_path: Path) -> None:
    app, session = ready_app(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/health")).json() == {"status": "ok"}
        assert (await client.get(f"/api/sessions/{session.session_id}")).status_code == 200
        response = await client.get(
            f"/api/sessions/{session.session_id}/telemetry",
            params={
                "start": 1,
                "end": 3,
                "fields": "timestamp,speed_mps",
                "max_points": 2,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["columns"] == ["timestamp", "speed_mps"]
        assert body["rows"] == [[1.0, 10.0], [3.0, 10.0]]
        geometry = (await client.get(f"/api/sessions/{session.session_id}/track-geometry")).json()
        assert geometry["coordinate_system"] == "WGS84 + right-handed ENU meters"
        assert geometry["route_wgs84"][0]["latitude"] == 34
        assert geometry["route_enu_m"][0]["east_m"] == 0
        media = await client.get(
            f"/api/sessions/{session.session_id}/media/proxy",
            headers={"Range": "bytes=2-5"},
        )
        assert media.status_code == 206
        assert media.content == b"2345"
        assert media.headers["content-range"] == "bytes 2-5/10"


@pytest.mark.anyio
async def test_track_edit_survives_reload(tmp_path: Path, monkeypatch) -> None:
    app, session = ready_app(tmp_path)
    # Reanalysis needs full kinematic columns, so isolate this contract test to persistence.
    app_importer = app.state.importer
    monkeypatch.setattr(
        app_importer, "reanalyze", lambda session_id: app_importer.catalog.get_manifest(session_id)
    )
    track = session.edits.track.model_dump()
    track.update(
        {
            "start_finish_a": {"east_m": 1, "north_m": 2},
            "start_finish_b": {"east_m": 3, "north_m": 4},
        }
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            f"/api/sessions/{session.session_id}/track", content=json.dumps(track)
        )
        assert response.status_code == 200
        reloaded = (await client.get(f"/api/sessions/{session.session_id}")).json()
        assert reloaded["edits"]["track"]["start_finish_a"]["east_m"] == 1
