# Race Review Architecture

## Scope

Race Review is a local-first, single-user application for reviewing ordered GoPro
race footage and its GPMF telemetry. It owns the `race_review/` directory only. The
ESP32 firmware and the separate reconstruction project remain independent systems.

The application currently provides:

- constrained local MP4 discovery and ordered session import;
- source fingerprinting without modifying or copying source recordings;
- native GPMF extraction through the pinned sibling `gopro-py` repository;
- GPS filtering, local projection, kinematics, laps, corners, and calibration estimates;
- a cached browser-compatible video proxy;
- synchronized video, telemetry, route position, gauges, lap summaries, and comparison;
- persisted edits and portable analysis-bundle export.

Authentication, remote multi-user deployment, coaching models, and a 3D artifact
contract are outside the current boundary.

## System context

```text
GoPro MP4 chapters (read-only)
        │
        ├── ffprobe ─────────────── media identity and stream validation
        ├── pinned gopro-py ─────── native telemetry plus timing quality
        └── FFmpeg ──────────────── thumbnail and H.264/AAC proxy
                                      │
                                      ▼
FastAPI / ImportService ─────── SQLite catalog + session manifest
        │                       Parquet telemetry + JSON analysis
        │
        ├── typed JSON APIs
        ├── byte-range media APIs
        └── built React application
                    │
                    ▼
        video clock → interpolation → gauges / map / chart / laps
```

## Runtime components

| Component | Responsibility |
| --- | --- |
| `config.py` | Trusted media roots, artifact root, FFmpeg tools, GPS threshold, and proxy acceleration policy. |
| `media.py` | MP4 discovery, ffprobe validation, recording/chapter identity, packet counts, and SHA-256 fingerprints. |
| `telemetry.py` | Quality-aware native stream extraction and one Parquet artifact per stream. |
| `analysis.py` | GPS validation, ENU projection, smoothing, kinematics, lap/corner analysis, calibration, and comparisons. |
| `proxy.py` | Proxy signature/cache, CUDA capability probe, FFmpeg command construction, progress parsing, fallback, and thumbnails. |
| `ingest.py` | Single-worker import orchestration, progress persistence, checkpoints, and deterministic artifact production. |
| `catalog.py` | SQLite sessions, chapter identities, jobs, and edits. |
| `storage.py` | Atomic JSON and Parquet writes. |
| `export.py` | CSV/JSON analysis-bundle assembly. |
| `api.py` | FastAPI routes, time-windowed telemetry, edits, range responses, export, and frontend serving. |
| React frontend | Session import/library, video-led review, maps, charts, controls, and editing surfaces. |

The Python API and built frontend run in one process for the production-style local
workflow. During frontend development, Vite runs separately and proxies `/api` to
FastAPI.

## Import lifecycle

1. Resolve every requested chapter against configured media roots.
2. Probe streams, duration, creation time, GoPro filename identity, codec, and GPMF.
3. Validate explicit chapter order; record missing chapters and source-time gaps as
   warnings instead of silently treating them as continuous recordings.
4. Compute path/size/mtime/SHA-256 source identities and create the versioned manifest.
5. Extract native `GPS5`/`GPS9`, `ACCL`, `GYRO`, `GRAV`, `CORI`, and `IORI` streams.
6. Persist each native stream with timing method, rate, confidence, validity, and
   available GPS quality fields.
7. Filter and project GPS, derive kinematics, infer the start/finish line, build laps
   and a centerline, detect corners, and estimate camera-axis calibration.
8. Persist analysis and a thumbnail, then checkpoint the manifest before the long
   proxy stage.
9. Reuse a matching proxy or transcode it while reporting percentage, speed, and ETA.
10. Atomically finalize the manifest and mark the catalog job ready.

`ImportService` currently uses a process-local `ThreadPoolExecutor` with one worker.
On startup, queued or processing manifests are resubmitted. A resumed import currently
recomputes extraction and analysis before reusing or rebuilding the proxy; it is safe
but not yet stage-minimal.

