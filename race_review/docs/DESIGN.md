# Product and Interface Design

## Product intent

Race Review should feel like a focused motorsport instrument rather than a generic
video player with charts attached. The driver starts with the footage, understands the
car's state at the current frame, then moves naturally into route, lap, and corner
comparison.

The first milestone optimizes for a trusted local user reviewing GoPro sessions on a
desktop or modern mobile browser. Automatic analysis is guidance, not authority: every
track, lap, calibration, and corner result should expose confidence or remain editable.

## Core interaction model

Video is the primary surface and the authoritative clock. One canonical time drives:

```text
video frame time
      ├── interpolated telemetry → speed / longitudinal g / lateral g / lap / delta
      ├── WGS84 position ────────→ route marker
      ├── chart x position ──────→ cursor and readout
      └── timeline position ─────→ scrubber and markers
```

Playback, scrubbing, lap-row selection, and comparison selection are different ways of
navigating the same session timeline. Seeking while paused must update all dependent
surfaces immediately; updates during playback should remain within one rendered frame.

## Desktop layout

The desktop review uses four persistent regions:

```text
┌──────────────────────── header / session / tune ────────────────────────┐
│ video + live gauges                           │ route + position          │
│                                               │ next corner               │
├──────────────── telemetry chart ──────────────┼ laps / comparison         │
└──────────────── compact transport + event timeline ─────────────────────┘
```

- The header establishes session context without competing with telemetry.
- Gauges overlay the video because they describe the visible frame.
- The route is intentionally usable without network tiles.
- The telemetry plot shows the whole-session context plus a moving time cursor/readout.
- Laps and comparison share a column because lap selection controls comparison.
- The transport bar is a compact persistent navigation control, not a content panel.

The player row is 46 px on desktop. Chart readouts occupy reserved space inside each
chart, so axis ticks and series values cannot be covered by the player bar.

## Responsive layout

Below 900 px, panels become a vertical document:

- the header remains sticky;
- the 16:9 video remains sticky below the header;
- gauges shrink while preserving speed and g;
- route, telemetry, and lap panels become full-width sections;
- the transport remains fixed at the bottom at 52 px;
- document padding reserves the transport height.

Below 560 px, lap and delta gauges are hidden to preserve readable speed and g values,
and player controls use narrower columns. Desktop and mobile overlap constraints are
covered by Playwright.

## Visual language

The interface uses a dark, low-glare base suited to in-car and garage environments.
The palette has semantic roles:

| Token | Meaning |
| --- | --- |
| Red `#ff4b34` | Primary action, live state, timeline progress, selected lap. |
| Amber `#ffb238` | Corners, secondary telemetry, delta emphasis. |
| Off-white | Primary speed trace and high-contrast data. |
| Cyan | Alternate lap/route distinction. |
| Gray-green panels | Structural separation without bright chrome. |

Condensed headings evoke timing screens while body text remains system sans-serif for
legibility. Small uppercase metadata is supporting information and must not contain the
only representation of a critical state.

## Video and controls

- Click/tap the video or transport control to toggle playback.
- Theater and fullscreen keep gauges and a compact telemetry readout with the video.
- A browser-compatible original chapter is preferred for one-chapter sessions; a source
  loading error falls back to the compatibility proxy.
- Multi-chapter sessions always use the proxy to preserve one continuous media clock.
- Video is letterboxed with `object-fit: contain`; content is never cropped.
- Playback rates range from 0.25× to 2×.
- The scrubber displays current and total canonical time on desktop.
- Chapter boundaries, lap crossings, and corners have distinct timeline markers.
- Two-second proxy keyframes balance seek latency and output efficiency.

Comma/period step one proxy frame; bracket keys navigate laps; semicolon/quote navigate
corner events; T toggles theater mode; F toggles fullscreen of the video stage. Transport
buttons expose adjacent frames and events. Play, pause, and ended media events update
transport icons independently of telemetry renders.

## Gauges

The live overlay prioritizes:

1. speed in mph;
2. GPS-derived longitudinal g;
3. GPS-derived lateral g;
4. current lap;
5. delta to the saved session reference lap, or the fastest complete, non-excluded lap.

Values are interpolated at video time. Lap number remains discrete. Missing numeric
values render as an em dash so they cannot be confused with a measured zero.

## Route view

MapLibre renders a local GeoJSON style with no external dependency:

- route lines retain a ground reference while GoPro GPS altitude forms an elevated
  cyan/amber/red ribbon;
- start/finish and detected corners are separate layers;
- the current position is a high-contrast marker updated without rebuilding the map;
- initial bounds contain the complete route;
- optional raster tiles may be configured locally.

