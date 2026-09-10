"""Prediction-artifact metrics for normalization, GEC, and FILLY A/B/C runs."""

from __future__ import annotations

import difflib
import math
import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .artifacts import CONDITION_NAMES, PredictionArtifact
from .validation import validate_prediction_bundle
from src.evaluation_noise.schema import EvaluationValidationError, replay_edits
from src.geg.tags import registry, require_registered, tag_ids


def _tokens(text: str) -> list[str]:
    return text.split()


def _edit_set(source: str, target: str) -> set[tuple[str, int, int, tuple[str, ...]]]:
    source_tokens = _tokens(source)
    target_tokens = _tokens(target)
    matcher = difflib.SequenceMatcher(None, source_tokens, target_tokens, autojunk=False)
    return {
        (opcode, source_start, source_end, tuple(target_tokens[target_start:target_end]))
        for opcode, source_start, source_end, target_start, target_end in matcher.get_opcodes()
        if opcode != "equal"
    }


def _prf(tp: int, fp: int, fn: int, *, beta: float = 0.5) -> dict[str, float | int]:
    precision = tp / (tp + fp) if tp + fp else 1.0 if fn == 0 else 0.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    beta2 = beta * beta
    fbeta = (1 + beta2) * precision * recall / (beta2 * precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f0.5": fbeta}


def _aggregate(rows: Sequence[tuple[str, str, str]]) -> dict[str, float | int]:
    tp = fp = fn = 0
    for source, gold, prediction in rows:
        gold_edits = _edit_set(source, gold)
        prediction_edits = _edit_set(source, prediction)
        tp += len(gold_edits & prediction_edits)
        fp += len(prediction_edits - gold_edits)
        fn += len(gold_edits - prediction_edits)
    result = _prf(tp, fp, fn)
    result["sentence_count"] = len(rows)
    result["exact_sentence_rate"] = sum(prediction == gold for _, gold, prediction in rows) / len(rows) if rows else 0.0
    before_errors = sum(len(_edit_set(source, gold)) for source, gold, _ in rows)
    after_errors = sum(len(_edit_set(prediction, gold)) for _, gold, prediction in rows)
    result["error_count_before"] = before_errors
    result["error_count_after"] = after_errors
    result["error_reduction_rate"] = (before_errors - after_errors) / before_errors if before_errors else 0.0
    result["mean_edit_distance_to_gold"] = sum(_levenshtein(prediction, gold) for _, gold, prediction in rows) / len(rows) if rows else 0.0
    result["mean_damerau_distance_to_gold"] = sum(_damerau_levenshtein(prediction, gold) for _, gold, prediction in rows) / len(rows) if rows else 0.0
    return result


def _levenshtein(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, 1):
        current = [left_index]
        for right_index, right_char in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[right_index] + 1, previous[right_index - 1] + (left_char != right_char)))
        previous = current
    return previous[-1]


def _damerau_levenshtein(left: str, right: str) -> int:
    """Optimal-string-alignment Damerau distance for reporting diagnostics."""

    if left == right:
        return 0
    previous_previous = None
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, 1):
        current = [left_index]
        for right_index, right_char in enumerate(right, 1):
            value = min(current[-1] + 1, previous[right_index] + 1, previous[right_index - 1] + (left_char != right_char))
            if previous_previous is not None and left_index > 1 and right_index > 1 and left[left_index - 1] == right[right_index - 2] and left[left_index - 2] == right_char:
                value = min(value, previous_previous[right_index - 2] + 1)
            current.append(value)
        previous_previous, previous = previous, current
    return previous[-1]


