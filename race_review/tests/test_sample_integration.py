from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest


@pytest.mark.skipif(
    not os.getenv("RACE_REVIEW_GOPRO_SAMPLE"), reason="large GoPro sample is opt-in"
)
def test_hero10_sample_has_full_quality_timing() -> None:
    import gopropy

    path = Path(os.environ["RACE_REVIEW_GOPRO_SAMPLE"])
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
    assert np.allclose(
        gps_frame["gps_dop"].to_numpy() * 100,
        gps_frame["gps_dop_raw"].to_numpy(),
        equal_nan=True,
    )
