from __future__ import annotations

import json
from pathlib import Path

from race_review.api import create_app
from race_review.config import Settings

root = Path(__file__).resolve().parents[1]
temporary_var = root / "var" / "openapi"
settings = Settings(project_root=root, var_root=temporary_var, media_roots=(root.parent / "data",))
schema = create_app(settings).openapi()
(root / "frontend" / "openapi.json").write_text(
    json.dumps(schema, indent=2) + "\n", encoding="utf-8"
)
