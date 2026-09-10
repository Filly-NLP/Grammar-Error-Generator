"""Shared Phase 9/10 dataset arithmetic and row invariants."""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Iterable

from .alignment import validate_replay
from .tags import validate_tags


SPLITS = ("train", "dev", "synthetic_test")
SPLIT_FRACTIONS = {"train": Decimal("0.70"), "dev": Decimal("0.15"), "synthetic_test": Decimal("0.15")}


def largest_remainder(total: int, fractions: dict[str, Decimal]) -> dict[str, int]:
    """Allocate an integer total without floating-point rounding drift."""

    if total < 0:
        raise ValueError("total must be non-negative")
    raw = {key: Decimal(total) * value for key, value in fractions.items()}
    result = {key: int(value.to_integral_value(rounding=ROUND_FLOOR)) for key, value in raw.items()}
    missing = total - sum(result.values())
    order = sorted(fractions, key=lambda key: (-(raw[key] - result[key]), tuple(fractions).index(key)))
    for key in order[:missing]:
        result[key] += 1
    return result


def total_composition(config: dict[str, Any]) -> dict[str, int]:
    dataset = config.get("dataset", {})
    total = int(dataset.get("target_total_pairs", 1_000_000))
    mode = str(dataset.get("counting_mode", "balarila_total"))
    if mode == "errorful_only":
        return {"total": total, "errorful": total, "identity": 0}
    if mode != "balarila_total":
        raise ValueError(f"unsupported dataset.counting_mode={mode!r}")
    errorful_fraction = Decimal(str(dataset.get("errorful_fraction", "0.83")))
    errorful = int((Decimal(total) * errorful_fraction).to_integral_value(rounding=ROUND_FLOOR))
    return {"total": total, "errorful": errorful, "identity": total - errorful}


def split_composition(total: int) -> dict[str, int]:
    return largest_remainder(total, SPLIT_FRACTIONS)


def stage_composition(errorful_total: int, identity_total: int, errorful_share: Decimal = Decimal("0.80")) -> dict[str, int]:
    stage1 = int((Decimal(errorful_total) * errorful_share).to_integral_value(rounding=ROUND_FLOOR))
    return {
        "dataset1_errorful": stage1,
        "dataset2_errorful": errorful_total - stage1,
        "dataset2_identity": identity_total,
        "dataset1_total": stage1,
        "dataset2_total": errorful_total - stage1 + identity_total,
    }


def bounded_quotas(capacities: dict[str, int], target: int) -> dict[str, int]:
    """Allocate a target across tags without exceeding observed capacity."""

    if target < 0 or any(value < 0 for value in capacities.values()):
        raise ValueError("target and capacities must be non-negative")
    total_capacity = sum(capacities.values())
    if total_capacity < target:
        raise ValueError(f"candidate capacity shortfall: {total_capacity} < {target}")
    if target == 0:
        return {key: 0 for key in capacities}
    raw = {key: Decimal(target) * Decimal(value) / Decimal(total_capacity) for key, value in capacities.items()}
    result = {key: min(capacities[key], int(value.to_integral_value(rounding=ROUND_FLOOR))) for key, value in raw.items()}
    missing = target - sum(result.values())
    while missing:
        choices = [key for key in capacities if result[key] < capacities[key]]
        if not choices:
            raise ValueError("unable to satisfy bounded quota")
        choices.sort(key=lambda key: (-(raw[key] - result[key]), key))
        for key in choices:
            if missing == 0:
                break
            result[key] += 1
            missing -= 1
    return result


def parse_json_field(value: Any, field: str) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"{field} is not valid JSON") from error
    return value


def validate_candidate_row(row: dict[str, Any], *, known_pair_keys: set[tuple[str, str]] | None = None) -> tuple[str, str] | None:
    """Validate one Phase 9 candidate; return its exact output-pair key."""

    split = str(row.get("split", ""))
    if split not in SPLITS:
        raise ValueError(f"unknown split: {split!r}")
    if not row.get("pair_id") or not row.get("clean_id"):
        raise ValueError("candidate is missing pair_id or clean_id")
    source = str(row.get("source_text", ""))
    target = str(row.get("target_text", ""))
    if not source or not target or source == target:
        raise ValueError("errorful candidate must have distinct non-empty source and target")
    if row.get("is_errorful") is not True or int(row.get("num_errors", 0)) != 1:
        raise ValueError("candidate must be one errorful operation")
    tags = parse_json_field(row.get("correction_tags", []), "correction_tags")
    if not isinstance(tags, list) or len(tags) != 1:
        raise ValueError("candidate must contain exactly one correction tag")
    validate_tags([str(tags[0])])
    operation = parse_json_field(row.get("generation_operation", {}), "generation_operation")
    if not isinstance(operation, dict):
        raise ValueError("generation_operation must be an object")
    replay = validate_replay(source, target, operation)
    if not replay.success or replay.replayed_target != target:
        raise ValueError(f"candidate replay failed: {replay.reason}")
    if row.get("alignment_success") is not True:
        raise ValueError("candidate alignment_success must be true")
    for field, expected in (("source_spans", replay.source_spans), ("target_spans", replay.target_spans)):
        recorded = parse_json_field(row.get(field, []), field)
        if recorded != list(expected):
            raise ValueError(f"{field} does not match replay-derived spans")
    key = (source, target)
    if known_pair_keys is not None and key in known_pair_keys:
        raise ValueError("generated output-pair collision")
    return key


def validate_identity_row(row: dict[str, Any], expected_split: str) -> None:
    if expected_split not in SPLITS:
        raise ValueError(f"unknown identity split: {expected_split!r}")
    if row.get("split") != expected_split or row.get("is_errorful") is not False:
        raise ValueError("identity row split/errorful flag is inconsistent")
    if not row.get("clean_id") or row.get("source_text") != row.get("target_text"):
        raise ValueError("identity row must preserve the clean sentence exactly")
    if int(row.get("num_errors", -1)) != 0:
        raise ValueError("identity row num_errors must be zero")
    tags = parse_json_field(row.get("correction_tags", []), "correction_tags")
    if tags not in ([], None):
        raise ValueError("identity row must have no correction tags")


def counts_by_split(rows: Iterable[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        split = str(row.get("split", ""))
        if split not in SPLITS:
            raise ValueError(f"unknown split: {split!r}")
        counts[split] += 1
    return counts