def _as_prediction_map(predictions: Iterable[PredictionArtifact | Mapping[str, Any]]) -> dict[tuple[str, str], PredictionArtifact]:
    result: dict[tuple[str, str], PredictionArtifact] = {}
    for item in predictions:
        artifact = item if isinstance(item, PredictionArtifact) else PredictionArtifact(
            sample_id=str(item["sample_id"]), condition=str(item["condition"]), raw_input=str(item.get("raw_input", "")),
            normalizer_output=item.get("normalizer_output"), gec_input=str(item["gec_input"]), gec_output=str(item["gec_output"]),
            predicted_tags=None if item.get("predicted_tags") is None else tuple(str(tag) for tag in item["predicted_tags"]),
            predicted_edits=None if item.get("predicted_edits") is None else tuple(dict(edit) for edit in item["predicted_edits"]),
            model_version=str(item.get("model_version", "dependency_injected")), evaluation_mode=str(item.get("evaluation_mode", "dependency_injected")),
            frozen_evaluation_sha256=None if item.get("frozen_evaluation_sha256") is None else str(item["frozen_evaluation_sha256"]),
            normalizer_version=None if item.get("normalizer_version") is None else str(item["normalizer_version"]),
            gec_version=None if item.get("gec_version") is None else str(item["gec_version"]),
            predicted_edits_coordinate_space=str(item.get("predicted_edits_coordinate_space", "gec_input")),
        )
        key = (artifact.sample_id, artifact.canonical_condition)
        if key in result:
            raise ValueError(f"duplicate prediction artifact: {key}")
        result[key] = artifact
    return result


def normalization_metrics(samples: Sequence[Mapping[str, Any]], predictions: Iterable[PredictionArtifact | Mapping[str, Any]]) -> dict[str, Any]:
    prediction_map = _as_prediction_map(predictions)
    rows: list[tuple[str, str, str]] = []
    groups: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    rule_groups: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for sample in samples:
        if sample.get("source_type") == "clean_control":
            continue
        key = (str(sample["sample_id"]), "raw_to_normalizer_to_gec")
        artifact = prediction_map.get(key)
        if artifact is None or artifact.normalizer_output is None:
            raise ValueError(f"missing normalizer prediction for sample {sample['sample_id']}")
        raw = str(sample["raw_informal"])
        gold = str(sample["gold_normalized_errorful"])
        rows.append((raw, gold, artifact.normalizer_output))
        for category in sample.get("normalization_types", []):
            groups[str(category)].append((raw, gold, artifact.normalizer_output))
        rule_groups[str(sample.get("normalization_rule_seen_status", "unknown"))].append((raw, gold, artifact.normalizer_output))
    result = _aggregate(rows)
    result.update({
        "module": "normalization",
        "accuracy_at_1": result["exact_sentence_rate"],
        "breakdown_by_normalization_type": {key: _aggregate(value) for key, value in sorted(groups.items())},
        "breakdown_by_rule_seen_status": {key: _aggregate(value) for key, value in sorted(rule_groups.items())},
    })
    return result


def _condition_rows(samples: Sequence[Mapping[str, Any]], prediction_map: Mapping[tuple[str, str], PredictionArtifact], condition: str, *, include_clean_controls: bool = False, baseline: str = "gec_input") -> list[tuple[str, str, str]]:
    rows = []
    canonical = CONDITION_NAMES[condition]
    for sample in samples:
        if not include_clean_controls and sample.get("source_type") == "clean_control":
            continue
        key = (str(sample["sample_id"]), canonical)
        if key not in prediction_map:
            raise ValueError(f"missing {condition} prediction for sample {sample['sample_id']}")
        artifact = prediction_map[key]
        if baseline == "raw_to_final":
            source = str(sample["raw_informal"])
        elif baseline == "gec_input":
            source = artifact.gec_input
        else:
            raise ValueError(f"unknown metric baseline: {baseline}")
        rows.append((source, str(sample["gold_final_correct"]), artifact.gec_output))
    return rows


