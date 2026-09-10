from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.evaluation.artifacts import PredictionArtifact
from src.evaluation.metrics import evaluate_predictions
from src.evaluation.routing import route_samples
from src.evaluation_noise.injector import (
    NoiseInjectionError,
    NoiseResourceError,
    NoiseRule,
    build_controlled_row,
    freeze_noise_rules,
    inject_informal_noise,
)
from src.evaluation_noise.schema import EvaluationValidationError, make_edit, replay_edits, validate_dataset


NORMALIZER_INVENTORY = {
    "version": "normalizer-v1",
    "status": "frozen",
    "source": "test",
    "license": "CC0-1.0",
    "rules": [{"id": "slang-good", "pattern_id": "pattern-good", "review_status": "approved"}],
}


def _sample() -> dict:
    raw = "slang1"
    normalized = "word1"
    return {
        "sample_id": "sample-1",
        "raw_informal": raw,
        "gold_normalized_errorful": normalized,
        "gold_final_correct": normalized + ".",
        "normalization_types": ["slang"],
        "normalization_edits": [{**edit, "rule_id": "rule_seen", "pattern_id": "pattern_seen", "seen_status": "seen_rule"} for edit in make_edit(raw, normalized)],
        "normalization_rule_ids": ["rule_seen"],
        "normalization_pattern_id": "pattern_seen",
        "normalization_pattern_ids": ["pattern_seen"],
        "grammar_tags": ["$ADD_PUNC_PERIOD"],
        "grammar_families": ["punctuation"],
        "grammar_edits": [{"start": len(normalized), "end": len(normalized), "source": "", "target": ".", "tag": "$ADD_PUNC_PERIOD"}],
        "source_type": "controlled",
        "real_or_controlled": "controlled",
        "base_clean_id": "base-1",
        "provenance": {"source_id": "fixture-1", "source_type": "fixture", "license": "CC0-1.0", "attribution": "test", "captured_at": "2026-09-10"},
        "annotator_1": "a",
        "annotator_2": "b",
        "adjudication_status": "fixture_approved",
        "normalization_rule_id": "rule_seen",
        "normalization_rule_seen_status": "seen_rule",
        "split": "test_only",
        "notes": "fixture",
    }


