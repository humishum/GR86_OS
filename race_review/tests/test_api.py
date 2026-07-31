from __future__ import annotations

import hashlib
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
            "altitude_m": [10.0, 11.5, 13.0, 12.0, 10.0],
            "speed_mps": [0.0, 10.0, 20.0, 10.0, 0.0],
            "longitudinal_g": [0.0] * 5,
            "lateral_g": [0.0] * 5,
            "distance_m": [0.0, 10.0, 30.0, 40.0, 40.0],
            "lap_number": [0] * 5,
            "lap_distance_m": [0.0, 10.0, 30.0, 40.0, 40.0],
            "valid": [True] * 5,
            "east_smooth_m": [0.0] * 5,
            "north_smooth_m": [0.0] * 5,
            "up_m": [0.0, 1.5, 3.0, 2.0, 0.0],
            "up_smooth_m": [0.0, 1.5, 3.0, 2.0, 0.0],
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
        default_telemetry = (
            await client.get(f"/api/sessions/{session.session_id}/telemetry")
        ).json()
        assert "altitude_m" in default_telemetry["columns"]
        assert "up_smooth_m" in default_telemetry["columns"]
        altitude_index = default_telemetry["columns"].index("altitude_m")
        assert default_telemetry["rows"][2][altitude_index] == 13.0
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
async def test_single_chapter_source_supports_constrained_byte_ranges(tmp_path: Path) -> None:
    app, session = ready_app(tmp_path)
    endpoint = f"/api/sessions/{session.session_id}/media/source"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        complete = await client.get(endpoint)
        assert complete.status_code == 200
        assert complete.content == b"source"
        assert complete.headers["accept-ranges"] == "bytes"
        assert complete.headers["content-length"] == "6"

        bounded = await client.get(endpoint, headers={"Range": "bytes=1-3"})
        assert bounded.status_code == 206
        assert bounded.content == b"our"
        assert bounded.headers["content-range"] == "bytes 1-3/6"

        suffix = await client.get(endpoint, headers={"Range": "bytes=-3"})
        assert suffix.status_code == 206
        assert suffix.content == b"rce"
        assert suffix.headers["content-range"] == "bytes 3-5/6"


@pytest.mark.anyio
async def test_source_endpoint_rejects_invalid_stale_and_multi_chapter_requests(
    tmp_path: Path,
) -> None:
    app, session = ready_app(tmp_path)
    endpoint = f"/api/sessions/{session.session_id}/media/source"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for value in ("items=0-1", "bytes=0-1,3-4", "bytes=99-"):
            response = await client.get(endpoint, headers={"Range": value})
            assert response.status_code == 416
            assert response.headers["content-range"] == "bytes */6"

        source = Path(session.chapters[0].fingerprint.path)
        source.write_bytes(b"changed")
        stale = await client.get(endpoint)
        assert stale.status_code == 409
        assert stale.json()["detail"] == "Source media is missing or has changed since import"

    multi_root = tmp_path / "multi"
    multi_root.mkdir()
    app, session = ready_app(multi_root)
    second = session.chapters[0].model_copy(deep=True)
    second.index = 1
    second.timeline_start_seconds = session.duration_seconds
    second.timeline_end_seconds = session.duration_seconds * 2
    session.chapters.append(second)
    app.state.catalog.save_manifest(session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/sessions/{session.session_id}/media/source")
        assert response.status_code == 409
        assert response.json()["detail"].startswith("Direct source playback")

    restricted_root = tmp_path / "restricted"
    restricted_root.mkdir()
    app, session = ready_app(restricted_root)
    outside = restricted_root / "outside.MP4"
    outside.write_bytes(b"source")
    session.chapters[0].fingerprint.path = str(outside)
    session.chapters[0].fingerprint.size_bytes = outside.stat().st_size
    session.chapters[0].fingerprint.modified_ns = outside.stat().st_mtime_ns
    app.state.catalog.save_manifest(session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/sessions/{session.session_id}/media/source")
        assert response.status_code == 403
        assert response.json()["detail"] == "Source media is outside configured media roots"


@pytest.mark.anyio
async def test_stale_source_can_be_relocated_only_to_identical_media(tmp_path: Path) -> None:
    app, session = ready_app(tmp_path)
    source = Path(session.chapters[0].fingerprint.path)
    current = app.state.catalog.get_manifest(session.session_id)
    current.chapters[0].fingerprint.sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    app.state.catalog.save_manifest(current)
    relocated = source.with_name("relocated.MP4")
    source.rename(relocated)
    wrong = relocated.with_name("wrong.MP4")
    wrong.write_bytes(b"different")
    endpoint = f"/api/sessions/{session.session_id}/relocate-source"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        mismatch = await client.post(
            endpoint, json={"chapter_index": 0, "path": str(wrong)}
        )
        assert mismatch.status_code == 422
        assert "SHA-256" in mismatch.json()["detail"]

        response = await client.post(
            endpoint, json={"chapter_index": 0, "path": str(relocated)}
        )
        assert response.status_code == 200
        assert response.json()["chapters"][0]["fingerprint"]["path"] == str(relocated)
        source_response = await client.get(
            f"/api/sessions/{session.session_id}/media/source"
        )
        assert source_response.status_code == 200
        assert source_response.content == b"source"

    with app.state.catalog.connect() as connection:
        row = connection.execute(
            "SELECT path FROM chapters WHERE session_id=? AND chapter_index=0",
            (session.session_id,),
        ).fetchone()
    assert row["path"] == str(relocated)


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


@pytest.mark.anyio
async def test_display_units_edit_survives_reload_and_records_edit(tmp_path: Path) -> None:
    app, session = ready_app(tmp_path)
    units = {
        "speed": "km/h",
        "acceleration": "m/s²",
        "distance": "m",
        "time": "s",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            f"/api/sessions/{session.session_id}/display-units", json=units
        )
        assert response.status_code == 200
        assert response.json()["edits"]["display_units"] == units
        reloaded = (await client.get(f"/api/sessions/{session.session_id}")).json()
        assert reloaded["edits"]["display_units"] == units

    assert app.state.catalog.get_edit(session.session_id, "display_units") == units
    manifest_path = app.state.settings.session_dir(session.session_id) / "manifest.json"
    assert json.loads(manifest_path.read_text())["edits"]["display_units"] == units


@pytest.mark.anyio
async def test_display_units_reject_invalid_choices(tmp_path: Path) -> None:
    app, session = ready_app(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            f"/api/sessions/{session.session_id}/display-units",
            json={
                "speed": "knots",
                "acceleration": "g",
                "distance": "yards",
                "time": "minutes",
            },
        )
    assert response.status_code == 422
