from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.geg.config import config_hash
from src.geg.dataset import split_composition, total_composition, validate_candidate_row
from src.geg.generators import GENERATOR_VERSION, all_tag_ids, generate_candidates
from src.geg.hashing import sha256_file
from src.geg.hashing import sha256_files
from src.geg.review import ReviewGateError, review_manifest_template, validate_review_manifest
from scripts.build_candidates import _candidate_record
from scripts.build_candidates import build_candidate_shard
from scripts.build_dataset import _validate_candidate_dependencies, _validate_candidate_provenance, _verify_candidate_manifests, build_final_dataset


class Phase9ArithmeticTests(unittest.TestCase):
    def test_exact_balarila_total_arithmetic(self) -> None:
        config = {"dataset": {"target_total_pairs": 1_000_000, "counting_mode": "balarila_total", "errorful_fraction": 0.83}}
        self.assertEqual({"total": 1_000_000, "errorful": 830_000, "identity": 170_000}, total_composition(config))
        self.assertEqual({"train": 581_000, "dev": 124_500, "synthetic_test": 124_500}, split_composition(830_000))
        self.assertEqual({"train": 119_000, "dev": 25_500, "synthetic_test": 25_500}, split_composition(170_000))

    def test_candidate_replay_invariant(self) -> None:
        candidate = generate_candidates("Maayos.", "$ADD_PUNC_PERIOD").candidates[0]
        row = _candidate_record(
            {"clean_id": "c1", "text": candidate.target_text, "split": "train"},
            candidate, 20260905, "config",
        )
        self.assertEqual((candidate.source_text, candidate.target_text), validate_candidate_row(row))
        row["source_text"] = "tampered"
        with self.assertRaises(ValueError):
            validate_candidate_row(row)


class ReviewGateTests(unittest.TestCase):
    def _files(self, root: Path) -> tuple[Path, Path, Path]:
        report = root / "pilot_report.json"
        output = root / "pilot.parquet"
        sample = root / "sample.jsonl"
        report.write_text(json.dumps({"status": "complete", "produced_rows": 1}), encoding="utf-8")
        output.write_bytes(b"pilot")
        sample.write_text('{"pair_id":"x"}\n', encoding="utf-8")
        return report, output, sample

    def _manifest(self, root: Path, status: str = "complete", decision: str = "approve") -> Path:
        report, output, sample = self._files(root)
        payload = review_manifest_template(report, output, sample, expected_review_rows=1)
        payload["status"] = status
        payload["decision"] = decision
        payload["reviewer"] = "fixture"
        payload["adjudicator"] = "fixture-adjudicator"
        payload["reviewed_at"] = "2026-09-08T00:00:00+00:00"
        payload["reviewed_rows"] = 1
        payload["accepted_rows"] = 1
        payload["row_decisions"][0].update({"decision": "approve", "notes": "accepted fixture"})
        path = root / "review.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_review_states_and_hash_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report, output, sample = self._files(root)
            missing = validate_review_manifest(root / "missing.json", pilot_report_path=report, pilot_output_path=output, review_sample_path=sample, root=root)
            self.assertEqual("incomplete", missing.status)
            manifest = self._manifest(root)
            self.assertEqual("complete", validate_review_manifest(manifest, root=root).status)
            output.write_bytes(b"changed")
            self.assertEqual("stale", validate_review_manifest(manifest, root=root).status)

    def test_review_revise_and_reject_are_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            revise = self._manifest(root, "revise", "revise")
            self.assertEqual("revise", validate_review_manifest(revise, root=root).status)
            reject = self._manifest(root, "reject", "reject")
            self.assertEqual("reject", validate_review_manifest(reject, root=root).status)

    def test_review_requires_row_decisions_and_distinct_adjudicator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report, output, sample = self._files(root)
            payload = review_manifest_template(report, output, sample, expected_review_rows=1)
            payload.update({"status": "complete", "decision": "approve", "reviewer": "same", "adjudicator": "same", "reviewed_at": "2026-09-08T00:00:00+00:00", "reviewed_rows": 1, "accepted_rows": 1})
            payload["row_decisions"][0].update({"decision": "approve", "notes": "ok"})
            manifest = root / "review.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual("incomplete", validate_review_manifest(manifest, root=root).status)
            payload["adjudicator"] = "different"
            payload["row_decisions"][0]["sample_row_sha256"] = "0" * 64
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual("stale", validate_review_manifest(manifest, root=root).status)


