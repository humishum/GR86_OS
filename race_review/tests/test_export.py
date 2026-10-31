from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from race_review import __version__
from race_review.analysis import ANALYSIS_VERSION
from race_review.export import build_analysis_bundle, collect_provenance, write_parquet_as_csv
from race_review.models import ChapterManifest, SessionManifest, SourceFingerprint
from race_review.proxy import PROXY_PROFILE
from race_review.storage import sha256_file, write_parquet


def _manifest(tmp_path: Path) -> tuple[SessionManifest, Path]:
    now = datetime.now(UTC)
    session_dir = tmp_path / "session"
    (session_dir / "telemetry").mkdir(parents=True)
    (session_dir / "analysis").mkdir()
    (session_dir / "media").mkdir()
    source = tmp_path / "GX010001.MP4"
    source.write_bytes(b"src")
    manifest = SessionManifest(
        session_id="export1",
        name="Export",
        created_at=now,
        updated_at=now,
        status="ready",
        duration_seconds=2,
        chapters=[
            ChapterManifest(
                index=0,
                filename=source.name,
                fingerprint=SourceFingerprint(
                    path=str(source), size_bytes=3, modified_ns=1, sha256="a" * 64
                ),
                duration_seconds=2,
                timeline_start_seconds=0,
                timeline_end_seconds=2,
            )
        ],
        processing_versions={
            "race_review": __version__,
            "analysis": ANALYSIS_VERSION,
            "manifest": "1",
            "gopropy": "abc",
        },
        artifacts={"derived_telemetry": "telemetry/derived.parquet"},
    )
    frame = pd.DataFrame({"timestamp": [0.0, 1.0], "speed_mps": [10.0, 20.0]})
    write_parquet(frame, session_dir / "telemetry" / "derived.parquet")
    (session_dir / "analysis" / "laps.json").write_text("[]")
    (session_dir / "media" / "proxy.json").write_text(
        json.dumps(
            {
                "backend": "cpu",
                "profile": PROXY_PROFILE,
                "cache_version": 1,
                "signature": "sig",
            }
        )
    )
    return manifest, session_dir


def test_export_streams_csv_and_includes_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, session_dir = _manifest(tmp_path)
    monkeypatch.setattr("race_review.export.ffmpeg_version", lambda _ffmpeg: "ffmpeg version test")
    monkeypatch.setattr(
        pd,
        "read_parquet",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("export must not load Parquet through pandas")
        ),
    )
    bundle = build_analysis_bundle(manifest, session_dir)
    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
        assert "provenance.json" in names
        assert "telemetry/derived.csv" in names
        provenance = json.loads(archive.read("provenance.json"))
        csv_text = archive.read("telemetry/derived.csv").decode("utf-8")
    assert provenance["application_version"] == __version__
    assert provenance["ffmpeg_version"] == "ffmpeg version test"
    assert provenance["proxy"]["backend"] == "cpu"
    assert provenance["proxy"]["profile"] == PROXY_PROFILE
    assert provenance["processing_versions"]["analysis"] == ANALYSIS_VERSION
    fingerprints = provenance["processing_fingerprints"]
    assert fingerprints["source_sha256"] == ["a" * 64]
    assert fingerprints["proxy_signature"] == "sig"
    assert fingerprints["artifacts"]["derived_telemetry"] == sha256_file(
        session_dir / "telemetry" / "derived.parquet"
    )
    assert "timestamp" in csv_text
    assert "10" in csv_text
    assert "20" in csv_text


def test_write_parquet_as_csv_uses_batches(tmp_path: Path) -> None:
    table = pa.table({"value": list(range(8))})
    path = tmp_path / "values.parquet"
    pq.write_table(table, path)
    output = tmp_path / "values.csv"
    with output.open("wb") as sink:
        write_parquet_as_csv(path, sink, batch_size=3)
    lines = output.read_text().strip().splitlines()
    assert lines[0].strip('"') == "value"
    assert len(lines) == 9


def test_collect_provenance_without_proxy_metadata(tmp_path: Path) -> None:
    manifest, session_dir = _manifest(tmp_path)
    (session_dir / "media" / "proxy.json").unlink()
    provenance = collect_provenance(manifest, session_dir, ffmpeg="missing-ffmpeg")
    assert provenance["proxy"]["backend"] is None
    assert provenance["ffmpeg_version"] is None
    assert provenance["processing_fingerprints"]["artifacts"]
