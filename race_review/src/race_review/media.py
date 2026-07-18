from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

from .config import Settings
from .models import MediaEntry, MediaStream, SourceFingerprint

GOPRO_NAME = re.compile(r"^(?:GOPR|GP|GX|GH)(?P<chapter>\d{2})(?P<recording>\d{4})$", re.I)


def _run_json(command: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required media tool not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError(exc.stderr.strip() or f"Media command failed: {command[0]}") from exc
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON returned by {command[0]}") from exc


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(path: Path) -> SourceFingerprint:
    stat = path.stat()
    return SourceFingerprint(
        path=str(path),
        size_bytes=stat.st_size,
        modified_ns=stat.st_mtime_ns,
        sha256=sha256_file(path),
    )


def _fraction(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    try:
        number = float(Fraction(value))
        return number if math.isfinite(number) else None
    except (ValueError, ZeroDivisionError):
        return None


def probe_media(path: Path, settings: Settings) -> dict[str, Any]:
    data = _run_json(
        [
            settings.ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    streams: list[MediaStream] = []
    for stream in data.get("streams", []):
        duration = stream.get("duration")
        streams.append(
            MediaStream(
                index=int(stream["index"]),
                codec_type=stream.get("codec_type", "unknown"),
                codec_name=stream.get("codec_name"),
                codec_tag=stream.get("codec_tag_string"),
                duration_seconds=float(duration) if duration is not None else None,
                frame_rate=_fraction(stream.get("avg_frame_rate") or stream.get("r_frame_rate")),
                width=stream.get("width"),
                height=stream.get("height"),
            )
        )
    format_info = data.get("format", {})
    duration = float(format_info.get("duration") or 0)
    creation = format_info.get("tags", {}).get("creation_time")
    if not creation:
        for stream in data.get("streams", []):
            creation = stream.get("tags", {}).get("creation_time")
            if creation:
                break
    creation_time = None
    if creation:
        try:
            creation_time = datetime.fromisoformat(creation.replace("Z", "+00:00"))
        except ValueError:
            pass
    stem_match = GOPRO_NAME.match(path.stem)
    return {
        "duration_seconds": duration,
        "creation_time": creation_time,
        "streams": streams,
        "recording_id": stem_match.group("recording") if stem_match else None,
        "chapter_number": int(stem_match.group("chapter")) if stem_match else None,
        "has_telemetry": any(s.codec_tag == "gpmd" for s in streams),
        "video_codec": next((s.codec_name for s in streams if s.codec_type == "video"), None),
    }


def list_media(settings: Settings, relative_path: str = "") -> list[MediaEntry]:
    entries: list[MediaEntry] = []
    for root in settings.media_roots:
        candidate = (root / relative_path).resolve()
        if not candidate.is_relative_to(root) or not candidate.exists() or not candidate.is_dir():
            continue
        for path in sorted(candidate.iterdir(), key=lambda item: item.name.lower()):
            if path.is_file() and path.suffix.lower() == ".mp4":
                stat = path.stat()
                entries.append(
                    MediaEntry(
                        path=str(path),
                        name=path.name,
                        size_bytes=stat.st_size,
                        modified_at=datetime.fromtimestamp(stat.st_mtime).astimezone(),
                    )
                )
    return entries


def source_is_current(source: SourceFingerprint) -> bool:
    path = Path(source.path)
    if not path.is_file():
        return False
    stat = path.stat()
    return stat.st_size == source.size_bytes and stat.st_mtime_ns == source.modified_ns


def telemetry_packet_count(path: Path, settings: Settings) -> int:
    data = _run_json(
        [
            settings.ffprobe,
            "-v",
            "error",
            "-select_streams",
            "d:m:handler_name:GoPro MET",
            "-count_packets",
            "-show_entries",
            "stream=nb_read_packets",
            "-of",
            "json",
            str(path),
        ]
    )
    values = [
        int(item["nb_read_packets"])
        for item in data.get("streams", [])
        if item.get("nb_read_packets")
    ]
    if values:
        return max(values)
    # Handler selectors vary between FFmpeg builds; gpmd is the authoritative fallback.
    data = _run_json(
        [
            settings.ffprobe,
            "-v",
            "error",
            "-select_streams",
            "d",
            "-count_packets",
            "-show_entries",
            "stream=codec_tag_string,nb_read_packets",
            "-of",
            "json",
            str(path),
        ]
    )
    for item in data.get("streams", []):
        if item.get("codec_tag_string") == "gpmd":
            return int(item.get("nb_read_packets") or 0)
    return 0