def mcnemar_exact(samples: Sequence[Mapping[str, Any]], predictions: Iterable[PredictionArtifact | Mapping[str, Any]], *, condition_a: str = "A", condition_b: str = "B") -> dict[str, Any]:
    """Exact two-sided McNemar test on sentence-level exact correction."""

    prediction_map = _as_prediction_map(predictions)
    b = c = 0
    usable = 0
    for sample in samples:
        if sample.get("source_type") == "clean_control":
            continue
        key_a = (str(sample["sample_id"]), CONDITION_NAMES[condition_a])
        key_b = (str(sample["sample_id"]), CONDITION_NAMES[condition_b])
        if key_a not in prediction_map or key_b not in prediction_map:
            raise ValueError(f"McNemar requires both conditions for {sample['sample_id']}")
        gold = str(sample["gold_final_correct"])
        a_correct = prediction_map[key_a].gec_output == gold
        b_correct = prediction_map[key_b].gec_output == gold
        usable += 1
        if a_correct and not b_correct:
            b += 1
        elif b_correct and not a_correct:
            c += 1
    discordant = b + c
    if discordant == 0:
        p_value = 1.0
    else:
        tail = sum(math.comb(discordant, i) for i in range(min(b, c) + 1)) / (2 ** discordant)
        p_value = min(1.0, 2 * tail)
    return {"condition_a": condition_a, "condition_b": condition_b, "n": usable, "b_a_only": b, "c_b_only": c, "discordant": discordant, "p_value": p_value}


def paired_bootstrap_delta(samples: Sequence[Mapping[str, Any]], predictions: Iterable[PredictionArtifact | Mapping[str, Any]], *, metric: str = "f0.5", condition_a: str = "A", condition_b: str = "B", baseline: str = "raw_to_final", n_resamples: int = 2000, seed: int = 20260905) -> dict[str, Any]:
    """Seeded paired bootstrap for delta(B-A) over a common baseline."""

    if n_resamples <= 0:
        raise ValueError("n_resamples must be positive")
    prediction_map = _as_prediction_map(predictions)
    rows_a = _condition_rows(samples, prediction_map, condition_a, baseline=baseline)
    rows_b = _condition_rows(samples, prediction_map, condition_b, baseline=baseline)
    if len(rows_a) != len(rows_b) or not rows_a:
        raise ValueError("paired bootstrap requires non-empty aligned samples")

    def value(indexes: Sequence[int], rows: Sequence[tuple[str, str, str]]) -> float:
        aggregate = _aggregate([rows[index] for index in indexes])
        if metric not in aggregate:
            raise ValueError(f"unsupported bootstrap metric: {metric}")
        return float(aggregate[metric])

    indexes = list(range(len(rows_a)))
    point_a = value(indexes, rows_a)
    point_b = value(indexes, rows_b)
    randomizer = random.Random(seed)
    deltas = []
    for _ in range(n_resamples):
        sampled = [randomizer.randrange(len(indexes)) for _ in indexes]
        deltas.append(value(sampled, rows_b) - value(sampled, rows_a))
    deltas.sort()
    low = deltas[int(0.025 * (len(deltas) - 1))]
    high = deltas[int(0.975 * (len(deltas) - 1))]
    return {"metric": metric, "baseline": baseline, "condition_a": condition_a, "condition_b": condition_b, "seed": seed, "n_resamples": n_resamples, "point_a": point_a, "point_b": point_b, "delta_b_minus_a": point_b - point_a, "ci95_low": low, "ci95_high": high}


def _tagged_edit_key(edit: Mapping[str, Any], *, field: str) -> tuple[str, int, int, str, str]:
    if not isinstance(edit, Mapping):
        raise ValueError(f"{field} must contain edit objects")
    if any(key not in edit for key in ("tag", "start", "end", "source", "target")):
        raise ValueError(f"{field} requires tag/start/end/source/target for span-aware scoring")
    try:
        start = int(edit["start"])
        end = int(edit["end"])
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} has non-integer edit span") from error
    if start < 0 or end < start:
        raise ValueError(f"{field} has invalid edit span")
    tag = str(edit["tag"])
    try:
        require_registered(tag)
    except ValueError as error:
        raise ValueError(f"{field} contains unregistered tag: {tag}") from error
    return tag, start, end, str(edit["source"]), str(edit["target"])


