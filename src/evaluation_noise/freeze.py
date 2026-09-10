"""Dependency-gated freeze operation for the end-to-end evaluation set."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import EvaluationValidationError, load_records_bytes, validate_dataset
from src.geg.artifacts import validate_destinations


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_path(path: Path) -> str:
    """Hash a file or a deterministic directory manifest."""

    if path.is_file():
        return _hash(path)
    if path.is_dir():
        digest = hashlib.sha256()
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            digest.update(str(child.relative_to(path)).replace("\\", "/").encode("utf-8"))
            digest.update(_hash(child).encode("ascii"))
        return digest.hexdigest()
    raise FileNotFoundError(path)


def _dependency_entries(*, informal_path: Path, controls_path: Path, rule_inventory_path: Path, gec_train: Path | None, gec_dev: Path | None, normalizer_train: Path | None) -> list[tuple[str, Path]]:
    entries = [
        ("informal_jsonl", informal_path),
        ("controls_jsonl", controls_path),
        ("rule_inventory", rule_inventory_path),
    ]
    if gec_train is not None:
        entries.append(("gec_train", gec_train))
    if gec_dev is not None:
        entries.append(("gec_dev", gec_dev))
    if normalizer_train is not None:
        entries.append(("normalizer_train", normalizer_train))
    return entries


def _snapshot(entries: list[tuple[str, Path]]) -> dict[str, str]:
    return {name: _hash_path(path) for name, path in entries}


def _set_dependency_hashes(result: dict[str, Any], hashes: dict[str, str]) -> None:
    dependencies = result["dependencies"]
    for name, digest in hashes.items():
        dependencies[f"{name}_sha256"] = digest


def _write_blocker(path: Path | None, reason: str) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": "filly-evaluation-freeze-v1", "status": "blocked", "reason": reason}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def freeze_evaluation(*, informal_path: Path, controls_path: Path, rule_inventory_path: Path, output_path: Path, gec_train: Path | None = None, gec_dev: Path | None = None, normalizer_train: Path | None = None, blocked_report: Path | None = None, require_full_composition: bool = True) -> dict[str, Any]:
    """Validate and atomically write a frozen manifest.

    The output is a JSON manifest containing hashes and the validated rows;
    no output file is created when a dependency or validation check fails.
    """

    destinations = {"frozen_output": output_path}
    if blocked_report is not None:
        destinations["blocked_report"] = blocked_report
    inputs = {
        "informal": informal_path,
        "controls": controls_path,
        "rule_inventory": rule_inventory_path,
    }
    if gec_train is not None:
        inputs["gec_train"] = gec_train
    if gec_dev is not None:
        inputs["gec_dev"] = gec_dev
    if normalizer_train is not None:
        inputs["normalizer_train"] = normalizer_train
    validate_destinations(inputs, destinations)
    result: dict[str, Any]
    try:
        if not informal_path.exists():
            raise EvaluationValidationError(f"authentic/controlled input does not exist: {informal_path}")
        if not controls_path.exists():
            raise EvaluationValidationError(f"clean-control input does not exist: {controls_path}")
        if not rule_inventory_path.exists():
            raise EvaluationValidationError(f"frozen normalizer-rule inventory does not exist: {rule_inventory_path}")
        if require_full_composition and gec_train is None:
            raise EvaluationValidationError("production freeze requires a GEC train manifest/view")
        if require_full_composition and gec_dev is None:
            raise EvaluationValidationError("production freeze requires a GEC dev manifest/view")
        if require_full_composition and normalizer_train is None:
            raise EvaluationValidationError("production freeze requires normalizer-example training data")
        for dependency_name, dependency in (("GEC train", gec_train), ("GEC dev", gec_dev), ("normalizer-example training", normalizer_train)):
            if dependency is not None and not dependency.exists():
                raise EvaluationValidationError(f"{dependency_name} dependency does not exist: {dependency}")
        entries = _dependency_entries(informal_path=informal_path, controls_path=controls_path, rule_inventory_path=rule_inventory_path, gec_train=gec_train, gec_dev=gec_dev, normalizer_train=normalizer_train)
        before_hashes = _snapshot(entries)
        # Keep the small JSONL/JSON inputs as immutable byte snapshots for
        # parsing; a later hash check catches any mutation of dependencies
        # consulted by validation.
        informal_bytes = informal_path.read_bytes()
        controls_bytes = controls_path.read_bytes()
        rule_bytes = rule_inventory_path.read_bytes()
        records = load_records_bytes(informal_bytes, source=str(informal_path))
        controls = load_records_bytes(controls_bytes, source=str(controls_path))
        inventory = json.loads(rule_bytes.decode("utf-8"))
        summary = validate_dataset(records, inventory, clean_controls=controls, gec_train=gec_train, gec_dev=gec_dev, normalizer_train=normalizer_train, require_full_composition=require_full_composition)
        result = {
            "schema_version": "filly-evaluation-freeze-v1",
            "status": "frozen",
            "frozen_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "summary": summary.as_dict(),
            "dependencies": {
                "informal_jsonl": str(informal_path.resolve()),
                "informal_sha256": before_hashes["informal_jsonl"],
                "controls_jsonl": str(controls_path.resolve()),
                "controls_sha256": before_hashes["controls_jsonl"],
                "rule_inventory": str(rule_inventory_path.resolve()),
                "rule_inventory_sha256": before_hashes["rule_inventory"],
                "gec_train": str(gec_train.resolve()) if gec_train else None,
                "gec_train_sha256": before_hashes.get("gec_train"),
                "gec_dev": str(gec_dev.resolve()) if gec_dev else None,
                "gec_dev_sha256": before_hashes.get("gec_dev"),
                "normalizer_train": str(normalizer_train.resolve()) if normalizer_train else None,
                "normalizer_train_sha256": before_hashes.get("normalizer_train"),
            },
            "informal_rows": records,
            "clean_control_rows": controls,
        }
    except (EvaluationValidationError, OSError, json.JSONDecodeError, TypeError, ValueError, AttributeError) as error:
        result = {"schema_version": "filly-evaluation-freeze-v1", "status": "blocked", "reason": str(error)}
        _write_blocker(blocked_report, str(error))
        raise EvaluationValidationError(str(error)) from error
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = output_path.with_suffix(output_path.suffix + ".lock")
    lock_fd: int | None = None
    lock_owned = False
    temp_path: Path | None = None
    try:
        try:
            lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            lock_owned = True
        except FileExistsError as error:
            raise FileExistsError(f"freeze publication lock already exists: {lock_path}") from error
        if output_path.exists():
            raise FileExistsError(f"refusing to overwrite frozen evaluation: {output_path}")
        try:
            current_hashes = _snapshot(entries)
        except OSError as error:
            reason = f"freeze dependency changed after validation: {error}"
            _write_blocker(blocked_report, reason)
            raise EvaluationValidationError(reason) from error
        if current_hashes != before_hashes:
            reason = "freeze dependency changed after validation"
            _write_blocker(blocked_report, reason)
            raise EvaluationValidationError(reason)
        _set_dependency_hashes(result, current_hashes)
        temp_fd, temp_name = tempfile.mkstemp(prefix=f".{output_path.name}.", suffix=".tmp", dir=str(output_path.parent))
        temp_path = Path(temp_name)
        payload = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        with os.fdopen(temp_fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            publish_hashes = _snapshot(entries)
        except OSError as error:
            reason = f"freeze dependency changed immediately before publication: {error}"
            _write_blocker(blocked_report, reason)
            raise EvaluationValidationError(reason) from error
        if publish_hashes != current_hashes:
            reason = "freeze dependency changed immediately before publication"
            _write_blocker(blocked_report, reason)
            raise EvaluationValidationError(reason)
        # Hard-link publication is atomic and refuses to replace a concurrent
        # winner, unlike os.replace().
        os.link(str(temp_path), str(output_path))
        temp_path.unlink()
        temp_path = None
        return result
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
        if lock_fd is not None:
            os.close(lock_fd)
        if lock_owned and lock_path.exists():
            lock_path.unlink()
