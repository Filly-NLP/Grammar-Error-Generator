"""Dependency-light configuration loading and hashing."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any


SPLITS = ("train", "dev", "synthetic_test")


def load_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as error:
            raise RuntimeError(
                "configuration is YAML; install PyYAML or keep config/filly.yaml JSON-compatible"
            ) from error
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"configuration root must be an object: {path}")
    return value


def config_hash(config: dict[str, Any]) -> str:
    canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as error:
        raise ValueError(f"{field} must be a decimal ratio") from error
    if not result.is_finite() or result < 0 or result > 1:
        raise ValueError(f"{field} must be between 0 and 1")
    return result


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate construction settings before any artifact can be written.

    The returned copy is JSON-compatible and retains the operator's values;
    Decimal conversion is applied by :func:`resolve_runtime_config` so config
    hashes remain stable and human-readable.
    """
    if not isinstance(config, dict):
        raise ValueError("configuration root must be an object")
    value = deepcopy(config)
    project = value.get("project", {})
    dataset = value.get("dataset", {})
    splits = value.get("splits", {})
    stages = value.get("stage_views", {})
    phase9 = value.get("phase9", {})
    morphology = value.get("morphology", {})
    total = int(dataset.get("target_total_pairs", 0))
    if total <= 0:
        raise ValueError("dataset.target_total_pairs must be positive")
    mode = str(dataset.get("counting_mode", "balarila_total"))
    if mode not in {"balarila_total", "errorful_only"}:
        raise ValueError(f"unsupported dataset.counting_mode={mode!r}")
    errorful = _decimal(dataset.get("errorful_fraction", 1 if mode == "errorful_only" else "0.83"), "dataset.errorful_fraction")
    identity = _decimal(dataset.get("identity_fraction", 0 if mode == "errorful_only" else "0.17"), "dataset.identity_fraction")
    if mode == "balarila_total" and errorful + identity != Decimal("1"):
        raise ValueError("dataset.errorful_fraction + dataset.identity_fraction must equal 1")
    if mode == "errorful_only" and identity != 0:
        raise ValueError("dataset.identity_fraction must be 0 in errorful_only mode")
    split_values = {split: _decimal(splits.get(split), f"splits.{split}") for split in SPLITS}
    if any(value <= 0 for value in split_values.values()):
        raise ValueError("train/dev/synthetic_test split fractions must be positive")
    if sum(split_values.values(), Decimal("0")) != Decimal("1"):
        raise ValueError("train/dev/synthetic_test split fractions must sum to 1")
    stage1 = _decimal(stages.get("dataset1_errorful_share", "0.80"), "stage_views.dataset1_errorful_share")
    stage2 = _decimal(stages.get("dataset2_errorful_share", "0.20"), "stage_views.dataset2_errorful_share")
    if stage1 + stage2 != Decimal("1"):
        raise ValueError("stage errorful shares must sum to 1")
    if not isinstance(phase9, dict):
        raise ValueError("phase9 must be an object")
    try:
        candidate_buffer = Decimal(str(phase9.get("candidate_buffer_ratio", "1.0")))
    except Exception as error:
        raise ValueError("phase9.candidate_buffer_ratio must be a decimal ratio") from error
    if not candidate_buffer.is_finite() or candidate_buffer < Decimal("1"):
        raise ValueError("phase9.candidate_buffer_ratio must be >= 1")
    if int(morphology.get("minimum_validated_states_per_lemma", 0)) < 1:
        raise ValueError("morphology.minimum_validated_states_per_lemma must be >= 1")
    try:
        from .tags import registry
        expected_tags = len(registry())
    except Exception:
        expected_tags = int(value.get("balarila", {}).get("table2_tag_count", 39))
    if int(value.get("balarila", {}).get("table2_tag_count", expected_tags)) != expected_tags:
        raise ValueError("balarila.table2_tag_count does not match the registered tag inventory")
    if "seed" not in project:
        raise ValueError("project.seed is required as the single source of truth")
    int(project["seed"])
    return value


def resolve_runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return validated settings with effective Decimal ratios and seed."""
    value = validate_config(config)
    dataset = value["dataset"]
    splits = value["splits"]
    stages = value["stage_views"]
    phase9 = value.get("phase9", {})
    candidate_buffer = Decimal(str(phase9.get("candidate_buffer_ratio", "1.0")))
    value["runtime"] = {
        "seed": int(value["project"]["seed"]),
        "split_fractions": {split: str(_decimal(splits[split], f"splits.{split}")) for split in SPLITS},
        "errorful_fraction": str(_decimal(dataset.get("errorful_fraction", 1), "dataset.errorful_fraction")),
        "identity_fraction": str(_decimal(dataset.get("identity_fraction", 0), "dataset.identity_fraction")),
        "dataset1_errorful_share": str(_decimal(stages["dataset1_errorful_share"], "stage_views.dataset1_errorful_share")),
        "dataset2_errorful_share": str(_decimal(stages["dataset2_errorful_share"], "stage_views.dataset2_errorful_share")),
        "group_by_document": bool(value.get("splits", {}).get("group_by_document", True)),
        "candidate_buffer_ratio": str(candidate_buffer),
    }
    # Keep a short alias for callers that need resolved values while keeping
    # the original config tree intact for hashing and provenance.
    value["splits"] = {**value["splits"], **value["runtime"]["split_fractions"]}
    return value