def _validate_supplied_prediction_edits(
    samples: Sequence[Mapping[str, Any]],
    prediction_map: Mapping[tuple[str, str], PredictionArtifact],
    condition: str,
) -> None:
    """Validate optional tagged artifacts even for direct metric callers.

    ``evaluate_predictions`` performs the complete route/binding validation
    first.  This smaller guard keeps the public ``per_tag_metrics`` helper
    safe when called directly: supplied edits are never merely counted without
    checking their coordinate source, replay, bounds, or tag alignment.
    """

    canonical = CONDITION_NAMES[condition]
    for sample in samples:
        if sample.get("source_type") == "clean_control":
            continue
        artifact = prediction_map.get((str(sample["sample_id"]), canonical))
        if artifact is None:
            continue
        if (artifact.predicted_tags is None) != (artifact.predicted_edits is None):
            raise ValueError(f"prediction {artifact.sample_id}/{canonical} must provide predicted_tags and predicted_edits together")
        if artifact.predicted_edits_coordinate_space not in {"gec_input", "gold_normalized"}:
            raise ValueError(f"prediction {artifact.sample_id}/{canonical} has unsupported edit coordinate space")
        if artifact.predicted_edits is None:
            continue
        source = artifact.gec_input if artifact.predicted_edits_coordinate_space == "gec_input" else str(sample["gold_normalized_errorful"])
        try:
            replayed = replay_edits(source, artifact.predicted_edits)
        except (EvaluationValidationError, TypeError, ValueError) as error:
            raise ValueError(f"prediction {artifact.sample_id}/{canonical} has invalid predicted_edits: {error}") from error
        if replayed != artifact.gec_output:
            raise ValueError(f"prediction {artifact.sample_id}/{canonical} predicted_edits do not replay to gec_output")
        edit_tags: list[str] = []
        for edit in artifact.predicted_edits:
            if edit.get("tag") is None:
                raise ValueError(f"prediction {artifact.sample_id}/{canonical} predicted_edits must carry tags")
            tag = str(edit["tag"])
            try:
                require_registered(tag)
            except ValueError as error:
                raise ValueError(f"prediction {artifact.sample_id}/{canonical} has unregistered predicted tag: {tag}") from error
            edit_tags.append(tag)
        if sorted(str(tag) for tag in artifact.predicted_tags or ()) != sorted(edit_tags):
            raise ValueError(f"prediction {artifact.sample_id}/{canonical} predicted_tags do not match predicted_edits")


def per_tag_metrics(samples: Sequence[Mapping[str, Any]], predictions: Iterable[PredictionArtifact | Mapping[str, Any]], *, condition: str = "B") -> dict[str, dict[str, Any]]:
    """Score tagged spans, retaining repeated identical edits with Counters."""

    prediction_map = _as_prediction_map(predictions)
    _validate_supplied_prediction_edits(samples, prediction_map, condition)
    if condition != "C" and not all(
        artifact.predicted_edits_coordinate_space == "gold_normalized"
        for (sample_id, artifact_condition), artifact in prediction_map.items()
        if artifact_condition == CONDITION_NAMES[condition]
    ):
        return {
            "_status": {
                "status": "unavailable",
                "reason": "A/B predicted edit spans are not explicitly aligned into gold_normalized coordinates",
            }
        }
    gold_by_tag: Counter[str] = Counter()
    predicted_by_tag: Counter[str] = Counter()
    matched_by_tag: Counter[str] = Counter()
    for sample in samples:
        if sample.get("source_type") == "clean_control":
            continue
        artifact = prediction_map.get((str(sample["sample_id"]), CONDITION_NAMES[condition]))
        if artifact is None:
            raise ValueError(f"missing prediction for per-tag metric: {sample['sample_id']}")
        if artifact.predicted_edits is None:
            raise ValueError("per-tag metrics require predicted_tags/predicted_edits with tagged spans")
        gold_counts: Counter[tuple[str, int, int, str, str]] = Counter(
            _tagged_edit_key(edit, field=f"grammar_edits for {sample['sample_id']}")
            for edit in sample.get("grammar_edits", [])
        )
        predicted_counts: Counter[tuple[str, int, int, str, str]] = Counter(
            _tagged_edit_key(edit, field=f"predicted_edits for {sample['sample_id']}")
            for edit in artifact.predicted_edits
        )
        for key, count in gold_counts.items():
            gold_by_tag[key[0]] += count
        for key, count in predicted_counts.items():
            predicted_by_tag[key[0]] += count
        for key, count in (gold_counts & predicted_counts).items():
            matched_by_tag[key[0]] += count
    family_by_tag = {item.id: item.family for item in registry()}
    result: dict[str, dict[str, Any]] = {}
    for tag in sorted(tag_ids()):
        tp = matched_by_tag[tag]
        fp = predicted_by_tag[tag] - tp
        fn = gold_by_tag[tag] - tp
        if gold_by_tag[tag] + predicted_by_tag[tag] == 0:
            scores: dict[str, Any] = {"tp": 0, "fp": 0, "fn": 0, "precision": 0.0, "recall": 0.0, "f0.5": 0.0}
        else:
            scores = _prf(tp, fp, fn)
        result[tag] = {**scores, "support": gold_by_tag[tag], "family": family_by_tag[tag]}
    return result