The route opens in a pitched 3D camera and supports pan, rotation/tilt, full-route reset,
a top-down view, 1×/3× vertical exaggeration, follow mode, heading-up rotation, and
per-lap visibility/color. A software-projected elevation route replaces the canvas if
WebGL initialization fails so other review surfaces remain available.

## Telemetry charts

uPlot is used for predictable performance on full-session arrays. The main chart shows
speed, lateral g, and longitudinal g against canonical seconds. Each chart reserves a
22 px readout row for axis context, colored series labels, current time, and values.
The built-in legend is disabled because its unconstrained layout could be clipped by the
persistent transport.

The main chart shows the whole session with zoom, pan, selection, and an optional
moving time window. Comparison speed and delta traces share a track-distance cursor
with video seek, the route marker, and a ghosted position for the other lap.

## Lap and corner editing

Lap rows seek to lap starts. Complete, non-excluded laps populate reference/comparison
selectors. Comparison traces are aligned by lap distance rather than wall-clock time,
and delta is calculated from the distance-aligned elapsed times. Hovering or clicking a
comparison chart, delta region, or corner card seeks the video to the matching distance
on the lap currently in view. The largest gain and loss regions and corner cards ranked
by time impact sit under the traces. The selected reference lap persists per session
and drives the live delta gauge.

Bookmarks store a timestamp, label, note, tags, and optional in/out clip range on the
session. They appear on the timeline and export with the analysis bundle. Export is
available from the library card and the review header; the ZIP includes application
version, FFmpeg version, proxy backend/profile, and processing fingerprints.

The library archives a session after an explicit confirmation, then keeps it recoverable
until the driver types the session id and permanently deletes it. Catalog backup and
artifact cleanup live on the library header; cleanup asks before removing regenerable
export copies and leftover partial transcodes.

Theater mode enlarges the video column while keeping gauges, route, charts, and
comparison visible. Fullscreen uses the video stage so gauges and a compact lap/corner
readout stay with the frame.

The Tune drawer owns user overrides:

- start/finish endpoints, direction, and exclusion settings;
- camera forward/lateral axis and sign;
- corner rename/create/update/delete/split/merge operations.

Edits persist in SQLite and the manifest, then trigger deterministic reanalysis where
needed. Direct manipulation on the route/chart is not implemented yet.

## Units and precision

Storage and calculations remain SI:

- seconds;
- meters and meters per second;
- meters per second squared;
- WGS84 degrees plus ENU meters.

US-motorsport display defaults are mph, g, feet, and seconds. Conversion happens at
the presentation boundary. Timestamps preserve millisecond display precision while
interpolation uses the underlying floating-point sample times.

## Loading, errors, and progress

Import progress is stage-based and persistent. Proxy progress includes FFmpeg output
time, speed, and an ETA. The completed analysis manifest is checkpointed before proxy
generation so a long encode does not make prior work appear missing.

Failed imports show the persisted error and structured stage attempt. The processing
screen exposes retry and cancel actions, while ready sessions expose an explicit proxy
rebuild. Valid version-matched analysis artifacts are reused on retry.

## Accessibility baseline

Current controls use native buttons, selects, and range inputs with labels for the video
timeline, playback rate, route map, gauges, and play/pause action. Contrast is generally
high, and information is not encoded solely by route color because lap/corner tables
remain textual.

Review keyboard shortcuts, `:focus-visible` styling, reduced-motion handling for CSS and
MapLibre, the analysis drawer as a keyboard-contained modal, and chart/map text summaries
are in place. Remaining accessibility work is stronger touch targets on dense mobile
controls.

## Design decisions

### Local-first artifacts

Large video and telemetry should not require upload. Source paths stay in place, and
derived data is inspectable/exportable. This makes processing reproducible and keeps
private driving footage local.

### Compatibility proxy plus preserved source

H.264/AAC is the deterministic browser baseline and creates one continuous media clock
for multiple chapters. One-chapter sessions prefer a browser-compatible original,
including an explicit `hvc1` capability check for HEVC, and fall back to the proxy on a
media loading error.

### SQLite plus Parquet

SQLite is appropriate for a small transactional catalog and user edits. Parquet is
appropriate for columnar native-rate telemetry and analysis. Keeping them separate
avoids storing large numeric arrays as database blobs or JSON.

### Route-first MapLibre

MapLibre supplies a stable rendering/update model without requiring a basemap or network
connection. WGS84 route data remains compatible with future tile configuration.

### Stable reconstruction boundary

`TrackGeometryAdapter` exposes WGS84 and right-handed ENU meters with optional time
alignment. It deliberately does not invent a 3D artifact format before the reconstruction
project defines its contract.

### Automatic results remain editable

GPS noise, pit-lane proximity, partial recordings, and camera mounting make perfect
automatic inference unrealistic. User edits are part of the core data model rather than
temporary UI state.
