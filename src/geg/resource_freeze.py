"""Fail-closed freeze/load helpers for reviewed linguistic resources."""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .hashing import sha256_file
from .states import state_by_id
from .tags import require_registered
from .tags import registry


def _reviewed_terminal_mark(context: str, value: Any) -> str | None:
    """Return a canonical terminal mark from a mark or full context pattern.

    The freeze input accepts either the canonical one-character surfaces or a
    full ``context + mark`` pattern.  In the latter form the lexical prefix
    must be byte-for-byte identical to the separately stored context.  This
    makes the lexical-equality invariant explicit instead of relying on a
    later generator comparison.
    """
    surface = str(value)
    if len(surface) == 1 and surface in ".?!":
        return surface
    if surface.startswith(context) and len(surface) == len(context) + 1 and surface[-1] in ".?!":
        return surface[-1]
    return None


def _atomic_publish(path: Path, payload: bytes) -> None:
    """Publish one file without ever replacing an existing destination.

    A concurrent freeze must lose with ``FileExistsError`` rather than
    silently replacing a resource that may already be bound into a dataset
    manifest.  A hard link is an exclusive create on the same filesystem, and
    the staged file is removed only after the destination has been created
    successfully.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite frozen resource: {path}")
    with tempfile.NamedTemporaryFile(prefix=f".{path.name}.", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        handle.write(payload)
    try:
        os.link(temp, path)
        temp.unlink(missing_ok=True)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number} is invalid JSON") from error
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number} must be an object")
        rows.append(row)
    return rows


def _stage_rows(path: Path, rows: list[dict[str, Any]]) -> Path:
    """Serialize rows to a same-directory temporary file and fsync it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as error:  # pragma: no cover - optional data dependency
            raise RuntimeError("Parquet resource freezing requires pyarrow") from error
        with tempfile.NamedTemporaryFile(prefix=f".{path.name}.", suffix=".parquet", dir=path.parent, delete=False) as handle:
            temp = Path(handle.name)
        try:
            pq.write_table(pa.Table.from_pylist(rows), temp, compression="zstd")
            with temp.open("ab") as stream:
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        return temp
    if path.suffix.lower() == ".json" and len(rows) == 1:
        payload = (json.dumps(rows[0], ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    else:
        payload = ("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)).encode("utf-8")
    with tempfile.NamedTemporaryFile(prefix=f".{path.name}.", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return temp


def _validate_freeze_paths(input_path: Path, resource_path: Path, manifest_path: Path) -> None:
    input_resolved = input_path.resolve()
    resource_resolved = resource_path.resolve()
    manifest_resolved = manifest_path.resolve()
    if resource_resolved == manifest_resolved:
        raise ValueError("resource and manifest destinations must be distinct")
    for destination in (resource_path, manifest_path):
        if destination.exists():
            raise FileExistsError(f"refusing to overwrite frozen resource: {destination}")
        # Existing hard-link/symlink aliases must never be overwritten, even
        # when the requested destination spelling differs from the input.
        if input_path.exists():
            try:
                if os.path.samefile(input_path, destination):
                    raise ValueError(f"resource destination aliases input: {destination}")
            except FileNotFoundError:
                pass


def _publish_pair(input_path: Path, resource_path: Path, manifest_path: Path, rows: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    """Publish resource and manifest as one lock-protected pair.

    Both files are staged beside their final paths. Exclusive hard-link
    publication means an existing destination can never be overwritten. If
    the second link loses a race, the first file created by this call is
    rolled back, leaving no half-frozen resource pair.
    """
    _validate_freeze_paths(input_path, resource_path, manifest_path)
    resource_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = resource_path.parent / f".{resource_path.name}.freeze.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError as error:
        raise FileExistsError(f"resource freeze is already in progress: {lock_path}") from error
    resource_temp: Path | None = None
    manifest_temp: Path | None = None
    published_resource = False
    try:
        if resource_path.exists() or manifest_path.exists():
            raise FileExistsError("refusing to overwrite frozen resource or manifest")
        resource_temp = _stage_rows(resource_path, rows)
        manifest["frozen_resource_sha256"] = sha256_file(resource_temp)
        manifest_temp = _stage_rows(manifest_path, [manifest])
        os.link(resource_temp, resource_path)
        published_resource = True
        resource_temp.unlink(missing_ok=True)
        resource_temp = None
        os.link(manifest_temp, manifest_path)
        manifest_temp.unlink(missing_ok=True)
        manifest_temp = None
        return manifest
    except Exception:
        if published_resource:
            resource_path.unlink(missing_ok=True)
        raise
    finally:
        if resource_temp is not None:
            resource_temp.unlink(missing_ok=True)
        if manifest_temp is not None:
            manifest_temp.unlink(missing_ok=True)
        lock_path.unlink(missing_ok=True)


def freeze_morphology(
    input_path: Path,
    resource_path: Path,
    manifest_path: Path,
    *,
    reviewer: str,
    reviewed_at: str,
    source_resource: str,
    source_version: str,
    license_text: str,
    mapping_rule_version: str,
    mapping_rule_artifact: Path | None = None,
    minimum_validated_states: int = 3,
) -> dict[str, Any]:
    """Freeze only explicitly approved, manually reviewed morphology rows."""
    if not reviewer.strip() or not reviewed_at.strip() or not source_resource.strip() or not source_version.strip() or not license_text.strip() or not mapping_rule_version.strip():
        raise ValueError("reviewer, reviewed_at, provenance, license, and mapping-rule metadata are required")
    try:
        datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("reviewed_at must be ISO-8601") from error
    if minimum_validated_states < 1:
        raise ValueError("minimum_validated_states must be >= 1")
    rows = _read_jsonl(input_path)
    if not rows:
        raise ValueError("reviewed morphology input is empty")
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    surface_lemmas: dict[str, str] = {}
    states_by_lemma: defaultdict[str, set[str]] = defaultdict(set)
    for index, row in enumerate(rows, 1):
        if row.get("review_status") != "approved":
            raise ValueError(f"row {index} is not explicitly approved")
        lemma = str(row.get("lemma", "")).strip()
        surface = str(row.get("surface", "")).strip()
        state = str(row.get("balarila_state", row.get("balarila_state_candidate", ""))).strip().upper()
        if not lemma or not surface or not state:
            raise ValueError(f"row {index} is missing lemma/surface/state")
        state_by_id(state)
        if row.get("confidence") not in {None, "reviewed", "high"}:
            raise ValueError(f"row {index} has non-reviewed confidence")
        key = (lemma, surface)
        if key in seen:
            raise ValueError(f"duplicate morphology surface: {lemma}/{surface}")
        seen.add(key)
        previous_lemma = surface_lemmas.get(surface)
        if previous_lemma is not None and previous_lemma != lemma:
            raise ValueError(f"homographic morphology surface requires contextual review: {surface!r} ({previous_lemma}, {lemma})")
        surface_lemmas[surface] = lemma
        states_by_lemma[lemma].add(state)
        normalized.append({
            "lemma": lemma,
            "surface": surface,
            "balarila_state": state,
            "aspect": row.get("aspect"),
            "focus": row.get("focus"),
            "source_resource": source_resource,
            "source_features": row.get("unimorph_features", row.get("source_features")),
            "confidence": "reviewed",
            "review_status": "approved",
        })
    enabled = {lemma for lemma, values in states_by_lemma.items() if len(values) >= minimum_validated_states}
    if not enabled:
        raise ValueError("no lemma satisfies the minimum validated sibling-state requirement")
    normalized = [row for row in normalized if row["lemma"] in enabled]
    if not normalized:
        raise ValueError("no approved rows remain after minimum-state filtering")
    if mapping_rule_artifact is None or not mapping_rule_artifact.is_file():
        raise ValueError("mapping_rule_artifact is required and must exist for an approved morphology freeze")
    manifest = {
        "schema_version": 1,
        "resource_version": "tagalog-verb-paradigms-v1",
        "source_resource": source_resource,
        "source_resource_version": source_version,
        "source_input_sha256": sha256_file(input_path),
        "license": license_text,
        "mapping_rule_version": mapping_rule_version,
        "mapping_rule_artifact": str(mapping_rule_artifact.resolve()),
        "mapping_rule_artifact_sha256": sha256_file(mapping_rule_artifact),
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "minimum_validated_states_per_lemma": minimum_validated_states,
        "row_count": len(normalized),
        "lemma_count": len(enabled),
        "state_counts": dict(sorted(Counter(row["balarila_state"] for row in normalized).items())),
        "frozen_resource": str(resource_path),
        "approved_only": True,
    }
    return _publish_pair(input_path, resource_path, manifest_path, normalized, manifest)


def freeze_constructions(
    input_path: Path,
    resource_path: Path,
    manifest_path: Path,
    *,
    reviewer: str,
    reviewed_at: str,
    source_resource: str,
    source_version: str,
    license_text: str,
) -> dict[str, Any]:
    """Freeze approved hyphen/spacing constructions without inventing rules."""
    if not all(item.strip() for item in (reviewer, reviewed_at, source_resource, source_version, license_text)):
        raise ValueError("reviewer, reviewed_at, source, version, and license are required")
    try:
        datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("reviewed_at must be ISO-8601") from error
    rows = _read_jsonl(input_path)
    if not rows:
        raise ValueError("reviewed construction input is empty")
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, row in enumerate(rows, 1):
        if row.get("review_status") != "approved":
            raise ValueError(f"row {index} is not explicitly approved")
        required = ("correct_surface", "generated_wrong_surface", "correction_tag", "family")
        if not all(str(row.get(field, "")).strip() for field in required):
            raise ValueError(f"row {index} is missing construction fields")
        if row["family"] not in {"hyphen", "space"}:
            raise ValueError(f"row {index} has unsupported construction family")
        require_registered(str(row["correction_tag"]))
        tag = str(row["correction_tag"])
        from .tags import registry
        matching = next(item for item in registry() if item.id == tag)
        if matching.family != row["family"]:
            raise ValueError(f"row {index} correction_tag/family mismatch")
        correct = str(row["correct_surface"])
        wrong = str(row["generated_wrong_surface"])
        if correct == wrong:
            raise ValueError(f"row {index} source and target construction are identical")
        key = (correct, wrong, tag)
        if key in seen:
            raise ValueError(f"duplicate construction record at row {index}")
        seen.add(key)
        normalized.append({
            "correct_surface": correct,
            "generated_wrong_surface": wrong,
            "correction_tag": tag,
            "family": str(row["family"]),
            "review_status": "approved",
            "resource_version": "filipino-constructions-v1",
            "notes": row.get("notes"),
        })
    manifest = {
        "schema_version": 1,
        "resource_version": "filipino-constructions-v1",
        "source_resource": source_resource,
        "source_resource_version": source_version,
        "source_input_sha256": sha256_file(input_path),
        "license": license_text,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "row_count": len(normalized),
        "family_counts": dict(sorted(Counter(row["family"] for row in normalized).items())),
        "frozen_resource": str(resource_path),
        "approved_only": True,
    }
    return _publish_pair(input_path, resource_path, manifest_path, normalized, manifest)


def freeze_punctuation_context(
    input_path: Path,
    resource_path: Path,
    manifest_path: Path,
    *,
    reviewer: str,
    reviewed_at: str,
    source_resource: str,
    source_version: str,
    license_text: str,
) -> dict[str, Any]:
    """Freeze explicitly reviewed punctuation-substitution contexts."""
    if not all(item.strip() for item in (reviewer, reviewed_at, source_resource, source_version, license_text)):
        raise ValueError("reviewer, reviewed_at, source, version, and license are required")
    try:
        datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("reviewed_at must be ISO-8601") from error
    rows = _read_jsonl(input_path)
    if not rows:
        raise ValueError("reviewed punctuation input is empty")
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    expected_surface = {
        "$CHANGE_PUNC_PERIOD": ".",
        "$CHANGE_PUNC_QMARK": "?",
        "$CHANGE_PUNC_EMARK": "!",
    }
    for index, row in enumerate(rows, 1):
        if row.get("review_status") != "approved":
            raise ValueError(f"row {index} is not explicitly approved")
        required = ("context", "correct_surface", "generated_wrong_surface", "correction_tag")
        if not all(str(row.get(field, "")).strip() for field in required):
            raise ValueError(f"row {index} is missing punctuation context fields")
        tag = str(row["correction_tag"])
        matching = next((item for item in registry() if item.id == tag), None)
        if matching is None or matching.family != "punctuation" or not tag.startswith("$CHANGE_PUNC_"):
            raise ValueError(f"row {index} must use a registered CHANGE_PUNC tag")
        context = str(row["context"]).strip()
        correct = _reviewed_terminal_mark(context, row["correct_surface"])
        wrong = _reviewed_terminal_mark(context, row["generated_wrong_surface"])
        if context.endswith((".", "?", "!")):
            raise ValueError(f"row {index} context must exclude terminal punctuation")
        if correct is None or wrong is None:
            raise ValueError(f"row {index} must contain one valid terminal punctuation character per surface")
        if correct == wrong or correct != expected_surface[tag]:
            raise ValueError(f"row {index} correct punctuation is inconsistent with correction_tag")
        # The context is stored separately and is shared byte-for-byte by the
        # correct and generated-wrong patterns.  Thus the only lexical change
        # possible in a production candidate is this one terminal character.
        key = (context, correct, wrong, tag)
        if key in seen:
            raise ValueError(f"duplicate punctuation context at row {index}")
        seen.add(key)
        normalized.append({
            "context": context,
            "correct_surface": correct,
            "generated_wrong_surface": wrong,
            "correction_tag": tag,
            "family": "punctuation",
            "review_status": "approved",
            "resource_version": "filipino-punctuation-context-v1",
            "notes": row.get("notes"),
        })
    manifest = {
        "schema_version": 1,
        "resource_version": "filipino-punctuation-context-v1",
        "source_resource": source_resource,
        "source_resource_version": source_version,
        "source_input_sha256": sha256_file(input_path),
        "license": license_text,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "row_count": len(normalized),
        "tag_counts": dict(sorted(Counter(row["correction_tag"] for row in normalized).items())),
        "frozen_resource": str(resource_path),
        "approved_only": True,
    }
    return _publish_pair(input_path, resource_path, manifest_path, normalized, manifest)


def load_frozen_jsonl(resource_path: Path, manifest_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not resource_path.is_file() or not manifest_path.is_file():
        return [], {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("resource_version"), str) or not manifest.get("resource_version", "").strip():
        raise ValueError(f"frozen resource manifest is missing resource_version: {manifest_path}")
    if manifest.get("frozen_resource_sha256") != sha256_file(resource_path) or manifest.get("approved_only") is not True:
        raise ValueError(f"frozen resource hash/approval mismatch: {resource_path}")
    if resource_path.suffix.lower() == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as error:  # pragma: no cover - optional data dependency
            raise RuntimeError("Parquet resource loading requires pyarrow") from error
        rows = pq.read_table(resource_path).to_pylist()
    else:
        rows = _read_jsonl(resource_path)
    if any(row.get("review_status") != "approved" for row in rows):
        raise ValueError(f"frozen resource contains unapproved rows: {resource_path}")
    return rows, manifest
