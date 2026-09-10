"""Deterministic reports for the frozen synthetic GEC test split."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .hashing import sha256_file
from .artifacts import validate_destinations
from .tags import registry


def _json_field(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default if value is None else value


def _length_bucket(text: str) -> str:
    count = len(str(text).split())
    if count < 10:
        return "0-9"
    if count < 20:
        return "10-19"
    if count < 30:
        return "20-29"
    if count < 50:
        return "30-49"
    return "50+"


def _all_families() -> list[str]:
    return list(dict.fromkeys(tag.family for tag in registry()))


def _manifest_output_hash(manifest: Mapping[str, Any], input_path: Path) -> str | None:
    outputs = manifest.get("outputs", {})
    if not isinstance(outputs, Mapping):
        return None
    candidates = [
        "synthetic_test/final.parquet",
        str(input_path).replace("\\", "/"),
        input_path.name,
    ]
    for key in candidates:
        item = outputs.get(key)
        if isinstance(item, Mapping) and item.get("sha256"):
            return str(item["sha256"])
    for key, item in outputs.items():
        if str(key).endswith("synthetic_test/final.parquet") and isinstance(item, Mapping):
            return str(item.get("sha256"))
    return None


def validate_synthetic_test_provenance(input_path: Path, manifest_path: Path) -> dict[str, Any]:
    """Validate that a synthetic-test artifact is the final manifest output."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"missing or invalid final dataset manifest: {manifest_path}") from error
    if manifest.get("status") != "complete":
        raise RuntimeError("final dataset manifest is not complete")
    expected = _manifest_output_hash(manifest, input_path)
    actual = sha256_file(input_path)
    if expected != actual:
        raise RuntimeError("synthetic-test artifact hash does not match final dataset manifest")
    split_counts = manifest.get("split_counts", {})
    if "synthetic_test" not in split_counts:
        raise RuntimeError("final dataset manifest lacks synthetic_test split count")
    return manifest