## Canonical timing contract

All joins use floating-point video-relative seconds:

```text
session time = chapter timeline_start_seconds + native chapter sample time
```

Chapter timeline starts are composed from ordered media durations. A wall-clock gap is
stored in `gap_before_seconds` and marked as a discontinuity, but the playback timeline
is currently continuous because the proxy concatenates chapters without inserting
black/silent media for the gap.

The frontend treats the HTML video element as the clock authority:

- `requestVideoFrameCallback` supplies presented-frame media time when available;
- media events synchronize loading, paused seeking, and completed seeks;
- `requestAnimationFrame` is the fallback;
- telemetry samples are deterministically interpolated at the current video time;
- discrete fields such as lap number use the nearest side of the interpolation interval.

GPS-derived display telemetry is currently evaluated at the native GPS rate. Native
high-rate IMU streams are retained independently and are not yet resampled into the
main review trace.

## Telemetry and analysis

### Native streams

The pinned `gopro-py` revision is recorded in `pyproject.toml` and each manifest.
Quality-aware extraction retains timestamps, packet association, valid masks, timing
method/confidence/residual summaries, and GPS fix/error/UTC metadata where present.

### GPS validity

Samples are preserved even when rejected. Validation includes finite/range checks,
fix dimension of at least two, and a configurable default horizontal error limit of
5 meters. `rejection_reason` and aggregate diagnostics explain exclusions.

### Derived coordinates and motion

Valid WGS84 points are projected into a local azimuthal-equidistant coordinate frame
and exposed as right-handed ENU meters. Smoothing is isolated to contiguous valid runs
and never crosses chapter segments. Derived columns include distance, speed, heading,
curvature, braking, longitudinal acceleration, lateral acceleration, and g values.

The gauges currently display GPS-derived longitudinal/lateral g. Raw IMU streams and
the calibration estimate are preserved for future fused metrics.

### Laps and corners

The start/finish inference searches for repeated, same-direction route proximity and
creates a directed line. Crossings are interpolated and constrained by line extent,
direction, segment continuity, and minimum lap duration. First/last partial laps are
retained and can be excluded.

A reference centerline supports normalized lap-distance projection and two-lap delta
calculation. Sustained curvature/lateral-acceleration regions produce editable corner
summaries with entry, apex, exit, speeds, braking, lateral g, and exit acceleration.

## Persistence model

```text
var/
├── catalog.sqlite3
└── sessions/<session-id>/
    ├── manifest.json
    ├── telemetry/
    │   ├── gps5.parquet or gps9.parquet
    │   ├── accl.parquet / gyro.parquet / ...
    │   └── derived.parquet
    ├── analysis/
    │   ├── laps.json
    │   ├── corners.json
    │   ├── diagnostics.json
    │   └── centerline.parquet
    ├── media/
    │   ├── thumbnail.jpg
    │   ├── proxy.mp4
    │   └── proxy.json
    └── export/
        └── analysis_bundle.zip
```

SQLite is the runtime catalog and edit store. The same manifest is atomically written
to the session directory as a portable processing record/checkpoint. Large tabular
artifacts live in Parquet rather than SQLite. `var/` is gitignored.

Source recordings are referenced in place. A source identity combines resolved path,
size, modification time, and SHA-256. Routine stale checks use size and modification
time; the captured SHA-256 provides provenance and proxy-cache identity.

## Proxy architecture

The compatibility proxy is H.264 High Profile/AAC in MP4 at 1080p59.94, with two-second
GOPs and fast-start metadata. Only video and optional audio are mapped; GoPro data
streams are not copied into the proxy.

The default acceleration policy is `auto`:

1. Exercise `h264_nvenc` with a tiny encode to verify runtime driver access.
2. If available, decode HEVC into CUDA frames, resize with `scale_cuda`, and encode with
   NVENC.
