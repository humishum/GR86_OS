from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path
    var_root: Path
    media_roots: tuple[Path, ...]
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    gps_error_limit_m: float = 5.0
    proxy_acceleration: str = "auto"

    @property
    def database_path(self) -> Path:
        return self.var_root / "catalog.sqlite3"

    @classmethod
    def from_env(cls) -> Settings:
        project_root = Path(os.getenv("RACE_REVIEW_ROOT", _default_project_root())).resolve()
        var_root = Path(os.getenv("RACE_REVIEW_VAR", project_root / "var")).resolve()
        configured = os.getenv("RACE_REVIEW_MEDIA_ROOTS")
        if configured:
            media_roots = tuple(
                Path(item).expanduser().resolve() for item in configured.split(os.pathsep)
            )
        else:
            repository_root = project_root.parent
            media_roots = (repository_root / "data",)
        proxy_acceleration = os.getenv("RACE_REVIEW_PROXY_ACCELERATION", "auto").lower()
        if proxy_acceleration not in {"auto", "cuda", "cpu"}:
            raise ValueError("RACE_REVIEW_PROXY_ACCELERATION must be one of: auto, cuda, cpu")
        return cls(
            project_root=project_root,
            var_root=var_root,
            media_roots=media_roots,
            ffmpeg=os.getenv("FFMPEG", "ffmpeg"),
            ffprobe=os.getenv("FFPROBE", "ffprobe"),
            gps_error_limit_m=float(os.getenv("RACE_REVIEW_GPS_ERROR_LIMIT_M", "5")),
            proxy_acceleration=proxy_acceleration,
        )

    def ensure_directories(self) -> None:
        self.var_root.mkdir(parents=True, exist_ok=True)
        (self.var_root / "sessions").mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        return self.var_root / "sessions" / session_id

    def resolve_media(self, candidate: str | Path, *, must_exist: bool = True) -> Path:
        path = Path(candidate).expanduser().resolve()
        if not any(path.is_relative_to(root) for root in self.media_roots):
            roots = ", ".join(str(root) for root in self.media_roots)
            raise ValueError(f"Media path is outside configured roots ({roots}): {path}")
        if must_exist and (not path.is_file() or path.suffix.lower() != ".mp4"):
            raise ValueError(f"Media path is not an MP4 file: {path}")
        return path
