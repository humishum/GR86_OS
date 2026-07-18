# Race Review Documentation

This directory describes the system that is implemented today and the direction of
the next milestones.

- [Architecture](ARCHITECTURE.md): components, data flow, storage, APIs, timing,
  processing, recovery, and operational boundaries.
- [Product and interface design](DESIGN.md): interaction model, synchronization,
  visual layout, responsive behavior, units, accessibility, and design decisions.
- [Roadmap](ROADMAP.md): ordered milestones, outcomes, dependencies, and definitions
  of done.
- [Active TODO list](../TODO.md): concrete, checkable engineering tasks.

The generated OpenAPI schema remains the canonical HTTP contract. Export it with
`uv run python scripts/export_openapi.py`; the checked-in TypeScript bindings are
generated from that schema.