3. If the real CUDA pipeline fails in automatic mode, retry from the beginning with
   `libx264`.
4. Record the selected backend in `proxy.json`.

`RACE_REVIEW_PROXY_ACCELERATION=cuda` requires NVIDIA acceleration and fails clearly if
it cannot initialize. `cpu` forces the portable path. Completed proxies are reused only
when their source SHA-256 list and versioned proxy profile match.

## HTTP API

| Method and path | Purpose |
| --- | --- |
| `GET /api/health` | Process health. |
| `GET /api/media` | List MP4 files inside trusted roots. |
| `GET /api/sessions` | List manifests. |
| `POST /api/sessions/import` | Validate, create, and enqueue a session. |
| `GET /api/sessions/{id}` | Manifest and stale-source warnings. |
| `GET /api/sessions/{id}/status` | Import stage, progress, speed/ETA message, and error. |
| `GET /api/sessions/{id}/telemetry` | Field-selectable, bounded, downsampled telemetry window. |
| `GET /api/sessions/{id}/laps` | Lap summaries. |
| `GET /api/sessions/{id}/corners` | Corner summaries. |
| `GET /api/sessions/{id}/comparison` | Distance-aligned two-lap traces and delta. |
| `GET /api/sessions/{id}/track-geometry` | WGS84 plus right-handed ENU handoff boundary. |
| `PUT /api/sessions/{id}/track` | Persist track configuration and reanalyze. |
| `PUT /api/sessions/{id}/calibration` | Persist manual axis calibration. |
| `PUT /api/sessions/{id}/corners` | Persist corner edits and reanalyze. |
| `POST /api/sessions/{id}/reanalyze` | Rebuild editable analysis artifacts. |
| `GET /api/sessions/{id}/media/proxy` | Byte-range proxy media. |
| `GET /api/sessions/{id}/thumbnail` | Session thumbnail. |
| `POST /api/sessions/{id}/export` | Build and stream an analysis ZIP. |

Pydantic response models feed the OpenAPI schema; frontend API types are generated from
that schema. Artifact and media responses validate resolved paths and implement explicit
single-range HTTP responses for deterministic browser seeking.

## Frontend architecture

`App.tsx` owns the active session and loads manifest, telemetry, laps, and corners.
Feature components receive data and callbacks rather than accessing global stores:

- `useVideoClock` owns canonical presented media time;
- `telemetry.ts` unpacks columnar API rows and interpolates samples;
- `Gauges` renders the current interpolated values;
- `TrackMap` initializes route/corner/start layers and updates only the position source;
- `TelemetryChart` owns uPlot lifecycle, resizing, cursor position, and visible readout;
- `Scrubber` maps canonical time to controls and event markers;
- `LapPanel` requests distance-aligned comparisons;
- `EditPanel` persists track, corner, and calibration overrides.

MapLibre runs with a route-only local style by default. An optional raster tile URL can
be stored locally, but tiles are never required for route review.

## Operational and security boundaries

- The process assumes one trusted local user and trusted configured media roots.
- There is no authentication, authorization, CSRF policy, remote tenancy, or TLS setup.
- Source paths can be disclosed through local manifests and exports.
- API artifact paths and media browsing are constrained to configured/session roots.
- Source MP4s are never modified by the application.
- SQLite writes are serialized in-process; multi-process writers are not a supported
  deployment mode.

## Verification layers

- Unit and synthetic analysis tests cover timing, gaps, GPS filtering, crossings,
  edits, calibration, comparisons, storage, proxy commands, cache identity, and ranges.
- API contract tests exercise typed endpoints and edit persistence.
- Playwright covers desktop/mobile review rendering and video-clock-driven state.
- The 4 GB GoPro integration test is opt-in through `RACE_REVIEW_GOPRO_SAMPLE`.
- Frontend production builds enforce TypeScript correctness.

Known gaps and planned work are tracked in [TODO.md](../TODO.md) and
[ROADMAP.md](ROADMAP.md).
