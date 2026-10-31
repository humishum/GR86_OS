from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .analysis import ANALYSIS_VERSION
from .models import SessionManifest

# Keep this equal to SessionManifest.schema_version. Bump only together with a
# registered migrate_vN_to_vN+1 function; additive v1 fields use compat patches.
# See docs/RELEASE.md.
CURRENT_SCHEMA_VERSION = 1

ManifestMigrator = Callable[[dict[str, Any]], dict[str, Any]]


def _as_int_version(value: object) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid manifest schema_version: {value!r}") from exc


def migrate_v0_to_v1(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize unversioned or incomplete manifests into schema version 1."""
    migrated = dict(payload)
    migrated["schema_version"] = 1
    migrated.setdefault("streams", [])
    migrated.setdefault("coordinate_origin", None)
    migrated.setdefault(
        "processing_versions",
        {
            "race_review": "unknown",
            "analysis": ANALYSIS_VERSION,
            "manifest": str(CURRENT_SCHEMA_VERSION),
        },
    )
    if isinstance(migrated["processing_versions"], dict):
        migrated["processing_versions"].setdefault("manifest", str(CURRENT_SCHEMA_VERSION))
        migrated["processing_versions"].setdefault("analysis", ANALYSIS_VERSION)
    migrated.setdefault("processing_options", {"generate_proxy": True})
    migrated.setdefault("processing_stages", {})
    migrated.setdefault("artifacts", {})
    migrated.setdefault("warnings", [])
    edits = migrated.get("edits")
    if not isinstance(edits, dict):
        edits = {}
    edits.setdefault("track", {})
    edits.setdefault("calibration", {})
    edits.setdefault("corner_edits", [])
    edits.setdefault("display_units", {})
    edits.setdefault("reference_lap", None)
    edits.setdefault("bookmarks", [])
    migrated["edits"] = edits
    allowed = set(SessionManifest.model_fields)
    return {key: value for key, value in migrated.items() if key in allowed}


def apply_v1_compat(payload: dict[str, Any]) -> dict[str, Any]:
    """Fill additive schema-version-1 fields without bumping the version."""
    migrated = dict(payload)
    migrated.setdefault("schema_version", 1)
    migrated.setdefault("processing_stages", {})
    migrated.setdefault("archived_from_status", None)
    migrated.setdefault("archived_at", None)
    edits = migrated.get("edits")
    if isinstance(edits, dict):
        edits.setdefault("corner_edits", [])
        edits.setdefault("display_units", {})
        edits.setdefault("reference_lap", None)
        edits.setdefault("bookmarks", [])
        migrated["edits"] = edits
    return migrated


MIGRATIONS: dict[int, ManifestMigrator] = {
    0: migrate_v0_to_v1,
}


def migrate_manifest_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a raw manifest dict to CURRENT_SCHEMA_VERSION.

    Schema version 2 must not ship until a migrate_v1_to_v2 function is
    registered here. In-version additive fields are handled by apply_v1_compat.
    """
    if not isinstance(payload, dict):
        raise ValueError("Manifest payload must be an object")
    migrated = dict(payload)
    version = _as_int_version(migrated.get("schema_version"))
    if version > CURRENT_SCHEMA_VERSION:
        raise ValueError(
            f"Manifest schema_version {version} is newer than supported {CURRENT_SCHEMA_VERSION}"
        )
    while version < CURRENT_SCHEMA_VERSION:
        previous = version
        migrator = MIGRATIONS.get(version)
        if migrator is None:
            raise ValueError(f"No manifest migration is registered from schema_version {version}")
        migrated = migrator(migrated)
        version = _as_int_version(migrated.get("schema_version"))
        if version <= previous:
            raise ValueError("Manifest migration did not advance schema_version")
    if CURRENT_SCHEMA_VERSION == 1:
        migrated = apply_v1_compat(migrated)
    migrated["schema_version"] = CURRENT_SCHEMA_VERSION
    return migrated


def load_manifest(payload: dict[str, Any]) -> SessionManifest:
    return SessionManifest.model_validate(migrate_manifest_payload(payload))
