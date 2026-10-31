from __future__ import annotations

import hashlib
import io
import json
import zipfile
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
        mismatch = await client.post(endpoint, json={"chapter_index": 0, "path": str(wrong)})
        assert mismatch.status_code == 422
        assert "SHA-256" in mismatch.json()["detail"]

        response = await client.post(endpoint, json={"chapter_index": 0, "path": str(relocated)})
        assert response.status_code == 200
        assert response.json()["chapters"][0]["fingerprint"]["path"] == str(relocated)
        source_response = await client.get(f"/api/sessions/{session.session_id}/media/source")
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
        response = await client.put(f"/api/sessions/{session.session_id}/display-units", json=units)
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


@pytest.mark.anyio
async def test_reference_lap_and_bookmarks_persist(tmp_path: Path) -> None:
    app, session = ready_app(tmp_path)
    bookmarks = [
        {
            "id": "mark-1",
            "seconds": 1.5,
            "label": "Turn in",
            "note": "Late apex",
            "tags": ["braking"],
            "clip": {"start_seconds": 1.2, "end_seconds": 2.4},
        }
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        reference = await client.put(
            f"/api/sessions/{session.session_id}/reference-lap",
            json={"reference_lap": 2},
        )
        assert reference.status_code == 200
        assert reference.json()["edits"]["reference_lap"] == 2
        saved = await client.put(
            f"/api/sessions/{session.session_id}/bookmarks",
            json=bookmarks,
        )
        assert saved.status_code == 200
        assert saved.json()["edits"]["bookmarks"] == bookmarks
        reloaded = (await client.get(f"/api/sessions/{session.session_id}")).json()
        assert reloaded["edits"]["reference_lap"] == 2
        assert reloaded["edits"]["bookmarks"][0]["label"] == "Turn in"

    assert app.state.catalog.get_edit(session.session_id, "reference_lap") == {"reference_lap": 2}
    assert app.state.catalog.get_edit(session.session_id, "bookmarks") == bookmarks


@pytest.mark.anyio
async def test_comparison_includes_regions_and_ranked_corners(tmp_path: Path) -> None:
    app, session = ready_app(tmp_path)
    directory = app.state.settings.session_dir(session.session_id)
    distance = [0.0, 100.0, 200.0, 300.0, 400.0]
    pd.DataFrame(
        {
            "timestamp": [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 62.0, 72.0, 81.0, 89.0],
            "lap_number": [1, 1, 1, 1, 1, 2, 2, 2, 2, 2],
            "lap_distance_m": distance + distance,
            "speed_mps": [20.0, 18.0, 16.0, 22.0, 24.0, 18.0, 15.0, 17.0, 24.0, 26.0],
            "lateral_g": [0.1, 1.1, 0.2, 0.8, 0.1, 0.1, 0.9, 0.2, 0.7, 0.1],
            "longitudinal_g": [0.0, -0.3, 0.1, -0.2, 0.0, -0.4, -0.3, 0.1, -0.1, 0.0],
            "valid": [True] * 10,
        }
    ).to_parquet(directory / "telemetry" / "derived.parquet", index=False)
    (directory / "analysis" / "corners.json").write_text(
        json.dumps(
            [
                {
                    "corner_id": "corner-1",
                    "name": "Turn 1",
                    "start_distance_m": 50,
                    "apex_distance_m": 100,
                    "end_distance_m": 150,
                },
                {
                    "corner_id": "corner-2",
                    "name": "Turn 2",
                    "start_distance_m": 250,
                    "apex_distance_m": 300,
                    "end_distance_m": 350,
                },
            ]
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/sessions/{session.session_id}/comparison",
            params={"reference_lap": 1, "comparison_lap": 2},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["reference_lap"] == 1
    assert body["regions"]
    assert body["corners"][0]["corner_id"] in {"corner-1", "corner-2"}
    assert abs(body["corners"][0]["time_impact_s"]) >= abs(body["corners"][1]["time_impact_s"])


EDIT_PATHS = (
    ("PUT", "/track"),
    ("PUT", "/calibration"),
    ("PUT", "/display-units"),
    ("PUT", "/reference-lap"),
    ("PUT", "/bookmarks"),
    ("PUT", "/corners"),
    ("POST", "/reanalyze"),
    ("POST", "/archive"),
    ("POST", "/restore"),
    ("DELETE", ""),
)


@pytest.mark.anyio
async def test_edit_and_lifecycle_endpoints_return_404_for_unknown_session(tmp_path: Path) -> None:
    app, _session = ready_app(tmp_path)
    payloads = {
        "/track": {"crossing_direction": 1, "minimum_lap_seconds": 20},
        "/calibration": {"transform": {"forward_axis": "x", "lateral_axis": "y"}},
        "/display-units": {"speed": "mph", "acceleration": "g", "distance": "ft", "time": "s"},
        "/reference-lap": {"reference_lap": 1},
        "/bookmarks": [],
        "/corners": [],
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for method, suffix in EDIT_PATHS:
            kwargs: dict[str, object] = {}
            if suffix in payloads:
                kwargs["json"] = payloads[suffix]
            if method == "DELETE":
                kwargs["params"] = {"confirm": "missing"}
            response = await client.request(method, f"/api/sessions/missing{suffix}", **kwargs)
            assert response.status_code == 404, suffix
            assert response.json()["detail"] == "Session not found"


@pytest.mark.anyio
async def test_every_edit_action_persists_to_sqlite_and_checkpoint(
    tmp_path: Path, monkeypatch
) -> None:
    app, session = ready_app(tmp_path)
    importer = app.state.importer
    monkeypatch.setattr(
        importer, "reanalyze", lambda session_id: importer.catalog.get_manifest(session_id)
    )
    directory = app.state.settings.session_dir(session.session_id)
    (directory / "analysis" / "corners.json").write_text(
        json.dumps(
            [
                {
                    "corner_id": "corner-1",
                    "name": "Turn 1",
                    "start_distance_m": 10,
                    "apex_distance_m": 20,
                    "end_distance_m": 30,
                }
            ]
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        calibration = await client.put(
            f"/api/sessions/{session.session_id}/calibration",
            json={
                "transform": {
                    "forward_axis": "z",
                    "lateral_axis": "x",
                    "forward_sign": -1,
                    "lateral_sign": 1,
                },
                "confidence": 0.4,
                "method": "manual",
            },
        )
        assert calibration.status_code == 200
        assert calibration.json()["edits"]["calibration"]["overridden"] is True

        corners = await client.put(
            f"/api/sessions/{session.session_id}/corners",
            json=[{"action": "update", "corner_id": "corner-1", "name": "Hairpin"}],
        )
        assert corners.status_code == 200
        assert corners.json()[0]["name"] == "Turn 1"

        reanalyze = await client.post(f"/api/sessions/{session.session_id}/reanalyze")
        assert reanalyze.status_code == 200

    catalog = app.state.catalog
    assert catalog.get_edit(session.session_id, "calibration")["transform"]["forward_axis"] == "z"
    assert catalog.get_edit(session.session_id, "corners")[0]["name"] == "Hairpin"
    checkpoint = json.loads((directory / "manifest.json").read_text())
    assert checkpoint["edits"]["calibration"]["transform"]["forward_axis"] == "z"
    assert checkpoint["edits"]["corner_edits"][0]["name"] == "Hairpin"


@pytest.mark.anyio
async def test_edit_payload_errors_are_422(tmp_path: Path) -> None:
    app, session = ready_app(tmp_path)
    prefix = f"/api/sessions/{session.session_id}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        cases = [
            (
                "PUT",
                f"{prefix}/calibration",
                {
                    "transform": {
                        "forward_axis": "x",
                        "lateral_axis": "x",
                    }
                },
            ),
            ("PUT", f"{prefix}/reference-lap", {"reference_lap": 0}),
            (
                "PUT",
                f"{prefix}/bookmarks",
                [
                    {
                        "id": "dup",
                        "seconds": 1,
                        "clip": {"start_seconds": 3, "end_seconds": 1},
                    }
                ],
            ),
            (
                "PUT",
                f"{prefix}/bookmarks",
                [
                    {"id": "same", "seconds": 1},
                    {"id": "same", "seconds": 2},
                ],
            ),
            ("PUT", f"{prefix}/corners", [{"action": "explode", "corner_id": "c1"}]),
            ("PUT", f"{prefix}/track", {"crossing_direction": 0}),
        ]
        for method, path, payload in cases:
            response = await client.request(method, path, json=payload)
            assert response.status_code == 422, path


@pytest.mark.anyio
async def test_conflict_error_responses(tmp_path: Path) -> None:
    app, session = ready_app(tmp_path)
    prefix = f"/api/sessions/{session.session_id}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        retry = await client.post(f"{prefix}/retry")
        assert retry.status_code == 409
        cancel = await client.post(f"{prefix}/cancel")
        assert cancel.status_code == 409
        telemetry = await client.get(f"{prefix}/telemetry", params={"start": 3, "end": 1})
        assert telemetry.status_code == 422
        comparison = await client.get(
            f"{prefix}/comparison", params={"reference_lap": 1, "comparison_lap": 9}
        )
        assert comparison.status_code == 422
        restore = await client.post(f"{prefix}/restore")
        assert restore.status_code == 409
        delete = await client.delete(prefix, params={"confirm": session.session_id})
        assert delete.status_code == 409
        delete_confirm = await client.delete(prefix, params={"confirm": "nope"})
        assert delete_confirm.status_code in {409, 422}

    missing_media = tmp_path / "noproxy"
    missing_media.mkdir()
    app, session = ready_app(missing_media)
    session.artifacts.pop("proxy", None)
    session.coordinate_origin = None
    app.state.catalog.save_manifest(session)
    (app.state.settings.session_dir(session.session_id) / "telemetry" / "derived.parquet").unlink()
    prefix = f"/api/sessions/{session.session_id}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get(f"{prefix}/telemetry")).status_code == 409
        assert (await client.get(f"{prefix}/track-geometry")).status_code == 409
        assert (await client.get(f"{prefix}/media/proxy")).status_code == 409
        assert (await client.get(f"{prefix}/thumbnail")).status_code == 409

        imported = await client.post("/api/sessions/import", json={"chapters": []})
        assert imported.status_code == 422


@pytest.mark.anyio
async def test_archive_restore_delete_confirmation_workflow(tmp_path: Path) -> None:
    app, session = ready_app(tmp_path)
    prefix = f"/api/sessions/{session.session_id}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        archived = await client.post(f"{prefix}/archive")
        assert archived.status_code == 200
        assert archived.json()["status"] == "archived"
        blocked = await client.put(
            f"{prefix}/display-units",
            json={"speed": "km/h", "acceleration": "g", "distance": "m", "time": "s"},
        )
        assert blocked.status_code == 409
        restored = await client.post(f"{prefix}/restore")
        assert restored.status_code == 200
        assert restored.json()["status"] == "ready"
        await client.post(f"{prefix}/archive")
        mismatch = await client.delete(prefix, params={"confirm": "other"})
        assert mismatch.status_code == 422
        removed = await client.delete(prefix, params={"confirm": session.session_id})
        assert removed.status_code == 204
        assert (await client.get(prefix)).status_code == 404


@pytest.mark.anyio
async def test_catalog_backup_cleanup_repair_and_export(tmp_path: Path) -> None:
    app, session = ready_app(tmp_path)
    directory = app.state.settings.session_dir(session.session_id)
    (directory / "export").mkdir()
    (directory / "export" / "stale.csv").write_text("old")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        backup = await client.post("/api/catalog/backup")
        assert backup.status_code == 200
        assert Path(backup.json()["path"]).is_file()
        cleanup = await client.post("/api/catalog/cleanup", json={"dry_run": False})
        assert cleanup.status_code == 200
        assert any(path.endswith("export") for path in cleanup.json()["removed_paths"])
        repair = await client.post("/api/catalog/repair")
        assert repair.status_code == 200
        exported = await client.post(f"/api/sessions/{session.session_id}/export")
        assert exported.status_code == 200
        assert exported.headers["content-type"].startswith("application/zip")
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            provenance = json.loads(archive.read("provenance.json"))
            assert "application_version" in provenance
            assert "processing_fingerprints" in provenance
            assert "telemetry/derived.csv" in archive.namelist()
