from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.evaluation.artifacts import PredictionArtifact, load_prediction_artifact, write_prediction_artifact
from src.evaluation.metrics import evaluate_predictions, normalization_metrics, paired_bootstrap_delta, per_tag_metrics
from src.evaluation.routing import route_samples
from src.evaluation.validation import validate_prediction_bundle
from src.evaluation_noise.freeze import freeze_evaluation
from src.evaluation_noise.schema import EvaluationValidationError, make_edit, replay_edits, validate_dataset
from src.evaluation_noise.template import template_manifest, write_template


RULE_INVENTORY = {
    "version": "fixture-rules-v1",
    "status": "frozen",
    "source": "deterministic-test-fixture",
    "license": "CC0-1.0",
    "rules": [{"id": "rule_seen"}],
}


def fixture_row(index: int, category: str = "slang", source_type: str = "controlled", *, unseen: bool = False) -> dict:
    raw = f"slang{index}"
    normalized = f"word{index}"
    final = normalized + "."
    return {
        "sample_id": f"sample-{index}",
        "clean_id": f"clean-{index}",
        "raw_informal": raw,
        "gold_normalized_errorful": normalized,
        "gold_final_correct": final,
        "normalization_types": [category],
        "normalization_edits": make_edit(raw, normalized),
        "grammar_tags": ["$ADD_PUNC_PERIOD"],
        "grammar_edits": [{"start": len(normalized), "end": len(normalized), "source": "", "target": ".", "tag": "$ADD_PUNC_PERIOD"}],
        "source_type": source_type,
        "base_clean_id": f"base-{index}" if source_type == "controlled" else None,
        "provenance": {"source_id": f"fixture-{index}", "source_type": "fixture", "license": "CC0-1.0", "attribution": "FILLY tests", "captured_at": "2026-09-08"},
        "annotator_1": "fixture-a",
        "annotator_2": "fixture-b",
        "adjudication_status": "fixture_approved",
        "normalization_rule_id": "rule_unseen" if unseen else "rule_seen",
        "normalization_rule_seen_status": "unseen_pattern" if unseen else "seen_rule",
        "split": "test_only",
        "notes": "deterministic fixture",
    }


def control_row(index: int) -> dict:
    text = f"Clean control {index}."
    return {
        "sample_id": f"control-{index}",
        "raw_informal": text,
        "gold_normalized_errorful": text,
        "gold_final_correct": text,
        "normalization_edits": [],
        "normalization_types": [],
        "grammar_tags": [],
        "grammar_edits": [],
        "source_type": "clean_control",
        "provenance": {"source_id": f"control-{index}", "source_type": "fixture", "license": "CC0-1.0", "attribution": "FILLY tests", "captured_at": "2026-09-08"},
        "annotator_1": "fixture-a",
        "annotator_2": "fixture-b",
        "adjudication_status": "fixture_approved",
        "normalization_rule_id": "control-rule",
        "normalization_rule_seen_status": "seen_rule",
        "split": "test_only",
        "notes": "deterministic clean control",
    }


