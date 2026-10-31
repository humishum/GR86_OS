from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient
from media_fixtures import manifest_for_media, requires_ffmpeg, write_h264_fixture
from test_api import ready_app

from race_review.config import Settings
from race_review.proxy import generate_proxy, generate_thumbnail


def _budgets() -> dict[str, float]:
    path = Path(__file__).resolve().parents[1] / "performance_budgets.json"
    return json.loads(path.read_text(encoding="utf-8"))


@requires_ffmpeg
@pytest.mark.ffmpeg
def test_cpu_import_media_stages_stay_within_budget(tmp_path: Path) -> None:
    budgets = _budgets()
    source = write_h264_fixture(tmp_path / "GX010001.MP4")
    settings = Settings(
        project_root=tmp_path,
        var_root=tmp_path / "var",
        media_roots=(tmp_path,),
        proxy_acceleration="cpu",
    )
    manifest = manifest_for_media(source, settings)
    session_dir = tmp_path / "session"
    started = time.perf_counter()
    generate_proxy(manifest, session_dir, settings)
    generate_thumbnail(manifest, session_dir, settings)
    elapsed = time.perf_counter() - started
    assert elapsed < budgets["cpu_proxy_short_fixture_s"]


@pytest.mark.anyio
async def test_telemetry_window_request_stays_within_budget(tmp_path: Path) -> None:
    budgets = _budgets()
    app, session = ready_app(tmp_path)
    session.duration_seconds = 500
    app.state.catalog.persist_manifest(session, app.state.settings.session_dir(session.session_id))
    rows = 50_000
    timestamps = np.linspace(0, 500, rows)
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "latitude": np.full(rows, 38.16),
            "longitude": np.full(rows, -122.46),
            "altitude_m": np.full(rows, 10.0),
            "east_smooth_m": np.linspace(0, 4000, rows),
            "north_smooth_m": np.linspace(0, 100, rows),
            "up_smooth_m": np.zeros(rows),
            "speed_mps": np.full(rows, 40.0),
            "longitudinal_g": np.zeros(rows),
            "lateral_g": np.zeros(rows),
            "distance_m": np.linspace(0, 4000, rows),
            "lap_number": np.ones(rows, dtype=int),
            "lap_distance_m": np.linspace(0, 4000, rows),
            "valid": np.ones(rows, dtype=bool),
        }
    )
    catalog_dir = app.state.settings.session_dir(session.session_id)
    frame.to_parquet(catalog_dir / "telemetry" / "derived.parquet", index=False)
    started = time.perf_counter()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/sessions/{session.session_id}/telemetry",
            params={"max_points": 8_000},
        )
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert response.status_code == 200
    body = response.json()
    assert 2 <= len(body["rows"]) <= 8_000
    assert elapsed_ms < budgets["telemetry_request_ms"]
