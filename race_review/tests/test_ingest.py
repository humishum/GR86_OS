from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import race_review.ingest as ingest_module
from race_review.catalog import Catalog
from race_review.config import Settings
from race_review.ingest import ImportService
from race_review.models import ImportRequest


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
