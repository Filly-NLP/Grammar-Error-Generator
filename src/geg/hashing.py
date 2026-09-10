"""Stable file and source-manifest hashing helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_files(paths: tuple[Path, ...], *, root: Path | None = None) -> str:
    root = (root or Path(__file__).resolve().parents[2]).resolve()
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda value: value.resolve().relative_to(root).as_posix()):
        digest.update(path.resolve().relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def generator_dependency_manifest(*, root: Path | None = None, resource_paths: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
    """Return the canonical code/resource dependency manifest.

    Paths are rooted at the repository, so hashes are identical regardless of
    the caller's current working directory. Missing optional reviewed
    resources remain explicit dependencies with ``present=false``; once a
    resource is supplied, its hash changes the dependency identity and makes
    older Phase 6/8/9/10 artifacts stale.
    """
    root = (root or Path(__file__).resolve().parents[2]).resolve()
    defaults = {
        "morphology": ("resources/morphology/tagalog_verb_paradigms_v1.parquet", "resources/morphology/morphology_manifest_v1.json"),
        "constructions": ("resources/constructions/filipino_constructions_v1.parquet", "resources/constructions/construction_manifest_v1.json"),
        "punctuation": ("resources/punctuation/punctuation_context_v1.parquet", "resources/punctuation/punctuation_manifest_v1.json"),
    }
    selected = resource_paths or {
        name: {"resource": values[0], "manifest": values[1]}
        for name, values in defaults.items()
    }
    selected_files: list[Path] = [
        root / selected[name][key]
        for name in ("morphology", "constructions", "punctuation")
        for key in ("resource", "manifest")
    ]
    for name in ("morphology", "constructions", "punctuation"):
        payload = root / selected[name]["resource"]
        fallback = payload.with_suffix(".jsonl")
        if not payload.is_file() and fallback.is_file():
            selected_files.append(fallback)
    candidates = tuple(
        [
        root / "src/geg/generators.py",
        root / "src/geg/alignment.py",
        root / "src/geg/morphology.py",
        root / "src/geg/resource_freeze.py",
        root / "src/geg/resources.py",
        root / "src/geg/states.py",
        root / "src/geg/tags.py",
        root / "src/geg/schema.py",
        root / "resources/balarila_tags.yaml",
        root / "resources/table3_states.yaml",
        # The configured payload/manifest are the active identities.  Also
        # retain the JSONL fallback beside the default v1 payload for the
        # dependency contract used by development fixtures.
        ] + selected_files
    )
    entries: list[dict[str, Any]] = []
    for path in sorted(candidates, key=lambda item: item.relative_to(root).as_posix()):
        rel = path.relative_to(root).as_posix()
        entries.append({
            "path": rel,
            "present": path.is_file(),
            "sha256": sha256_file(path) if path.is_file() else None,
        })
        # A reviewed morphology manifest may point at an external mapping-rule
        # artifact. Bind its current bytes too, so changing the rule artifact
        # invalidates the Phase 6/8/9/10 chain even when the frozen payload is
        # unchanged.
        if path.name.startswith("morphology_manifest") and path.is_file():
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                artifact = Path(str(manifest.get("mapping_rule_artifact", "")))
                if not artifact.is_absolute():
                    artifact = root / artifact
                if artifact.is_file():
                    # Do not put an operator's absolute local path in the
                    # dependency identity.  The content digest is the
                    # identity; the path is deliberately omitted so the
                    # result is stable across checkouts and working dirs.
                    artifact_digest = sha256_file(artifact)
                    entries.append({
                        "path": f"external-content::{artifact_digest}",
                        "present": True,
                        "sha256": artifact_digest,
                    })
            except (OSError, UnicodeError, json.JSONDecodeError):
                pass
    return {"schema_version": 1, "entries": entries}


def generator_dependency_hash(*, root: Path | None = None, resource_paths: dict[str, dict[str, str]] | None = None) -> str:
    manifest = generator_dependency_manifest(root=root, resource_paths=resource_paths)
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def legacy_generator_hash(*, root: Path | None = None) -> str:
    """Compatibility digest for isolated pre-v2 development fixtures.

    It is intentionally root-anchored and is never accepted by production
    Phase 6/8/9/10 artifacts.
    """
    root = (root or Path(__file__).resolve().parents[2]).resolve()
    return sha256_files((root / "src/geg/generators.py", root / "src/geg/alignment.py"), root=root)
