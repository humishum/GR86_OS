#!/usr/bin/env python3
"""Benchmark the production CPU and CUDA proxy profiles on one source chapter.

The report is rewritten after every backend so a completed CPU result survives a
later CUDA failure. Run from ``race_review``:

    uv run python scripts/benchmark_proxy.py ../data/GX020115.MP4
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from race_review.config import Settings
from race_review.proxy import PROXY_PROFILE, build_proxy_command


def parse_progress_line(line: str, progress: dict[str, str]) -> float | None:
    """Update an FFmpeg progress block and return a newly reported speed."""
    if "=" not in line:
        return None
    key, value = line.strip().split("=", 1)
    progress[key] = value
    if key != "speed":
        return None
    try:
        return float(value.removesuffix("x"))
    except ValueError:
        return None


def probe_format(path: Path, ffprobe: str) -> dict[str, float | int]:
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,bit_rate",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    values = json.loads(completed.stdout)["format"]
    return {
        "duration_seconds": float(values["duration"]),
        "size_bytes": int(values["size"]),
        "average_bitrate_bps": int(values["bit_rate"]),
    }


def seek_latency(
    path: Path, timestamp: float, ffmpeg: str, *, repeats: int
) -> dict[str, Any]:
    samples = []
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-frames:v",
        "1",
        "-f",
        "null",
        "-",
    ]
    for _ in range(repeats):
        started = time.perf_counter()
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        samples.append(time.perf_counter() - started)
    return {
        "timestamp_seconds": timestamp,
        "median_seconds": statistics.median(samples),
        "samples_seconds": samples,
    }


def benchmark_backend(
    source: Path,
    output_dir: Path,
    backend: str,
    settings: Settings,
    ffprobe: str,
    *,
    seek_points: list[float],
    seek_repeats: int,
) -> dict[str, Any]:
    output = output_dir / f"{source.stem}-{backend}.mp4"
    partial = output.with_suffix(".partial.mp4")
    partial.unlink(missing_ok=True)
    command = build_proxy_command(
        [source],
        output_dir / "unused.ffconcat",
        partial,
        settings,
        use_cuda=backend == "cuda",
    )
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    progress: dict[str, str] = {}
    final_speed = None
    tail: list[str] = []
    if process.stdout is not None:
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            tail = [*tail[-39:], line]
            speed = parse_progress_line(line, progress)
            if speed is not None:
                final_speed = speed
    return_code = process.wait()
    wall_seconds = time.perf_counter() - started
    if return_code:
        partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"{backend} FFmpeg failed with status {return_code} after {wall_seconds:.2f}s:\n"
            + "\n".join(tail[-12:])
        )
    partial.replace(output)
    measured = probe_format(output, ffprobe)
    measured.update(
        {
            "status": "completed",
            "backend": backend,
            "wall_seconds": wall_seconds,
            "final_ffmpeg_speed": final_speed,
            "output": str(output.resolve()),
            "seek_latency": [
                seek_latency(output, point, settings.ffmpeg, repeats=seek_repeats)
                for point in seek_points
            ],
            "command": command,
        }
    )
    return measured


def command_version(command: str) -> str:
    completed = subprocess.run(
        [command, "-version"], check=True, capture_output=True, text=True
    )
    return completed.stdout.splitlines()[0]


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.partition(":")[2].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--backend",
        choices=("all", "cpu", "cuda"),
        default="all",
        help="profiles to run, in CPU-then-CUDA order (default: all)",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("var/benchmarks/proxy"))
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--seek",
        type=float,
        action="append",
        help="output timestamp to seek; repeat for multiple points",
    )
    parser.add_argument("--seek-repeats", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    if not source.is_file():
        raise SystemExit(f"Source not found: {source}")
    if args.seek_repeats < 1:
        raise SystemExit("--seek-repeats must be at least 1")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = (args.report or output_dir / f"{source.stem}-benchmark.json").resolve()
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        raise SystemExit("ffmpeg and ffprobe must be on PATH")
    settings = Settings(
        project_root=Path.cwd(),
        var_root=output_dir,
        media_roots=(source.parent,),
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
    )
    source_probe = probe_format(source, ffprobe)
    seek_points = args.seek or [
        5.0,
        source_probe["duration_seconds"] / 2,
        source_probe["duration_seconds"] - 5,
    ]
    seek_points = [point for point in seek_points if 0 <= point < source_probe["duration_seconds"]]
    backends = ["cpu", "cuda"] if args.backend == "all" else [args.backend]
    report: dict[str, Any] = {
        "schema_version": 1,
        "started_at": datetime.now(UTC).isoformat(),
        "source": str(source),
        "source_probe": source_probe,
        "proxy_profile": PROXY_PROFILE,
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": cpu_model(),
            "ffmpeg": command_version(ffmpeg),
        },
        "results": [],
    }
    write_report(report_path, report)
    exit_code = 0
    for backend in backends:
        print(f"Benchmarking {backend}: {source}", flush=True)
        try:
            result = benchmark_backend(
                source,
                output_dir,
                backend,
                settings,
                ffprobe,
                seek_points=seek_points,
                seek_repeats=args.seek_repeats,
            )
        except Exception as exc:
            result = {"status": "failed", "backend": backend, "error": str(exc)}
            exit_code = 1
        report["results"].append(result)
        write_report(report_path, report)
        print(json.dumps(result, indent=2), flush=True)
        if exit_code:
            break
    report["finished_at"] = datetime.now(UTC).isoformat()
    write_report(report_path, report)
    print(f"Report: {report_path}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
