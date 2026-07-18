from __future__ import annotations

import json
import mimetypes
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from .analysis import compare_laps
from .catalog import Catalog
from .config import Settings
from .export import build_analysis_bundle
from .ingest import ImportService
from .media import list_media, source_is_current
from .models import (
    Calibration,
    CornerEdit,
    CornerSummary,
    ENUPoint,
    ImportRequest,
    ImportResponse,
    JobStatus,
    LapSummary,
    MediaEntry,
    SessionManifest,
    TelemetryWindow,
    TrackConfig,
    TrackGeometryAdapter,
    WGS84Point,
)


def _session_file(settings: Settings, session_id: str, relative: str) -> Path:
    session_dir = settings.session_dir(session_id).resolve()
    path = (session_dir / relative).resolve()
    if not path.is_relative_to(session_dir):
        raise HTTPException(400, "Invalid artifact path")
    return path


def _json_file(path: Path) -> Any:
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _finite_json(value: object) -> float | int | bool | None:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    try:
        number = float(value)
        return number if np.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _downsample(frame: pd.DataFrame, maximum: int) -> pd.DataFrame:
    if len(frame) <= maximum:
        return frame
    # Deterministic evenly-spaced samples preserve endpoints and video interpolation behavior.
    indices = np.linspace(0, len(frame) - 1, maximum, dtype=int)
    return frame.iloc[np.unique(indices)]


