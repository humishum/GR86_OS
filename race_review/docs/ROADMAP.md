# Race Review Roadmap

This roadmap orders work by user-visible risk and dependency. Dates are intentionally
relative; the active checklist in [TODO.md](../TODO.md) is the day-to-day source of truth.

## Tomorrow: reliability and workflow kickoff

Outcome: the current single-chapter Sonoma workflow is fast, observable, and trustworthy.

1. Benchmark the GTX 1070 CUDA pipeline on the real 4K60 chapter and record CPU/CUDA
   speed, output size, seek latency, and visual quality.
2. Add a real short media fixture to Playwright so presented-frame callbacks, playback,
   paused seeking, gauge changes, map movement, chart cursor movement, and scrubber time
   are tested together.
3. Add an in-app diagnostics panel showing the telemetry timestamp range, sample rate,
   current video time, nearest sample time, and drift.
4. Distinguish missing telemetry from numeric zero in gauges and chart readouts.
5. Add keyboard playback controls: space, arrows, frame-step, rate changes, and lap jumps.

Definition of done:

- the GPU path is confirmed on the host rather than inferred from encoder listings;
- a browser regression fails if the canonical clock freezes again;
- users can explain the current media/telemetry state without opening developer tools;
- all primary controls work without a mouse.

Kickoff progress (2026-07-18): the browser regression, opt-in diagnostics, missing-value
semantics, and keyboard workflow are complete. The CUDA host path and a representative
30-second CPU/CUDA window are verified in [the GTX 1070 benchmark](benchmarks/proxy-2026-07-18.md);
the full-chapter benchmark remains deferred to keep effort focused on review and analysis
features.

## Milestone 0.2: fast source-to-review

Outcome: supported single-chapter sessions become reviewable immediately, while every
environment retains a reliable fallback.

- Add a byte-range endpoint for the original chapter.
- Probe `hvc1` playback capability and prefer direct HEVC for supported single chapters.
- Generate the compatibility proxy in the background or on demand.
- Preserve the proxy as the required continuous timeline for multi-chapter sessions.
- Make import stages independently resumable and skip valid telemetry/analysis artifacts.
- Add cancel, retry, and explicit rebuild-proxy actions.
- Show CUDA/CPU backend and real progress consistently in the library and review screen.

Definition of done:

- a supported mac M3/modern desktop opens a one-chapter session without waiting for a proxy;
- an unsupported browser falls back without manual intervention;
- restarting at any import stage repeats only invalid or incomplete work;
- no operation modifies the GoPro source.

## Milestone 0.3: analysis confidence and editing

Outcome: automatically detected laps and corners are easy to validate and correct.

- Draw and drag the start/finish line directly on the route.
- Preview crossing direction and lap boundaries before saving.
- Add confidence and diagnostic explanations for track, lap, corner, and calibration
  inference.
- Add interactive corner boundary/apex handles on the chart and route.
- Improve pit-lane/proximity rejection and noisy-GPS handling.
- Overlay calibrated IMU and GPS-derived g for validation.
- Add manual lap exclusion and labels for out, hot, cooldown, and in laps.
- Make reanalysis dependency-aware so corner edits do not rebuild unrelated artifacts.

Definition of done:

- every automatic result has an understandable confidence/diagnostic surface;
- all supported edits survive reload and export;
- reanalysis produces byte-equivalent results for unchanged inputs and processing versions.

## Milestone 0.4: driver comparison workspace

Outcome: the application answers where and how two laps differ.

- Linked track-distance cursors across route, speed traces, delta, and video.
- Zoomable time and distance windows with reset/full-session controls on the main chart.
- Corner comparison cards for braking point, entry/apex/exit speed, lateral peak, and
  time gained/lost, ranked by time impact.
- Reusable reference laps persisted per session.
- Annotations, bookmarks, notes, tags, and referenced clip ranges.
- Theater and fullscreen video that keep gauges and a compact telemetry readout visible.
- Remaining: sectors as an optional overlay, and synchronized A/B or ghosted video
  navigation where source coverage permits.

Definition of done:

- selecting a point on any comparison surface updates every other surface;
- a driver can identify the largest deltas and the contributing corner metrics without
  manually reading raw telemetry.

## Milestone 0.5: performance and packaging

Outcome: installation and large-session use are routine rather than developer workflows.

- Code-split MapLibre/uPlot/editor bundles and reduce initial JavaScript transfer.
- Window or level-of-detail telemetry for very long sessions.
- Catalog backup, session archive/delete confirmation, and artifact cleanup are in
  the library; remaining packaging work is an installable launcher, first-run
  dependency diagnostics, structured logs, and a support bundle.
- Support configurable proxy resolution/frame rate/quality policies.
- Add structured application logs and a downloadable support bundle.
- CI runs Ruff, pytest, the TypeScript production build, and Playwright on Linux and
  macOS with CPU media fixtures; real GoPro and NVIDIA tests remain opt-in on the
  [release checklist](RELEASE.md).

## Later roadmap

- Multi-camera and external logger time alignment.
- Vehicle-specific channels and CAN/OBD ingestion.
- Coaching summaries using deterministic analysis outputs; no multimodal provider is a
  first-milestone dependency.
- Collaboration/export workflows that preserve local privacy.
- 3D reconstruction integration only after its project publishes a stable geometry and
  time-alignment contract.

## Architectural guardrails

Every milestone continues to preserve these constraints:

- canonical joins remain video-relative seconds;
- calculations and storage remain SI;
- source media remains read-only and fingerprinted;
- rejected telemetry remains inspectable;
- automatic analysis remains editable;
- route review works offline;
- `TrackGeometryAdapter` does not expand into an invented 3D format;
- processing/cache versions change whenever output semantics change.
