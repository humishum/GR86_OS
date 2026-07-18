from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd

from .models import SessionManifest


def build_analysis_bundle(
    manifest: SessionManifest, session_dir: Path, *, include_clip_references: bool = False
) -> Path:
    export_dir = session_dir / "export"
    csv_dir = export_dir / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    for parquet in sorted((session_dir / "telemetry").glob("*.parquet")):
        pd.read_parquet(parquet).to_csv(csv_dir / f"{parquet.stem}.csv", index=False)
    bundle = export_dir / "analysis_bundle.zip"
    temporary = bundle.with_suffix(".partial.zip")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest.model_dump_json(indent=2))
        for name in ("laps.json", "corners.json", "diagnostics.json"):
            path = session_dir / "analysis" / name
            if path.is_file():
                archive.write(path, f"analysis/{name}")
        for csv_path in sorted(csv_dir.glob("*.csv")):
            archive.write(csv_path, f"telemetry/{csv_path.name}")
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
                    ],
                    indent=2,
                ),
            )
    temporary.replace(bundle)
    return bundle
