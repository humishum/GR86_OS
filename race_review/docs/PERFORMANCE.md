# Race Review Performance Budgets

These budgets are the regression ceiling, not a tuning target. Machine-readable copies
live in [`performance_budgets.json`](../performance_budgets.json) and are asserted in
pytest and Playwright.

## CI-enforced budgets

| Operation | Budget | Measurement |
| --- | --- | --- |
| Import media stages for the 2 s portable H.264 fixture (CPU proxy + thumbnail) | 30 s | `tests/test_performance.py` |
| Telemetry window request (50,000 rows downsampled to 8,000 points) | 500 ms | `tests/test_performance.py` |
| Map position source update after a paused seek | 500 ms | `frontend/e2e/media-sync.spec.ts` |
| Paused seek until map and speed gauge both change | 750 ms | `frontend/e2e/media-sync.spec.ts` |

The portable fixture is 320×180 libx264/AAC generated with FFmpeg on Linux and macOS.
It is not a substitute for the 4K GoPro chapter. It is the path that must stay fast on
CPU-only CI runners. Seek and map Playwright budgets are asserted on the desktop
project; mobile emulation is not a performance target.

## Host reference (not CI)

Recorded on the GTX 1070 host in [the 2026-07-18 proxy benchmark](benchmarks/proxy-2026-07-18.md)
for a 30-second window of `GX020115.MP4`:

| Operation | Observed | Release expectation |
| --- | --- | --- |
| CPU proxy of a 30 s 4K60 window | 30.42 s wall, 0.99× | Finish near 1× realtime at CRF 21 veryfast |
| CUDA proxy of the same window | 10.69 s wall, 2.89× | Remain clearly faster than CPU |
| Seek into the 1080p60 proxy | 0.17–0.24 s | Stay under 250 ms at representative points |

A full-chapter proxy encode is intentionally not a CI budget. Re-record it only when
changing `PROXY_PROFILE`.

## How to change a budget

1. Measure on Linux and macOS CPU fixtures, and on the NVIDIA host if the change
   touches media.
2. Update `performance_budgets.json` and this table together.
3. Explain the why in `CHANGELOG.md`. Do not raise a budget to hide a regression
   without a recorded cause.
