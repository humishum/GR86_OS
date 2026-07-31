from __future__ import annotations

import json
import logging
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from . import __version__
from .analysis import (
    apply_corner_edits,
    build_laps,
    build_reference_centerline,
    derive_kinematics,
    detect_corners,
    estimate_calibration,
    filter_gps,
    infer_start_finish,
    project_laps_to_centerline,
    project_wgs84_to_enu,
)
from .catalog import Catalog
from .config import Settings
from .media import fingerprint, probe_media, telemetry_packet_count
from .models import ChapterManifest, ImportRequest, ProcessingStage, SessionManifest
from .proxy import PROXY_PROFILE, ProxyCancelled, generate_proxy, generate_thumbnail
from .storage import atomic_json, write_parquet
from .telemetry import GOPROPY_REVISION, extract_chapters

logger = logging.getLogger(__name__)


class ImportCancelled(RuntimeError):
    pass


class ImportService:
    def __init__(self, settings: Settings, catalog: Catalog):
        self.settings = settings
        self.catalog = catalog
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="race-import")
        self._running: set[str] = set()
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def prepare(self, request: ImportRequest) -> SessionManifest:
        paths = [self.settings.resolve_media(item) for item in request.chapters]
        probes = [probe_media(path, self.settings) for path in paths]
        warnings: list[str] = []
        recording_ids = {probe["recording_id"] for probe in probes if probe["recording_id"]}
        if len(recording_ids) > 1:
            raise ValueError("Chapters belong to different GoPro recording identities")
        chapter_numbers = [probe["chapter_number"] for probe in probes]
        present_numbers = [number for number in chapter_numbers if number is not None]
        if present_numbers and present_numbers != sorted(present_numbers):
            raise ValueError("GoPro chapters are not in recording order")
        if len(present_numbers) > 1 and any(
            current != previous + 1
            for previous, current in zip(present_numbers, present_numbers[1:], strict=False)
        ):
            warnings.append(
                "One or more GoPro chapters are missing; the discontinuity is preserved"
            )

        chapters: list[ChapterManifest] = []
        timeline = 0.0
        previous_creation = None
        previous_duration = 0.0
        for index, (path, probe) in enumerate(zip(paths, probes, strict=True)):
            if probe["duration_seconds"] <= 0:
                raise ValueError(f"Chapter has no usable media duration: {path}")
            if not probe["has_telemetry"]:
                raise ValueError(f"Chapter has no GoPro GPMF telemetry stream: {path}")
            if not probe["video_codec"]:
                raise ValueError(f"Chapter has no video stream: {path}")
            gap = 0.0
            discontinuity = False
            creation = probe["creation_time"]
            if previous_creation and creation:
                gap = (creation - previous_creation).total_seconds() - previous_duration
                if gap < -1:
                    raise ValueError("Chapter creation times overlap or are out of order")
                if abs(gap) > 1:
                    discontinuity = True
                    warnings.append(
                        f"Chapter {index + 1} has a {gap:.3f}s source-time discontinuity"
                    )
            chapter = ChapterManifest(
                index=index,
                filename=path.name,
                fingerprint=fingerprint(path),
                creation_time=creation,
                duration_seconds=probe["duration_seconds"],
                timeline_start_seconds=timeline,
                timeline_end_seconds=timeline + probe["duration_seconds"],
                gap_before_seconds=gap,
                discontinuity=discontinuity,
                recording_id=probe["recording_id"],
                streams=probe["streams"],
                telemetry_packets=telemetry_packet_count(path, self.settings),
            )
            chapters.append(chapter)
            timeline = chapter.timeline_end_seconds
            previous_creation, previous_duration = creation, probe["duration_seconds"]

        now = datetime.now(UTC)
        session_id = uuid.uuid4().hex[:12]
        manifest = SessionManifest(
            session_id=session_id,
            name=request.name or paths[0].stem,
            created_at=now,
            updated_at=now,
            status="queued",
            duration_seconds=timeline,
            chapters=chapters,
            processing_versions={
                "race_review": __version__,
                "analysis": "1",
                "manifest": "1",
                "gopropy": GOPROPY_REVISION,
            },
            processing_options={
                "generate_proxy": request.generate_proxy,
            },
            warnings=warnings,
        )
        session_dir = self.settings.session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(session_dir / "manifest.json", manifest.model_dump(mode="json"))
        self.catalog.create_session(manifest)
        return manifest

    def submit(self, manifest: SessionManifest, request: ImportRequest) -> None:
        with self._lock:
            if manifest.session_id in self._running:
                return
            self._running.add(manifest.session_id)
            self._cancel_events.setdefault(manifest.session_id, threading.Event()).clear()
        self._executor.submit(self._guarded_process, manifest.session_id, request)

    def retry(self, session_id: str) -> SessionManifest:
        manifest = self.catalog.get_manifest(session_id)
        if manifest.status not in {"failed", "cancelled"}:
            raise ValueError("Only failed or cancelled imports can be retried")
        manifest.status = "queued"
        self._save(manifest)
        self.catalog.set_job(
            session_id, status="queued", stage="queued", progress=0, message="Waiting to retry"
        )
        self.submit(
            manifest,
            ImportRequest(
                chapters=[chapter.fingerprint.path for chapter in manifest.chapters],
                name=manifest.name,
                generate_proxy=manifest.processing_options.get("generate_proxy", True),
            ),
        )
        return manifest

    def relocate_source(
        self, session_id: str, chapter_index: int, candidate: str
    ) -> SessionManifest:
        manifest = self.catalog.get_manifest(session_id)
        chapter = next(
            (item for item in manifest.chapters if item.index == chapter_index), None
        )
        if chapter is None:
            raise ValueError(f"Chapter {chapter_index} does not exist")
        path = self.settings.resolve_media(candidate)
        replacement = fingerprint(path)
        if replacement.sha256 != chapter.fingerprint.sha256:
            raise ValueError("Replacement file does not match the imported source SHA-256")
        chapter.fingerprint = replacement
        chapter.filename = path.name
        stale_prefix = "Source is missing or stale:"
        manifest.warnings = [
            warning
            for warning in manifest.warnings
            if not warning.startswith(stale_prefix)
        ]
        self._save(manifest)
        return manifest

    def cancel(self, session_id: str) -> SessionManifest:
        manifest = self.catalog.get_manifest(session_id)
        with self._lock:
            if session_id not in self._running:
                raise ValueError("Import is not running")
            self._cancel_events.setdefault(session_id, threading.Event()).set()
        manifest.status = "cancelling"
        self._save(manifest)
        job = self.catalog.get_job(session_id)
        self.catalog.set_job(
            session_id,
            status="cancelling",
            stage=job.stage,
            progress=job.progress,
            message="Cancelling import",
        )
        return manifest

    def rebuild_proxy(self, session_id: str) -> SessionManifest:
        manifest = self.catalog.get_manifest(session_id)
        if manifest.status != "ready":
            raise ValueError("Proxy can only be rebuilt for a ready session")
        with self._lock:
            if session_id in self._running:
                raise ValueError("Another session action is already running")
            self._running.add(session_id)
            self._cancel_events.setdefault(session_id, threading.Event()).clear()
        manifest.status = "processing"
        self._save(manifest)
        self._executor.submit(self._guarded_rebuild_proxy, session_id)
        return manifest

    def _is_cancelled(self, session_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(session_id)
            return bool(event and event.is_set())

    def _check_cancelled(self, session_id: str) -> None:
        if self._is_cancelled(session_id):
            raise ImportCancelled("Import cancelled")

    def _start_stage(
        self,
        manifest: SessionManifest,
        stage: str,
        *,
        command_profile: str,
        backend: str | None = None,
    ) -> None:
        attempts = manifest.processing_stages.setdefault(stage, [])
        attempts.append(
            ProcessingStage(
                attempt=len(attempts) + 1,
                status="running",
                started_at=datetime.now(UTC),
                backend=backend,
                command_profile=command_profile,
            )
        )
        self._save(manifest)

    def _set_stage_backend(
        self, manifest: SessionManifest, stage: str, backend: str
    ) -> None:
        attempts = manifest.processing_stages.get(stage, [])
        if attempts and attempts[-1].status == "running":
            attempts[-1].backend = backend
            self._save(manifest)

    def _finish_stage(
        self,
        manifest: SessionManifest,
        stage: str,
        *,
        status: str = "completed",
        failure: BaseException | None = None,
    ) -> None:
        attempts = manifest.processing_stages.get(stage, [])
        if not attempts or attempts[-1].status != "running":
            return
        attempt = attempts[-1]
        attempt.status = status  # type: ignore[assignment]
        attempt.ended_at = datetime.now(UTC)
        if failure is not None:
            attempt.failure_diagnostics = {
                "exception_type": type(failure).__name__,
                "message": str(failure),
            }
        self._save(manifest)

    def _finish_active_stage(
        self, manifest: SessionManifest, *, status: str, failure: BaseException | None = None
    ) -> None:
        running = [
            (name, attempts[-1])
            for name, attempts in manifest.processing_stages.items()
            if attempts and attempts[-1].status == "running"
        ]
        if running:
            name, _ = max(running, key=lambda item: item[1].started_at)
            self._finish_stage(manifest, name, status=status, failure=failure)

    def process(self, session_id: str, request: ImportRequest) -> SessionManifest:
        return self._process(session_id, request)

    def _guarded_process(self, session_id: str, request: ImportRequest) -> None:
        try:
            self._process(session_id, request)
        except (ImportCancelled, ProxyCancelled) as exc:
            manifest = self.catalog.get_manifest(session_id)
            self._finish_active_stage(manifest, status="cancelled", failure=exc)
            manifest = self.catalog.get_manifest(session_id)
            manifest.status = "cancelled"
            self._save(manifest)
            self.catalog.set_job(
                session_id,
                status="cancelled",
                stage="cancelled",
                progress=1,
                message="Import cancelled",
            )
        except Exception as exc:  # Background failures are persisted for UI inspection.
            logger.exception("Session import failed: %s", session_id)
            self.catalog.set_job(
                session_id,
                status="failed",
                stage="failed",
                progress=1,
                message=str(exc),
                error="".join(traceback.format_exception_only(type(exc), exc)).strip(),
            )
            try:
                manifest = self.catalog.get_manifest(session_id)
                self._finish_active_stage(manifest, status="failed", failure=exc)
                manifest = self.catalog.get_manifest(session_id)
                manifest.status = "failed"
                manifest.warnings.append(str(exc))
                self._save(manifest)
            except Exception:
                logger.exception("Could not persist failed manifest")
        finally:
            with self._lock:
                self._running.discard(session_id)

    def _guarded_rebuild_proxy(self, session_id: str) -> None:
        try:
            manifest = self.catalog.get_manifest(session_id)
            session_dir = self.settings.session_dir(session_id)
            self._start_stage(
                manifest, "proxy", command_profile=PROXY_PROFILE
            )
            self.catalog.set_job(
                session_id,
                status="processing",
                stage="proxy",
                progress=0,
                message=f"Rebuilding {PROXY_PROFILE} browser proxy",
            )
            proxy, _ = generate_proxy(
                manifest,
                session_dir,
                self.settings,
                on_progress=lambda completed, _speed: self.catalog.set_job(
                    session_id,
                    status="processing",
                    stage="proxy",
                    progress=completed,
                    message=f"Rebuilding browser proxy · {round(completed * 100)}%",
                ),
                on_backend=lambda backend: self._set_stage_backend(
                    manifest, "proxy", backend
                ),
                should_cancel=lambda: self._is_cancelled(session_id),
                force=True,
            )
            manifest.artifacts["proxy"] = str(proxy.relative_to(session_dir))
            self._finish_stage(manifest, "proxy")
            manifest = self.catalog.get_manifest(session_id)
            manifest.status = "ready"
            self._save(manifest)
            self.catalog.set_job(
                session_id,
                status="ready",
                stage="complete",
                progress=1,
                message="Browser proxy rebuilt",
            )
        except (ImportCancelled, ProxyCancelled) as exc:
            manifest = self.catalog.get_manifest(session_id)
            self._finish_active_stage(manifest, status="cancelled", failure=exc)
            manifest = self.catalog.get_manifest(session_id)
            manifest.status = "cancelled"
            self._save(manifest)
            self.catalog.set_job(
                session_id, status="cancelled", stage="cancelled", progress=1,
                message="Proxy rebuild cancelled",
            )
        except Exception as exc:
            logger.exception("Proxy rebuild failed: %s", session_id)
            manifest = self.catalog.get_manifest(session_id)
            self._finish_active_stage(manifest, status="failed", failure=exc)
            manifest = self.catalog.get_manifest(session_id)
            manifest.status = "failed"
            manifest.warnings.append(str(exc))
            self._save(manifest)
            self.catalog.set_job(
                session_id, status="failed", stage="failed", progress=1,
                message=str(exc), error=str(exc),
            )
        finally:
            with self._lock:
                self._running.discard(session_id)

    def _save(self, manifest: SessionManifest) -> None:
        session_dir = self.settings.session_dir(manifest.session_id)
        self.catalog.save_manifest(manifest)
        atomic_json(session_dir / "manifest.json", manifest.model_dump(mode="json"))

    def _analysis_artifacts_current(
        self, manifest: SessionManifest, session_dir: Path
    ) -> bool:
        if (
            manifest.processing_versions.get("gopropy") != GOPROPY_REVISION
            or manifest.processing_versions.get("analysis") != "1"
        ):
            return False
        required = {
            "derived_telemetry": {"timestamp", "valid", "latitude", "longitude"},
            "centerline": set(),
        }
        try:
            for name, columns in required.items():
                relative = manifest.artifacts.get(name)
                if not relative:
                    return False
                path = session_dir / relative
                if not path.is_file() or path.stat().st_size == 0:
                    return False
                if not columns.issubset(pd.read_parquet(path).columns):
                    return False
            for name in ("laps", "corners", "diagnostics"):
                relative = manifest.artifacts.get(name)
                path = session_dir / relative if relative else None
                if path is None or not path.is_file() or path.stat().st_size == 0:
                    return False
                json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return bool(manifest.streams)

    def _extract_and_analyze(
        self, manifest: SessionManifest, session_dir: Path
    ) -> SessionManifest:
        session_id = manifest.session_id
        manifest.processing_versions["gopropy"] = GOPROPY_REVISION
        manifest.processing_versions["analysis"] = "1"
        self._start_stage(
            manifest,
            "telemetry",
            command_profile=f"gopropy@{GOPROPY_REVISION}",
            backend="python",
        )
        self.catalog.set_job(
            session_id,
            status="processing",
            stage="telemetry",
            progress=0.05,
            message="Extracting GPMF",
        )
        paths = [Path(chapter.fingerprint.path) for chapter in manifest.chapters]
        offsets = [chapter.timeline_start_seconds for chapter in manifest.chapters]
        streams, summaries, detected_model = extract_chapters(
            paths, offsets, session_dir / "telemetry"
        )
        self._finish_stage(manifest, "telemetry")
        manifest = self.catalog.get_manifest(session_id)
        self._check_cancelled(session_id)
        manifest.streams = summaries
        if detected_model:
            manifest.processing_versions["camera_model"] = detected_model
        gps_name = "GPS9" if "GPS9" in streams else "GPS5" if "GPS5" in streams else None
        if gps_name is None:
            raise ValueError("No GPS5 or GPS9 stream was extracted")

        self._start_stage(
            manifest,
            "analysis",
            command_profile=manifest.processing_versions["analysis"],
            backend="python",
        )
        self.catalog.set_job(
            session_id,
            status="processing",
            stage="analysis",
            progress=0.35,
            message="Deriving route and laps",
        )
        gps = streams[gps_name].copy()
        gps["segment_id"] = gps["chapter_index"]
        gps = filter_gps(gps, self.settings.gps_dop_limit)
        gps, origin = project_wgs84_to_enu(gps)
        gps = derive_kinematics(gps)
        manifest.coordinate_origin = origin
        if manifest.edits.track.start_finish_a is None:
            manifest.edits.track = infer_start_finish(gps)
        laps = build_laps(gps, manifest.edits.track)
        centerline = build_reference_centerline(gps, laps)
        gps = project_laps_to_centerline(gps, laps, centerline)
        corners = apply_corner_edits(detect_corners(gps), manifest.edits.corner_edits)
        imu = streams.get("ACCL")
        if not manifest.edits.calibration.overridden:
            manifest.edits.calibration = estimate_calibration(gps, imu, streams.get("GRAV"))

        write_parquet(gps, session_dir / "telemetry" / "derived.parquet")
        write_parquet(centerline, session_dir / "analysis" / "centerline.parquet")
        atomic_json(session_dir / "analysis" / "laps.json", [lap.model_dump() for lap in laps])
        atomic_json(
            session_dir / "analysis" / "corners.json", [corner.model_dump() for corner in corners]
        )
        diagnostics = {
            "gps_total": len(gps),
            "gps_valid": int(gps["valid"].sum()),
            "rejections": gps.loc[~gps["valid"], "rejection_reason"].value_counts().to_dict(),
            "warnings": manifest.warnings,
        }
        atomic_json(session_dir / "analysis" / "diagnostics.json", diagnostics)
        manifest.artifacts.update(
            {
                "derived_telemetry": "telemetry/derived.parquet",
                "laps": "analysis/laps.json",
                "corners": "analysis/corners.json",
                "centerline": "analysis/centerline.parquet",
                "diagnostics": "analysis/diagnostics.json",
            }
        )
        self._finish_stage(manifest, "analysis")
        manifest = self.catalog.get_manifest(session_id)
        self._check_cancelled(session_id)
        return manifest

    def _process(self, session_id: str, request: ImportRequest) -> SessionManifest:
        manifest = self.catalog.get_manifest(session_id)
        session_dir = self.settings.session_dir(session_id)
        manifest.status = "processing"
        self._save(manifest)
        self._check_cancelled(session_id)

        if self._analysis_artifacts_current(manifest, session_dir):
            self.catalog.set_job(
                session_id,
                status="processing",
                stage="resume",
                progress=0.5,
                message="Verified analysis artifacts; resuming media stages",
            )
        else:
            manifest = self._extract_and_analyze(manifest, session_dir)

        thumbnail_relative = manifest.artifacts.get("thumbnail")
        thumbnail = session_dir / thumbnail_relative if thumbnail_relative else None
        if thumbnail is None or not thumbnail.is_file() or thumbnail.stat().st_size == 0:
            self._start_stage(
                manifest, "thumbnail", command_profile="ffmpeg-thumbnail-v1", backend="cpu"
            )
            self.catalog.set_job(
                session_id,
                status="processing",
                stage="thumbnail",
                progress=0.55,
                message="Creating preview",
            )
            thumbnail = generate_thumbnail(manifest, session_dir, self.settings)
            manifest.artifacts["thumbnail"] = str(thumbnail.relative_to(session_dir))
            self._finish_stage(manifest, "thumbnail")
            manifest = self.catalog.get_manifest(session_id)
            manifest.artifacts["thumbnail"] = str(thumbnail.relative_to(session_dir))
        # Persist the completed analysis before the long-running proxy stage so a
        # restart does not leave a manifest that appears empty.
        self._save(manifest)
        self._check_cancelled(session_id)

        if request.generate_proxy:
            self._start_stage(manifest, "proxy", command_profile=PROXY_PROFILE)
            self.catalog.set_job(
                session_id,
                status="processing",
                stage="proxy",
                progress=0.6,
                message="Transcoding browser proxy",
            )

            def proxy_progress(completed: float, speed: float | None) -> None:
                overall_progress = 0.6 + 0.38 * completed
                percent = round(completed * 100)
                detail = f"Transcoding browser proxy · {percent}%"
                if speed and speed > 0:
                    remaining_seconds = manifest.duration_seconds * (1 - completed) / speed
                    minutes, seconds = divmod(max(0, round(remaining_seconds)), 60)
                    detail += f" · {speed:.2f}× · about {minutes}:{seconds:02d} remaining"
                elif completed >= 1:
                    detail = "Finalizing browser proxy"
                self.catalog.set_job(
                    session_id,
                    status="processing",
                    stage="proxy",
                    progress=min(overall_progress, 0.98),
                    message=detail,
                )

            def proxy_backend(backend: str) -> None:
                self._set_stage_backend(manifest, "proxy", backend)
                label = "NVIDIA CUDA" if backend == "cuda" else "CPU"
                self.catalog.set_job(
                    session_id,
                    status="processing",
                    stage="proxy",
                    progress=0.6,
                    message=f"Starting {label} browser proxy",
                )

            proxy, reused = generate_proxy(
                manifest,
                session_dir,
                self.settings,
                on_progress=proxy_progress,
                on_backend=proxy_backend,
                should_cancel=lambda: self._is_cancelled(session_id),
            )
            manifest.artifacts["proxy"] = str(proxy.relative_to(session_dir))
            self._finish_stage(manifest, "proxy")
            manifest = self.catalog.get_manifest(session_id)
            manifest.artifacts["proxy"] = str(proxy.relative_to(session_dir))
            if reused:
                manifest.warnings.append("Existing proxy reused from cache")
        else:
            manifest.warnings.append("Browser proxy was skipped for this import")

        manifest.status = "ready"
        self._save(manifest)
        self.catalog.set_job(
            session_id, status="ready", stage="complete", progress=1, message="Race review ready"
        )
        return manifest

    def reanalyze(self, session_id: str) -> SessionManifest:
        manifest = self.catalog.get_manifest(session_id)
        session_dir = self.settings.session_dir(session_id)
        gps = pd.read_parquet(session_dir / "telemetry" / "derived.parquet")
        laps = build_laps(gps, manifest.edits.track)
        centerline = build_reference_centerline(gps, laps)
        gps = project_laps_to_centerline(gps, laps, centerline)
        corners = apply_corner_edits(detect_corners(gps), manifest.edits.corner_edits)
        write_parquet(gps, session_dir / "telemetry" / "derived.parquet")
        write_parquet(centerline, session_dir / "analysis" / "centerline.parquet")
        atomic_json(session_dir / "analysis" / "laps.json", [lap.model_dump() for lap in laps])
        atomic_json(
            session_dir / "analysis" / "corners.json", [corner.model_dump() for corner in corners]
        )
        self._save(manifest)
        return manifest
