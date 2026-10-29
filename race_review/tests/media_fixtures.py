from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from race_review.media import fingerprint, probe_media
from race_review.models import ChapterManifest, SessionManifest, SourceFingerprint
from race_review.proxy import _cuda_encoder_available

SHORT_FIXTURE_SECONDS = 2.0
SHORT_FIXTURE_SIZE = "320x180"
SHORT_FIXTURE_RATE = 30


def ffmpeg_is_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def nvidia_validation_requested() -> bool:
    return os.getenv("RACE_REVIEW_NVIDIA") == "1"


def write_h264_fixture(
    path: Path,
    *,
    duration: float = SHORT_FIXTURE_SECONDS,
    size: str = SHORT_FIXTURE_SIZE,
    rate: int = SHORT_FIXTURE_RATE,
) -> Path:
    """Write a portable CPU H.264/AAC clip that FFmpeg can generate on Linux and macOS."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.mp4")
    temporary.unlink(missing_ok=True)
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={size}:rate={rate}:duration={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:duration={duration}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-profile:v",
            "baseline",
            "-level:v",
            "3.0",
            "-pix_fmt",
            "yuv420p",
            "-g",
            str(rate),
            "-keyint_min",
            str(rate),
            "-sc_threshold",
            "0",
            "-bf",
            "0",
            "-c:a",
            "aac",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            "-map_metadata",
            "-1",
            "-y",
            str(temporary),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"FFmpeg could not generate the H.264 fixture:\n{result.stderr}")
    temporary.replace(path)
    return path


def manifest_for_media(path: Path, settings) -> SessionManifest:
    probed = probe_media(path, settings)
    identity = fingerprint(path)
    duration = float(probed["duration_seconds"])
    now = datetime.now(UTC)
    return SessionManifest(
        session_id="fixture",
        name="CPU media fixture",
        created_at=now,
        updated_at=now,
        status="queued",
        duration_seconds=duration,
        chapters=[
            ChapterManifest(
                index=0,
                filename=path.name,
                fingerprint=SourceFingerprint(
                    path=str(path),
                    size_bytes=identity.size_bytes,
                    modified_ns=identity.modified_ns,
                    sha256=identity.sha256,
                ),
                duration_seconds=duration,
                timeline_start_seconds=0,
                timeline_end_seconds=duration,
            )
        ],
        processing_versions={"race_review": "test"},
    )


def cuda_encoder_available(ffmpeg: str = "ffmpeg") -> bool:
    return _cuda_encoder_available(ffmpeg)


requires_ffmpeg = pytest.mark.skipif(
    not ffmpeg_is_available(), reason="ffmpeg and ffprobe are required for media fixtures"
)
requires_nvidia = pytest.mark.skipif(
    not nvidia_validation_requested(),
    reason="NVIDIA validation is opt-in via RACE_REVIEW_NVIDIA=1",
)