def build_synthetic_test_diagnostics(
    input_path: Path,
    json_report: Path,
    markdown_report: Path,
    *,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Create machine-readable and Markdown diagnostics for synthetic test.

    ``manifest_path`` is required for a frozen production report.  It is
    optional for development fixtures, but when supplied the row artifact must
    match the final manifest hash exactly.
    """
    try:
        import pyarrow.parquet as pq
    except ImportError as error:  # pragma: no cover
        raise RuntimeError("synthetic diagnostics require pyarrow") from error
    input_path = input_path.resolve()
    manifest_resolved = manifest_path.resolve() if manifest_path else None
    output_json = json_report
    output_markdown = markdown_report
    for destination in (output_json, output_markdown):
        # Path.resolve() follows a dangling leaf symlink; refuse the original
        # leaf explicitly so publication can never overwrite an unintended
        # target through a symlink.
        if destination.is_symlink():
            raise ValueError(f"diagnostic output leaf must not be a symlink: {destination}")
    validate_destinations(
        {"input": input_path, **({"manifest": manifest_resolved} if manifest_resolved else {})},
        {"json_report": output_json, "markdown_report": output_markdown},
    )
    manifest = validate_synthetic_test_provenance(input_path, manifest_resolved) if manifest_resolved else None
    tag_counts = Counter({tag.id: 0 for tag in registry()})
    family_counts = Counter({family: 0 for family in _all_families()})
    lengths = Counter({bucket: 0 for bucket in ("0-9", "10-19", "20-29", "30-49", "50+")})
    publishers: Counter[str] = Counter()
    publisher_errorful: Counter[str] = Counter()
    publisher_identity: Counter[str] = Counter()
    transitions: Counter[str] = Counter()
    total = errorful = identity = 0
    with pq.ParquetFile(input_path) as parquet:
        required = {"source_text", "target_text", "is_errorful", "correction_tags", "error_families", "publisher"}
        missing = sorted(required - set(parquet.schema_arrow.names))
        if missing:
            raise RuntimeError(f"synthetic-test artifact missing required columns: {missing}")
        for batch in parquet.iter_batches():
            rows = batch.to_pylist()
            for row in rows:
                total += 1
                is_errorful = bool(row.get("is_errorful"))
                if is_errorful:
                    errorful += 1
                    publisher_errorful[str(row.get("publisher") or "<unknown>")] += 1
                else:
                    identity += 1
                    publisher_identity[str(row.get("publisher") or "<unknown>")] += 1
                lengths[_length_bucket(str(row.get("target_text", row.get("source_text", ""))))] += 1
                publishers[str(row.get("publisher") or "<unknown>")] += 1
                tags = _json_field(row.get("correction_tags"), []) or []
                families = _json_field(row.get("error_families"), []) or []
                for tag in tags:
                    if str(tag) not in tag_counts:
                        raise RuntimeError(f"synthetic-test row contains unknown correction tag: {tag}")
                    tag_counts[str(tag)] += 1
                for family in families:
                    if str(family) not in family_counts:
                        raise RuntimeError(f"synthetic-test row contains unknown error family: {family}")
                    family_counts[str(family)] += 1
                source_state = row.get("morphology_source_state")
                target_state = row.get("morphology_target_state")
                is_morphology = any(str(tag).startswith("$TRANSFORM_VERB_") for tag in tags)
                if is_morphology and (not source_state or not target_state):
                    raise RuntimeError("morphology row lacks source/target state provenance")
                if not is_morphology and (source_state or target_state or row.get("morphology_lemma") or row.get("morphology_resource_version")):
                    raise RuntimeError("non-morphology row contains morphology provenance")
                if source_state and target_state:
                    transitions[f"{source_state} -> {target_state}"] += 1
    if errorful + identity != total:
        raise RuntimeError("synthetic-test errorful/identity counts do not sum to total")
    if errorful and sum(tag_counts.values()) != errorful:
        raise RuntimeError("synthetic-test tag counts do not match errorful row count")
    if errorful and sum(family_counts.values()) != errorful:
        raise RuntimeError("synthetic-test family counts do not match errorful row count")
    report: dict[str, Any] = {
        "status": "complete",
        "input": str(input_path),
        "input_sha256": sha256_file(input_path),
        "manifest": str(manifest_path.resolve()) if manifest_path else None,
        "manifest_sha256": sha256_file(manifest_path.resolve()) if manifest_path else None,
        "total_rows": total,
        "errorful_rows": errorful,
        "identity_rows": identity,
        "tag_counts_all_39": dict(tag_counts),
        "family_counts_all_10": dict(family_counts),
        "sentence_length_buckets": dict(lengths),
        "publisher_counts": dict(sorted(publishers.items())),
        "publisher_distribution": {
            publisher: {
                "total": publishers[publisher],
                "errorful": publisher_errorful[publisher],
                "identity": publisher_identity[publisher],
            }
            for publisher in sorted(publishers)
        },
        "morphology_transition_counts": dict(sorted(transitions.items())),
        "config_hash": manifest.get("config_hash") if manifest else None,
        "generator_dependency_hash": (manifest.get("candidate_generator_sha256") or manifest.get("generator_dependency_hash")) if manifest else None,
        "dataset_builder_version": manifest.get("builder_version") if manifest else None,
    }
    if manifest is not None and total != int(manifest["split_counts"]["synthetic_test"]):
        raise RuntimeError(
            "synthetic-test row count does not match final dataset manifest: "
            f"{total} != {manifest['split_counts']['synthetic_test']}"
        )
    if output_json.exists() or output_markdown.exists():
        raise FileExistsError("refusing to overwrite existing synthetic diagnostics")
    lines = [
        "# Synthetic-test diagnostics", "",
        f"- Rows: **{total}**", f"- Errorful: **{errorful}**", f"- Identity: **{identity}**",
        f"- Input SHA-256: `{report['input_sha256']}`", "", "## Tag counts", "",
        "| Tag | Rows |", "|---|---:|",
    ]
    lines.extend(f"| {tag} | {count} |" for tag, count in tag_counts.items())
    lines.extend(["", "## Error families", "", "| Family | Rows |", "|---|---:|"])
    lines.extend(f"| {family} | {count} |" for family, count in family_counts.items())
    lines.extend(["", "## Sentence length", "", "| Bucket | Rows |", "|---|---:|"])
    lines.extend(f"| {bucket} | {count} |" for bucket, count in lengths.items())
    lines.extend(["", "## Publisher Distribution", "", "| Publisher | Total | Share | Errorful | Identity |", "|---|---:|---:|---:|---:|"])
    for publisher, count in sorted(publishers.items(), key=lambda item: (-item[1], item[0])):
        share = (count / total) if total else 0.0
        lines.append(f"| {publisher} | {count} | {share:.4f} | {publisher_errorful[publisher]} | {publisher_identity[publisher]} |")
    lines.extend(["", "## Morphology transitions", "", "| Transition | Rows |", "|---|---:|"])
    lines.extend(f"| {key} | {count} |" for key, count in sorted(transitions.items()))
    # Publish both reports through unique temporary siblings under exclusive
    # locks.  If the second rename fails, remove the first publication too;
    # callers never observe a half-published diagnostics pair.
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    lock_paths = [Path(str(output_json) + ".lock"), Path(str(output_markdown) + ".lock")]
    temp_paths: list[Path] = []
    published: list[tuple[Path, Path]] = []
    try:
        for lock in lock_paths:
            if lock.exists() or lock.is_symlink():
                raise FileExistsError(f"diagnostic output is locked: {lock}")
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        for destination, content in (
            (output_json, json.dumps(report, ensure_ascii=False, indent=2) + "\n"),
            (output_markdown, "\n".join(lines) + "\n"),
        ):
            temp_dir = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=str(destination.parent)))
            temp_path = temp_dir / destination.name
            temp_path.write_text(content, encoding="utf-8", newline="\n")
            with temp_path.open("r+b") as stream:
                os.fsync(stream.fileno())
            temp_paths.append(temp_path)
        for temp_path, destination in zip(temp_paths, (output_json, output_markdown)):
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(f"refusing to overwrite diagnostic output: {destination}")
            # ``link`` is create-new: unlike os.replace, it cannot overwrite
            # a destination won by another process between the preflight and
            # publication. The temporary hard link is removed during cleanup.
            os.link(str(temp_path), str(destination))
            published.append((destination, temp_path))
    except Exception:
        for destination, temp_path in published:
            try:
                if destination.exists() and temp_path.exists() and destination.samefile(temp_path):
                    destination.unlink()
            except (FileNotFoundError, OSError):
                pass
        raise
    finally:
        for temp_path in temp_paths:
            shutil.rmtree(temp_path.parent, ignore_errors=True)
        for lock in lock_paths:
            try:
                lock.unlink()
            except FileNotFoundError:
                pass
    return report
