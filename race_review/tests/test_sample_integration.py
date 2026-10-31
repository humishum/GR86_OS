from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from race_review.analysis import (
    build_laps,
    build_reference_centerline,
    derive_kinematics,
    detect_corners,
    filter_gps,
    infer_start_finish,
    project_laps_to_centerline,
    project_wgs84_to_enu,
)

# Documented Sonoma Raceway benchmark from docs/TRACK_ANALYSIS.md.
SONOMA_START = (38.16535, -122.45973)
SONOMA_COMPLETE_LAP_TIMES_S = (147.7, 148.7)
SONOMA_LAP_DISTANCE_M = 3_990
SONOMA_CORNER_REGIONS_M = (
    (492, 582),
    (618, 756),
    (900, 978),
    (1008, 1062),
    (1188, 1284),
    (1362, 1500),
    (1656, 1920),
    (2352, 2508),
    (2748, 2808),
    (2862, 2928),
    (3354, 3444),
    (3762, 3876),
)

gopro_sample = pytest.mark.skipif(
    not os.getenv("RACE_REVIEW_GOPRO_SAMPLE"),
    reason="large GoPro sample is opt-in via RACE_REVIEW_GOPRO_SAMPLE",
)


def _sample_path() -> Path:
    return Path(os.environ["RACE_REVIEW_GOPRO_SAMPLE"])


@gopro_sample
@pytest.mark.gopro_sample
def test_hero10_sample_has_full_quality_timing() -> None:
    import gopropy

    path = _sample_path()
    telemetry = gopropy.load(str(path))
    assert telemetry.detected_model in {"HERO10", "HERO10_BLACK"}
    gps = next(telemetry.get_stream(name) for name in telemetry.list_streams() if "GPS" in name)
    acceleration = next(
        telemetry.get_stream(name)
        for name in telemetry.list_streams()
        if (telemetry.get_stream(name).metadata or {}).get("fourcc") == "ACCL" or "ACCL" in name
    )
    assert len(gps.timestamps) == 9_060
    assert len(acceleration.timestamps) == 107_890
    assert np.all(np.diff(gps.timestamps) > 0)
    assert np.all(np.diff(acceleration.timestamps) > 0)
    assert gps.timestamps[-1] == pytest.approx(534.534, abs=0.2)
    assert getattr(gps, "valid_mask", (gps.metadata or {}).get("valid_mask")) is not None
    gps_frame = gps.to_dataframe(
        model_config=getattr(gps, "model_config", None), include_quality=True
    )
    assert {"gps_dop", "gps_dop_raw"}.issubset(gps_frame.columns)
    dop = pd.to_numeric(gps_frame["gps_dop"], errors="coerce").to_numpy(float)
    dop_raw = pd.to_numeric(gps_frame["gps_dop_raw"], errors="coerce").to_numpy(float)
    assert np.allclose(dop * 100, dop_raw, equal_nan=True)


@gopro_sample
@pytest.mark.gopro_sample
def test_hero10_sample_matches_sonoma_analysis_benchmark() -> None:
    import gopropy

    telemetry = gopropy.load(str(_sample_path()))
    gps_stream = next(
        telemetry.get_stream(name) for name in telemetry.list_streams() if "GPS" in name
    )
    gps = gps_stream.to_dataframe(
        model_config=getattr(gps_stream, "model_config", None), include_quality=True
    ).copy()
    gps["timestamp"] = np.asarray(gps_stream.timestamps, dtype=float)
    gps["chapter_index"] = 0
    gps["segment_id"] = 0
    gps["valid"] = np.asarray(
        getattr(gps_stream, "valid_mask", gps.get("valid", np.ones(len(gps), dtype=bool))),
        dtype=bool,
    )
    gps = filter_gps(gps)
    gps, origin = project_wgs84_to_enu(gps)
    gps = derive_kinematics(gps)
    assert origin is not None
    assert origin.latitude == pytest.approx(SONOMA_START[0], abs=0.01)
    assert origin.longitude == pytest.approx(SONOMA_START[1], abs=0.01)

    config = infer_start_finish(gps)
    laps = build_laps(gps, config)
    complete = [lap for lap in laps if lap.complete and not lap.excluded]
    assert len(complete) == 2
    times = sorted(lap.lap_time_seconds for lap in complete)
    assert times[0] == pytest.approx(SONOMA_COMPLETE_LAP_TIMES_S[0], abs=2.5)
    assert times[1] == pytest.approx(SONOMA_COMPLETE_LAP_TIMES_S[1], abs=2.5)

    centerline = build_reference_centerline(gps, laps)
    gps = project_laps_to_centerline(gps, laps, centerline)
    distances = [
        float(gps.loc[gps["lap_number"] == lap.lap_number, "lap_distance_m"].max())
        for lap in complete
    ]
    assert distances[0] == pytest.approx(SONOMA_LAP_DISTANCE_M, abs=80)
    assert distances[1] == pytest.approx(SONOMA_LAP_DISTANCE_M, abs=80)

    corners = detect_corners(gps)
    assert len(corners) == len(SONOMA_CORNER_REGIONS_M)
    for corner, (start, end) in zip(corners, SONOMA_CORNER_REGIONS_M, strict=True):
        assert corner.start_distance_m == pytest.approx(start, abs=30)
        assert corner.end_distance_m == pytest.approx(end, abs=30)
