from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .models import (
    AxisTransform,
    Calibration,
    CoordinateOrigin,
    CornerSummary,
    LapSummary,
    LinePoint,
    TrackConfig,
)

G = 9.80665


def _first_present(frame: pd.DataFrame, names: Iterable[str]) -> str | None:
    return next((name for name in names if name in frame.columns), None)


def normalize_gps_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize GPS5/GPS9 exports while retaining every original sample."""
    result = frame.copy()
    aliases = {
        "latitude": ("latitude", "lat", "GPS5_lat", "GPS9_lat"),
        "longitude": ("longitude", "lon", "GPS5_lon", "GPS9_lon"),
        "altitude_m": ("altitude_m", "alt", "GPS5_alt", "GPS9_alt"),
        "speed_2d_mps": ("speed_2d_mps", "speed_2d", "GPS5_speed_2d", "GPS9_speed_2d"),
        "speed_3d_mps": ("speed_3d_mps", "speed_3d", "GPS5_speed_3d", "GPS9_speed_3d"),
        "gps_fix": ("gps_fix", "fix", "GPSF", "GPS9_fix"),
        # gopropy 0.1.1 corrected GPSP: this value is dimensionless dilution
        # of precision, never a positional error measured in metres.
        "gps_dop": ("gps_dop", "dop", "GPSP", "GPS9_dop", "gps_precision"),
        "gps_utc": ("gps_utc", "utc", "GPSU"),
    }
    for target, candidates in aliases.items():
        source = _first_present(result, candidates)
        if source is not None and target not in result:
            result[target] = result[source]
    if "altitude_m" not in result:
        result["altitude_m"] = 0.0
    return result


def filter_gps(frame: pd.DataFrame, gps_dop_limit: float = 5.0) -> pd.DataFrame:
    result = normalize_gps_columns(frame)
    required = ("timestamp", "latitude", "longitude")
    missing = [name for name in required if name not in result]
    if missing:
        raise ValueError(f"GPS telemetry is missing required columns: {', '.join(missing)}")

    latitude = pd.to_numeric(result["latitude"], errors="coerce").to_numpy(float)
    longitude = pd.to_numeric(result["longitude"], errors="coerce").to_numpy(float)
    timestamp = pd.to_numeric(result["timestamp"], errors="coerce").to_numpy(float)
    valid = np.isfinite(timestamp) & np.isfinite(latitude) & np.isfinite(longitude)
    reasons = np.full(len(result), "", dtype=object)
    reasons[~valid] = "non_finite"

    in_range = (np.abs(latitude) <= 90) & (np.abs(longitude) <= 180)
    reasons[valid & ~in_range] = "coordinate_out_of_range"
    valid &= in_range

    if "gps_fix" in result:
        fix = pd.to_numeric(result["gps_fix"], errors="coerce").to_numpy(float)
        bad_fix = ~np.isfinite(fix) | (fix < 2)
        reasons[valid & bad_fix] = "gps_fix_below_2d"
        valid &= ~bad_fix

    if "gps_dop" in result:
        dop = pd.to_numeric(result["gps_dop"], errors="coerce").to_numpy(float)
        bad_dop = ~np.isfinite(dop) | (dop > gps_dop_limit)
        reasons[valid & bad_dop] = "gps_dop_limit"
        valid &= ~bad_dop

    if "valid" in result:
        source_valid = result["valid"].fillna(False).to_numpy(bool)
        reasons[valid & ~source_valid] = "source_marked_invalid"
        valid &= source_valid

    result["valid"] = valid
    result["rejection_reason"] = reasons
    return result


def project_wgs84_to_enu(frame: pd.DataFrame) -> tuple[pd.DataFrame, CoordinateOrigin | None]:
    result = frame.copy()
    valid = result.get("valid", pd.Series(True, index=result.index)).to_numpy(bool)
    if not valid.any():
        for name in ("east_m", "north_m", "up_m"):
            result[name] = np.nan
        return result, None

    lat = pd.to_numeric(result["latitude"], errors="coerce").to_numpy(float)
    lon = pd.to_numeric(result["longitude"], errors="coerce").to_numpy(float)
    alt = pd.to_numeric(result.get("altitude_m", 0.0), errors="coerce").to_numpy(float)
    origin_index = int(np.flatnonzero(valid)[0])
    lat0, lon0 = float(lat[origin_index]), float(lon[origin_index])
    alt0 = float(alt[origin_index]) if np.isfinite(alt[origin_index]) else 0.0

    try:
        from pyproj import CRS, Transformer

        local = CRS.from_proj4(
            f"+proj=aeqd +lat_0={lat0:.12f} +lon_0={lon0:.12f} +datum=WGS84 +units=m"
        )
        transformer = Transformer.from_crs("EPSG:4326", local, always_xy=True)
        east, north = transformer.transform(lon, lat)
        east = np.asarray(east, dtype=float)
        north = np.asarray(north, dtype=float)
    except (ImportError, RuntimeError):
        # Accurate to well below GPS noise over a normal race circuit.
        earth_radius_m = 6_378_137.0
        east = np.deg2rad(lon - lon0) * earth_radius_m * math.cos(math.radians(lat0))
        north = np.deg2rad(lat - lat0) * earth_radius_m

    result["east_m"] = np.where(valid, east, np.nan)
    result["north_m"] = np.where(valid, north, np.nan)
    result["up_m"] = np.where(valid, alt - alt0, np.nan)
    return result, CoordinateOrigin(latitude=lat0, longitude=lon0, altitude_m=alt0)


def _contiguous_runs(mask: np.ndarray, segment: np.ndarray) -> list[np.ndarray]:
    indices = np.flatnonzero(mask)
    if not len(indices):
        return []
    splits = (
        np.flatnonzero((np.diff(indices) != 1) | (segment[indices[1:]] != segment[indices[:-1]]))
        + 1
    )
    return [part for part in np.split(indices, splits) if len(part)]


def _smooth(
    values: np.ndarray, mask: np.ndarray, segment: np.ndarray, window: int = 11
) -> np.ndarray:
    output = np.full_like(values, np.nan, dtype=float)
    for indices in _contiguous_runs(mask & np.isfinite(values), segment):
        data = values[indices]
        if len(indices) < 5:
            output[indices] = data
            continue
        actual_window = min(window, len(indices) if len(indices) % 2 else len(indices) - 1)
        try:
            from scipy.signal import savgol_filter

            output[indices] = savgol_filter(
                data, actual_window, min(2, actual_window - 1), mode="interp"
            )
        except ImportError:
            output[indices] = (
                pd.Series(data).rolling(actual_window, center=True, min_periods=1).mean().to_numpy()
            )
    return output


def derive_kinematics(frame: pd.DataFrame) -> pd.DataFrame:
    """Smooth valid points per chapter/run and calculate SI kinematics."""
    result = frame.sort_values("timestamp", kind="stable").reset_index(drop=True).copy()
    valid = result["valid"].to_numpy(bool)
    segment = result.get("segment_id", pd.Series(0, index=result.index)).to_numpy()
    t = result["timestamp"].to_numpy(float)
    east = result["east_m"].to_numpy(float)
    north = result["north_m"].to_numpy(float)
    up = pd.to_numeric(
        result.get("up_m", pd.Series(np.nan, index=result.index)), errors="coerce"
    ).to_numpy(float)
    east_s = _smooth(east, valid, segment)
    north_s = _smooth(north, valid, segment)
    up_s = _smooth(up, valid, segment)
    result["east_smooth_m"] = east_s
    result["north_smooth_m"] = north_s
    result["up_smooth_m"] = up_s

    ds = np.full(len(result), np.nan)
    dt = np.full(len(result), np.nan)
    same_run = valid[1:] & valid[:-1] & (segment[1:] == segment[:-1])
    dt[1:] = np.where(same_run, np.diff(t), np.nan)
    ds[1:] = np.where(same_run, np.hypot(np.diff(east_s), np.diff(north_s)), np.nan)
    plausible = (dt > 0) & (dt < 5)
    ds[~plausible] = np.nan

    distance = np.zeros(len(result), dtype=float)
    distance[0] = 0.0
    for index in range(1, len(result)):
        distance[index] = distance[index - 1] + (ds[index] if np.isfinite(ds[index]) else 0.0)
    result["distance_m"] = distance

    source_speed_name = _first_present(result, ("speed_2d_mps", "speed_3d_mps"))
    calculated_speed = np.divide(ds, dt, out=np.full(len(result), np.nan), where=plausible)
    if source_speed_name:
        source_speed = pd.to_numeric(result[source_speed_name], errors="coerce").to_numpy(float)
        calculated_speed = np.where(np.isfinite(source_speed), source_speed, calculated_speed)
    speed = _smooth(calculated_speed, valid & plausible, segment, window=9)
    # Preserve a valid first point in each run by back-filling only within that run.
    speed = pd.Series(speed).groupby(segment).bfill(limit=1).to_numpy()
    result["speed_mps"] = speed

    dx = np.r_[np.nan, np.diff(east_s)]
    dy = np.r_[np.nan, np.diff(north_s)]
    raw_heading = np.arctan2(dy, dx)
    heading = np.full(len(result), np.nan)
    for indices in _contiguous_runs(valid & np.isfinite(raw_heading), segment):
        heading[indices] = np.unwrap(raw_heading[indices])
    result["heading_rad"] = heading
    dheading = np.r_[np.nan, np.diff(heading)]
    curvature = np.divide(dheading, ds, out=np.full(len(result), np.nan), where=ds > 0.2)
    curvature = _smooth(curvature, valid & np.isfinite(curvature), segment, window=9)
    result["curvature_1pm"] = curvature

    dv = np.r_[np.nan, np.diff(speed)]
    longitudinal = np.divide(dv, dt, out=np.full(len(result), np.nan), where=plausible)
    longitudinal = _smooth(longitudinal, valid & np.isfinite(longitudinal), segment, window=7)
    result["longitudinal_accel_mps2"] = longitudinal
    result["braking_mps2"] = np.maximum(-longitudinal, 0)
    result["lateral_accel_mps2"] = speed**2 * curvature
    result["longitudinal_g"] = longitudinal / G
    result["lateral_g"] = result["lateral_accel_mps2"] / G
    return result


def infer_start_finish(frame: pd.DataFrame, minimum_lap_seconds: float = 20.0) -> TrackConfig:
    """Infer a repeatable timing gate and refine it from every observed passage.

    A closed GPS trace cannot reveal which of its infinitely many cross-sections is
    the venue's official timing line.  This chooses the most repeatable forward
    loop closure, then uses the median position and circular-mean heading of all
    passages so one noisy GPS sample does not move or rotate the gate.
    """
    valid_frame = frame.loc[frame["valid"] & frame["heading_rad"].notna()].copy()
    if len(valid_frame) < 10:
        return TrackConfig(minimum_lap_seconds=minimum_lap_seconds)
    points = valid_frame[["east_smooth_m", "north_smooth_m"]].to_numpy(float)
    headings = valid_frame["heading_rad"].to_numpy(float)
    times = valid_frame["timestamp"].to_numpy(float)
    step = max(1, len(points) // 500)
    best: tuple[int, int, float] | None = None
    radius_m = 12.0
    for i in range(0, len(points), step):
        distance = np.hypot(points[:, 0] - points[i, 0], points[:, 1] - points[i, 1])
        heading_delta = np.abs(np.angle(np.exp(1j * (headings - headings[i]))))
        matches = np.flatnonzero(
            (distance < radius_m)
            & (heading_delta < math.radians(35))
            & (times - times[i] > minimum_lap_seconds)
        )
        if len(matches):
            candidate = (i, int(matches[0]), float(distance[matches[0]]))
            if best is None or candidate[2] < best[2]:
                best = candidate
    index = best[0] if best else len(points) // 2
    center = points[index]
    heading = headings[index]
    if best is not None:
        distance = np.hypot(points[:, 0] - center[0], points[:, 1] - center[1])
        heading_delta = np.abs(np.angle(np.exp(1j * (headings - heading))))
        nearby = np.flatnonzero((distance < radius_m) & (heading_delta < math.radians(35)))
        # Adjacent samples describe the same passage.  Keep its closest sample,
        # then aggregate passages robustly instead of trusting the seed lap.
        passage_indices = [
            int(group[np.argmin(distance[group])])
            for group in np.split(
                nearby,
                np.flatnonzero(
                    (np.diff(nearby) != 1) | (np.diff(times[nearby]) > 2.0)
                )
                + 1,
            )
            if len(group)
        ]
        if len(passage_indices) >= 2:
            center = np.median(points[passage_indices], axis=0)
            unit_headings = np.exp(1j * headings[passage_indices])
            heading = float(np.angle(np.mean(unit_headings)))
    normal = np.array([-math.sin(heading), math.cos(heading)])
    half_width_m = 18.0
    a = center - normal * half_width_m
    b = center + normal * half_width_m
    return TrackConfig(
        start_finish_a=LinePoint(east_m=float(a[0]), north_m=float(a[1])),
        start_finish_b=LinePoint(east_m=float(b[0]), north_m=float(b[1])),
        crossing_direction=-1,
        minimum_lap_seconds=minimum_lap_seconds,
    )


def line_crossings(frame: pd.DataFrame, config: TrackConfig) -> list[float]:
    if config.start_finish_a is None or config.start_finish_b is None:
        return []
    a = np.array([config.start_finish_a.east_m, config.start_finish_a.north_m])
    b = np.array([config.start_finish_b.east_m, config.start_finish_b.north_m])
    line = b - a
    length_squared = float(line @ line)
    if length_squared < 1e-6:
        return []
    points = frame[["east_smooth_m", "north_smooth_m"]].to_numpy(float)
    times = frame["timestamp"].to_numpy(float)
    valid = frame["valid"].to_numpy(bool)
    segment = frame.get("segment_id", pd.Series(0, index=frame.index)).to_numpy()
    signed = line[0] * (points[:, 1] - a[1]) - line[1] * (points[:, 0] - a[0])
    crossings: list[float] = []
    for index in range(1, len(points)):
        if not valid[index - 1] or not valid[index] or segment[index - 1] != segment[index]:
            continue
        s0, s1 = signed[index - 1], signed[index]
        direction = 1 if s1 > s0 else -1
        if direction != config.crossing_direction or not (s0 <= 0 < s1 or s1 <= 0 < s0):
            continue
        alpha = -s0 / (s1 - s0) if s1 != s0 else 0.0
        crossing_point = points[index - 1] + alpha * (points[index] - points[index - 1])
        projection = float((crossing_point - a) @ line / length_squared)
        if 0 <= projection <= 1:
            crossing_time = float(times[index - 1] + alpha * (times[index] - times[index - 1]))
            if not crossings or crossing_time - crossings[-1] >= config.minimum_lap_seconds:
                crossings.append(crossing_time)
    return crossings


def build_laps(frame: pd.DataFrame, config: TrackConfig) -> list[LapSummary]:
    crossing_times = line_crossings(frame, config)
    laps: list[LapSummary] = []

    def summarize(number: int, start: float, end: float, *, complete: bool, excluded: bool) -> None:
        window = frame[(frame["timestamp"] >= start) & (frame["timestamp"] <= end)]
        speed = window.get("speed_mps", pd.Series(dtype=float))
        long_g = window.get("longitudinal_g", pd.Series(dtype=float))
        lat_g = window.get("lateral_g", pd.Series(dtype=float))
        laps.append(
            LapSummary(
                lap_number=number,
                start_seconds=start,
                end_seconds=end,
                lap_time_seconds=end - start,
                complete=complete,
                excluded=excluded,
                minimum_speed_mps=_finite_stat(speed, np.nanmin),
                maximum_speed_mps=_finite_stat(speed, np.nanmax),
                peak_acceleration_mps2=_finite_stat(
                    window.get("longitudinal_accel_mps2", pd.Series(dtype=float)), np.nanmax
                ),
                peak_braking_mps2=_finite_stat(
                    window.get("braking_mps2", pd.Series(dtype=float)), np.nanmax
                ),
                peak_longitudinal_g=_finite_abs_peak(long_g),
                peak_lateral_g=_finite_abs_peak(lat_g),
            )
        )

    if not crossing_times:
        return []
    recording_start = float(frame["timestamp"].min())
    recording_end = float(frame["timestamp"].max())
    if crossing_times[0] - recording_start > 1:
        summarize(
            0, recording_start, crossing_times[0], complete=False, excluded=config.exclude_out_lap
        )
    for number, (start, end) in enumerate(zip(crossing_times, crossing_times[1:], strict=False), 1):
        summarize(number, start, end, complete=True, excluded=False)
    if recording_end - crossing_times[-1] > 1:
        summarize(
            len(crossing_times),
            crossing_times[-1],
            recording_end,
            complete=False,
            excluded=config.exclude_in_lap,
        )
    return laps


def _finite_stat(series: pd.Series, function: object) -> float | None:
    values = pd.to_numeric(series, errors="coerce").to_numpy(float)
    return None if not np.isfinite(values).any() else float(function(values))  # type: ignore[operator]


def _finite_abs_peak(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").to_numpy(float)
    return None if not np.isfinite(values).any() else float(np.nanmax(np.abs(values)))


def assign_lap_distance(frame: pd.DataFrame, laps: list[LapSummary]) -> pd.DataFrame:
    result = frame.copy()
    result["lap_number"] = 0
    result["lap_complete"] = False
    result["lap_excluded"] = False
    result["lap_distance_m"] = np.nan
    result["lap_progress"] = np.nan
    for lap in laps:
        mask = (result["timestamp"] >= lap.start_seconds) & (result["timestamp"] <= lap.end_seconds)
        indices = result.index[mask]
        if not len(indices):
            continue
        base = float(result.loc[indices[0], "distance_m"])
        distance = result.loc[indices, "distance_m"] - base
        total = float(distance.iloc[-1])
        result.loc[indices, "lap_number"] = lap.lap_number
        result.loc[indices, "lap_complete"] = lap.complete
        result.loc[indices, "lap_excluded"] = lap.excluded
        result.loc[indices, "lap_distance_m"] = distance
        if total > 0:
            result.loc[indices, "lap_progress"] = distance / total
    return result


def build_reference_centerline(
    frame: pd.DataFrame, laps: list[LapSummary], points: int = 500
) -> pd.DataFrame:
    """Resample the quickest complete lap into a stable ENU centerline."""
    complete = [lap for lap in laps if lap.complete and not lap.excluded]
    columns = ["normalized_distance", "distance_m", "east_m", "north_m"]
    if not complete:
        return pd.DataFrame(columns=columns)
    reference = min(complete, key=lambda lap: lap.lap_time_seconds)
    section = frame[
        (frame["timestamp"] >= reference.start_seconds)
        & (frame["timestamp"] <= reference.end_seconds)
        & frame["valid"]
    ].dropna(subset=["east_smooth_m", "north_smooth_m", "distance_m"])
    if len(section) < 2:
        return pd.DataFrame(columns=columns)
    along = section["distance_m"].to_numpy(float)
    along -= along[0]
    unique = np.r_[True, np.diff(along) > 0]
    along = along[unique]
    # A closed circuit's final point coincides with its first. Excluding the duplicate
    # endpoint prevents nearest-neighbor projection from assigning lap starts to 100%.
    target = np.linspace(0, along[-1], points, endpoint=False)
    return pd.DataFrame(
        {
            "normalized_distance": target / along[-1],
            "distance_m": target,
            "east_m": np.interp(target, along, section["east_smooth_m"].to_numpy(float)[unique]),
            "north_m": np.interp(target, along, section["north_smooth_m"].to_numpy(float)[unique]),
        }
    )


def project_laps_to_centerline(
    frame: pd.DataFrame, laps: list[LapSummary], centerline: pd.DataFrame
) -> pd.DataFrame:
    """Project every lap to monotonically increasing reference-track distance."""
    if centerline.empty:
        return assign_lap_distance(frame, laps)
    result = frame.copy()
    result["lap_number"] = 0
    result["lap_complete"] = False
    result["lap_excluded"] = False
    result["lap_distance_m"] = np.nan
    result["lap_progress"] = np.nan
    center_points = centerline[["east_m", "north_m"]].to_numpy(float)
    center_distance = centerline["distance_m"].to_numpy(float)
    try:
        from scipy.spatial import cKDTree

        tree = cKDTree(center_points)

        def nearest(points: np.ndarray) -> np.ndarray:
            return tree.query(points)[1]

    except ImportError:

        def nearest(points: np.ndarray) -> np.ndarray:
            squared = ((points[:, None, :] - center_points[None, :, :]) ** 2).sum(axis=2)
            return np.argmin(squared, axis=1)

    for lap in laps:
        mask = (
            (result["timestamp"] >= lap.start_seconds)
            & (result["timestamp"] <= lap.end_seconds)
            & result["valid"]
        )
        indices = result.index[mask]
        if not len(indices):
            continue
        positions = result.loc[indices, ["east_smooth_m", "north_smooth_m"]].to_numpy(float)
        projected_indices = np.maximum.accumulate(nearest(positions))
        distance = center_distance[projected_indices]
        result.loc[indices, "lap_number"] = lap.lap_number
        result.loc[indices, "lap_complete"] = lap.complete
        result.loc[indices, "lap_excluded"] = lap.excluded
        result.loc[indices, "lap_distance_m"] = distance
        result.loc[indices, "lap_progress"] = distance / center_distance[-1]
    return result


def detect_corners(frame: pd.DataFrame) -> list[CornerSummary]:
    """Detect sustained, repeatable changes of heading along a lap.

    When at least two near-complete laps are available, curvature and lateral
    acceleration are interpolated onto a common distance grid and combined with
    a pointwise median.  This rejects lap-local GPS noise before segmentation.
    """
    if frame.empty or "curvature_1pm" not in frame:
        return []
    working = frame
    signal_distance: np.ndarray | None = None
    signal_curvature: np.ndarray | None = None
    signal_lateral: np.ndarray | None = None
    signal_support: np.ndarray | None = None
    if "lap_number" in frame and "lap_distance_m" in frame:
        lap_candidates = frame[
            (frame["lap_number"] > 0) & frame["lap_distance_m"].notna() & frame["valid"]
        ]
        candidates = lap_candidates
        if "lap_complete" in candidates:
            complete_mask = candidates["lap_complete"].fillna(False).astype(bool)
            if "lap_excluded" in candidates:
                complete_mask &= ~candidates["lap_excluded"].fillna(False).astype(bool)
            candidates = candidates[complete_mask]
        if not candidates.empty:
            lap_groups = candidates.groupby("lap_number", sort=True)
            by_length = lap_groups["lap_distance_m"].max()
            maximum_length = float(by_length.max())
            coverage_ratio = 0.98 if "lap_complete" in frame else 0.995
            complete_numbers = by_length[
                by_length >= coverage_ratio * maximum_length
            ].index.tolist()
            durations = lap_groups["timestamp"].agg(lambda values: values.max() - values.min())
            reference_number = min(complete_numbers, key=lambda number: durations.loc[number])
            working = candidates[candidates["lap_number"] == reference_number].copy()
            working["distance_m"] = working["lap_distance_m"]

            if len(complete_numbers) >= 2:
                grid_step_m = 6.0
                common_length = float(by_length.loc[complete_numbers].min())
                signal_distance = np.arange(0.0, common_length, grid_step_m)
                curvature_laps: list[np.ndarray] = []
                lateral_laps: list[np.ndarray] = []
                for number in complete_numbers:
                    lap = candidates[candidates["lap_number"] == number].sort_values(
                        "lap_distance_m", kind="stable"
                    )
                    distance = lap["lap_distance_m"].to_numpy(float)
                    lap_curvature = lap["curvature_1pm"].to_numpy(float)
                    lap_lateral = lap["lateral_accel_mps2"].to_numpy(float)
                    finite = (
                        np.isfinite(distance)
                        & np.isfinite(lap_curvature)
                        & np.isfinite(lap_lateral)
                    )
                    distance = distance[finite]
                    lap_curvature = lap_curvature[finite]
                    lap_lateral = lap_lateral[finite]
                    if len(distance) < 2:
                        continue
                    unique = np.r_[True, np.diff(distance) > 0]
                    distance = distance[unique]
                    if len(distance) < 2:
                        continue
                    curvature_laps.append(
                        np.interp(
                            signal_distance,
                            distance,
                            lap_curvature[unique],
                        )
                    )
                    lateral_laps.append(
                        np.interp(
                            signal_distance,
                            distance,
                            lap_lateral[unique],
                        )
                    )
                if len(curvature_laps) >= 2:
                    curvature_stack = np.vstack(curvature_laps)
                    lateral_stack = np.vstack(lateral_laps)
                    signal_curvature = np.nanmedian(curvature_stack, axis=0)
                    signal_lateral = np.nanmedian(lateral_stack, axis=0)
                    agrees = (
                        (np.abs(curvature_stack) >= 0.004)
                        & (np.abs(lateral_stack) >= 1.0)
                        & (curvature_stack * signal_curvature > 0)
                    )
                    # Strict majority means both laps must agree when only two
                    # are available, while one outlier cannot dominate 3+ laps.
                    signal_support = np.mean(agrees, axis=0) > 0.5
        elif not lap_candidates.empty:
            # No lap is marked complete (for example, a recording containing
            # only out/in laps). Never concatenate reset lap distances into one
            # artificial signal; degrade deliberately to the longest valid lap.
            fallback_number = (
                lap_candidates.groupby("lap_number")["lap_distance_m"].max().idxmax()
            )
            working = lap_candidates[
                lap_candidates["lap_number"] == fallback_number
            ].copy()
            working["distance_m"] = working["lap_distance_m"]

    consensus = signal_distance is not None and signal_curvature is not None
    if consensus:
        assert signal_distance is not None
        assert signal_curvature is not None
        assert signal_lateral is not None
        assert signal_support is not None
        distance = signal_distance
        curvature = signal_curvature
        lateral = signal_lateral
        # The consensus permits a lower curvature threshold than a noisy single
        # lap.  0.006 1/m is a 167 m radius; the acceleration guard rejects slow
        # paddock motion and GPS wandering.
        active = (
            (np.abs(curvature) >= 0.006)
            & (np.abs(lateral) >= 1.5)
            & signal_support
        )
        active_indices = np.flatnonzero(active)
        for left, right in zip(active_indices[:-1], active_indices[1:], strict=False):
            same_direction = np.sign(curvature[left]) == np.sign(curvature[right])
            if same_direction and distance[right] - distance[left] <= 32.0:
                active[left : right + 1] = True
        groups = _contiguous_runs(active, np.zeros(len(distance), dtype=int))
    else:
        distance = working["distance_m"].to_numpy(float)
        curvature = working["curvature_1pm"].to_numpy(float)
        lateral = working["lateral_accel_mps2"].to_numpy(float)
        active = (
            (np.abs(curvature) >= 0.008)
            & (np.abs(lateral) >= 1.5)
            & working["valid"].to_numpy(bool)
        )
        # Close a few samples of dropout when no multi-lap consensus is possible.
        active = pd.Series(active).rolling(5, center=True, min_periods=1).max().to_numpy(bool)
        groups = _contiguous_runs(active, np.zeros(len(working), dtype=int))

    corners: list[CornerSummary] = []
    for indices in groups:
        start_distance = float(distance[indices[0]])
        end_distance = float(distance[indices[-1]])
        minimum_length_m = 18.0 if consensus else 12.0
        corner_curvature = curvature[indices]
        corner_distance = distance[indices]
        heading_change = abs(
            float(
                np.sum(
                    (corner_curvature[1:] + corner_curvature[:-1])
                    * np.diff(corner_distance)
                    / 2
                )
            )
        )
        if (
            len(indices) < 4
            or end_distance - start_distance < minimum_length_m
            or (consensus and heading_change < math.radians(8.0))
        ):
            continue
        section = working[
            (working["distance_m"] >= start_distance)
            & (working["distance_m"] <= end_distance)
        ]
        if section.empty:
            continue
        consensus_apex_distance = float(
            distance[indices[int(np.nanargmax(np.abs(lateral[indices])))]]
        )
        apex_position = int(
            np.nanargmin(
                np.abs(section["distance_m"].to_numpy(float) - consensus_apex_distance)
            )
        )
        apex = section.iloc[apex_position]
        before = working[
            (working["distance_m"] >= start_distance - 120)
            & (working["distance_m"] <= start_distance)
        ]
        braking_candidates = before[before.get("braking_mps2", 0) > 1.0]
        braking_distance = (
            float(braking_candidates["distance_m"].iloc[0])
            if not braking_candidates.empty
            else None
        )
        exit_window = section.iloc[apex_position:]
        number = len(corners) + 1
        corners.append(
            CornerSummary(
                corner_id=f"corner-{number}",
                name=f"Turn {number}",
                start_distance_m=start_distance,
                apex_distance_m=float(apex["distance_m"]),
                end_distance_m=end_distance,
                entry_seconds=float(section["timestamp"].iloc[0]),
                apex_seconds=float(apex["timestamp"]),
                exit_seconds=float(section["timestamp"].iloc[-1]),
                entry_speed_mps=float(section["speed_mps"].iloc[0]),
                apex_speed_mps=float(apex["speed_mps"]),
                exit_speed_mps=float(section["speed_mps"].iloc[-1]),
                minimum_speed_mps=_finite_stat(section["speed_mps"], np.nanmin),
                braking_distance_m=braking_distance,
                peak_lateral_g=_finite_abs_peak(section["lateral_g"]),
                exit_acceleration_mps2=_finite_stat(
                    exit_window["longitudinal_accel_mps2"], np.nanmax
                ),
            )
        )
    return corners


def apply_corner_edits(
    detected: list[CornerSummary], edits: list[dict[str, object]]
) -> list[CornerSummary]:
    corners = {corner.corner_id: corner for corner in detected}
    for edit in edits:
        action = edit.get("action", "update")
        corner_id = str(edit.get("corner_id", ""))
        if action == "delete":
            corners.pop(corner_id, None)
        elif action == "update" and corner_id in corners:
            values = corners[corner_id].model_dump()
            values.update({key: value for key, value in edit.items() if key in values})
            corners[corner_id] = CornerSummary.model_validate(values)
        elif action == "create":
            values = {key: value for key, value in edit.items() if key != "action"}
            corner = CornerSummary.model_validate(values)
            corners[corner.corner_id] = corner
        elif action == "split" and corner_id in corners:
            original = corners.pop(corner_id)
            boundary = float(edit.get("boundary_distance_m", original.apex_distance_m))
            boundary = float(np.clip(boundary, original.start_distance_m, original.end_distance_m))
            first = original.model_copy(
                update={
                    "corner_id": f"{corner_id}-a",
                    "name": str(edit.get("first_name", f"{original.name} A")),
                    "end_distance_m": boundary,
                    "apex_distance_m": min(original.apex_distance_m, boundary),
                }
            )
            second = original.model_copy(
                update={
                    "corner_id": f"{corner_id}-b",
                    "name": str(edit.get("second_name", f"{original.name} B")),
                    "start_distance_m": boundary,
                    "apex_distance_m": max(original.apex_distance_m, boundary),
                }
            )
            corners[first.corner_id], corners[second.corner_id] = first, second
        elif action == "merge":
            ids = [str(value) for value in edit.get("corner_ids", [])]  # type: ignore[union-attr]
            selected = [corners[value] for value in ids if value in corners]
            if len(selected) >= 2:
                selected.sort(key=lambda corner: corner.start_distance_m)
                for value in ids:
                    corners.pop(value, None)
                apex_source = max(selected, key=lambda corner: abs(corner.peak_lateral_g or 0))
                merged_id = str(edit.get("merged_id", "+".join(ids)))
                corners[merged_id] = apex_source.model_copy(
                    update={
                        "corner_id": merged_id,
                        "name": str(
                            edit.get("name", " / ".join(corner.name for corner in selected))
                        ),
                        "start_distance_m": selected[0].start_distance_m,
                        "end_distance_m": selected[-1].end_distance_m,
                    }
                )
    return sorted(corners.values(), key=lambda corner: corner.start_distance_m)


def estimate_calibration(
    gps: pd.DataFrame, imu: pd.DataFrame | None, gravity: pd.DataFrame | None = None
) -> Calibration:
    if imu is None or imu.empty or "longitudinal_accel_mps2" not in gps:
        return Calibration(diagnostics={"reason": "insufficient IMU/GPS overlap"})
    time_name = _first_present(imu, ("timestamp",))
    if time_name is None:
        return Calibration(diagnostics={"reason": "IMU has no timestamps"})
    axis_names = [name for name in ("x", "y", "z", "ACCL_x", "ACCL_y", "ACCL_z") if name in imu]
    if len(axis_names) < 2:
        return Calibration(diagnostics={"reason": "IMU has fewer than two axes"})
    suitable = gps[
        gps["valid"]
        & (gps["speed_mps"] > 8)
        & (gps["longitudinal_accel_mps2"].abs() > 0.5)
        & gps["longitudinal_accel_mps2"].notna()
    ]
    if len(suitable) < 20:
        return Calibration(diagnostics={"reason": "insufficient dynamic driving samples"})
    target_t = suitable["timestamp"].to_numpy(float)
    target_forward = suitable["longitudinal_accel_mps2"].to_numpy(float)
    target_lateral = suitable["lateral_accel_mps2"].to_numpy(float)
    source_t = imu[time_name].to_numpy(float)
    vertical_axis: str | None = None
    if gravity is not None and not gravity.empty:
        gravity_axes = [name for name in ("x", "y", "z") if name in gravity]
        if gravity_axes:
            magnitudes = {
                name: abs(float(pd.to_numeric(gravity[name], errors="coerce").median()))
                for name in gravity_axes
            }
            vertical_axis = max(magnitudes, key=magnitudes.get)  # type: ignore[arg-type]
    scores: dict[tuple[str, str], tuple[float, int]] = {}
    for name in axis_names:
        values = pd.to_numeric(imu[name], errors="coerce").to_numpy(float)
        interpolated = np.interp(target_t, source_t, values)
        for target_name, target in (
            ("forward", target_forward),
            ("lateral", target_lateral),
        ):
            correlation = np.corrcoef(target, interpolated)[0, 1]
            if np.isfinite(correlation):
                scores[(name[-1], target_name)] = (
                    abs(float(correlation)),
                    1 if correlation >= 0 else -1,
                )
    if not scores:
        return Calibration(diagnostics={"reason": "calibration correlation failed"})
    candidates: list[tuple[float, str, str, int, int]] = []
    for forward_axis in ("x", "y", "z"):
        for lateral_axis in ("x", "y", "z"):
            if forward_axis == lateral_axis or vertical_axis in (forward_axis, lateral_axis):
                continue
            forward_score = scores.get((forward_axis, "forward"))
            lateral_score = scores.get((lateral_axis, "lateral"))
            if forward_score and lateral_score:
                candidates.append(
                    (
                        (forward_score[0] + lateral_score[0]) / 2,
                        forward_axis,
                        lateral_axis,
                        forward_score[1],
                        lateral_score[1],
                    )
                )
    if not candidates:
        return Calibration(diagnostics={"reason": "no non-vertical axis pair was available"})
    correlation, forward_axis, lateral_axis, forward_sign, lateral_sign = max(candidates)
    confidence = float(np.clip((correlation - 0.15) / 0.65, 0, 1))
    return Calibration(
        transform=AxisTransform(
            forward_axis=forward_axis,
            lateral_axis=lateral_axis,
            forward_sign=forward_sign,
            lateral_sign=lateral_sign,
        ),
        confidence=confidence,
        method="bounded gravity and GPS/IMU correlation",
        diagnostics={
            "correlation": correlation,
            "samples": len(target_t),
            "vertical_axis": vertical_axis,
            "heading_span_rad": float(np.ptp(np.unwrap(suitable["heading_rad"].to_numpy(float)))),
        },
    )


@dataclass(frozen=True, slots=True)
class LapComparison:
    distance_m: np.ndarray
    reference_time_s: np.ndarray
    comparison_time_s: np.ndarray
    delta_s: np.ndarray
    reference_speed_mps: np.ndarray
    comparison_speed_mps: np.ndarray


def compare_laps(
    frame: pd.DataFrame, reference_lap: int, comparison_lap: int, points: int = 500
) -> LapComparison:
    reference = frame[frame["lap_number"] == reference_lap].dropna(subset=["lap_distance_m"])
    comparison = frame[frame["lap_number"] == comparison_lap].dropna(subset=["lap_distance_m"])
    if len(reference) < 2 or len(comparison) < 2:
        raise ValueError("Both laps need at least two telemetry samples")
    maximum = min(
        float(reference["lap_distance_m"].max()), float(comparison["lap_distance_m"].max())
    )
    distance = np.linspace(0, maximum, points)

    def interpolate(section: pd.DataFrame, column: str) -> np.ndarray:
        x = section["lap_distance_m"].to_numpy(float)
        y = section[column].to_numpy(float)
        unique = np.r_[True, np.diff(x) > 0]
        return np.interp(distance, x[unique], y[unique])

    reference_time = interpolate(reference, "timestamp")
    comparison_time = interpolate(comparison, "timestamp")
    reference_time -= reference_time[0]
    comparison_time -= comparison_time[0]
    return LapComparison(
        distance_m=distance,
        reference_time_s=reference_time,
        comparison_time_s=comparison_time,
        delta_s=comparison_time - reference_time,
        reference_speed_mps=interpolate(reference, "speed_mps"),
        comparison_speed_mps=interpolate(comparison, "speed_mps"),
    )
