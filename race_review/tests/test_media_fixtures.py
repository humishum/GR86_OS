from __future__ import annotations

import json

import pytest
from media_fixtures import (
    cuda_encoder_available,
    manifest_for_media,
    requires_ffmpeg,
    requires_nvidia,
    write_h264_fixture,
)

from race_review.config import Settings
from race_review.media import probe_media
from race_review.proxy import generate_proxy, generate_thumbnail, select_proxy_backend


@requires_ffmpeg
@pytest.mark.ffmpeg
def test_linux_macos_cpu_fixture_probe_proxy_and_thumbnail(tmp_path) -> None:
    source = write_h264_fixture(tmp_path / "GX010001.MP4")
    settings = Settings(
        project_root=tmp_path,
        var_root=tmp_path / "var",
        media_roots=(tmp_path,),
        proxy_acceleration="cpu",
    )
    probed = probe_media(source, settings)
    assert probed["duration_seconds"] == pytest.approx(2.0, abs=0.15)
    assert probed["video_codec"] in {"h264", "avc1"}

    manifest = manifest_for_media(source, settings)
    session_dir = tmp_path / "session"
    output, reused = generate_proxy(manifest, session_dir, settings)
    assert reused is False
    proxy = probe_media(output, settings)
    assert proxy["video_codec"] in {"h264", "avc1"}
    height = next(
        stream.height
        for stream in proxy["streams"]
        if stream.codec_type == "video" and stream.height
    )
    assert height == 1080
    metadata = json.loads((session_dir / "media" / "proxy.json").read_text(encoding="utf-8"))
    assert metadata["backend"] == "cpu"

    thumbnail = generate_thumbnail(manifest, session_dir, settings)
    assert thumbnail.is_file()
    assert thumbnail.stat().st_size > 0


@requires_ffmpeg
@requires_nvidia
@pytest.mark.ffmpeg
@pytest.mark.nvidia
def test_opt_in_nvidia_proxy_uses_cuda_backend(tmp_path) -> None:
    assert cuda_encoder_available(), "RACE_REVIEW_NVIDIA=1 requires a working FFmpeg NVENC encoder"
    source = write_h264_fixture(tmp_path / "GX010001.MP4")
    settings = Settings(
        project_root=tmp_path,
        var_root=tmp_path / "var",
        media_roots=(tmp_path,),
        proxy_acceleration="cuda",
    )
    assert select_proxy_backend(settings) == "cuda"
    manifest = manifest_for_media(source, settings)
    output, reused = generate_proxy(manifest, tmp_path / "session", settings)
    assert reused is False
    metadata = json.loads((tmp_path / "session" / "media" / "proxy.json").read_text())
    assert metadata["backend"] == "cuda"
    assert output.stat().st_size > 0
    probed = probe_media(output, settings)
    assert probed["video_codec"] in {"h264", "avc1"}
