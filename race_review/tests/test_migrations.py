from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from race_review.analysis import ANALYSIS_VERSION
from race_review.migrations import (
    CURRENT_SCHEMA_VERSION,
    apply_v1_compat,
    load_manifest,
    migrate_manifest_payload,
    migrate_v0_to_v1,
)
from race_review.models import SessionManifest


def _base_v0() -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    return {
        "session_id": "legacy01",
        "name": "Legacy",
        "created_at": now,
        "updated_at": now,
        "status": "ready",
        "duration_seconds": 10,
        "chapters": [
            {
                "index": 0,
                "filename": "GX010001.MP4",
                "fingerprint": {
                    "path": "/media/GX010001.MP4",
                    "size_bytes": 1,
                    "modified_ns": 1,
                    "sha256": "0" * 64,
                },
                "duration_seconds": 10,
                "timeline_start_seconds": 0,
                "timeline_end_seconds": 10,
            }
        ],
        "processing_versions": {"race_review": "0.0.1"},
        "unknown_legacy_field": True,
    }


def test_current_schema_version_matches_model() -> None:
    annotation = SessionManifest.model_fields["schema_version"].annotation
    assert annotation.__args__[0] == CURRENT_SCHEMA_VERSION


def test_v0_manifest_migrates_to_v1_and_loads() -> None:
    migrated = migrate_manifest_payload(_base_v0())
    assert migrated["schema_version"] == 1
    assert "unknown_legacy_field" not in migrated
    assert migrated["edits"]["bookmarks"] == []
    assert migrated["processing_stages"] == {}
    assert migrated["processing_versions"]["analysis"] == ANALYSIS_VERSION
    assert migrated["processing_versions"]["manifest"] == str(CURRENT_SCHEMA_VERSION)
    manifest = load_manifest(_base_v0())
    assert manifest.schema_version == 1
    assert manifest.archived_from_status is None
    assert manifest.edits.display_units.speed == "mph"


def test_v1_compat_fills_additive_archive_fields() -> None:
    payload = migrate_v0_to_v1(_base_v0())
    payload.pop("archived_from_status", None)
    payload.pop("archived_at", None)
    patched = apply_v1_compat(payload)
    assert patched["archived_from_status"] is None
    assert patched["archived_at"] is None


def test_future_schema_version_is_rejected() -> None:
    payload = _base_v0()
    payload["schema_version"] = CURRENT_SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="newer than supported"):
        migrate_manifest_payload(payload)


def test_invalid_payload_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        migrate_manifest_payload([])  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        load_manifest({"schema_version": 1, "session_id": "x"})
