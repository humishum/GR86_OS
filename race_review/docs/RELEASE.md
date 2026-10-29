# Race Review Release Notes and Checklist

This is the local release contract. CI covers Linux and macOS CPU fixtures. The full
GoPro chapter and NVIDIA paths stay opt-in on a machine that has the sample and GPU.

## Versioning

Bump the matching identifier whenever output semantics change, then add a
[changelog](../CHANGELOG.md) entry in the same pull request. Import resume and proxy
reuse treat a mismatch as stale and recompute.

| Identifier | Location | When to bump |
| --- | --- | --- |
| Application version | `pyproject.toml`, `src/race_review/__init__.py`, `frontend/package.json` | User-visible release. |
| Manifest `schema_version` | `migrations.CURRENT_SCHEMA_VERSION` and `SessionManifest.schema_version` | Stored manifest JSON shape changes. Register `migrate_vN_to_vN+1` before shipping version N+1. Additive v1 fields use `apply_v1_compat` instead of a bump. |
| Analysis version | `analysis.ANALYSIS_VERSION` | Derived telemetry, lap, corner, calibration, or resume-validity semantics change. |
| Proxy profile | `proxy.PROXY_PROFILE` | Encode settings change (resolution, GOP, encoder options). Existing proxies become invalid. |
| Proxy cache version | `proxy.PROXY_CACHE_VERSION` | Cache identity algorithm changes. |
| gopropy pin | `pyproject.toml` `[tool.race-review]`, `telemetry.GOPROPY_REVISION`, `telemetry.GOPROPY_VERSION`, `.github/workflows/race-review.yml` | Parser checkout or published version changes. |

Release notes in `CHANGELOG.md` must call out manifest, analysis, and proxy profile
changes in dedicated subsections so operators know which artifacts to rebuild.

## CI and CPU fixtures

GitHub Actions runs on Ubuntu and macOS:

- Ruff
- pytest, including generated Linux/macOS H.264 fixtures
- frontend unit tests
- TypeScript production build
- Playwright against the generated four-second H.264 fixture

NVIDIA CUDA/NVENC tests are skipped unless `RACE_REVIEW_NVIDIA=1`. The 4 GB GoPro
chapter is skipped unless `RACE_REVIEW_GOPRO_SAMPLE` points at the file.

## Local release checklist

Run from `race_review/` after `uv sync --extra dev` and `cd frontend && npm ci`.

1. `uv run ruff check src tests scripts`
2. `uv run pytest`
3. `cd frontend && npm test && npm run build && npm run test:e2e`
4. Confirm `performance_budgets.json` still matches [the recorded budgets](PERFORMANCE.md).
5. If this change touches analysis, manifests, or the proxy, update `CHANGELOG.md` and
   the version identifiers in the table above.
6. Full GoPro sample (requires `data/GX020115.MP4` or an equivalent HERO10 chapter):

```bash
RACE_REVIEW_GOPRO_SAMPLE=../data/GX020115.MP4 uv run pytest tests/test_sample_integration.py
```

7. NVIDIA validation (requires a working NVENC FFmpeg):

```bash
RACE_REVIEW_NVIDIA=1 uv run pytest -m nvidia
```

8. Optional host proxy benchmark for the real chapter, recorded under `docs/benchmarks/`.

## Full GoPro sample assertions

`tests/test_sample_integration.py` is the executable form of this list. A release that
changes parser or analysis behavior must keep these passing on `GX020115.MP4`.

Native GPMF:

- detected model is `HERO10` or `HERO10_BLACK`
- GPS sample count is 9,060 with strictly increasing timestamps ending at 534.534 s ± 0.2 s
- ACCL sample count is 107,890 with strictly increasing timestamps
- GPS valid mask is present
- `gps_dop` equals `gps_dop_raw / 100`

Sonoma analysis benchmark from [Track, lap, and corner analysis](TRACK_ANALYSIS.md):

- first valid WGS84 point is approximately 38.16535, -122.45973
- two complete laps of about 147.7 s and 148.7 s
- complete-lap distance is about 3.99 km
- twelve consensus corners at the documented start/end distances
