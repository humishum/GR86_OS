# Changelog

All notable Race Review changes are documented here. Version identifiers for the
application, manifest schema, analysis pipeline, and proxy profile are defined in
[the release notes](docs/RELEASE.md).

## Unreleased

### Added

- Linked lap comparisons with shared video/route cursors, a ghost route position,
  largest gain/loss regions, and corner cards ranked by time impact.
- Per-session reference laps, bookmarks, notes, tags, and clip ranges, with timeline
  markers and analysis-bundle export.
- Theater and fullscreen video modes with telemetry context and keyboard shortcuts.
- Recoverable session archiving, restore, confirmed permanent deletion, catalog backup,
  and artifact cleanup through the library and API.
- Versioned manifest loading and SQLite/checkpoint repair on startup and from the CLI.
- Streamed Parquet-to-CSV ZIP exports with application, FFmpeg, proxy, and processing
  fingerprint provenance.
- Linux and macOS CI for Ruff, pytest, the TypeScript production build, and Playwright.
- Portable CPU H.264 media fixtures for pytest, with NVIDIA CUDA/NVENC validation
  behind `RACE_REVIEW_NVIDIA=1`.
- Recorded performance budgets for short-fixture import, telemetry requests, map
  updates, and paused seeking.
- Local release checklist including the full `GX020115.MP4` sample assertions.

### Fixed

- Artifact cleanup skips running imports and preserves unregistered directories and
  unreadable or unsupported manifests for recovery. Database write reservations keep
  imports from starting while cleanup removes files.
- Manifest persistence serializes SQLite and checkpoint writes to prevent concurrent
  writers from leaving an older checkpoint behind.
- The lap-comparison retry regression runs against both development and production
  frontend builds without relying on StrictMode request counts.

### Versioning

- Manifest schema: 1 (unchanged). Additive v1 fields still use compatibility patches.
- Analysis version: `1` (`ANALYSIS_VERSION`). Resume invalidates artifacts on mismatch.
- Proxy profile: `h264-1080p60-aac-gop2s-v3` / cache version 1 (unchanged).
