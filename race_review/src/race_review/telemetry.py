from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .models import StreamQualitySummary
from .storage import write_parquet

logger = logging.getLogger(__name__)


AXES = {
    "GPS5": ["lat", "lon", "alt", "speed_2d", "speed_3d"],
    "GPS9": ["lat", "lon", "alt", "speed_2d", "speed_3d", "days", "secs", "dop", "fix"],
    "ACCL": ["x", "y", "z"],
    "GYRO": ["x", "y", "z"],
    "GRAV": ["x", "y", "z"],
    "CORI": ["w", "x", "y", "z"],
    "IORI": ["w", "x", "y", "z"],
}


def _stream_frame(name: str, stream: Any, chapter_index: int, offset: float) -> pd.DataFrame:
    fourcc = (getattr(stream, "metadata", {}) or {}).get("fourcc") or name
    try:
        frame = stream.to_dataframe(
            model_config=getattr(stream, "model_config", None), include_quality=True
        )
    except TypeError as exc:
        raise RuntimeError(
            "gopropy does not provide the required quality-aware DataFrame API; "
            "install revision 3040b2f4efc8624e24c0962289eabb25f6a26c7b"
        ) from exc
    frame = frame.copy()
    frame["timestamp"] = pd.to_numeric(frame["timestamp"], errors="coerce") + offset
    frame.insert(1, "chapter_index", chapter_index)
    frame["rejection_reason"] = np.where(frame["valid"], "", "source_marked_invalid")
    frame["source_stream"] = fourcc
    return frame


def extract_chapters(
    chapter_paths: list[Path], offsets: list[float], artifact_dir: Path
) -> tuple[dict[str, pd.DataFrame], list[StreamQualitySummary], str | None]:
    """Extract native streams with gopropy's immutable packet timing API."""
    try:
        import gopropy
    except ImportError as exc:
        raise RuntimeError("Pinned gopropy dependency is not installed") from exc

    accumulated: dict[str, list[pd.DataFrame]] = {}
    quality_inputs: dict[str, list[dict[str, Any]]] = {}
    detected_model: str | None = None
    for chapter_index, (path, offset) in enumerate(zip(chapter_paths, offsets, strict=True)):
        telemetry = gopropy.load(str(path))
        detected_model = detected_model or getattr(telemetry, "detected_model", None)
        for name in telemetry.list_streams():
            stream = telemetry.get_stream(name)
            fourcc = (getattr(stream, "metadata", {}) or {}).get("fourcc") or name
            if fourcc not in AXES:
                continue
            frame = _stream_frame(name, stream, chapter_index, offset)
            accumulated.setdefault(fourcc, []).append(frame)
            metadata = getattr(stream, "metadata", {}) or {}
            quality_inputs.setdefault(fourcc, []).append(
                {
                    "method": getattr(
                        stream, "timing_method", metadata.get("timing_method", "unknown")
                    ),
                    "confidence": float(
                        getattr(stream, "timing_confidence", metadata.get("timing_confidence", 0.0))
                    ),
                    "residuals": getattr(stream, "timing_residuals", np.array([])),
                    "estimated_rate_hz": getattr(stream, "estimated_rate_hz", np.nan),
                    "discontinuities": len(
                        getattr(stream, "discontinuities", metadata.get("discontinuities", []))
                    ),
                }
            )

    streams: dict[str, pd.DataFrame] = {}
    summaries: list[StreamQualitySummary] = []
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for name, parts in accumulated.items():
        frame = pd.concat(parts, ignore_index=True).sort_values("timestamp", kind="stable")
        streams[name] = frame
        path = artifact_dir / f"{name.lower()}.parquet"
        write_parquet(frame, path)
        inputs = quality_inputs[name]
        residuals = np.concatenate([np.asarray(item["residuals"], dtype=float) for item in inputs])
        residuals = residuals[np.isfinite(residuals)]
        rates = np.asarray([item["estimated_rate_hz"] for item in inputs], dtype=float)
        rates = rates[np.isfinite(rates)]
        method = inputs[0]["method"] if len({item["method"] for item in inputs}) == 1 else "mixed"
        summaries.append(
            StreamQualitySummary(
                name=name,
                samples=len(frame),
                timing_method=str(method),
                estimated_rate_hz=float(np.mean(rates)) if len(rates) else None,
                confidence=float(np.mean([item["confidence"] for item in inputs])),
                residual_rms_seconds=(
                    float(np.sqrt(np.mean(residuals**2))) if len(residuals) else None
                ),
                discontinuities=sum(int(item["discontinuities"]) for item in inputs),
                valid_samples=int(frame["valid"].sum()),
                artifact=str(path.relative_to(artifact_dir.parent)),
            )
        )
    return streams, summaries, detected_model