def _breakdown(
    samples: Sequence[Mapping[str, Any]],
    predictions: Mapping[tuple[str, str], PredictionArtifact],
    condition: str,
    field: str,
    *,
    baseline: str = "raw_to_final",
) -> dict[str, dict[str, Any]]:
    """Score one category breakdown from an explicitly named baseline.

    The primary A/B end-to-end comparison is always ``raw_to_final``.  A
    separate ``gec_input`` view remains useful for diagnosing the GEC module,
    but must never be mislabeled as an end-to-end result because condition B
    has a different GEC input after normalization.
    """
    grouped: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for sample in samples:
        if sample.get("source_type") == "clean_control":
            continue
        key = (str(sample["sample_id"]), CONDITION_NAMES[condition])
        artifact = predictions.get(key)
        if artifact is None:
            raise ValueError(f"missing prediction for breakdown: {sample['sample_id']}")
        values = sample.get(field, [])
        if field in {"error_families", "grammar_families"} and not values:
            family_by_tag = {item.id: item.family for item in registry()}
            values = [family_by_tag[tag] for tag in sample.get("grammar_tags", []) if tag in family_by_tag]
        values = values if isinstance(values, list) else [values]
        if baseline == "raw_to_final":
            source = str(sample["raw_informal"])
        elif baseline == "gec_input":
            source = artifact.gec_input
        else:
            raise ValueError(f"unknown metric baseline: {baseline}")
        for value in values:
            grouped[str(value)].append((source, str(sample["gold_final_correct"]), artifact.gec_output))
    return {key: _aggregate(rows) for key, rows in sorted(grouped.items())}


