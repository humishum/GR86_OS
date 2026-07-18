from __future__ import annotations

import math

import numpy as np
import pandas as pd

from race_review.analysis import (
    apply_corner_edits,
    assign_lap_distance,
    build_laps,
    build_reference_centerline,
    derive_kinematics,
    filter_gps,
    line_crossings,
    project_laps_to_centerline,
    project_wgs84_to_enu,
)
from race_review.models import CornerSummary, LinePoint, TrackConfig


def circular_session(laps: float = 3.1, samples: int = 2_000) -> pd.DataFrame:
    theta = np.linspace(-0.25, 2 * math.pi * laps, samples)
    radius = 50.0
    time = np.linspace(0, 150, samples)
    return pd.DataFrame(
        {
            "timestamp": time,
            "latitude": 34.0 + (radius * np.sin(theta)) / 111_320,
            "longitude": -118.0 + (radius * np.cos(theta)) / (111_320 * math.cos(math.radians(34))),
            "altitude_m": 100.0,
            "speed_2d_mps": 20.0,
            "gps_fix": 3,
            "gps_error_m": 1.2,
            "segment_id": 0,
        }
    )


def prepared_session() -> pd.DataFrame:
    frame = filter_gps(circular_session())
    frame, _ = project_wgs84_to_enu(frame)
    return derive_kinematics(frame)


def test_gps_quality_keeps_rejected_samples_and_reason() -> None:
    frame = circular_session(samples=8)
    frame.loc[1, "gps_fix"] = 1
    frame.loc[2, "gps_error_m"] = 20
    frame.loc[3, "latitude"] = 100
    filtered = filter_gps(frame)
    assert len(filtered) == 8
    assert filtered["valid"].sum() == 5
    assert filtered.loc[1, "rejection_reason"] == "gps_fix_below_2d"
    assert filtered.loc[2, "rejection_reason"] == "horizontal_error_limit"
    assert filtered.loc[3, "rejection_reason"] == "coordinate_out_of_range"


def test_kinematics_do_not_bridge_segment_gap() -> None:
    frame = filter_gps(circular_session(samples=30))
    frame.loc[15:, "segment_id"] = 1
    projected, _ = project_wgs84_to_enu(frame)
    result = derive_kinematics(projected)
    assert result.loc[15, "distance_m"] == result.loc[14, "distance_m"]
    assert math.isnan(result.loc[15, "longitudinal_accel_mps2"])


def test_directional_laps_and_incomplete_boundaries() -> None:
    frame = prepared_session()
    theta0 = -0.25
    center_east = -50 * math.cos(theta0)
    center_north = -50 * math.sin(theta0)
    config = TrackConfig(
        start_finish_a=LinePoint(east_m=center_east, north_m=center_north),
        start_finish_b=LinePoint(east_m=center_east + 70, north_m=center_north),
        crossing_direction=1,
        minimum_lap_seconds=20,
    )
    crossings = line_crossings(frame, config)
    assert len(crossings) >= 3
    laps = build_laps(frame, config)
    assert any(lap.complete for lap in laps)
    assert laps[0].complete is False
    assert laps[0].excluded is True
    with_distance = assign_lap_distance(frame, laps)
    assert with_distance["lap_number"].max() >= 1
    centerline = build_reference_centerline(frame, laps, points=100)
    projected = project_laps_to_centerline(frame, laps, centerline)
    assert len(centerline) == 100
    complete_number = next(lap.lap_number for lap in laps if lap.complete)
    lap_distance = projected.loc[
        projected["lap_number"] == complete_number, "lap_distance_m"
    ].dropna()
    assert (lap_distance.diff().dropna() >= 0).all()
    assert lap_distance.max() > 250

    reverse = config.model_copy(update={"crossing_direction": -1})
    assert line_crossings(frame, reverse) == []


def test_corner_edit_rename_split_and_merge() -> None:
    corner = CornerSummary(
        corner_id="corner-1",
        name="Turn 1",
        start_distance_m=100,
        apex_distance_m=140,
        end_distance_m=180,
        peak_lateral_g=1.1,
    )
    renamed = apply_corner_edits(
        [corner], [{"action": "update", "corner_id": "corner-1", "name": "Esses"}]
    )
    assert renamed[0].name == "Esses"
    split = apply_corner_edits(
        [corner], [{"action": "split", "corner_id": "corner-1", "boundary_distance_m": 145}]
    )
    assert [item.corner_id for item in split] == ["corner-1-a", "corner-1-b"]
    merged = apply_corner_edits(
        split,
        [{"action": "merge", "corner_ids": ["corner-1-a", "corner-1-b"], "merged_id": "esses"}],
    )
    assert len(merged) == 1
    assert merged[0].start_distance_m == 100
    assert merged[0].end_distance_m == 180
