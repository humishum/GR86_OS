# GR86 Race Review

Local-first GoPro session review. Source MP4s are fingerprinted and referenced in place; the application writes only its SQLite catalog, Parquet telemetry, analysis JSON, thumbnails, and browser proxy below `var/`.

## Documentation

- [Architecture and data flow](docs/ARCHITECTURE.md)
- [Product and interface design](docs/DESIGN.md)
- [Roadmap](docs/ROADMAP.md)
- [Active TODO list](TODO.md)

## Requirements

- Python 3.12 and `uv`
- Node 20 and npm
- FFmpeg/ffprobe with H.264 encoding support
- The sibling `gopro-py` checkout pinned at `3040b2f4efc8624e24c0962289eabb25f6a26c7b`

## Run locally

```bash
cd race_review
uv sync --extra dev
uv run race-review serve
```

In another terminal:

```bash
cd race_review/frontend
npm install
npm run dev
```

Vite serves the UI at `http://127.0.0.1:5173` and proxies API calls to FastAPI. For a single production-style process, run `npm run build` first; FastAPI serves the resulting `frontend/dist` at `http://127.0.0.1:8000`.

By default the only browsable media root is the repository's `data/` directory. Configure one or more trusted roots with an OS-path-separator-delimited environment variable:

```bash
RACE_REVIEW_MEDIA_ROOTS=/media/gopro:/srv/races uv run race-review serve
```

Proxy generation automatically uses NVIDIA CUDA/NVENC when FFmpeg can initialize it,
including GPU HEVC decode, resize, and H.264 encode. It falls back to CPU encoding if
the driver or GPU is unavailable. Override detection when troubleshooting with:

```bash
RACE_REVIEW_PROXY_ACCELERATION=cuda uv run race-review serve  # require NVIDIA
RACE_REVIEW_PROXY_ACCELERATION=cpu uv run race-review serve   # force CPU
```

Import ordered chapters from the CLI and optionally defer the expensive proxy transcode:

```bash
uv run race-review import --media-root ../data --skip-proxy ../data/GX020115.MP4
```

## Storage and timing

- `var/catalog.sqlite3`: sessions, jobs, source identities, and user edits.
- `var/sessions/<id>/manifest.json`: versioned, portable analysis manifest.
- `var/sessions/<id>/telemetry/*.parquet`: native and derived SI telemetry.
- `var/sessions/<id>/analysis/`: lap, corner, and quality diagnostics.
- `var/sessions/<id>/media/proxy.mp4`: cached H.264/AAC 1080p60 proxy with two-second GOPs and fast-start metadata.

All joins use canonical video-relative seconds. Chapter source-time discontinuities are recorded in the manifest and are never silently inferred away. Display conversions (mph, g, feet) occur only in the frontend.

## API contract

Export the OpenAPI schema and regenerate TypeScript types after changing backend models:

```bash
uv run python scripts/export_openapi.py
cd frontend
npm run generate:api
```

The `TrackGeometryAdapter` schema intentionally stops at WGS84 plus right-handed ENU meters with an optional time offset. A 3D artifact contract is deferred until the reconstruction project defines one.

## Verification

```bash
uv run pytest
cd frontend && npm run build
```

The 4 GB sample integration test is opt-in via `RACE_REVIEW_GOPRO_SAMPLE`; normal tests do not transcode it.