class EvaluationRemediationTests(unittest.TestCase):
    def test_primary_breakdowns_use_common_raw_baseline(self) -> None:
        sample = _sample()
        controls = dict(sample)
        controls.update({"sample_id": "control-1", "raw_informal": "formal.", "gold_normalized_errorful": "formal.", "gold_final_correct": "formal.", "normalization_types": [], "normalization_edits": [], "grammar_tags": [], "grammar_families": [], "grammar_edits": [], "source_type": "clean_control", "real_or_controlled": "controlled", "base_clean_id": None, "normalization_rule_id": "control", "normalization_rule_seen_status": "seen_rule"})
        normalizer = lambda text: text.replace("slang", "word")
        gec = lambda text: text if text.endswith(".") else text + "."
        predictions = route_samples([sample, controls], normalizer=normalizer, gec=gec, frozen_evaluation_sha256="f", normalizer_version="n", gec_version="g")
        report = evaluate_predictions([sample, controls], predictions, frozen_evaluation_sha256="f", normalizer_version="n", gec_version="g", bootstrap_resamples=5)
        a = report["conditions"]["A"]["end_to_end_breakdown_by_normalization_type"]["slang"]
        b = report["conditions"]["B"]["end_to_end_breakdown_by_normalization_type"]["slang"]
        self.assertEqual(a["error_count_before"], b["error_count_before"])
        self.assertGreater(a["error_count_before"], 0)
        self.assertEqual(1, report["conditions"]["B"]["gec_input_breakdown_by_normalization_type"]["slang"]["error_count_before"])

    def test_schema_canonicalizes_alias_and_rejects_conflict(self) -> None:
        row = _sample()
        row.pop("grammar_families")
        row["error_families"] = ["punctuation"]
        validate_dataset([row], {"version": "v", "status": "frozen", "source": "s", "license": "l", "rules": [{"id": "rule_seen", "pattern_id": "pattern_seen", "review_status": "approved"}]}, require_full_composition=False)
        conflict = _sample()
        conflict["error_families"] = ["morphology"]
        with self.assertRaisesRegex(EvaluationValidationError, "disagree"):
            validate_dataset([conflict], {"version": "v", "status": "frozen", "source": "s", "license": "l", "rules": [{"id": "rule_seen", "pattern_id": "pattern_seen", "review_status": "approved"}]}, require_full_composition=False)

    def test_schema_rejects_tag_family_mismatch(self) -> None:
        row = _sample()
        row["grammar_families"] = ["morphology"]
        with self.assertRaisesRegex(EvaluationValidationError, "grammar_families"):
            validate_dataset([row], {"version": "v", "status": "frozen", "source": "s", "license": "l", "rules": [{"id": "rule_seen", "pattern_id": "pattern_seen", "review_status": "approved"}]}, require_full_composition=False)

    def test_injector_is_deterministic_and_replayable(self) -> None:
        rule = NoiseRule("slang-good", "slang", "gud", "good", "noise-v1", pattern_id="pattern-good")
        first = inject_informal_noise("good araw", [rule], category="slang", sample_id="s1", seed=7, normalizer_training_rule_ids=NORMALIZER_INVENTORY)
        second = inject_informal_noise("good araw", [rule], category="slang", sample_id="s1", seed=7, normalizer_training_rule_ids=NORMALIZER_INVENTORY)
        self.assertEqual(first, second)
        self.assertEqual("gud araw", first["raw_informal"])
        self.assertEqual("good araw", replay_edits(first["raw_informal"], first["normalization_edits"]))
        self.assertEqual("seen_rule", first["normalization_rule_seen_status"])

    def test_unseen_pattern_overlap_is_not_misclassified(self) -> None:
        rule = NoiseRule("slang-good", "slang", "gud", "good", "noise-v1", pattern_id="pattern-good")
        result = inject_informal_noise("good", [rule], category="slang", sample_id="s1", seed=7, normalizer_training_rule_ids={**NORMALIZER_INVENTORY, "rules": [{"id": "other", "pattern_id": "other-pattern", "review_status": "approved"}]})
        self.assertEqual("unseen_pattern", result["normalization_rule_seen_status"])
        with self.assertRaises(NoiseInjectionError):
            inject_informal_noise("good", [rule], category="slang", sample_id="s1", seed=7, normalizer_training_rule_ids=NORMALIZER_INVENTORY, protected_spans=[(0, 4)])

    def test_inventory_must_be_frozen_and_approved(self) -> None:
        rule = NoiseRule("slang-good", "slang", "gud", "good", "noise-v1", pattern_id="pattern-good")
        for inventory in (
            {**NORMALIZER_INVENTORY, "status": "draft"},
            {**NORMALIZER_INVENTORY, "rules": [{"id": "slang-good", "pattern_id": "pattern-good", "review_status": "needs_review"}]},
            {"rules": [{"id": "slang-good"}]},
            {"slang-good"},
        ):
            with self.assertRaises(NoiseResourceError):
                inject_informal_noise("good", [rule], category="slang", sample_id="s1", seed=1, normalizer_training_rule_ids=inventory)  # type: ignore[arg-type]

    def test_mixed_statuses_are_rejected_instead_of_coerced(self) -> None:
        rules = [
            NoiseRule("seen", "slang", "gud", "good", "noise-v1", pattern_id="seen-pattern"),
            NoiseRule("unseen", "abbreviation", "w/", "with", "noise-v1", pattern_id="unseen-pattern"),
        ]
        with self.assertRaises(NoiseInjectionError):
            inject_informal_noise("good with", rules, category="mixed_noise", sample_id="s1", seed=1, normalizer_training_rule_ids={**NORMALIZER_INVENTORY, "rules": [{"id": "seen", "pattern_id": "seen-pattern", "review_status": "approved"}]})

    def test_mixed_noise_requires_two_non_overlapping_rules(self) -> None:
        rules = [
            NoiseRule("s", "slang", "gud", "good", "noise-v1"),
            NoiseRule("a", "abbreviation", "w/", "with", "noise-v1"),
        ]
        mixed_inventory = {**NORMALIZER_INVENTORY, "rules": [{"id": "other-s", "pattern_id": "other-s-pattern", "review_status": "approved"}, {"id": "other-a", "pattern_id": "other-a-pattern", "review_status": "approved"}]}
        result = inject_informal_noise("good with", rules, category="mixed_noise", sample_id="s1", seed=1, normalizer_training_rule_ids=mixed_inventory)
        self.assertEqual("gud w/", result["raw_informal"])
        self.assertEqual("good with", replay_edits(result["raw_informal"], result["normalization_edits"]))

    def test_unreviewed_resource_cannot_load_or_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = root / "rules.json"
            resource.write_text(json.dumps({"resource_version": "v1", "source": "x", "license": "y", "rules": [{"id": "r", "category": "slang", "source": "x", "target": "y", "review_status": "needs_review"}]}), encoding="utf-8")
            with self.assertRaises(NoiseResourceError):
                freeze_noise_rules(resource, root / "frozen.json", reviewer="reviewer", reviewed_at="2026-09-10")

    def test_controlled_rows_are_pending_and_cannot_validate_as_frozen(self) -> None:
        rule = NoiseRule("s", "slang", "gud", "good", "noise-v1")
        row = build_controlled_row(
            sample_id="s1", base_clean_id="base-1", gold_normalized_errorful="good", gold_final_correct="good.",
            grammar_tags=["$ADD_PUNC_PERIOD"], grammar_families=["punctuation"],
            grammar_edits=[{"start": 4, "end": 4, "source": "", "target": ".", "tag": "$ADD_PUNC_PERIOD"}],
            rules=[rule], category="slang", seed=1,
            provenance={"source_id": "operator", "source_type": "held-out", "license": "CC0-1.0", "attribution": "operator", "captured_at": "2026-09-10"},
            normalizer_training_rule_ids={"version": "v", "status": "frozen", "source": "test", "license": "CC0-1.0", "rules": [{"id": "s", "review_status": "approved"}]},
        )
        self.assertEqual("pending_annotation", row["generation_status"])
        with self.assertRaisesRegex(EvaluationValidationError, "annotator_1"):
            validate_dataset([row], {"version": "v", "status": "frozen", "source": "s", "license": "l", "rules": [{"id": "s", "review_status": "approved"}]}, require_full_composition=False)

    def test_validator_checks_per_edit_provenance_and_overall_status(self) -> None:
        row = _sample()
        row["normalization_edits"][0]["seen_status"] = "unseen_pattern"
        with self.assertRaisesRegex(EvaluationValidationError, "seen_status"):
            validate_dataset([row], {**NORMALIZER_INVENTORY, "rules": [{"id": "rule_seen", "pattern_id": "pattern_seen", "review_status": "approved"}]}, require_full_composition=False)
        row = _sample()
        row["normalization_rule_seen_status"] = "unseen_pattern"
        with self.assertRaisesRegex(EvaluationValidationError, "normalization_rule_seen_status"):
            validate_dataset([row], {**NORMALIZER_INVENTORY, "rules": [{"id": "rule_seen", "pattern_id": "pattern_seen", "review_status": "approved"}]}, require_full_composition=False)


if __name__ == "__main__":
    unittest.main()
