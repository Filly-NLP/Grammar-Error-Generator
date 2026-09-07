"""Load the repository's JSON-compatible YAML resource files without dependencies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_resource(name: str) -> dict[str, Any]:
    path = project_root() / "resources" / name
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"resource root must be an object: {path}")
    return value
