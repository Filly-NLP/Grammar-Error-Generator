"""A/B/C evaluation routing with dependency-injected model callables."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .artifacts import PredictionArtifact


CONDITIONS = ("A", "B", "C")


def _invoke(component: Any, text: str) -> tuple[str, tuple[str, ...] | None, tuple[dict[str, Any], ...] | None]:
    result = component(text) if callable(component) else component.normalize(text) if hasattr(component, "normalize") else component.correct(text)
    if isinstance(result, str):
        return result, None, None
    if isinstance(result, Mapping):
        output = result.get("text", result.get("output"))
        if not isinstance(output, str):
            raise ValueError("injected component mapping must contain string text/output")
        tags = result.get("predicted_tags")
        edits = result.get("predicted_edits")
        return output, None if tags is None else tuple(str(tag) for tag in tags), None if edits is None else tuple(dict(edit) for edit in edits)
    if isinstance(result, tuple) and len(result) in {2, 3}:
        output, tags = result[:2]
        edits = result[2] if len(result) == 3 else None
        if not isinstance(output, str):
            raise ValueError("injected component tuple output must be a string")
        return output, None if tags is None else tuple(str(tag) for tag in tags), None if edits is None else tuple(dict(edit) for edit in edits)
    raise ValueError("injected component must return text, (text, tags), or {text, predicted_tags}")


def route_samples(samples: Sequence[Mapping[str, Any]], *, normalizer: Any, gec: Any, conditions: Sequence[str] = CONDITIONS, model_version: str = "dependency_injected", frozen_evaluation_sha256: str = "fixture-frozen-evaluation", normalizer_version: str = "fixture-normalizer-v1", gec_version: str = "fixture-gec-v1") -> list[PredictionArtifact]:
    """Run the same samples through explicit A/B/C dependency-injected paths.

    A: raw -> GEC; B: raw -> normalizer -> GEC; C: gold intermediate -> GEC.
    This function contains no model imports and therefore cannot claim a real
    model evaluation when deterministic stubs are supplied by tests.
    """

    normalized_conditions = []
    for condition in conditions:
        canonical = {"raw_to_gec": "A", "raw_to_normalizer_to_gec": "B", "oracle_normalized_to_gec": "C"}.get(condition, condition)
        if canonical not in CONDITIONS:
            raise ValueError(f"unknown evaluation condition: {condition}")
        if canonical not in normalized_conditions:
            normalized_conditions.append(canonical)
    predictions: list[PredictionArtifact] = []
    for sample in samples:
        sample_id = str(sample.get("sample_id", ""))
        raw = sample.get("raw_informal")
        gold_normalized = sample.get("gold_normalized_errorful")
        if not sample_id or not isinstance(raw, str) or not isinstance(gold_normalized, str):
            raise ValueError("evaluation sample requires sample_id, raw_informal, and gold_normalized_errorful")
        for condition in normalized_conditions:
            if condition == "A":
                gec_input = raw
                output, tags, edits = _invoke(gec, gec_input)
                normalizer_output = None
            elif condition == "B":
                normalizer_output, _, _ = _invoke(normalizer, raw)
                gec_input = normalizer_output
                output, tags, edits = _invoke(gec, gec_input)
            else:
                gec_input = gold_normalized
                output, tags, edits = _invoke(gec, gec_input)
                normalizer_output = gold_normalized
            predictions.append(PredictionArtifact(sample_id, condition, raw, normalizer_output, gec_input, output, tags, edits, model_version=model_version, frozen_evaluation_sha256=frozen_evaluation_sha256, normalizer_version=normalizer_version, gec_version=gec_version))
    return predictions
