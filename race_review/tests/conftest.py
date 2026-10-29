import json
from pathlib import Path

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def performance_budgets() -> dict[str, float]:
    path = Path(__file__).resolve().parents[1] / "performance_budgets.json"
    return json.loads(path.read_text(encoding="utf-8"))
