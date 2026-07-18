from __future__ import annotations

import json
import logging
import os
import subprocess
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from .config import Settings
from .models import SessionManifest
from .storage import atomic_json

PROXY_PROFILE = "h264-1080p60-aac-gop2s-v3"
logger = logging.getLogger(__name__)


def proxy_cache_signature(manifest: SessionManifest) -> str:
    return (
        ":".join(chapter.fingerprint.sha256 for chapter in manifest.chapters) + ":" + PROXY_PROFILE
    )


def proxy_is_current(output: Path, metadata: Path, manifest: SessionManifest) -> bool:
    if not output.is_file() or output.stat().st_size == 0 or not metadata.is_file():
        return False
    try:
        value = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return value.get("signature") == proxy_cache_signature(manifest)


def build_proxy_command(
    chapters: list[Path],
    concat_file: Path,
    output: Path,
    settings: Settings,
    *,
    use_cuda: bool = False,
) -> list[str]:
    if not chapters:
        raise ValueError("At least one source chapter is required")
    input_args = (
        ["-i", str(chapters[0])]
        if len(chapters) == 1
        else ["-f", "concat", "-safe", "0", "-i", str(concat_file)]
    )
    acceleration_args = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"] if use_cuda else []
    video_args = (
        [
            "-vf",
            "scale_cuda=-2:1080:interp_algo=lanczos",
            "-r",
            "60000/1001",
            "-vsync",
            "cfr",
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p4",
            "-tune",
            "hq",
            "-rc",
            "vbr",
            "-cq",
            "21",
            "-b:v",
            "0",
            "-profile:v",
            "high",
        ]
        if use_cuda
        else [
            "-vf",
            "scale=-2:1080:flags=lanczos,fps=60000/1001",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "21",
            "-pix_fmt",
            "yuv420p",
        ]
    )
    return [
        settings.ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-fflags",
        "+genpts",
        *acceleration_args,
        *input_args,
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        *video_args,
        "-g",
        "120",
        "-keyint_min",
        "120",
        "-sc_threshold",
        "0",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-af",
        "aresample=async=1:first_pts=0",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-avoid_negative_ts",
        "make_zero",
        "-max_muxing_queue_size",
        "4096",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        str(output),
    ]


@lru_cache(maxsize=8)
def _cuda_encoder_available(ffmpeg: str) -> bool:
    """Exercise NVENC instead of trusting build-time encoder listings."""
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=size=64x64:rate=1:duration=0.1",
                "-frames:v",
                "1",
                "-c:v",
                "h264_nvenc",
                "-f",
                "null",
                "-",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def select_proxy_backend(settings: Settings) -> str:
    if settings.proxy_acceleration == "cpu":
        return "cpu"
    available = _cuda_encoder_available(settings.ffmpeg)
    if settings.proxy_acceleration == "cuda" and not available:
        raise RuntimeError(
            "CUDA proxy acceleration was requested, but FFmpeg could not initialize NVENC"
        )
    return "cuda" if available else "cpu"


def _run_proxy_command(
    command: list[str],
    manifest: SessionManifest,
    on_progress: Callable[[float, float | None], None] | None,
) -> tuple[int, list[str]]:
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"ffmpeg not found: {command[0]}") from exc
    output_lines: list[str] = []
    progress_values: dict[str, str] = {}
    if process.stdout is not None:
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            output_lines.append(line)
            output_lines = output_lines[-20:]
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            progress_values[key] = value
            if key != "progress" or on_progress is None:
                continue
            try:
                output_seconds = int(progress_values.get("out_time_ms", "0")) / 1_000_000
            except ValueError:
                output_seconds = 0.0
            speed_text = progress_values.get("speed", "").removesuffix("x")
            try:
                speed = float(speed_text)
            except ValueError:
                speed = None
            completed = min(1.0, max(0.0, output_seconds / manifest.duration_seconds))
            on_progress(completed, speed)
    return process.wait(), output_lines


def _ffconcat_path(path: Path) -> str:
    return str(path).replace("'", "'\\''")


def generate_proxy(
    manifest: SessionManifest,
    session_dir: Path,
    settings: Settings,
    on_progress: Callable[[float, float | None], None] | None = None,
    on_backend: Callable[[str], None] | None = None,
) -> tuple[Path, bool]:
    output = session_dir / "media" / "proxy.mp4"
    metadata = session_dir / "media" / "proxy.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    if proxy_is_current(output, metadata, manifest):
        return output, True
    concat_file = session_dir / "media" / "chapters.ffconcat"
    concat_file.write_text(
        "ffconcat version 1.0\n"
        + "".join(
            f"file '{_ffconcat_path(Path(chapter.fingerprint.path))}'\n"
            for chapter in manifest.chapters
        ),
        encoding="utf-8",
    )
    partial = output.with_suffix(".partial.mp4")
    backend = select_proxy_backend(settings)
    if on_backend is not None:
        on_backend(backend)
    command = build_proxy_command(
        [Path(chapter.fingerprint.path) for chapter in manifest.chapters],
        concat_file,
        partial,
        settings,
        use_cuda=backend == "cuda",
    )
    return_code, output_lines = _run_proxy_command(command, manifest, on_progress)
    if return_code and backend == "cuda" and settings.proxy_acceleration == "auto":
        logger.warning("CUDA proxy transcode failed; retrying on CPU: %s", output_lines[-1:])
        backend = "cpu"
        if on_backend is not None:
            on_backend(backend)
        command = build_proxy_command(
            [Path(chapter.fingerprint.path) for chapter in manifest.chapters],
            concat_file,
            partial,
            settings,
        )
        return_code, output_lines = _run_proxy_command(command, manifest, on_progress)
    if return_code:
        detail = "\n".join(output_lines[-8:])
        raise RuntimeError(
            f"Proxy transcode failed with status {return_code}" + (f":\n{detail}" if detail else "")
        )
    if on_progress is not None:
        on_progress(1.0, None)
    os.replace(partial, output)
    atomic_json(
        metadata,
        {
            "profile": PROXY_PROFILE,
            "backend": backend,
            "signature": proxy_cache_signature(manifest),
            "source_sha256": [chapter.fingerprint.sha256 for chapter in manifest.chapters],
        },
    )
    return output, False


def generate_thumbnail(manifest: SessionManifest, session_dir: Path, settings: Settings) -> Path:
    output = session_dir / "media" / "thumbnail.jpg"
    if output.is_file() and output.stat().st_size:
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    chapter = manifest.chapters[0]
    timestamp = min(5.0, chapter.duration_seconds / 2)
    subprocess.run(
        [
            settings.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            str(timestamp),
            "-i",
            chapter.fingerprint.path,
            "-frames:v",
            "1",
            "-vf",
            "scale=640:-2",
            str(output),
        ],
        check=True,
    )
    return output