def evaluate_predictions(samples: Sequence[Mapping[str, Any]], predictions: Iterable[PredictionArtifact | Mapping[str, Any]], *, include_per_tag: bool = False, bootstrap_resamples: int = 2000, seed: int = 20260905, frozen_evaluation_sha256: str | None = None, normalizer_version: str | None = None, gec_version: str | None = None, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    prediction_map = _as_prediction_map(predictions)
    validate_prediction_bundle(
        samples,
        prediction_map.values(),
        frozen_evaluation_sha256=frozen_evaluation_sha256,
        normalizer_version=normalizer_version,
        gec_version=gec_version,
        metadata=metadata,
    )
    result: dict[str, Any] = {
        "evaluation_mode": "prediction_artifact",
        "bindings": {
            "frozen_evaluation_sha256": frozen_evaluation_sha256,
            "normalizer_version": normalizer_version,
            "gec_version": gec_version,
        },
        "conditions": {},
        "sentence_level": [],
        "clean_controls": {},
    }
    for sample in samples:
        for condition in ("A", "B", "C"):
            artifact = prediction_map.get((str(sample["sample_id"]), CONDITION_NAMES[condition]))
            if artifact is None:
                raise ValueError(f"missing condition {condition} prediction for {sample['sample_id']}")
            result["sentence_level"].append({"sample_id": str(sample["sample_id"]), "condition": condition, "gec_input": artifact.gec_input, "gec_output": artifact.gec_output, "gold_final_correct": str(sample["gold_final_correct"]), "exact_correct": artifact.gec_output == str(sample["gold_final_correct"]), "source_type": sample.get("source_type")})
    for condition in ("A", "B", "C"):
        rows = _condition_rows(samples, prediction_map, condition)
        end_to_end_breakdowns = {
            "normalization_type": _breakdown(samples, prediction_map, condition, "normalization_types", baseline="raw_to_final"),
            "source_type": _breakdown(samples, prediction_map, condition, "source_type", baseline="raw_to_final"),
            "error_family": _breakdown(samples, prediction_map, condition, "grammar_families", baseline="raw_to_final"),
        }
        gec_input_breakdowns = {
            "normalization_type": _breakdown(samples, prediction_map, condition, "normalization_types", baseline="gec_input"),
            "source_type": _breakdown(samples, prediction_map, condition, "source_type", baseline="gec_input"),
            "error_family": _breakdown(samples, prediction_map, condition, "grammar_families", baseline="gec_input"),
        }
        result["conditions"][condition] = {
            "gec": _aggregate(rows),
            "end_to_end": _aggregate([(str(sample["raw_informal"]), str(sample["gold_final_correct"]), prediction_map[(str(sample["sample_id"]), CONDITION_NAMES[condition])].gec_output) for sample in samples if sample.get("source_type") != "clean_control"]),
            # Explicit names are the canonical report contract.
            "end_to_end_breakdown_by_normalization_type": end_to_end_breakdowns["normalization_type"],
            "end_to_end_breakdown_by_source_type": end_to_end_breakdowns["source_type"],
            "end_to_end_breakdown_by_error_family": end_to_end_breakdowns["error_family"],
            "gec_input_breakdown_by_normalization_type": gec_input_breakdowns["normalization_type"],
            "gec_input_breakdown_by_source_type": gec_input_breakdowns["source_type"],
            "gec_input_breakdown_by_error_family": gec_input_breakdowns["error_family"],
            # Backwards-compatible aliases.  These are explicitly the
            # primary raw-to-final end-to-end view, not the GEC-input view.
            "breakdown_by_normalization_type": end_to_end_breakdowns["normalization_type"],
            "breakdown_by_source_type": end_to_end_breakdowns["source_type"],
            "breakdown_by_error_family": end_to_end_breakdowns["error_family"],
        }
        if include_per_tag:
            result["conditions"][condition]["per_tag"] = per_tag_metrics(samples, prediction_map.values(), condition=condition)
    clean_controls = [sample for sample in samples if sample.get("source_type") == "clean_control"]
    if clean_controls:
        for condition in ("A", "B", "C"):
            exact = []
            for sample in clean_controls:
                artifact = prediction_map[(str(sample["sample_id"]), CONDITION_NAMES[condition])]
                exact.append(artifact.gec_output == str(sample["gold_final_correct"]))
            result["clean_controls"][condition] = {"count": len(exact), "overcorrection_count": sum(not value for value in exact), "overcorrection_rate": sum(not value for value in exact) / len(exact)}
    paired_conditions_available = all(
        (str(sample["sample_id"]), CONDITION_NAMES["A"]) in prediction_map
        and (str(sample["sample_id"]), CONDITION_NAMES["B"]) in prediction_map
        for sample in samples
    )
    if paired_conditions_available:
        bootstrap = paired_bootstrap_delta(samples, prediction_map.values(), condition_a="A", condition_b="B", baseline="raw_to_final", n_resamples=bootstrap_resamples, seed=seed)
        bootstrap["metrics"] = {
            metric: paired_bootstrap_delta(samples, prediction_map.values(), metric=metric, condition_a="A", condition_b="B", baseline="raw_to_final", n_resamples=bootstrap_resamples, seed=seed)
            for metric in ("precision", "recall", "f0.5")
        }
        result["paired_bootstrap_A_vs_B"] = bootstrap
        result["paired_bootstrap_gec_input_A_vs_B"] = {
            metric: paired_bootstrap_delta(samples, prediction_map.values(), metric=metric, condition_a="A", condition_b="B", baseline="gec_input", n_resamples=bootstrap_resamples, seed=seed)
            for metric in ("precision", "recall", "f0.5")
        }
        result["mcnemar_A_vs_B"] = mcnemar_exact(samples, prediction_map.values(), condition_a="A", condition_b="B")
    result["normalization"] = normalization_metrics(samples, prediction_map.values()) if any(str(sample.get("source_type")) != "clean_control" for sample in samples) else None
    return result
