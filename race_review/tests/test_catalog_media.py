from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from race_review.catalog import Catalog
from race_review.config import Settings
from race_review.media import source_is_current
from race_review.models import ChapterManifest, SessionManifest, SourceFingerprint
from race_review.proxy import (
    build_proxy_command,
    generate_proxy,
    proxy_cache_signature,
    proxy_is_current,
)


def manifest(path: Path) -> SessionManifest:
    now = datetime.now(UTC)
    return SessionManifest(
        session_id="abc123",
        name="Test session",
        created_at=now,
        updated_at=now,
        status="queued",
        duration_seconds=10,
        chapters=[
            ChapterManifest(
                index=0,
                filename=path.name,
                fingerprint=SourceFingerprint(
                    path=str(path), size_bytes=4, modified_ns=1, sha256="f" * 64
                ),
                duration_seconds=10,
                timeline_start_seconds=0,
                timeline_end_seconds=10,
            )
        ],
        processing_versions={"race_review": "test"},
    )


def test_catalog_round_trip_and_edit_persistence(tmp_path: Path) -> None:
    source = tmp_path / "GX010001.MP4"
    source.write_bytes(b"test")
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    value = manifest(source)
    catalog.create_session(value)
    catalog.save_edit(value.session_id, "track", {"direction": 1})
    assert catalog.get_manifest(value.session_id).name == "Test session"
    assert catalog.get_edit(value.session_id, "track") == {"direction": 1}
    assert catalog.get_job(value.session_id).progress == 0


def test_media_root_rejects_traversal(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    inside = root / "GX010001.MP4"
    inside.write_bytes(b"test")
    outside = tmp_path / "GX020001.MP4"
    outside.write_bytes(b"test")
    settings = Settings(project_root=tmp_path, var_root=tmp_path / "var", media_roots=(root,))
    assert settings.resolve_media(inside) == inside
    with pytest.raises(ValueError, match="outside configured roots"):
        settings.resolve_media(outside)


def test_stale_or_missing_source_is_reported(tmp_path: Path) -> None:
    source = tmp_path / "GX010001.MP4"
    source.write_bytes(b"test")
    value = manifest(source).chapters[0].fingerprint
    value.modified_ns = source.stat().st_mtime_ns
    assert source_is_current(value)
    source.write_bytes(b"changed")
    assert not source_is_current(value)
    source.unlink()
    assert not source_is_current(value)


def test_proxy_profile_is_browser_compatible(tmp_path: Path) -> None:
    source = tmp_path / "GX010001.MP4"
    source.write_bytes(b"test")
    settings = Settings(project_root=tmp_path, var_root=tmp_path / "var", media_roots=(tmp_path,))
    command = build_proxy_command(
        [source], tmp_path / "list.ffconcat", tmp_path / "proxy.mp4", settings
    )
    joined = " ".join(command)
    assert "libx264" in command
    assert "scale=-2:1080" in joined
    assert command[command.index("-g") + 1] == "120"
    assert command[command.index("-preset") + 1] == "veryfast"
    assert "+faststart" in command
    assert "aac" in command
    assert "-progress" in command
    assert "concat" not in command

    second = tmp_path / "GX020001.MP4"
    second.write_bytes(b"test")
    multi = build_proxy_command(
        [source, second], tmp_path / "list.ffconcat", tmp_path / "proxy.mp4", settings
    )
    assert "concat" in multi

    cuda = build_proxy_command(
        [source], tmp_path / "list.ffconcat", tmp_path / "proxy.mp4", settings, use_cuda=True
    )
    assert "cuda" in cuda
    assert "scale_cuda=-2:1080:interp_algo=lanczos" in cuda
    assert "h264_nvenc" in cuda
    assert "-vsync" in cuda
    assert "-fps_mode" not in cuda
    assert "libx264" not in cuda


def test_proxy_cache_reuses_only_matching_source_identity(tmp_path: Path) -> None:
    source = tmp_path / "GX010001.MP4"
    source.write_bytes(b"test")
    value = manifest(source)
    output = tmp_path / "proxy.mp4"
    metadata = tmp_path / "proxy.json"
    output.write_bytes(b"proxy")
    metadata.write_text('{"signature":"' + proxy_cache_signature(value) + '"}')
    assert proxy_is_current(output, metadata, value)
    changed = value.model_copy(deep=True)
    changed.chapters[0].fingerprint.sha256 = "a" * 64
    assert not proxy_is_current(output, metadata, changed)


def test_proxy_reports_ffmpeg_progress(tmp_path: Path) -> None:
    source = tmp_path / "GX010001.MP4"
    source.write_bytes(b"test")
    value = manifest(source)
    fake_ffmpeg = tmp_path / "fake-ffmpeg"
    fake_ffmpeg.write_text(
        "#!/bin/sh\n"
        'for value in "$@"; do output="$value"; done\n'
        'printf proxy > "$output"\n'
        "printf 'out_time_ms=5000000\\nspeed=2.0x\\nprogress=continue\\n'\n",
        encoding="utf-8",
    )
    fake_ffmpeg.chmod(0o755)
    settings = Settings(
        project_root=tmp_path,
        var_root=tmp_path / "var",
        media_roots=(tmp_path,),
        ffmpeg=str(fake_ffmpeg),
        proxy_acceleration="cpu",
    )
    progress: list[tuple[float, float | None]] = []
    output, reused = generate_proxy(
        value,
        tmp_path / "session",
        settings,
        on_progress=lambda done, speed: progress.append((done, speed)),
    )
    assert output.read_bytes() == b"proxy"
    assert reused is False
    assert progress[0] == (0.5, 2.0)
    assert progress[-1] == (1.0, None)
