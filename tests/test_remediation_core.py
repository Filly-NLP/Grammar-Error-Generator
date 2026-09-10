from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from src.geg.config import resolve_runtime_config, validate_config
from src.geg import resource_freeze
from src.geg.generators import GeneratorContext, all_tag_ids, generate_candidates, production_coverage
from src.geg.hashing import generator_dependency_hash
from src.geg.resource_freeze import freeze_constructions, freeze_morphology, freeze_punctuation_context
from scripts.evaluate_predictions import resolve_evaluation_seed


class RemediationCoreTests(unittest.TestCase):
    @staticmethod
    def _context(*, morphology_rows=(), morphology_manifest=None, punctuation_rows=(), punctuation_manifest=None, by_state=None):
        morphology_rows = tuple(MappingProxyType(dict(row)) for row in morphology_rows)
        punctuation_rows = tuple(MappingProxyType(dict(row)) for row in punctuation_rows)
        by_lemma = {}
        by_surface = {}
        for row in morphology_rows:
            by_lemma.setdefault(str(row["lemma"]), []).append(row)
            by_surface.setdefault(str(row["surface"]), []).append(row)
        by_tag = {}
        for row in punctuation_rows:
            by_tag.setdefault(str(row["correction_tag"]), []).append(row)
        return GeneratorContext(
            morphology_rows=morphology_rows,
            morphology_manifest=MappingProxyType(dict(morphology_manifest or {})),
            morphology_by_lemma=MappingProxyType({key: tuple(value) for key, value in by_lemma.items()}),
            morphology_by_state=by_state if by_state is not None else MappingProxyType({}),
            morphology_by_surface=MappingProxyType({key: tuple(value) for key, value in by_surface.items()}),
            construction_rows=(),
            construction_manifest=MappingProxyType({}),
            constructions_by_tag=MappingProxyType({}),
            punctuation_rows=punctuation_rows,
            punctuation_manifest=MappingProxyType(dict(punctuation_manifest or {})),
            punctuation_by_tag=MappingProxyType({key: tuple(value) for key, value in by_tag.items()}),
        )

    def test_config_resolves_authoritative_seed_and_custom_ratios(self) -> None:
        config = {
            "project": {"seed": 7},
            "dataset": {"target_total_pairs": 10, "counting_mode": "balarila_total", "errorful_fraction": 0.6, "identity_fraction": 0.4},
            "splits": {"train": 0.6, "dev": 0.2, "synthetic_test": 0.2, "group_by_document": False},
            "stage_views": {"dataset1_errorful_share": 0.8, "dataset2_errorful_share": 0.2},
            "morphology": {"minimum_validated_states_per_lemma": 3},
            "balarila": {"table2_tag_count": 39},
        }
        resolved = resolve_runtime_config(config)
        self.assertEqual(7, resolved["runtime"]["seed"])
        self.assertEqual("0.6", resolved["runtime"]["split_fractions"]["train"])
        self.assertFalse(resolved["runtime"]["group_by_document"])

    def test_invalid_ratio_sum_fails_before_runtime(self) -> None:
        config = {
            "project": {"seed": 7},
            "dataset": {"target_total_pairs": 10, "counting_mode": "balarila_total", "errorful_fraction": 0.6, "identity_fraction": 0.3},
            "splits": {"train": 0.6, "dev": 0.2, "synthetic_test": 0.2},
            "stage_views": {"dataset1_errorful_share": 0.8, "dataset2_errorful_share": 0.2},
            "morphology": {"minimum_validated_states_per_lemma": 3},
            "balarila": {"table2_tag_count": 39},
        }
        with self.assertRaises(ValueError):
            validate_config(config)

    def test_evaluation_cli_seed_uses_config_unless_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({
                "project": {"seed": 41},
                "dataset": {"target_total_pairs": 10, "counting_mode": "balarila_total", "errorful_fraction": 0.6, "identity_fraction": 0.4},
                "splits": {"train": 0.6, "dev": 0.2, "synthetic_test": 0.2},
                "stage_views": {"dataset1_errorful_share": 0.8, "dataset2_errorful_share": 0.2},
                "morphology": {"minimum_validated_states_per_lemma": 3},
                "balarila": {"table2_tag_count": 39},
            }), encoding="utf-8")
            self.assertEqual(41, resolve_evaluation_seed(path))
            self.assertEqual(99, resolve_evaluation_seed(path, 99))

    def test_dependency_hash_is_cwd_independent(self) -> None:
        expected = generator_dependency_hash()
        original = Path.cwd()
        try:
            os.chdir(tempfile.gettempdir())
            self.assertEqual(expected, generator_dependency_hash())
        finally:
            os.chdir(original)

    def test_all_registered_tags_have_implementation_paths(self) -> None:
        coverage = production_coverage()
        self.assertEqual(39, len(all_tag_ids()))
        self.assertEqual(39, len(coverage))
        self.assertTrue(all(item["implemented"] for item in coverage.values()))

    def test_morphology_freeze_rejects_unreviewed_and_enforces_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mapping.jsonl"
            source.write_text(json.dumps({"lemma": "sulat", "surface": "sulat", "balarila_state": "BASE", "review_status": "needs_review"}) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                freeze_morphology(source, root / "resource.jsonl", root / "manifest.json", reviewer="r", reviewed_at="2026-09-10T00:00:00+00:00", source_resource="test", source_version="1", license_text="test", mapping_rule_version="1")

    def test_resource_backed_families_fail_closed_without_approved_resource(self) -> None:
        for tag in ("$MERGE_HYPHEN", "$MERGE_SPACE", "$TRANSFORM_VERB_COMPACT"):
            result = generate_candidates("Nagsulat siya.", tag)
            self.assertEqual("unavailable", result.status)

    def test_punctuation_freeze_requires_context_and_tag_consistent_single_terminal_mark(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "punctuation.jsonl"
            source.write_text(json.dumps({
                "context": "Masaya",
                "correct_surface": "Masaya.",
                "generated_wrong_surface": "Masaya?",
                "correction_tag": "$CHANGE_PUNC_PERIOD",
                "review_status": "approved",
            }) + "\n", encoding="utf-8")
            result = freeze_punctuation_context(
                source, root / "resource.jsonl", root / "manifest.json",
                reviewer="reviewer", reviewed_at="2026-09-10T00:00:00+00:00",
                source_resource="test", source_version="1", license_text="test",
            )
            self.assertEqual("filipino-punctuation-context-v1", result["resource_version"])
            self.assertTrue((root / "resource.jsonl").is_file())
            self.assertTrue((root / "manifest.json").is_file())
            frozen_row = json.loads((root / "resource.jsonl").read_text(encoding="utf-8").strip())
            self.assertEqual({"context": "Masaya", "correct_surface": ".", "generated_wrong_surface": "?"}, {
                key: frozen_row[key] for key in ("context", "correct_surface", "generated_wrong_surface")
            })

            invalid_rows = [
                {"context": "Malungkot?", "correct_surface": ".", "generated_wrong_surface": "?", "correction_tag": "$CHANGE_PUNC_PERIOD", "review_status": "approved"},
                {"context": "Masaya", "correct_surface": "?", "generated_wrong_surface": ".", "correction_tag": "$CHANGE_PUNC_PERIOD", "review_status": "approved"},
                {"context": "Masaya", "correct_surface": ".", "generated_wrong_surface": "!?", "correction_tag": "$CHANGE_PUNC_PERIOD", "review_status": "approved"},
            ]
            for number, row in enumerate(invalid_rows, 1):
                invalid = root / f"invalid-{number}.jsonl"
                invalid.write_text(json.dumps(row) + "\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    freeze_punctuation_context(
                        invalid, root / f"invalid-{number}.resource.jsonl", root / f"invalid-{number}.manifest.json",
                        reviewer="reviewer", reviewed_at="2026-09-10T00:00:00+00:00",
                        source_resource="test", source_version="1", license_text="test",
                    )

    def test_punctuation_matches_exact_reviewed_context_and_rejects_adversarial_sentences(self) -> None:
        context = self._context(
            punctuation_rows=(
                {"context": "Masaya", "correct_surface": ".", "generated_wrong_surface": "?", "correction_tag": "$CHANGE_PUNC_PERIOD", "review_status": "approved", "resource_version": "punct-v1"},
            ),
            punctuation_manifest={"resource_version": "punct-v1"},
        )
        matching = generate_candidates("Masaya.", "$CHANGE_PUNC_PERIOD", context=context)
        self.assertEqual(("Masaya?",), tuple(candidate.source_text for candidate in matching.candidates))
        self.assertEqual("Masaya", matching.candidates[0].generation_operation["context"])
        for sentence in ("Malungkot.", "Malungkot?", "Masaya!", "Masayang."):
            self.assertFalse(generate_candidates(sentence, "$CHANGE_PUNC_PERIOD", context=context).candidates)

    def test_morphology_uses_exact_surface_index_before_state_rows(self) -> None:
        class ExplodingStateIndex(dict):
            def get(self, *args, **kwargs):
                raise AssertionError("morphology generation scanned the state index")

        rows = (
            {"lemma": "sulat", "surface": "sumulat", "balarila_state": "COMPACT", "review_status": "approved"},
            {"lemma": "sulat", "surface": "susulat", "balarila_state": "CONTACT", "review_status": "approved"},
            {"lemma": "ibang", "surface": "iba", "balarila_state": "COMPACT", "review_status": "approved"},
        )
        context = self._context(
            morphology_rows=rows,
            morphology_manifest={"resource_version": "morph-v1"},
            by_state=ExplodingStateIndex(),
        )
        result = generate_candidates("sumulat siya.", "$TRANSFORM_VERB_COMPACT", context=context)
        self.assertEqual(("susulat siya.",), tuple(candidate.source_text for candidate in result.candidates))
        candidate = result.candidates[0]
        self.assertEqual("sulat", candidate.morphology_lemma)
        self.assertEqual("CONTACT", candidate.morphology_source_state)
        self.assertEqual("COMPACT", candidate.morphology_target_state)
        self.assertEqual("morph-v1", candidate.morphology_resource_version)

    def test_resource_pair_rolls_back_first_publication_when_manifest_loses_race(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "construction.jsonl"
            source.write_text(json.dumps({
                "correct_surface": "pag-aaral",
                "generated_wrong_surface": "pag aaral",
                "correction_tag": "$MERGE_HYPHEN",
                "family": "hyphen",
                "review_status": "approved",
            }) + "\n", encoding="utf-8")
            resource_path = root / "resource.jsonl"
            manifest_path = root / "manifest.json"
            real_link = resource_freeze.os.link
            calls = 0

            def link_once_then_lose(source_path, destination_path):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise FileExistsError("simulated manifest race")
                return real_link(source_path, destination_path)

            with patch.object(resource_freeze.os, "link", side_effect=link_once_then_lose):
                with self.assertRaises(FileExistsError):
                    freeze_constructions(
                        source, resource_path, manifest_path,
                        reviewer="reviewer", reviewed_at="2026-09-10T00:00:00+00:00",
                        source_resource="test", source_version="1", license_text="test",
                    )
            self.assertFalse(resource_path.exists())
            self.assertFalse(manifest_path.exists())
