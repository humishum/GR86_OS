from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def benchmark_module():
    path = Path(__file__).parents[1] / "scripts" / "benchmark_proxy.py"
    spec = importlib.util.spec_from_file_location("benchmark_proxy", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_progress_line_keeps_final_valid_speed(benchmark_module) -> None:
    progress: dict[str, str] = {}
    assert benchmark_module.parse_progress_line("frame=120", progress) is None
    assert benchmark_module.parse_progress_line("speed=2.89x", progress) == 2.89
    assert benchmark_module.parse_progress_line("speed=N/A", progress) is None
    assert progress == {"frame": "120", "speed": "N/A"}


def test_probe_format_normalizes_ffprobe_values(
    benchmark_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Completed:
        stdout = json.dumps(
            {"format": {"duration": "30.030", "size": "123456", "bit_rate": "32895"}}
        )

    monkeypatch.setattr(benchmark_module.subprocess, "run", lambda *args, **kwargs: Completed())
    assert benchmark_module.probe_format(Path("proxy.mp4"), "ffprobe") == {
        "duration_seconds": 30.03,
        "size_bytes": 123456,
        "average_bitrate_bps": 32895,
    }


def test_write_report_is_valid_pretty_json(benchmark_module, tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    benchmark_module.write_report(path, {"results": [{"backend": "cpu"}]})
    assert json.loads(path.read_text())["results"][0]["backend"] == "cpu"
    assert path.read_text().endswith("\n")
