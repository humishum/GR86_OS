from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

import race_review.ingest as ingest_module
from race_review.catalog import Catalog
from race_review.config import Settings
from race_review.ingest import ImportService
from race_review.models import ImportRequest, StreamQualitySummary
from race_review.telemetry import GOPROPY_REVISION


def test_ordered_chapters_preserve_gap_and_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    first = media / "GX010001.MP4"
    third = media / "GX030001.MP4"
    first.write_bytes(b"first-source")
    third.write_bytes(b"third-source")
    original = {first: first.read_bytes(), third: third.read_bytes()}
    creation = datetime(2026, 1, 1, tzinfo=UTC)

    def probe(path: Path, _: Settings) -> dict[str, object]:
        return {
            "duration_seconds": 10.0,
            "creation_time": creation if path == first else creation + timedelta(seconds=12),
            "streams": [],
            "recording_id": "0001",
            "chapter_number": 1 if path == first else 3,
            "has_telemetry": True,
            "video_codec": "hevc",
        }

    monkeypatch.setattr(ingest_module, "probe_media", probe)
    monkeypatch.setattr(ingest_module, "telemetry_packet_count", lambda *_: 10)
    settings = Settings(project_root=tmp_path, var_root=tmp_path / "var", media_roots=(media,))
    settings.ensure_directories()
    service = ImportService(settings, Catalog(settings.database_path))
    manifest = service.prepare(
        ImportRequest(chapters=[str(first), str(third)], generate_proxy=False)
    )
    assert manifest.chapters[1].gap_before_seconds == 2
    assert manifest.chapters[1].discontinuity is True
    assert any("missing" in warning for warning in manifest.warnings)
    assert first.read_bytes() == original[first]
    assert third.read_bytes() == original[third]

    with pytest.raises(ValueError, match="recording order"):
        service.prepare(ImportRequest(chapters=[str(third), str(first)]))


def test_stage_diagnostics_and_resume_artifact_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    source = media / "GX010001.MP4"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        ingest_module,
        "probe_media",
        lambda *_: {
            "duration_seconds": 10.0,
            "creation_time": None,
            "streams": [],
            "recording_id": "0001",
            "chapter_number": 1,
            "has_telemetry": True,
            "video_codec": "hevc",
        },
    )
    monkeypatch.setattr(ingest_module, "telemetry_packet_count", lambda *_: 10)
    settings = Settings(project_root=tmp_path, var_root=tmp_path / "var", media_roots=(media,))
    settings.ensure_directories()
    service = ImportService(settings, Catalog(settings.database_path))
    manifest = service.prepare(ImportRequest(chapters=[str(source)], generate_proxy=False))

    service._start_stage(
        manifest, "telemetry", command_profile=f"gopropy@{GOPROPY_REVISION}", backend="python"
    )
    service._finish_stage(manifest, "telemetry")
    manifest = service.catalog.get_manifest(manifest.session_id)
    stage = manifest.processing_stages["telemetry"][0]
    assert stage.status == "completed"
    assert stage.ended_at is not None
    assert stage.backend == "python"
    assert stage.command_profile.endswith(GOPROPY_REVISION)

    session_dir = settings.session_dir(manifest.session_id)
    (session_dir / "telemetry").mkdir(exist_ok=True)
    (session_dir / "analysis").mkdir(exist_ok=True)
    pd.DataFrame(
        {"timestamp": [0.0], "valid": [True], "latitude": [1.0], "longitude": [2.0]}
    ).to_parquet(session_dir / "telemetry" / "derived.parquet", index=False)
    pd.DataFrame({"distance_m": [0.0]}).to_parquet(
        session_dir / "analysis" / "centerline.parquet", index=False
    )
    for name, value in (
        ("laps.json", []),
        ("corners.json", []),
        ("diagnostics.json", {}),
    ):
        (session_dir / "analysis" / name).write_text(json.dumps(value), encoding="utf-8")
    manifest.artifacts.update(
        {
            "derived_telemetry": "telemetry/derived.parquet",
            "centerline": "analysis/centerline.parquet",
            "laps": "analysis/laps.json",
            "corners": "analysis/corners.json",
            "diagnostics": "analysis/diagnostics.json",
        }
    )
    manifest.streams = [
        StreamQualitySummary(
            name="GPS5",
            samples=1,
            timing_method="test",
            artifact="telemetry/gps5.parquet",
        )
    ]
    assert service._analysis_artifacts_current(manifest, session_dir)
    manifest.processing_versions["gopropy"] = "stale"
    assert not service._analysis_artifacts_current(manifest, session_dir)
