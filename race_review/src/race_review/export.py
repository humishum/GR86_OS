from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path
from typing import BinaryIO

import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from . import __version__
from .config import Settings
from .models import SessionManifest
from .proxy import PROXY_CACHE_VERSION, PROXY_PROFILE
from .storage import sha256_file

PARQUET_CSV_BATCH_SIZE = 65_536


def ffmpeg_version(ffmpeg: str) -> str | None:
    try:
        result = subprocess.run(
            [ffmpeg, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = (result.stdout or result.stderr).splitlines()
    return lines[0].strip() if lines else None


def write_parquet_as_csv(
    parquet_path: Path, sink: BinaryIO, *, batch_size: int = PARQUET_CSV_BATCH_SIZE
) -> None:
    """Stream a Parquet file to CSV without materializing the full table."""
    parquet_file = pq.ParquetFile(parquet_path)
    writer = pacsv.CSVWriter(sink, parquet_file.schema_arrow)
    try:
        for batch in parquet_file.iter_batches(batch_size=batch_size):
            writer.write_batch(batch)
    finally:
        writer.close()


def _proxy_metadata(session_dir: Path) -> dict[str, object]:
    path = session_dir / "media" / "proxy.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def collect_provenance(
    manifest: SessionManifest, session_dir: Path, *, ffmpeg: str = "ffmpeg"
) -> dict[str, object]:
    proxy = _proxy_metadata(session_dir)
    artifact_fingerprints: dict[str, str] = {}
    for name, relative in sorted(manifest.artifacts.items()):
        path = session_dir / relative
        if path.is_file():
            artifact_fingerprints[name] = sha256_file(path)
    return {
        "application_version": __version__,
        "ffmpeg_version": ffmpeg_version(ffmpeg),
        "proxy": {
            "backend": proxy.get("backend"),
            "profile": proxy.get("profile", PROXY_PROFILE),
            "cache_version": proxy.get("cache_version", PROXY_CACHE_VERSION),
            "signature": proxy.get("signature"),
        },
        "processing_versions": dict(manifest.processing_versions),
        "processing_fingerprints": {
            "source_sha256": [chapter.fingerprint.sha256 for chapter in manifest.chapters],
            "proxy_signature": proxy.get("signature"),
            "proxy_backend": proxy.get("backend"),
            "proxy_profile": proxy.get("profile", PROXY_PROFILE),
            "artifacts": artifact_fingerprints,
            "processing_versions": dict(manifest.processing_versions),
        },
    }


def build_analysis_bundle(
    manifest: SessionManifest,
    session_dir: Path,
    *,
    include_clip_references: bool = False,
    settings: Settings | None = None,
) -> Path:
    export_dir = session_dir / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    bundle = export_dir / "analysis_bundle.zip"
    temporary = bundle.with_suffix(".partial.zip")
    ffmpeg = settings.ffmpeg if settings is not None else "ffmpeg"
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest.model_dump_json(indent=2))
        archive.writestr(
            "provenance.json",
            json.dumps(
                collect_provenance(manifest, session_dir, ffmpeg=ffmpeg),
                indent=2,
            ),
        )
        for name in ("laps.json", "corners.json", "diagnostics.json"):
            path = session_dir / "analysis" / name
            if path.is_file():
                archive.write(path, f"analysis/{name}")
        telemetry_dir = session_dir / "telemetry"
        if telemetry_dir.is_dir():
            for parquet in sorted(telemetry_dir.glob("*.parquet")):
                with archive.open(f"telemetry/{parquet.stem}.csv", "w", force_zip64=True) as sink:
                    write_parquet_as_csv(parquet, sink)
        timestamps = {
            "canonical_time": "video-relative seconds",
            "chapters": [
                {
                    "index": chapter.index,
                    "source": chapter.fingerprint.path,
                    "timeline_start_seconds": chapter.timeline_start_seconds,
                    "timeline_end_seconds": chapter.timeline_end_seconds,
                    "gap_before_seconds": chapter.gap_before_seconds,
                    "creation_time": chapter.creation_time.isoformat()
                    if chapter.creation_time
                    else None,
                }
                for chapter in manifest.chapters
            ],
        }
        archive.writestr("timestamps.json", json.dumps(timestamps, indent=2))
        archive.writestr(
            "analysis/bookmarks.json",
            json.dumps(
                [bookmark.model_dump(mode="json") for bookmark in manifest.edits.bookmarks],
                indent=2,
            ),
        )
        if include_clip_references:
            archive.writestr(
                "clip_references.json",
                json.dumps(
                    [
                        {
                            "path": chapter.fingerprint.path,
                            "sha256": chapter.fingerprint.sha256,
                            "offset_seconds": chapter.timeline_start_seconds,
                        }
                        for chapter in manifest.chapters
                    ]
                    + [
                        {
                            "bookmark_id": bookmark.id,
                            "label": bookmark.label,
                            "seconds": bookmark.seconds,
                            "clip": (
                                bookmark.clip.model_dump(mode="json") if bookmark.clip else None
                            ),
                        }
                        for bookmark in manifest.edits.bookmarks
                    ],
                    indent=2,
                ),
            )
    temporary.replace(bundle)
    return bundle
