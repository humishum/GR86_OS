from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    frame.to_parquet(temporary, index=False, engine="pyarrow", compression="zstd")
    os.replace(temporary, path)


def read_parquet(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(path, columns=columns, engine="pyarrow")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()