def _range_response(
    path: Path, request: Request, media_type: str, *, filename: str | None = None
) -> StreamingResponse:
    size = path.stat().st_size
    start, end, status = 0, max(0, size - 1), 200
    requested = request.headers.get("range")
    if requested:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested.strip())
        if not match or (not match.group(1) and not match.group(2)):
            raise HTTPException(
                416, "Invalid byte range", headers={"Content-Range": f"bytes */{size}"}
            )
        if match.group(1):
            start = int(match.group(1))
            end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
        else:
            suffix = int(match.group(2))
            start, end = max(0, size - suffix), size - 1
        if start >= size or end < start:
            raise HTTPException(
                416,
                "Byte range is outside the artifact",
                headers={"Content-Range": f"bytes */{size}"},
            )
        status = 206

    async def chunks():
        remaining = end - start + 1
        with path.open("rb") as source:
            source.seek(start)
            while remaining:
                block = source.read(min(1024 * 1024, remaining))
                if not block:
                    break
                remaining -= len(block)
                yield block

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "ETag": f'"{size:x}-{path.stat().st_mtime_ns:x}"',
    }
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    if filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return StreamingResponse(chunks(), status_code=status, media_type=media_type, headers=headers)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_directories()
    catalog = Catalog(settings.database_path)
    importer = ImportService(settings, catalog)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        for manifest in catalog.list_manifests():
            if manifest.status in {"queued", "processing"}:
                importer.submit(
                    manifest,
                    ImportRequest(
                        chapters=[chapter.fingerprint.path for chapter in manifest.chapters],
                        name=manifest.name,
                        generate_proxy=manifest.processing_options.get("generate_proxy", True),
                    ),
                )
        yield

    app = FastAPI(
        title="GR86 Race Review API",
        version="0.1.0",
        description="Local-first GoPro race review using canonical video-relative seconds.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.catalog = catalog
    app.state.importer = importer
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def manifest_or_404(session_id: str) -> SessionManifest:
        try:
            return catalog.get_manifest(session_id)
        except KeyError as exc:
            raise HTTPException(404, "Session not found") from exc

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/media", response_model=list[MediaEntry])
    async def browse_media(path: str = "") -> list[MediaEntry]:
        return list_media(settings, path)

    @app.get("/api/sessions", response_model=list[SessionManifest])
    async def sessions() -> list[SessionManifest]:
        return catalog.list_manifests()

    @app.post("/api/sessions/import", response_model=ImportResponse, status_code=202)
    async def import_session(payload: ImportRequest) -> ImportResponse:
        try:
            manifest = importer.prepare(payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        importer.submit(manifest, payload)
        return ImportResponse(session_id=manifest.session_id, status=manifest.status)

    @app.get("/api/sessions/{session_id}", response_model=SessionManifest)
    async def session(session_id: str) -> SessionManifest:
        manifest = manifest_or_404(session_id)
        for chapter in manifest.chapters:
            if not source_is_current(chapter.fingerprint):
                warning = f"Source is missing or stale: {chapter.fingerprint.path}"
                if warning not in manifest.warnings:
                    manifest.warnings.append(warning)
        return manifest

    @app.get("/api/sessions/{session_id}/status", response_model=JobStatus)
    async def import_status(session_id: str) -> JobStatus:
        manifest_or_404(session_id)
        return catalog.get_job(session_id)

    @app.get("/api/sessions/{session_id}/telemetry", response_model=TelemetryWindow)
    async def telemetry(
        session_id: str,
        start: Annotated[float, Query(ge=0)] = 0,
        end: float | None = Query(default=None, gt=0),
        fields: str | None = None,
        max_points: Annotated[int, Query(ge=2, le=100_000)] = 8_000,
    ) -> TelemetryWindow:
        manifest = manifest_or_404(session_id)
        path = _session_file(settings, session_id, manifest.artifacts.get("derived_telemetry", ""))
        if not path.is_file():
            raise HTTPException(409, "Derived telemetry is not ready")
        frame = pd.read_parquet(path)
        end_time = manifest.duration_seconds if end is None else min(end, manifest.duration_seconds)
        if end_time < start:
            raise HTTPException(422, "end must be after start")
        frame = frame[(frame["timestamp"] >= start) & (frame["timestamp"] <= end_time)]
        default_fields = [
            "timestamp",
            "latitude",
            "longitude",
            "east_smooth_m",
            "north_smooth_m",
            "speed_mps",
            "longitudinal_g",
            "lateral_g",
            "distance_m",
            "lap_number",
            "lap_distance_m",
            "valid",
        ]
        requested = [item.strip() for item in fields.split(",")] if fields else default_fields
        columns = [name for name in requested if name in frame.columns]
        if "timestamp" not in columns:
            columns.insert(0, "timestamp")
        frame = _downsample(frame[columns], max_points)
        rows = [
            [_finite_json(value) for value in row]
            for row in frame.itertuples(index=False, name=None)
        ]
        return TelemetryWindow(
            columns=columns, rows=rows, start_seconds=start, end_seconds=end_time
        )

    @app.get("/api/sessions/{session_id}/laps", response_model=list[LapSummary])
    async def laps(session_id: str) -> list[LapSummary]:
        manifest_or_404(session_id)
        values = _json_file(_session_file(settings, session_id, "analysis/laps.json"))
        return [LapSummary.model_validate(value) for value in values]

    @app.get("/api/sessions/{session_id}/corners", response_model=list[CornerSummary])
    async def corners(session_id: str) -> list[CornerSummary]:
        manifest_or_404(session_id)
        values = _json_file(_session_file(settings, session_id, "analysis/corners.json"))
        return [CornerSummary.model_validate(value) for value in values]

    @app.get("/api/sessions/{session_id}/comparison")
    async def lap_comparison(
        session_id: str,
        reference_lap: Annotated[int, Query(ge=1)],
        comparison_lap: Annotated[int, Query(ge=1)],
        points: Annotated[int, Query(ge=50, le=2_000)] = 500,
    ) -> dict[str, list[float]]:
        manifest = manifest_or_404(session_id)
        frame = pd.read_parquet(
            _session_file(settings, session_id, manifest.artifacts["derived_telemetry"])
        )
        try:
            value = compare_laps(frame, reference_lap, comparison_lap, points)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "distance_m": value.distance_m.tolist(),
            "reference_time_s": value.reference_time_s.tolist(),
            "comparison_time_s": value.comparison_time_s.tolist(),
            "delta_s": value.delta_s.tolist(),
            "reference_speed_mps": value.reference_speed_mps.tolist(),
            "comparison_speed_mps": value.comparison_speed_mps.tolist(),
        }

    @app.get("/api/sessions/{session_id}/track-geometry", response_model=TrackGeometryAdapter)
    async def track_geometry(session_id: str) -> TrackGeometryAdapter:
        manifest = manifest_or_404(session_id)
        if manifest.coordinate_origin is None:
            raise HTTPException(409, "Track geometry is not ready")
        frame = pd.read_parquet(
            _session_file(settings, session_id, manifest.artifacts["derived_telemetry"])
        )
        frame = _downsample(frame[frame["valid"]], 5_000)
        return TrackGeometryAdapter(
            origin=manifest.coordinate_origin,
            route_wgs84=[
                WGS84Point(
                    latitude=float(row.latitude),
                    longitude=float(row.longitude),
                    altitude_m=(
                        float(row.altitude_m)
                        if np.isfinite(float(getattr(row, "altitude_m", np.nan)))
                        else None
                    ),
                )
                for row in frame.itertuples()
            ],
            route_enu_m=[
                ENUPoint(
                    east_m=float(row.east_smooth_m),
                    north_m=float(row.north_smooth_m),
                    up_m=(
                        float(row.up_m) if np.isfinite(float(getattr(row, "up_m", np.nan))) else 0.0
                    ),
                )
                for row in frame.itertuples()
            ],
        )

    @app.put("/api/sessions/{session_id}/track", response_model=SessionManifest)
    async def update_track(session_id: str, track: TrackConfig) -> SessionManifest:
        manifest = manifest_or_404(session_id)
        manifest.edits.track = track
        catalog.save_edit(session_id, "track", track.model_dump(mode="json"))
        catalog.save_manifest(manifest)
        return importer.reanalyze(session_id)

    @app.put("/api/sessions/{session_id}/calibration", response_model=SessionManifest)
    async def update_calibration(session_id: str, calibration: Calibration) -> SessionManifest:
        manifest = manifest_or_404(session_id)
        calibration.overridden = True
        manifest.edits.calibration = calibration
        catalog.save_edit(session_id, "calibration", calibration.model_dump(mode="json"))
        catalog.save_manifest(manifest)
        importer._save(manifest)
        return manifest

    @app.put("/api/sessions/{session_id}/corners", response_model=list[CornerSummary])
    async def update_corners(session_id: str, edits: list[CornerEdit]) -> list[CornerSummary]:
        manifest = manifest_or_404(session_id)
        edit_values = [edit.model_dump(exclude_none=True, mode="json") for edit in edits]
        manifest.edits.corner_edits = [*manifest.edits.corner_edits, *edit_values]
        catalog.save_edit(session_id, "corners", manifest.edits.corner_edits)
        catalog.save_manifest(manifest)
        importer.reanalyze(session_id)
        return await corners(session_id)

    @app.post("/api/sessions/{session_id}/reanalyze", response_model=SessionManifest)
    async def reanalyze(session_id: str) -> SessionManifest:
        manifest_or_404(session_id)
        return importer.reanalyze(session_id)

    @app.get("/api/sessions/{session_id}/media/proxy")
    async def proxy_media(session_id: str, request: Request) -> StreamingResponse:
        manifest = manifest_or_404(session_id)
        relative = manifest.artifacts.get("proxy")
        if not relative:
            raise HTTPException(409, "Browser proxy was not generated")
        path = _session_file(settings, session_id, relative)
        if not path.is_file():
            raise HTTPException(404, "Proxy artifact is missing")
        return _range_response(path, request, "video/mp4")

    @app.get("/api/sessions/{session_id}/thumbnail")
    async def thumbnail(session_id: str) -> Response:
        manifest = manifest_or_404(session_id)
        relative = manifest.artifacts.get("thumbnail")
        if not relative:
            raise HTTPException(409, "Thumbnail is not ready")
        return Response(
            content=_session_file(settings, session_id, relative).read_bytes(),
            media_type="image/jpeg",
        )

    @app.post("/api/sessions/{session_id}/export")
    async def export_bundle(
        session_id: str, request: Request, include_clip_references: bool = False
    ) -> StreamingResponse:
        manifest = manifest_or_404(session_id)
        bundle = build_analysis_bundle(
            manifest,
            settings.session_dir(session_id),
            include_clip_references=include_clip_references,
        )
        return _range_response(
            bundle,
            request,
            "application/zip",
            filename=f"{session_id}-analysis.zip",
        )

    frontend_dist = settings.project_root / "frontend" / "dist"
    if frontend_dist.is_dir():

        @app.get("/{asset_path:path}", include_in_schema=False)
        async def frontend(asset_path: str) -> Response:
            candidate = (frontend_dist / asset_path).resolve()
            if not candidate.is_relative_to(frontend_dist) or not candidate.is_file():
                candidate = frontend_dist / "index.html"
            media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            cache = "no-cache" if candidate.name == "index.html" else "public, max-age=31536000"
            return Response(
                content=candidate.read_bytes(),
                media_type=media_type,
                headers={"Cache-Control": cache},
            )

    return app


app = create_app()
