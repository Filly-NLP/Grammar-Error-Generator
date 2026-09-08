"""Validate artifact destinations and upstream provenance before writing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .hashing import sha256_file


def validate_destinations(inputs: Mapping[str, Path], outputs: Mapping[str, Path]) -> None:
    """Reject path aliases, including existing hard links, before any writer opens."""
    resolved_inputs = [(name, path.resolve()) for name, path in inputs.items()]
    seen = list(resolved_inputs)
    for name, original in outputs.items():
        path = original.resolve()
        for other_name, other in seen:
            if path == other or (path.exists() and other.exists() and path.samefile(other)):
                raise ValueError(f"output {name} aliases {other_name}: {path}; paths must be distinct")
        seen.append((name, path))


def verify_manifest(path: Path, artifact: Path, config_digest: str, artifact_key: str | None = None) -> dict[str, Any]:
    """Fail closed on missing, blocked, stale, or mismatched upstream manifests."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"missing or invalid upstream manifest {path}; regenerate upstream artifacts") from error
    if not isinstance(manifest, dict) or manifest.get("status") != "complete":
        raise RuntimeError(f"upstream manifest is not complete: {path}")
    if manifest.get("config_hash") != config_digest:
        raise RuntimeError(f"stale upstream configuration: {path}; regenerate upstream artifacts")
    if artifact_key:
        hashes = manifest.get("artifact_hashes")
        if not isinstance(hashes, dict):
            raise RuntimeError(f"upstream manifest lacks artifact hashes: {path}")
        expected = hashes.get(artifact_key)
    else:
        expected = manifest.get("output_sha256")
    if expected != sha256_file(artifact):
        raise RuntimeError(f"upstream artifact hash mismatch: {artifact}; regenerate upstream artifacts")
    return manifest
