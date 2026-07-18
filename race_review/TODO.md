# Race Review TODO

This is the active engineering checklist. Keep tasks small enough to complete or produce
a reviewable artifact in one focused session. Move larger outcome changes into the
[roadmap](docs/ROADMAP.md).

## Start tomorrow

- [x] Run `nvidia-smi` and the forced CUDA proxy path on the host.
- [ ] Benchmark `GX020115.MP4` with CPU and CUDA: wall time, FFmpeg speed, output size,
  average bitrate, and representative seek latency. A bounded 30-second host verification
  is recorded in [the GTX 1070 benchmark](docs/benchmarks/proxy-2026-07-18.md); the
  full-chapter run is intentionally deferred.
- [x] Visually compare NVENC CQ 21 against the existing x264 proxy at fast motion and
  track-edge detail; adjust CQ/preset only with recorded results.
- [x] Add a generated 3–5 second H.264 test fixture with changing telemetry for real
  Playwright playback and seeking.
- [x] Assert that video time, timeline, lap gauge, speed gauge, map source, chart cursor,
  and readout all change after playback and paused seeking.
- [x] Add a compact diagnostics drawer for current media/telemetry synchronization. Keep
  it disabled by default and expose it only through a menu.
- [x] Render unavailable gauge values as `—`, not `0.00`.
- [x] Add Space, Left/Right, Shift+Left/Right, and frame-step keyboard controls.

## Media and import reliability

- [ ] Expose the original single chapter through a constrained byte-range endpoint.
- [ ] Detect browser `hvc1` support and implement direct-source-first playback with proxy
  fallback for one-chapter sessions.
- [ ] Keep the compatibility proxy mandatory for a continuous multi-chapter media clock.
- [ ] Add explicit rebuild proxy, retry import, and cancel import actions.
- [ ] Make import resume stage-aware with artifact validity/version checks.
- [ ] Persist structured per-stage start/end time, backend, command profile, and failure
  diagnostics.
- [ ] Decide whether source-time gaps should remain metadata-only or become explicit
  black/silent spans in the canonical media timeline.
- [ ] Test CUDA failure after partial progress and confirm clean CPU fallback.
- [ ] Test proxy-cache invalidation across backend/profile/version changes.
- [ ] Add stale-source relocation rather than warning only.

## Playback and synchronization

- [ ] Add a development synchronization overlay: video time, sample bracket, interpolated
  time, requestVideoFrameCallback support, and drift.
- [ ] Add play/pause/ended state listeners so icons update independently of telemetry
  renders.
- [ ] Add previous/next frame and previous/next event controls.
- [ ] Add lap and corner keyboard navigation.
- [ ] Test seeking near zero, duration, keyframes, chapter boundaries, and discontinuities.
- [ ] Test background-tab pause/resume and playback-rate changes.
- [ ] Add a user-visible media error with source/proxy fallback action.

## Charts and route

- [x] Reserve chart readout space so axis details are not covered by the player bar.
- [x] Reduce the persistent player bar to 46 px desktop and 52 px mobile.
- [ ] Give speed and g independent labeled y scales.
- [ ] Add zoom, pan, selection, reset, and a moving time window.
- [ ] Link chart hover/click to video seek and route position.
- [ ] Add track-distance mode to the main chart.
- [ ] Add map follow mode, heading-up mode, and full-route reset.
- [ ] Allow individual lap visibility/color selection.
- [ ] Add accessible text summaries for chart windows and selected points.
- [ ] Confirm all readouts fit at 320, 375, 768, 1440, and ultrawide widths.

## Analysis quality

- [ ] Display GPS validity, fix dimension, horizontal error, and rejection reason near the
  current point.
- [ ] Show confidence and diagnostics for inferred start/finish, laps, corners, and axes.
- [ ] Add direct map editing for start/finish position and crossing direction.
- [ ] Add direct chart/map editing for corner entry, apex, and exit.
- [ ] Validate pit-lane proximity and noisy GPS against synthetic and real cases.
- [ ] Fuse or compare calibrated IMU acceleration with GPS-derived g.
- [ ] Add explicit out/hot/cooldown/in lap classification and manual exclusion.
- [ ] Add sector definitions without making sectors a prerequisite for lap delta.
- [ ] Add deterministic processing fingerprints for derived analysis artifacts.

## Comparison and review workflow

- [ ] Link comparison charts, route-distance cursor, delta trace, and video seek.
- [ ] Add largest-gain/loss region summaries.
- [ ] Add corner comparison cards and rank differences by time impact.
- [ ] Add bookmarks, notes, tags, and clip ranges.
- [ ] Add a reference-lap preference that persists per session.
- [ ] Add fullscreen/theater video modes without hiding telemetry context.

## API, storage, and export

- [ ] Add endpoint contract tests for every edit action and error response.
- [ ] Add manifest migrations before schema version 2.
- [ ] Make SQLite/file-manifest authority and repair behavior explicit in code.
- [ ] Add session delete/archive with a recoverable confirmation workflow.
- [ ] Add catalog backup and artifact cleanup tooling.
- [ ] Add export provenance: application version, FFmpeg version, proxy backend/profile,
  and full processing fingerprints.
- [ ] Stream large CSV exports without loading each Parquet file fully into memory.

## Frontend quality and accessibility

- [ ] Add visible focus styles and audit keyboard tab order.
- [ ] Add reduced-motion handling.
- [ ] Increase or adapt small metadata text where it carries operational meaning.
- [ ] Code-split MapLibre, comparison, and editor paths; the current main bundle is about
  1.33 MB before gzip.
- [ ] Add error boundaries and actionable API/media error states.
- [ ] Persist display-unit choices through the API manifest as well as local defaults.
- [ ] Add component-level tests for interpolation readouts and missing values.

## Test and release hygiene

- [ ] Run Ruff, pytest, TypeScript build, and Playwright in CI.
- [ ] Add Linux/macOS media fixtures and opt-in NVIDIA validation.
- [ ] Add the full GoPro sample assertions to a documented local release checklist.
- [ ] Record performance budgets for import, telemetry requests, map updates, and seeking.
- [ ] Define versioning/release notes for manifest, analysis, and proxy profile changes.
- [ ] Keep [Architecture](docs/ARCHITECTURE.md), [Design](docs/DESIGN.md), this TODO,
  and the [Roadmap](docs/ROADMAP.md) current with behavior changes.