class Phase10FixtureTests(unittest.TestCase):
    def test_final_builder_exact_fixture_and_overwrite_refusal(self) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "pilot_report.json"
            pilot = root / "pilot.parquet"
            sample = root / "sample.jsonl"
            report.write_text(json.dumps({"status": "complete", "produced_rows": 1}), encoding="utf-8")
            pilot.write_bytes(b"pilot")
            sample.write_text('{"pair_id":"x"}\n', encoding="utf-8")
            review = review_manifest_template(report, pilot, sample, expected_review_rows=1)
            review.update({"status": "complete", "decision": "approve", "reviewer": "fixture", "adjudicator": "fixture-adjudicator", "reviewed_at": "2026-09-08T00:00:00+00:00", "reviewed_rows": 1, "accepted_rows": 1})
            review["row_decisions"][0].update({"decision": "approve", "notes": "accepted fixture"})
            review_path = root / "review.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            review_hash = sha256_file(review_path)

            split_rows = []
            candidate_rows = []
            for split, count in (("train", 4), ("dev", 1), ("synthetic_test", 1)):
                for index in range(count):
                    clean_id = f"{split}-{index}"
                    text = f"Sentence {split} {index}."
                    split_rows.append({"clean_id": clean_id, "text": text, "split": split, "source_corpus": "fixture", "publisher": "fixture", "source_doc_id": clean_id, "sqlite_table": "sentences", "sqlite_rowid": index + 1})
                    candidate = generate_candidates(text, "$ADD_PUNC_PERIOD").candidates[0]
                    candidate_rows.append(_candidate_record(split_rows[-1], candidate, 20260905, "fixture"))
            split_input = root / "split.parquet"
            pq.write_table(pa.Table.from_pylist(split_rows), split_input)
            config_path = root / "config.json"
            config = {
                "dataset": {"target_total_pairs": 10, "counting_mode": "balarila_total", "errorful_fraction": 0.60},
                "stage_views": {"dataset1_errorful_share": 0.80},
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")
            candidate_dir = root / "candidates"
            candidate_dir.mkdir()
            shard = candidate_dir / "shard.parquet"
            config_hash_value = config_hash(config)
            for row in candidate_rows:
                row["config_hash"] = config_hash_value
            pq.write_table(pa.Table.from_pylist(candidate_rows), shard)
            generator_sha256 = sha256_files((Path("src/geg/generators.py").resolve(), Path("src/geg/alignment.py").resolve()))
            shard_manifest = {
                "status": "complete", "output": str(shard), "output_sha256": sha256_file(shard),
                "review_manifest": str(review_path), "review_manifest_sha256": review_hash, "capacity_report_sha256": "capacity", "quality_manifest_sha256": "quality", "split_report_sha256": "split-report", "input_sqlite_sha256": "sqlite", "input": str(split_input),
                "input_sha256": sha256_file(split_input), "config": str(config_path), "config_hash": config_hash_value,
                "generator_version": GENERATOR_VERSION, "generator_sha256": generator_sha256,
                "builder_version": "filly-phase9-sharded-v1", "candidate_builder_version": "filly-phase9-sharded-v1", "seed": 20260905,
                "tag_status": {tag: {"status": "fixture", "reason": ""} for tag in all_tag_ids()},
                "shard_index": 0, "shard_count": 1,
            }
            shard.with_suffix(".manifest.json").write_text(json.dumps(shard_manifest), encoding="utf-8")
            output = root / "final"
            report_out = build_final_dataset(
                candidate_dir, split_input, output,
                review_manifest_path=review_path,
                pilot_report_path=report,
                pilot_output_path=pilot,
                review_sample_path=sample,
                config_path=config_path,
                allow_development=True,
            )
            self.assertEqual(10, report_out["target_total_pairs"])
            self.assertEqual({"train": 7, "dev": 2, "synthetic_test": 1}, report_out["split_counts"])
            self.assertEqual(10, sum(report_out["split_counts"].values()))
            self.assertTrue((output / "manifest.json").exists())
            self.assertTrue((output / "train" / "final.parquet").exists())
            self.assertTrue((output / "dev" / "final.parquet").exists())
            self.assertTrue((output / "synthetic_test" / "final.parquet").exists())
            self.assertFalse((output / "dataset1_stage2.parquet").exists())
            self.assertFalse((output / "dataset2_stage3.parquet").exists())
            wrong_seed_output = root / "wrong-seed"
            with self.assertRaisesRegex(RuntimeError, "seed/builder-version"):
                build_final_dataset(
                    candidate_dir, split_input, wrong_seed_output,
                    review_manifest_path=review_path,
                    pilot_report_path=report,
                    pilot_output_path=pilot,
                    review_sample_path=sample,
                    config_path=config_path,
                    allow_development=True,
                    seed=999,
                )
            self.assertFalse(wrong_seed_output.exists())
            with self.assertRaises(FileExistsError):
                build_final_dataset(
                    candidate_dir, split_input, output,
                    review_manifest_path=review_path,
                    pilot_report_path=report,
                    pilot_output_path=pilot,
                    review_sample_path=sample,
                    config_path=config_path,
                    allow_development=True,
                )

    def test_pending_review_blocks_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocked = root / "blocked.json"
            output = root / "must-not-exist"
            with self.assertRaises(ReviewGateError):
                build_final_dataset(
                    root / "missing-candidates", root / "missing-split", output,
                    review_manifest_path=root / "missing-review.json",
                    pilot_report_path=root / "missing-report.json",
                    pilot_output_path=root / "missing-pilot.parquet",
                    review_sample_path=root / "missing-sample.jsonl",
                    blocked_report_path=blocked,
                )
            self.assertFalse(output.exists())
            self.assertEqual("incomplete", json.loads(blocked.read_text(encoding="utf-8"))["status"])

    def test_phase9_is_bounded_streamed_and_has_complete_tag_manifest(self) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "pilot_report.json"
            pilot = root / "pilot.parquet"
            sample = root / "sample.jsonl"
            report.write_text(json.dumps({"status": "complete"}), encoding="utf-8")
            pilot.write_bytes(b"pilot")
            sample.write_text('{"pair_id":"x"}\n', encoding="utf-8")
            review = review_manifest_template(report, pilot, sample, expected_review_rows=1)
            review.update({"status": "complete", "decision": "approve", "reviewer": "reviewer", "adjudicator": "adjudicator", "reviewed_at": "2026-09-08T00:00:00+00:00", "reviewed_rows": 1, "accepted_rows": 1})
            review["row_decisions"][0].update({"decision": "approve", "notes": "accepted"})
            review_path = root / "review.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")

            config = {"dataset": {"target_total_pairs": 10, "counting_mode": "balarila_total", "errorful_fraction": 0.6}}
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            split = root / "split.parquet"
            split_row = {"clean_id": "clean-1", "text": "Maayos.", "split": "train", "source_corpus": "fixture", "publisher": "fixture", "source_doc_id": "doc-1", "sqlite_table": "sentences", "sqlite_rowid": 1}
            pq.write_table(pa.Table.from_pylist([split_row]), split)
            generator_sha256 = sha256_files((Path("src/geg/generators.py").resolve(), Path("src/geg/alignment.py").resolve()))
            capacity = root / "capacity.json"
            capacity.write_text(json.dumps({
                "input_sha256": sha256_file(split), "config_hash": config_hash(config), "quality_manifest_sha256": "quality", "split_report_sha256": "split-report", "input_sqlite_sha256": "sqlite",
                "generator_version": GENERATOR_VERSION, "generator_sha256": generator_sha256,
                "tags": [{"tag": tag, "status": "supported" if tag == "$ADD_PUNC_PERIOD" else "unavailable", "candidates": 1 if tag == "$ADD_PUNC_PERIOD" else 0, "reason": "fixture"} for tag in all_tag_ids()],
            }), encoding="utf-8")
            output = root / "candidates" / "shard.parquet"
            manifest = build_candidate_shard(
                split, capacity, output, review_manifest_path=review_path,
                pilot_report_path=report, pilot_output_path=pilot,
                review_sample_path=sample, config_path=config_path,
                allow_development=True,
                shard_index=0, shard_count=1, max_rows=1,
            )
            self.assertEqual(1, manifest["candidate_rows"])
            self.assertEqual(set(all_tag_ids()), set(manifest["tag_counts"]))
            self.assertTrue(output.exists())
            self.assertFalse(Path(str(output) + ".lock").exists())
            self.assertFalse(any(path.name.startswith(".") for path in output.parent.iterdir()))
            unbounded = root / "candidates" / "unbounded.parquet"
            with self.assertRaisesRegex(ValueError, "explicit production shard bound"):
                build_candidate_shard(
                    split, capacity, unbounded, review_manifest_path=review_path,
                    pilot_report_path=report, pilot_output_path=pilot,
                    review_sample_path=sample, config_path=config_path,
                    allow_development=True,
                    shard_index=0, shard_count=1,
                )
            self.assertFalse(unbounded.exists())

    def test_phase10_rejects_incomplete_shards_and_bad_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            split = root / "split.parquet"
            split.write_bytes(b"split")
            shard = root / "shard-0.parquet"
            shard.write_bytes(b"candidate")
            generator_sha256 = sha256_files((Path("src/geg/generators.py").resolve(), Path("src/geg/alignment.py").resolve()))
            manifest = {
                "status": "complete", "output": str(shard), "output_sha256": sha256_file(shard),
                "input": str(split), "input_sha256": sha256_file(split), "config_hash": "config", "quality_manifest_sha256": "quality", "split_report_sha256": "split-report", "input_sqlite_sha256": "sqlite", "generator_version": GENERATOR_VERSION,
                "generator_sha256": generator_sha256, "builder_version": "filly-phase9-sharded-v1", "candidate_builder_version": "filly-phase9-sharded-v1", "seed": 20260905, "review_manifest": str(root / "review.json"), "review_manifest_sha256": "review", "capacity_report_sha256": "capacity", "config": str(root / "config.json"), "tag_status": {tag: {"status": "fixture", "reason": ""} for tag in all_tag_ids()}, "shard_index": 0, "shard_count": 2,
            }
            shard.with_suffix(".manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                _verify_candidate_manifests([shard], split_input=split, config_path=root / "config.json", review_manifest_path=root / "review.json", config_hash="config", review_manifest_sha256="review", seed=20260905)
            shard2 = root / "shard-1.parquet"
            shard2.write_bytes(b"candidate-2")
            manifest2 = dict(manifest)
            manifest2.update({"output": str(shard2), "output_sha256": sha256_file(shard2), "shard_index": 1, "seed": 999})
            shard2.with_suffix(".manifest.json").write_text(json.dumps(manifest2), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "seed/builder-version"):
                _verify_candidate_manifests([shard, shard2], split_input=split, config_path=root / "config.json", review_manifest_path=root / "review.json", config_hash="config", review_manifest_sha256="review", seed=20260905)
            manifest2.update({"seed": 20260905, "input_sqlite_sha256": "different-sqlite"})
            shard2.with_suffix(".manifest.json").write_text(json.dumps(manifest2), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "input SQLite"):
                _verify_candidate_manifests([shard, shard2], split_input=split, config_path=root / "config.json", review_manifest_path=root / "review.json", config_hash="config", review_manifest_sha256="review", seed=20260905)
            clean = {"clean-1": {"clean_id": "clean-1", "text": "Target.", "split": "train", "source_corpus": "fixture", "publisher": "fixture", "source_doc_id": "doc-1", "sqlite_table": "sentences", "sqlite_rowid": 1}}
            with self.assertRaisesRegex(RuntimeError, "target_text"):
                _validate_candidate_provenance({"clean_id": "clean-1", "target_text": "Tampered.", "split": "train", "source_corpus": "fixture", "publisher": "fixture", "source_doc_id": "doc-1", "sqlite_table": "sentences", "sqlite_rowid": 1}, clean)
            with self.assertRaisesRegex(RuntimeError, "seed mismatch"):
                _validate_candidate_dependencies({"pair_id": "pair", "seed": 999, "generator_version": GENERATOR_VERSION, "candidate_builder_version": "filly-phase9-sharded-v1", "config_hash": "config"}, seed=20260905, config_hash="config")


if __name__ == "__main__":
    unittest.main()