class Phase11SchemaTests(unittest.TestCase):
    def test_replay_and_registered_tags(self) -> None:
        row = fixture_row(1)
        self.assertEqual(row["gold_normalized_errorful"], replay_edits(row["raw_informal"], row["normalization_edits"]))
        self.assertEqual(row["gold_final_correct"], replay_edits(row["gold_normalized_errorful"], row["grammar_edits"]))
        summary = validate_dataset([row], RULE_INVENTORY, clean_controls=[control_row(1)], require_full_composition=False)
        self.assertEqual(1, summary.informal_count)
        self.assertEqual(1, summary.clean_control_count)

    def test_replay_rejects_out_of_bounds_and_impossible_insertions(self) -> None:
        for edit in (
            {"start": 4, "end": 4, "source": "", "target": "x"},
            {"start": 2, "end": 4, "source": "c", "target": "x"},
        ):
            with self.assertRaisesRegex(EvaluationValidationError, "outside source length"):
                replay_edits("abc", [edit])

    def test_normalization_and_gold_grammar_reject_noop_edits(self) -> None:
        row = fixture_row(8)
        row["normalization_edits"] = [{"start": 0, "end": 0, "source": "", "target": ""}]
        with self.assertRaisesRegex(EvaluationValidationError, "no-op"):
            validate_dataset([row], RULE_INVENTORY, require_full_composition=False)
        row = fixture_row(9)
        row["grammar_edits"] = [{"start": len(row["gold_normalized_errorful"]), "end": len(row["gold_normalized_errorful"]), "source": "", "target": "", "tag": "$ADD_PUNC_PERIOD"}]
        with self.assertRaisesRegex(EvaluationValidationError, "no-op"):
            validate_dataset([row], RULE_INVENTORY, require_full_composition=False)

    def test_invalid_tag_and_leakage_are_blocking(self) -> None:
        row = fixture_row(1)
        row["grammar_edits"][0]["tag"] = "$NOT_REGISTERED"
        with self.assertRaises(ValueError):
            validate_dataset([row], RULE_INVENTORY, require_full_composition=False)
        row = fixture_row(2)
        with self.assertRaises(EvaluationValidationError):
            validate_dataset([row], RULE_INVENTORY, forbidden_clean_ids={"clean-2"}, require_full_composition=False)

    def test_controlled_rows_require_base_clean_id_and_distinct_annotators(self) -> None:
        row = fixture_row(3, source_type="controlled")
        row["base_clean_id"] = None
        with self.assertRaisesRegex(EvaluationValidationError, "base_clean_id"):
            validate_dataset([row], RULE_INVENTORY, require_full_composition=False)
        row = fixture_row(4)
        row["annotator_2"] = row["annotator_1"]
        with self.assertRaisesRegex(EvaluationValidationError, "distinct"):
            validate_dataset([row], RULE_INVENTORY, require_full_composition=False)

    def test_full_composition_and_source_mix(self) -> None:
        rows = []
        for category, count in (("slang", 300), ("abbreviation", 300), ("spelling_variation", 300), ("mixed_noise", 100)):
            for index in range(count):
                offset = len(rows)
                rows.append(fixture_row(offset, category, "authentic" if offset == 0 else "controlled", unseen=(offset == 1)))
        controls = [control_row(index) for index in range(200)]
        summary = validate_dataset(rows, RULE_INVENTORY, clean_controls=controls)
        self.assertEqual(1000, summary.informal_count)
        self.assertEqual(200, summary.clean_control_count)
        self.assertEqual(1000, sum(summary.informal_by_type.values()))

    def test_template_contains_no_examples(self) -> None:
        self.assertEqual("template_only", template_manifest()["status"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "template.json"
            write_template(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("rows", payload)

    def test_freeze_missing_dependencies_creates_only_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "frozen.json"
            blocked = root / "blocked.json"
            with self.assertRaises(EvaluationValidationError):
                freeze_evaluation(informal_path=root / "missing.jsonl", controls_path=root / "controls.jsonl", rule_inventory_path=root / "rules.json", output_path=output, blocked_report=blocked)
            self.assertFalse(output.exists())
            self.assertEqual("blocked", json.loads(blocked.read_text(encoding="utf-8"))["status"])

    def test_production_freeze_requires_training_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            informal = root / "informal.jsonl"
            controls = root / "controls.jsonl"
            rules = root / "rules.json"
            informal.write_text("\n", encoding="utf-8")
            controls.write_text("\n", encoding="utf-8")
            rules.write_text(json.dumps(RULE_INVENTORY), encoding="utf-8")
            with self.assertRaisesRegex(EvaluationValidationError, "GEC train"):
                freeze_evaluation(informal_path=informal, controls_path=controls, rule_inventory_path=rules, output_path=root / "frozen.json", require_full_composition=True)

    def test_normalizer_example_training_leakage_and_empty_gec_dependency_block(self) -> None:
        row = fixture_row(8)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalizer_train = root / "normalizer.jsonl"
            normalizer_train.write_text(json.dumps({"source": row["raw_informal"], "target": row["gold_normalized_errorful"]}) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(EvaluationValidationError, "normalizer training example"):
                validate_dataset([row], RULE_INVENTORY, normalizer_train=normalizer_train, require_full_composition=False)
            empty_gec = root / "gec.jsonl"
            empty_gec.write_text("\n", encoding="utf-8")
            with self.assertRaisesRegex(EvaluationValidationError, "contains no clean IDs"):
                validate_dataset([row], RULE_INVENTORY, gec_train=empty_gec, require_full_composition=False)

    def test_freeze_publication_is_exclusive_and_cleans_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            informal = root / "informal.jsonl"
            controls = root / "controls.jsonl"
            rules = root / "rules.json"
            informal.write_text(json.dumps(fixture_row(20)) + "\n", encoding="utf-8")
            controls.write_text(json.dumps(control_row(20)) + "\n", encoding="utf-8")
            rules.write_text(json.dumps(RULE_INVENTORY), encoding="utf-8")
            output = root / "frozen.json"
            freeze_evaluation(informal_path=informal, controls_path=controls, rule_inventory_path=rules, output_path=output, require_full_composition=False)
            self.assertTrue(output.exists())
            self.assertFalse(output.with_suffix(output.suffix + ".lock").exists())
            with self.assertRaises(FileExistsError):
                freeze_evaluation(informal_path=informal, controls_path=controls, rule_inventory_path=rules, output_path=output, require_full_composition=False)
            locked_output = root / "locked.json"
            locked_output.with_suffix(locked_output.suffix + ".lock").write_text("held", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "publication lock"):
                freeze_evaluation(informal_path=informal, controls_path=controls, rule_inventory_path=rules, output_path=locked_output, require_full_composition=False)
            self.assertTrue(locked_output.with_suffix(locked_output.suffix + ".lock").exists())

    def test_freeze_records_all_training_dependency_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            informal = root / "informal.jsonl"
            controls = root / "controls.jsonl"
            rules = root / "rules.json"
            train = root / "train.jsonl"
            dev = root / "dev.jsonl"
            normalizer_train = root / "normalizer.jsonl"
            informal.write_text(json.dumps(fixture_row(21)) + "\n", encoding="utf-8")
            controls.write_text(json.dumps(control_row(21)) + "\n", encoding="utf-8")
            rules.write_text(json.dumps(RULE_INVENTORY), encoding="utf-8")
            train.write_text(json.dumps({"clean_id": "not-in-eval", "text": "other train"}) + "\n", encoding="utf-8")
            dev.write_text(json.dumps({"clean_id": "not-in-eval-dev", "text": "other dev"}) + "\n", encoding="utf-8")
            normalizer_train.write_text(json.dumps({"source": "other raw", "target": "other normalized"}) + "\n", encoding="utf-8")
            result = freeze_evaluation(informal_path=informal, controls_path=controls, rule_inventory_path=rules, gec_train=train, gec_dev=dev, normalizer_train=normalizer_train, output_path=root / "frozen.json", require_full_composition=False)
            dependencies = result["dependencies"]
            for key in ("informal_sha256", "controls_sha256", "rule_inventory_sha256", "gec_train_sha256", "gec_dev_sha256", "normalizer_train_sha256"):
                self.assertEqual(64, len(dependencies[key]))

    def test_freeze_rejects_dependency_mutation_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            informal = root / "informal.jsonl"
            controls = root / "controls.jsonl"
            rules = root / "rules.json"
            informal.write_text(json.dumps(fixture_row(22)) + "\n", encoding="utf-8")
            controls.write_text(json.dumps(control_row(22)) + "\n", encoding="utf-8")
            rules.write_text(json.dumps(RULE_INVENTORY), encoding="utf-8")
            from src.evaluation_noise import freeze as freeze_module

            original_validate = freeze_module.validate_dataset

            def validate_then_mutate(*args, **kwargs):
                summary = original_validate(*args, **kwargs)
                informal.write_text(informal.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                return summary

            blocked = root / "blocked.json"
            with patch.object(freeze_module, "validate_dataset", side_effect=validate_then_mutate):
                with self.assertRaisesRegex(EvaluationValidationError, "dependency changed"):
                    freeze_evaluation(informal_path=informal, controls_path=controls, rule_inventory_path=rules, output_path=root / "frozen.json", blocked_report=blocked, require_full_composition=False)
            self.assertFalse((root / "frozen.json").exists())
            self.assertEqual("blocked", json.loads(blocked.read_text(encoding="utf-8"))["status"])

    def test_freeze_rejects_dependency_mutation_immediately_before_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            informal = root / "informal.jsonl"
            controls = root / "controls.jsonl"
            rules = root / "rules.json"
            informal.write_text(json.dumps(fixture_row(23)) + "\n", encoding="utf-8")
            controls.write_text(json.dumps(control_row(23)) + "\n", encoding="utf-8")
            rules.write_text(json.dumps(RULE_INVENTORY), encoding="utf-8")
            from src.evaluation_noise import freeze as freeze_module

            original_snapshot = freeze_module._snapshot
            calls = 0

            def snapshot_then_mutate(entries):
                nonlocal calls
                calls += 1
                if calls == 3:
                    informal.write_text(informal.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                return original_snapshot(entries)

            blocked = root / "blocked.json"
            with patch.object(freeze_module, "_snapshot", side_effect=snapshot_then_mutate):
                with self.assertRaisesRegex(EvaluationValidationError, "immediately before publication"):
                    freeze_evaluation(informal_path=informal, controls_path=controls, rule_inventory_path=rules, output_path=root / "frozen.json", blocked_report=blocked, require_full_composition=False)
            self.assertFalse((root / "frozen.json").exists())
            self.assertEqual("blocked", json.loads(blocked.read_text(encoding="utf-8"))["status"])


class Phase12EvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.samples = [fixture_row(1), fixture_row(2, "abbreviation", "authentic"), control_row(1)]

    def test_dependency_injected_abc_routes(self) -> None:
        normalizer = lambda text: text.replace("slang", "word")
        gec = lambda text: (text if text.endswith(".") else text + ".", ("$ADD_PUNC_PERIOD",) if not text.endswith(".") else (), [{"start": len(text), "end": len(text), "source": "", "target": ".", "tag": "$ADD_PUNC_PERIOD"}] if not text.endswith(".") else [])
        predictions = route_samples(self.samples, normalizer=normalizer, gec=gec)
        self.assertEqual(9, len(predictions))
        b = [row for row in predictions if row.condition == "B" and row.sample_id == "sample-1"][0]
        self.assertEqual("word1", b.gec_input)
        self.assertEqual("word1.", b.gec_output)
        self.assertEqual("slang1.", [row for row in predictions if row.condition == "A" and row.sample_id == "sample-1"][0].gec_output)

    def test_metrics_bootstrap_mcnemar_clean_and_per_tag(self) -> None:
        normalizer = lambda text: text.replace("slang", "word")
        gec = lambda text: (text if text.endswith(".") else text + ".", ("$ADD_PUNC_PERIOD",) if not text.endswith(".") else (), [{"start": len(text), "end": len(text), "source": "", "target": ".", "tag": "$ADD_PUNC_PERIOD"}] if not text.endswith(".") else [])
        predictions = route_samples(self.samples, normalizer=normalizer, gec=gec)
        report = evaluate_predictions(self.samples, predictions, include_per_tag=True, bootstrap_resamples=50, seed=17, frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")
        self.assertIn("normalization", report)
        self.assertIn("error_reduction_rate", report["normalization"])
        self.assertIn("seen_rule", report["normalization"]["breakdown_by_rule_seen_status"])
        self.assertEqual(0.0, report["clean_controls"]["B"]["overcorrection_rate"])
        self.assertEqual("unavailable", report["conditions"]["B"]["per_tag"]["_status"]["status"])
        self.assertEqual(39, len(report["conditions"]["C"]["per_tag"]) - 0)
        self.assertIn("$ADD_PUNC_PERIOD", report["conditions"]["C"]["per_tag"])
        self.assertIn("punctuation", report["conditions"]["B"]["breakdown_by_error_family"])
        self.assertEqual(17, report["paired_bootstrap_A_vs_B"]["seed"])
        self.assertEqual("raw_to_final", report["paired_bootstrap_A_vs_B"]["baseline"])
        self.assertEqual("gec_input", report["paired_bootstrap_gec_input_A_vs_B"]["precision"]["baseline"])
        self.assertEqual({"precision", "recall", "f0.5"}, set(report["paired_bootstrap_A_vs_B"]["metrics"]))
        self.assertIn("p_value", report["mcnemar_A_vs_B"])

    def test_metrics_require_external_frozen_binding(self) -> None:
        normalizer = lambda text: text.replace("slang", "word")
        gec = lambda text: (text if text.endswith(".") else text + ".", ("$ADD_PUNC_PERIOD",) if not text.endswith(".") else (), [{"start": len(text), "end": len(text), "source": "", "target": ".", "tag": "$ADD_PUNC_PERIOD"}] if not text.endswith(".") else [])
        predictions = route_samples(self.samples, normalizer=normalizer, gec=gec)
        with self.assertRaisesRegex(ValueError, "frozen_evaluation_sha256"):
            evaluate_predictions(self.samples, predictions)

    def test_text_only_metrics_allow_optional_tag_artifacts(self) -> None:
        normalizer = lambda text: text.replace("slang", "word")
        gec = lambda text: text if text.endswith(".") else text + "."
        predictions = route_samples(self.samples, normalizer=normalizer, gec=gec)
        report = evaluate_predictions(self.samples, predictions, frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")
        self.assertNotIn("per_tag", report["conditions"]["C"])
        with self.assertRaisesRegex(ValueError, "predicted_tags"):
            evaluate_predictions(self.samples, predictions, include_per_tag=True, frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")

    def test_per_tag_fails_without_predicted_tags(self) -> None:
        predictions = [PredictionArtifact("sample-1", "C", "slang1", "word1", "word1", "word1.", None)]
        with self.assertRaisesRegex(ValueError, "predicted_tags"):
            per_tag_metrics([self.samples[0]], predictions, condition="C")

    def test_per_tag_is_span_aware_and_counts_repeated_edits(self) -> None:
        row = fixture_row(6)
        row["gold_normalized_errorful"] = "ab"
        row["gold_final_correct"] = "ba"
        row["grammar_edits"] = [{"start": 0, "end": 2, "source": "ab", "target": "ba", "tag": "$ADD_PUNC_PERIOD"}]
        predictions = [PredictionArtifact("sample-6", "C", "slang6", "ab", "ab", "ba", ("$ADD_PUNC_PERIOD", "$ADD_PUNC_PERIOD"), ({"start": 0, "end": 1, "source": "a", "target": "b", "tag": "$ADD_PUNC_PERIOD"}, {"start": 1, "end": 2, "source": "b", "target": "a", "tag": "$ADD_PUNC_PERIOD"}))]
        result = per_tag_metrics([row], predictions, condition="C")["$ADD_PUNC_PERIOD"]
        self.assertEqual(0, result["tp"])
        self.assertEqual(2, result["fp"])
        self.assertEqual(1, result["fn"])

    def test_repeated_same_boundary_edits_are_replayable_and_counted(self) -> None:
        row = fixture_row(7)
        row["gold_final_correct"] = "word7.."
        insertion = {"start": 5, "end": 5, "source": "", "target": ".", "tag": "$ADD_PUNC_PERIOD"}
        row["grammar_edits"] = [dict(insertion), dict(insertion)]
        predictions = [PredictionArtifact("sample-7", "C", "slang7", "word7", "word7", "word7..", ("$ADD_PUNC_PERIOD", "$ADD_PUNC_PERIOD"), (dict(insertion), dict(insertion)))]
        self.assertEqual("word7..", replay_edits("word7", row["grammar_edits"]))
        result = per_tag_metrics([row], predictions, condition="C")["$ADD_PUNC_PERIOD"]
        self.assertEqual(2, result["tp"])
        self.assertEqual(0, result["fp"])
        self.assertEqual(0, result["fn"])

    def test_metric_denominators_are_safe_on_empty_or_clean_inputs(self) -> None:
        result = normalization_metrics([], [])
        self.assertEqual(0.0, result["error_reduction_rate"])
        self.assertEqual(0.0, result["mean_damerau_distance_to_gold"])

    def test_prediction_routes_are_exact_and_bound(self) -> None:
        normalizer = lambda text: text.replace("slang", "word")
        gec = lambda text: (text if text.endswith(".") else text + ".", ("$ADD_PUNC_PERIOD",) if not text.endswith(".") else (), [{"start": len(text), "end": len(text), "source": "", "target": ".", "tag": "$ADD_PUNC_PERIOD"}] if not text.endswith(".") else [])
        predictions = route_samples(self.samples, normalizer=normalizer, gec=gec)
        bound = validate_prediction_bundle(self.samples, predictions, frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")
        self.assertEqual(9, len(bound))
        wrong_input = list(predictions)
        wrong_input[0] = PredictionArtifact(wrong_input[0].sample_id, wrong_input[0].condition, "tampered", wrong_input[0].normalizer_output, wrong_input[0].gec_input, wrong_input[0].gec_output, wrong_input[0].predicted_tags, wrong_input[0].predicted_edits, frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")
        with self.assertRaisesRegex(ValueError, "raw_input"):
            validate_prediction_bundle(self.samples, wrong_input, frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")
        with self.assertRaisesRegex(ValueError, "wrong frozen"):
            validate_prediction_bundle(self.samples, predictions, frozen_evaluation_sha256="other", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")
        with self.assertRaisesRegex(ValueError, "missing required routes"):
            validate_prediction_bundle(self.samples, predictions[:-1], frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")
        extra = PredictionArtifact("extra", "A", "extra", None, "extra", "extra", None, None, frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")
        with self.assertRaisesRegex(ValueError, "extra routes"):
            validate_prediction_bundle(self.samples, predictions + [extra], frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")

    def test_prediction_edit_spans_replay_nonoverlap_and_tag_binding(self) -> None:
        normalizer = lambda text: text.replace("slang", "word")
        gec = lambda text: (text if text.endswith(".") else text + ".", ("$ADD_PUNC_PERIOD",) if not text.endswith(".") else (), [{"start": len(text), "end": len(text), "source": "", "target": ".", "tag": "$ADD_PUNC_PERIOD"}] if not text.endswith(".") else [])
        predictions = route_samples(self.samples, normalizer=normalizer, gec=gec)
        original = predictions[1]
        bad_edit = dict(original.predicted_edits[0])
        bad_edit["source"] = "wrong"
        tampered = list(predictions)
        tampered[1] = PredictionArtifact(original.sample_id, original.condition, original.raw_input, original.normalizer_output, original.gec_input, original.gec_output, original.predicted_tags, (bad_edit,), frozen_evaluation_sha256=original.frozen_evaluation_sha256, normalizer_version=original.normalizer_version, gec_version=original.gec_version)
        with self.assertRaisesRegex(ValueError, "invalid predicted_edits"):
            validate_prediction_bundle(self.samples, tampered, frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")
        bad_tags = list(predictions)
        bad_tags[1] = PredictionArtifact(original.sample_id, original.condition, original.raw_input, original.normalizer_output, original.gec_input, original.gec_output, (), original.predicted_edits, frozen_evaluation_sha256=original.frozen_evaluation_sha256, normalizer_version=original.normalizer_version, gec_version=original.gec_version)
        with self.assertRaisesRegex(ValueError, "predicted_tags"):
            validate_prediction_bundle(self.samples, bad_tags, frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")

        out_of_bounds = list(predictions)
        out_of_bounds_edit = dict(original.predicted_edits[0])
        out_of_bounds_edit.update({"start": len(original.gec_input) + 1, "end": len(original.gec_input) + 1})
        out_of_bounds[1] = PredictionArtifact(original.sample_id, original.condition, original.raw_input, original.normalizer_output, original.gec_input, original.gec_output, ("$ADD_PUNC_PERIOD",), (out_of_bounds_edit,), frozen_evaluation_sha256=original.frozen_evaluation_sha256, normalizer_version=original.normalizer_version, gec_version=original.gec_version)
        with self.assertRaisesRegex(ValueError, "invalid predicted_edits"):
            validate_prediction_bundle(self.samples, out_of_bounds, frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")
        with self.assertRaisesRegex(ValueError, "invalid predicted_edits"):
            per_tag_metrics(self.samples, out_of_bounds, condition="B")

        overlapping = list(predictions)
        overlap_edit = {"start": 3, "end": 5, "source": "d1", "target": "x", "tag": "$ADD_PUNC_PERIOD"}
        overlapping[1] = PredictionArtifact(original.sample_id, original.condition, original.raw_input, original.normalizer_output, original.gec_input, original.gec_output, ("$ADD_PUNC_PERIOD", "$ADD_PUNC_PERIOD"), (overlap_edit, dict(overlap_edit)), frozen_evaluation_sha256=original.frozen_evaluation_sha256, normalizer_version=original.normalizer_version, gec_version=original.gec_version)
        with self.assertRaisesRegex(ValueError, "invalid predicted_edits"):
            validate_prediction_bundle(self.samples, overlapping, frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")

        noop = list(predictions)
        noop_edit = dict(original.predicted_edits[0])
        noop_edit["target"] = ""
        noop[1] = PredictionArtifact(original.sample_id, original.condition, original.raw_input, original.normalizer_output, original.gec_input, original.gec_output, ("$ADD_PUNC_PERIOD",), (noop_edit,), frozen_evaluation_sha256=original.frozen_evaluation_sha256, normalizer_version=original.normalizer_version, gec_version=original.gec_version)
        with self.assertRaisesRegex(ValueError, "invalid predicted_edits"):
            validate_prediction_bundle(self.samples, noop, frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")

        fabricated = list(predictions)
        fabricated_edit = dict(original.predicted_edits[0])
        fabricated_edit["tag"] = "$FABRICATED_TAG"
        fabricated[1] = PredictionArtifact(original.sample_id, original.condition, original.raw_input, original.normalizer_output, original.gec_input, original.gec_output, ("$FABRICATED_TAG",), (fabricated_edit,), frozen_evaluation_sha256=original.frozen_evaluation_sha256, normalizer_version=original.normalizer_version, gec_version=original.gec_version)
        with self.assertRaisesRegex(ValueError, "invalid predicted_edits|unregistered"):
            validate_prediction_bundle(self.samples, fabricated, frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")

    def test_prediction_artifact_round_trip_and_seeded_bootstrap(self) -> None:
        predictions = [PredictionArtifact("sample-1", "B", "slang1", "word1", "word1", "word1.", ("$ADD_PUNC_PERIOD",), ({"start": 5, "end": 5, "source": "", "target": ".", "tag": "$ADD_PUNC_PERIOD"},), frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "predictions.jsonl"
            write_prediction_artifact(path, predictions, metadata={"mode": "fixture"})
            metadata, loaded = load_prediction_artifact(path)
            self.assertEqual("fixture", metadata["mode"])
            self.assertEqual(predictions[0].as_dict(), loaded[0].as_dict())
            text_only_path = Path(directory) / "text-only.jsonl"
            text_only = PredictionArtifact("sample-2", "C", "slang2", "word2", "word2", "word2.", None, None, frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1")
            write_prediction_artifact(text_only_path, [text_only])
            _, text_only_loaded = load_prediction_artifact(text_only_path)
            self.assertIsNone(text_only_loaded[0].predicted_tags)
            self.assertIsNone(text_only_loaded[0].predicted_edits)
        rows = [fixture_row(1), fixture_row(2)]
        full = []
        for row in rows:
            full.extend([
                PredictionArtifact(row["sample_id"], "A", row["raw_informal"], None, row["raw_informal"], row["raw_informal"] + ".", None, [{"start": len(row["raw_informal"]), "end": len(row["raw_informal"]), "source": "", "target": ".", "tag": "$ADD_PUNC_PERIOD"}], frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1"),
                PredictionArtifact(row["sample_id"], "B", row["raw_informal"], row["gold_normalized_errorful"], row["gold_normalized_errorful"], row["gold_final_correct"], ("$ADD_PUNC_PERIOD",), [{"start": len(row["gold_normalized_errorful"]), "end": len(row["gold_normalized_errorful"]), "source": "", "target": ".", "tag": "$ADD_PUNC_PERIOD"}], frozen_evaluation_sha256="fixture-frozen-evaluation", normalizer_version="fixture-normalizer-v1", gec_version="fixture-gec-v1"),
            ])
        first = paired_bootstrap_delta(rows, full, n_resamples=30, seed=123)
        second = paired_bootstrap_delta(rows, full, n_resamples=30, seed=123)
        self.assertEqual(first, second)

    def test_prediction_artifact_partial_row_failure_cleans_unique_temp(self) -> None:
        valid = PredictionArtifact(
            "sample-1", "A", "raw", None, "raw", "raw.",
            ("$ADD_PUNC_PERIOD",),
            ({"start": 3, "end": 3, "source": "", "target": ".", "tag": "$ADD_PUNC_PERIOD"},),
            frozen_evaluation_sha256="fixture-frozen-evaluation",
            normalizer_version="fixture-normalizer-v1",
            gec_version="fixture-gec-v1",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "predictions.jsonl"
            broken = {
                "sample_id": "broken", "condition": "A", "raw_input": "raw",
                "normalizer_output": None, "gec_input": "raw", "gec_output": "raw.",
                "frozen_evaluation_sha256": "fixture-frozen-evaluation",
                "normalizer_version": "fixture-normalizer-v1", "gec_version": "fixture-gec-v1",
            }
            with self.assertRaisesRegex(ValueError, "model_version"):
                write_prediction_artifact(path, [valid, broken])
            self.assertFalse(path.exists())
            self.assertEqual([], list(root.glob(f".{path.name}.*.tmp")))

    def test_prediction_artifact_rejects_dangling_leaf_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "predictions.jsonl"
            target = root / "not-created.jsonl"
            try:
                path.symlink_to(target)
            except OSError:
                self.skipTest("filesystem does not support symlinks")
            with self.assertRaisesRegex(FileExistsError, "symlink"):
                write_prediction_artifact(path, [])
            self.assertTrue(path.is_symlink())
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
