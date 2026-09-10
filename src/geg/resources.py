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


def load_frozen_constructions() -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    from .resource_freeze import load_frozen_jsonl
    root = project_root()
    resource = root / "resources/constructions/filipino_constructions_v1.parquet"
    if not resource.exists():
        resource = root / "resources/constructions/filipino_constructions_v1.jsonl"
    rows, manifest = load_frozen_jsonl(resource, root / "resources/constructions/construction_manifest_v1.json")
    return tuple(rows), manifest


def load_frozen_punctuation() -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    """Load reviewed punctuation-substitution contexts, if supplied.

    Generic punctuation swaps are intentionally not a production resource.
    The path remains explicit so a reviewed, versioned context file can be
    supplied later without changing generator semantics.
    """
    from .resource_freeze import load_frozen_jsonl
    root = project_root()
    resource = root / "resources/punctuation/punctuation_context_v1.parquet"
    if not resource.exists():
        resource = root / "resources/punctuation/punctuation_context_v1.jsonl"
    rows, manifest = load_frozen_jsonl(resource, root / "resources/punctuation/punctuation_manifest_v1.json")
    return tuple(rows), manifest
