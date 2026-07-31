from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceFingerprint(BaseModel):
    path: str
    size_bytes: int
    modified_ns: int
    sha256: str


class MediaStream(BaseModel):
    index: int
    codec_type: str
    codec_name: str | None = None
    codec_tag: str | None = None
    duration_seconds: float | None = None
    frame_rate: float | None = None
    width: int | None = None
    height: int | None = None


class ChapterManifest(BaseModel):
    index: int
    filename: str
    fingerprint: SourceFingerprint
    creation_time: datetime | None = None
    duration_seconds: float
    timeline_start_seconds: float
    timeline_end_seconds: float
    gap_before_seconds: float = 0.0
    discontinuity: bool = False
    recording_id: str | None = None
    streams: list[MediaStream] = Field(default_factory=list)
    telemetry_packets: int | None = None


class StreamQualitySummary(BaseModel):
    name: str
    samples: int
    timing_method: str
    estimated_rate_hz: float | None = None
    confidence: float = 0.0
    residual_rms_seconds: float | None = None
    discontinuities: int = 0
    valid_samples: int = 0
    artifact: str


class CoordinateOrigin(BaseModel):
    latitude: float
    longitude: float
    altitude_m: float
    convention: Literal["WGS84 + right-handed ENU meters"] = "WGS84 + right-handed ENU meters"


class LinePoint(BaseModel):
    east_m: float
    north_m: float


class TrackConfig(BaseModel):
    start_finish_a: LinePoint | None = None
    start_finish_b: LinePoint | None = None
    crossing_direction: Literal[-1, 1] = 1
    minimum_lap_seconds: float = 20.0
    exclude_out_lap: bool = True
    exclude_in_lap: bool = True


class AxisTransform(BaseModel):
    forward_axis: Literal["x", "y", "z"] = "x"
    lateral_axis: Literal["x", "y", "z"] = "y"
    forward_sign: Literal[-1, 1] = 1
    lateral_sign: Literal[-1, 1] = 1

    @field_validator("lateral_axis")
    @classmethod
    def axes_are_distinct(cls, value: str, info: Any) -> str:
        if info.data.get("forward_axis") == value:
            raise ValueError("forward and lateral axes must be distinct")
        return value


class Calibration(BaseModel):
    transform: AxisTransform = Field(default_factory=AxisTransform)
    confidence: float = 0.0
    method: str = "unavailable"
    overridden: bool = False
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class DisplayUnits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speed: Literal["mph", "km/h"] = "mph"
    acceleration: Literal["g", "m/s²"] = "g"
    distance: Literal["ft", "m"] = "ft"
    time: Literal["s"] = "s"


class UserEdits(BaseModel):
    track: TrackConfig = Field(default_factory=TrackConfig)
    calibration: Calibration = Field(default_factory=Calibration)
    corner_edits: list[dict[str, Any]] = Field(default_factory=list)
    display_units: DisplayUnits = Field(default_factory=DisplayUnits)


class ProcessingStage(BaseModel):
    attempt: int
    status: Literal["running", "completed", "failed", "cancelled"]
    started_at: datetime
    ended_at: datetime | None = None
    backend: str | None = None
    command_profile: str
    failure_diagnostics: dict[str, Any] = Field(default_factory=dict)


class SessionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    session_id: str
    name: str
    created_at: datetime
    updated_at: datetime
    status: str
    duration_seconds: float
    chapters: list[ChapterManifest]
    streams: list[StreamQualitySummary] = Field(default_factory=list)
    coordinate_origin: CoordinateOrigin | None = None
    processing_versions: dict[str, str]
    processing_options: dict[str, bool] = Field(default_factory=lambda: {"generate_proxy": True})
    processing_stages: dict[str, list[ProcessingStage]] = Field(default_factory=dict)
    edits: UserEdits = Field(default_factory=UserEdits)
    artifacts: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ImportRequest(BaseModel):
    chapters: list[str] = Field(min_length=1)
    name: str | None = None
    generate_proxy: bool = True


class ImportResponse(BaseModel):
    session_id: str
    status: str


class SourceRelocationRequest(BaseModel):
    chapter_index: int = Field(ge=0)
    path: str


class JobStatus(BaseModel):
    session_id: str
    status: str
    stage: str
    progress: float = Field(ge=0, le=1)
    message: str = ""
    error: str | None = None
    updated_at: datetime


class MediaEntry(BaseModel):
    path: str
    name: str
    size_bytes: int
    modified_at: datetime


class LapSummary(BaseModel):
    lap_number: int
    start_seconds: float
    end_seconds: float
    lap_time_seconds: float
    complete: bool
    excluded: bool = False
    minimum_speed_mps: float | None = None
    maximum_speed_mps: float | None = None
    peak_acceleration_mps2: float | None = None
    peak_braking_mps2: float | None = None
    peak_longitudinal_g: float | None = None
    peak_lateral_g: float | None = None


class CornerSummary(BaseModel):
    corner_id: str
    name: str
    start_distance_m: float
    apex_distance_m: float
    end_distance_m: float
    entry_seconds: float | None = None
    apex_seconds: float | None = None
    exit_seconds: float | None = None
    entry_speed_mps: float | None = None
    apex_speed_mps: float | None = None
    exit_speed_mps: float | None = None
    minimum_speed_mps: float | None = None
    braking_distance_m: float | None = None
    peak_lateral_g: float | None = None
    exit_acceleration_mps2: float | None = None


class CornerEdit(BaseModel):
    action: Literal["update", "delete", "create", "split", "merge"] = "update"
    corner_id: str | None = None
    corner_ids: list[str] = Field(default_factory=list)
    merged_id: str | None = None
    name: str | None = None
    first_name: str | None = None
    second_name: str | None = None
    start_distance_m: float | None = None
    apex_distance_m: float | None = None
    end_distance_m: float | None = None
    boundary_distance_m: float | None = None


class TelemetryWindow(BaseModel):
    columns: list[str]
    rows: list[list[float | int | bool | None]]
    start_seconds: float
    end_seconds: float


class WGS84Point(BaseModel):
    latitude: float
    longitude: float
    altitude_m: float | None = None


class ENUPoint(BaseModel):
    east_m: float
    north_m: float
    up_m: float


class TrackGeometryAdapter(BaseModel):
    """Stable handoff boundary for future reconstruction geometry."""

    schema_version: Literal[1] = 1
    coordinate_system: Literal["WGS84 + right-handed ENU meters"] = (
        "WGS84 + right-handed ENU meters"
    )
    origin: CoordinateOrigin
    time_alignment_seconds: float | None = None
    route_wgs84: list[WGS84Point]
    route_enu_m: list[ENUPoint]
