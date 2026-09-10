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


def _selected_path(value: str | Path, root: Path) -> Path:
    path = (root / Path(value)).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError("configured resource must remain inside the repository") from error
    return path


def load_frozen_constructions(resource_paths: dict[str, str] | None = None) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    from .resource_freeze import load_frozen_jsonl
    root = project_root()
    selected = resource_paths or {
        "resource": "resources/constructions/filipino_constructions_v1.parquet",
        "manifest": "resources/constructions/construction_manifest_v1.json",
    }
    resource = _selected_path(selected["resource"], root)
    if not resource.exists():
        fallback = resource.with_suffix(".jsonl")
        if fallback.exists():
            resource = fallback
    rows, manifest = load_frozen_jsonl(resource, _selected_path(selected["manifest"], root))
    return tuple(rows), manifest


def load_frozen_punctuation(resource_paths: dict[str, str] | None = None) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    """Load reviewed punctuation-substitution contexts, if supplied.

    Generic punctuation swaps are intentionally not a production resource.
    The path remains explicit so a reviewed, versioned context file can be
    supplied later without changing generator semantics.
    """
    from .resource_freeze import load_frozen_jsonl
    root = project_root()
    selected = resource_paths or {
        "resource": "resources/punctuation/punctuation_context_v1.parquet",
        "manifest": "resources/punctuation/punctuation_manifest_v1.json",
    }
    resource = _selected_path(selected["resource"], root)
    if not resource.exists():
        fallback = resource.with_suffix(".jsonl")
        if fallback.exists():
            resource = fallback
    rows, manifest = load_frozen_jsonl(resource, _selected_path(selected["manifest"], root))
    return tuple(rows), manifest
