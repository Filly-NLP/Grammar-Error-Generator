"""Binding and route invariants for Phase 12 prediction artifacts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .artifacts import CONDITION_NAMES, PredictionArtifact
from src.evaluation_noise.schema import EvaluationValidationError, replay_edits
from src.geg.tags import require_registered


REQUIRED_CONDITIONS = ("raw_to_gec", "raw_to_normalizer_to_gec", "oracle_normalized_to_gec")


def _prediction_map(predictions: Iterable[PredictionArtifact]) -> dict[tuple[str, str], PredictionArtifact]:
    result: dict[tuple[str, str], PredictionArtifact] = {}
    for artifact in predictions:
        key = (artifact.sample_id, artifact.canonical_condition)
        if key in result:
            raise ValueError(f"prediction bundle contains duplicate route: {key}")
        result[key] = artifact
    return result


def validate_prediction_bundle(
    samples: Sequence[Mapping[str, Any]],
    predictions: Iterable[PredictionArtifact],
    *,
    frozen_evaluation_sha256: str | None,
    normalizer_version: str | None,
    gec_version: str | None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[tuple[str, str], PredictionArtifact]:
    """Validate exact A/B/C coverage and artifact inputs before metrics.

    All three routes must occur exactly once for every frozen sample.  The
    model inputs are checked against the frozen item fields; callers may not
    substitute their own gold/raw text after this point.
    """

    if not frozen_evaluation_sha256:
        raise ValueError("prediction bundle requires frozen_evaluation_sha256 binding")
    if not normalizer_version:
        raise ValueError("prediction bundle requires normalizer_version binding")
    if not gec_version:
        raise ValueError("prediction bundle requires gec_version binding")
    metadata = dict(metadata or {})
    for field, expected in (
        ("frozen_evaluation_sha256", frozen_evaluation_sha256),
        ("normalizer_version", normalizer_version),
        ("gec_version", gec_version),
    ):
        if field in metadata and str(metadata[field]) != str(expected):
            raise ValueError(f"prediction metadata {field} does not match expected binding")
    sample_by_id: dict[str, Mapping[str, Any]] = {}
    for sample in samples:
        sample_id = str(sample.get("sample_id", ""))
        if not sample_id or sample_id in sample_by_id:
            raise ValueError(f"frozen evaluation contains duplicate/empty sample_id: {sample_id!r}")
        sample_by_id[sample_id] = sample
    prediction_list = list(predictions)
    prediction_map = _prediction_map(prediction_list)
    expected_keys = {(sample_id, condition) for sample_id in sample_by_id for condition in REQUIRED_CONDITIONS}
    actual_keys = set(prediction_map)
    missing = sorted(expected_keys - actual_keys)
    extras = sorted(actual_keys - expected_keys)
    if missing:
        raise ValueError(f"prediction bundle missing required routes: {missing}")
    if extras:
        raise ValueError(f"prediction bundle contains extra routes: {extras}")
    for artifact in prediction_list:
        if artifact.frozen_evaluation_sha256 != frozen_evaluation_sha256:
            raise ValueError(f"prediction {artifact.sample_id}/{artifact.canonical_condition} is bound to the wrong frozen evaluation")
        if artifact.normalizer_version != normalizer_version:
            raise ValueError(f"prediction {artifact.sample_id}/{artifact.canonical_condition} has the wrong normalizer version")
        if artifact.gec_version != gec_version:
            raise ValueError(f"prediction {artifact.sample_id}/{artifact.canonical_condition} has the wrong GEC version")
        if not artifact.model_version:
            raise ValueError(f"prediction {artifact.sample_id}/{artifact.canonical_condition} requires model_version")
        if (artifact.predicted_tags is None) != (artifact.predicted_edits is None):
            raise ValueError(f"prediction {artifact.sample_id}/{artifact.canonical_condition} must provide predicted_tags and predicted_edits together")
        if artifact.predicted_edits_coordinate_space not in {"gec_input", "gold_normalized"}:
            raise ValueError(f"prediction {artifact.sample_id}/{artifact.canonical_condition} has unsupported edit coordinate space")
        sample = sample_by_id[artifact.sample_id]
        edit_source = artifact.gec_input if artifact.predicted_edits_coordinate_space == "gec_input" else str(sample["gold_normalized_errorful"])
        if artifact.predicted_edits is not None:
            try:
                replayed_output = replay_edits(edit_source, artifact.predicted_edits)
            except (EvaluationValidationError, TypeError, ValueError) as error:
                raise ValueError(f"prediction {artifact.sample_id}/{artifact.canonical_condition} has invalid predicted_edits: {error}") from error
            if replayed_output != artifact.gec_output:
                raise ValueError(f"prediction {artifact.sample_id}/{artifact.canonical_condition} predicted_edits do not replay to gec_output")
            edit_tags: list[str] = []
            for edit in artifact.predicted_edits:
                if edit.get("tag") is None:
                    raise ValueError(f"prediction {artifact.sample_id}/{artifact.canonical_condition} predicted_edits must carry tags")
                tag = str(edit["tag"])
                try:
                    require_registered(tag)
                except ValueError as error:
                    raise ValueError(f"prediction {artifact.sample_id}/{artifact.canonical_condition} has unregistered predicted tag: {tag}") from error
                edit_tags.append(tag)
            if sorted(str(tag) for tag in artifact.predicted_tags or ()) != sorted(edit_tags):
                raise ValueError(f"prediction {artifact.sample_id}/{artifact.canonical_condition} predicted_tags do not match predicted_edits")
        raw = str(sample["raw_informal"])
        normalized = str(sample["gold_normalized_errorful"])
        if artifact.raw_input != raw:
            raise ValueError(f"prediction {artifact.sample_id}/{artifact.canonical_condition} raw_input does not match frozen item")
        if artifact.canonical_condition == "raw_to_gec":
            if artifact.normalizer_output is not None or artifact.gec_input != raw:
                raise ValueError(f"prediction {artifact.sample_id}/A violates raw-to-GEC route invariant")
        elif artifact.canonical_condition == "raw_to_normalizer_to_gec":
            if artifact.normalizer_output is None or artifact.gec_input != artifact.normalizer_output:
                raise ValueError(f"prediction {artifact.sample_id}/B must use its artifact normalizer output as GEC input")
        elif artifact.canonical_condition == "oracle_normalized_to_gec":
            if artifact.normalizer_output != normalized or artifact.gec_input != normalized:
                raise ValueError(f"prediction {artifact.sample_id}/C must use frozen oracle-normalized text")
    return prediction_map
