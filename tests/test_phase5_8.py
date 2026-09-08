from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path

from src.geg.generators import generate_candidates
from src.geg.alignment import validate_replay
from scripts.build_pilot import _structurally_valid
from scripts.build_pilot import build_pilot
from src.geg.split import assign_group_splits


class SplitTests(unittest.TestCase):
    def test_group_assignment_is_deterministic_and_complete(self) -> None:
        groups = {"document:a": 10, "document:b": 7, "document:c": 3, "document:d": 2}
        fractions = {"train": 0.70, "dev": 0.15, "synthetic_test": 0.15}
        first = assign_group_splits(groups, fractions, 20260905)
        second = assign_group_splits(groups, fractions, 20260905)
        self.assertEqual(first, second)
        self.assertEqual(set(groups), set(first))
        self.assertEqual({"train", "dev", "synthetic_test"}, {item.split for item in first.values()})


class GeneratorTests(unittest.TestCase):
    def _find(self, text: str, tag: str):
        result = generate_candidates(text, tag)
        self.assertEqual("supported", result.status)
        self.assertTrue(result.candidates)
        return result.candidates[0]

    def test_ng_nang_is_inverse_and_complete_token_only(self) -> None:
        candidate = self._find("Kumain ng isda.", "$REPLACE_ng")
        self.assertEqual("Kumain nang isda.", candidate.source_text)
        self.assertEqual("Kumain ng isda.", candidate.target_text)
        self.assertEqual("ng", candidate.generation_operation["correct"])

    def test_enclitic_uses_previous_phonological_class(self) -> None:
        candidate = self._find("Pumunta ako rin.", "$REPLACE_rin")
        self.assertEqual("Pumunta ako din.", candidate.source_text)
        self.assertEqual("vowel", candidate.generation_operation["previous_final_class"])
        self.assertFalse(generate_candidates("Aalis rin.", "$REPLACE_rin").candidates)

    def test_punctuation_and_pronoun_direction(self) -> None:
        punctuation = self._find("Maayos.", "$ADD_PUNC_PERIOD")
        self.assertEqual("Maayos", punctuation.source_text)
        pronoun = self._find("Umalis siya kahapon.", "$REPLACE_siya")
        self.assertEqual("Umalis niya kahapon.", pronoun.source_text)
        self.assertEqual("medium", pronoun.confidence)

    def test_replay_alignment_and_spans_are_real(self) -> None:
        candidate = self._find("Nakita ang bata.", "$APPEND_t1")
        self.assertTrue(candidate.source_spans)
        self.assertTrue(candidate.target_spans)
        self.assertEqual(candidate.target_text, validate_replay(
            candidate.source_text, candidate.target_text, candidate.generation_operation
        ).replayed_target)
        valid, reason, alignment = _structurally_valid(candidate)
        self.assertTrue(valid, reason)
        self.assertTrue(alignment.success)
        self.assertEqual(candidate.source_spans, alignment.source_spans)
        self.assertEqual(candidate.target_spans, alignment.target_spans)

    def test_alignment_is_explicit_and_does_not_leak_between_calls(self) -> None:
        without = generate_candidates("Kumain ng isda.", "$REPLACE_ng", compute_alignment=False).candidates[0]
        with_alignment = generate_candidates("Kumain ng isda.", "$REPLACE_ng").candidates[0]
        self.assertEqual((), without.source_spans)
        self.assertEqual((), without.target_spans)
        self.assertTrue(with_alignment.source_spans)
        self.assertTrue(with_alignment.target_spans)

    def test_append_at_start_uses_explicit_start_anchor(self) -> None:
        candidate = self._find("Ang bata.", "$APPEND_t1")
        self.assertEqual("$START", candidate.generation_operation["anchor"])
        self.assertEqual("prepend", candidate.generation_operation["position"])
        self.assertIsNone(candidate.source_token_index)
        self.assertEqual("$START", candidate.generation_operation["source_token_index_sentinel"])
        self.assertEqual("bata.", candidate.source_text)
        self.assertTrue(validate_replay(
            candidate.source_text, candidate.target_text, candidate.generation_operation
        ).success)

        after_anchor = self._find("Nakita ang bata.", "$APPEND_t1")
        self.assertEqual("previous_token", after_anchor.generation_operation["anchor"])
        self.assertEqual(after_anchor.target_token_index - 1, after_anchor.source_token_index)
        self.assertEqual(after_anchor.source_token_index, after_anchor.generation_operation["source_token_index_anchor"])

    def test_casing_metadata_describes_actual_surface(self) -> None:
        candidate = self._find("Bata.", "$TRANSFORM_CASE_CAPITAL")
        self.assertEqual("Bata.", candidate.generation_operation["correct"])
        self.assertEqual("bata.", candidate.generation_operation["generated_wrong"])
        self.assertEqual("capitalize", candidate.generation_operation["direction"])

    def test_pilot_rejects_stale_capacity_dependency(self) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "split.parquet"
            pq.write_table(pa.table({
                "clean_id": ["x"], "text": ["Bata."], "split": ["train"],
                "source_corpus": ["test"], "publisher": ["p"], "source_doc_id": ["d"],
                "sqlite_table": ["sentences"], "sqlite_rowid": [1],
            }), input_path)
            capacity = root / "capacity.json"
            capacity.write_text(json.dumps({
                "input_sha256": "stale", "generator_version": "stale",
                "generator_sha256": "stale", "tags": [],
            }), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "stale capacity report"):
                build_pilot(
                    input_path, capacity, root / "pilot.parquet", root / "report.json",
                    root / "report.md", root / "review.jsonl",
                )

    def test_duplicate_and_missing_word_are_restricted_function_words(self) -> None:
        duplicate = self._find("Nakita ang bata.", "$DELETE")
        self.assertEqual("Nakita ang ang bata.", duplicate.source_text)
        missing = self._find("Nakita ang bata.", "$APPEND_t1")
        self.assertEqual("Nakita bata.", missing.source_text)
        self.assertFalse(generate_candidates("Nakita bata.", "$DELETE").candidates)

    def test_unavailable_resources_fail_closed(self) -> None:
        for tag in (
            "$MERGE_HYPHEN", "$TRANSFORM_INSERT_HYPHEN", "$TRANSFORM_SPLIT_HYPHEN",
            "$MERGE_SPACE", "$TRANSFORM_SPLIT_SPACE", "$TRANSFORM_VERB_COMPACT",
        ):
            result = generate_candidates("Nagsulat siya.", tag)
            self.assertEqual("unavailable", result.status)
            self.assertFalse(result.candidates)
            self.assertTrue(result.reason)

    def test_unregistered_tags_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            generate_candidates("Kumusta.", "$TRANSFORM_NOT_REGISTERED")


if __name__ == "__main__":
    unittest.main()
