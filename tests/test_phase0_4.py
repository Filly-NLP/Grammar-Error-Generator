from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.export_sqlite import export
from scripts.import_unimorph_tgl import import_tsv
from src.geg.ingest import assert_unique_normalized_text, connect_read_only, normalize_text
from src.geg.morphology import map_unimorph_features
from src.geg.states import state_by_id, states
from src.geg.tags import registry, require_registered


class RegistryTests(unittest.TestCase):
    def test_table2_has_exactly_39_unique_labels(self) -> None:
        values = registry()
        self.assertEqual(39, len(values))
        self.assertEqual(39, len({value.id for value in values}))

    def test_unknown_tag_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            require_registered("$TRANSFORM_NOT_BALARILA")

    def test_table3_has_source_only_imperative_states(self) -> None:
        values = states()
        self.assertEqual(10, len(values))
        self.assertFalse(state_by_id("IMPACT").can_be_target)
        self.assertFalse(state_by_id("IMPOBJ").can_be_target)
        self.assertIsNone(state_by_id("IMPACT").correction_tag)
        self.assertIsNotNone(state_by_id("COMPACT").correction_tag)


class MorphologyTests(unittest.TestCase):
    def test_provisional_completed_actor_mapping(self) -> None:
        mapping = map_unimorph_features("V;PFV;AF")
        self.assertEqual("COMPACT", mapping.state)
        self.assertEqual("provisional", mapping.confidence)

    def test_imperative_is_source_only_candidate(self) -> None:
        mapping = map_unimorph_features("V;IMP;OF")
        self.assertEqual("IMPOBJ", mapping.state)

    def test_unknown_feature_bundle_is_not_invented(self) -> None:
        self.assertIsNone(map_unimorph_features("V;MYSTERY").state)


class IngestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._repository_reports = {
            path: path.read_bytes() if path.exists() else None
            for path in (
                Path("reports/quality_report.json"),
                Path("reports/run_manifest.json"),
                Path("reports/upstream_integrity_report.json"),
            )
        }

    @classmethod
    def tearDownClass(cls) -> None:
        for path, before in cls._repository_reports.items():
            after = path.read_bytes() if path.exists() else None
            if after != before:
                raise AssertionError(f"test mutated repository report: {path}")
        super().tearDownClass()

    def _fixture(self, duplicate: bool = False) -> Path:
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        path = Path(handle.name)
        connection = sqlite3.connect(path)
        connection.executescript(
            """
            CREATE TABLE sentences (
              sentence_id TEXT PRIMARY KEY, article_id TEXT NOT NULL, source_id TEXT NOT NULL,
              sentence_index INTEGER NOT NULL, paragraph_index INTEGER NOT NULL,
              sentence_text TEXT NOT NULL, normalized_text TEXT NOT NULL, language TEXT,
              language_confidence REAL, token_count INTEGER NOT NULL, quality_score REAL NOT NULL,
              is_quote INTEGER NOT NULL, is_headline INTEGER NOT NULL, content_hash TEXT NOT NULL,
              is_duplicate INTEGER NOT NULL, duplicate_group_id TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE articles (
              article_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, url TEXT NOT NULL,
              canonical_url TEXT, publication_date TEXT, headline TEXT
            );
            CREATE TABLE sources (source_id TEXT PRIMARY KEY, name TEXT, domain TEXT);
            """
        )
        connection.execute("INSERT INTO sources VALUES ('s1','Test Publisher','test.example')")
        connection.execute("INSERT INTO articles VALUES ('a1','s1','https://example.test/a',NULL,'2026-01-01','Headline')")
        rows = [
            ('x1', 'a1', 's1', 0, 0, '  Kumusta\nsa mundo! ', 'Kumusta sa mundo!', 'fil', 0.99, 3, 1.0, 0, 0, 'h1', 0, None, 'now'),
        ]
        if duplicate:
            rows.append(('x2', 'a1', 's1', 1, 0, 'Other', 'Kumusta sa mundo!', 'fil', 0.99, 3, 1.0, 0, 0, 'h2', 0, None, 'now'))
        connection.executemany("INSERT INTO sentences VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        connection.commit()
        connection.close()
        return path

    def test_normalization_and_read_only_connection(self) -> None:
        self.assertEqual("á b", normalize_text("  á\n b "))
        path = self._fixture()
        connection = connect_read_only(path)
        try:
            self.assertTrue(assert_unique_normalized_text(connection)["passed"])
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("UPDATE sentences SET sentence_text='x'")
        finally:
            connection.close()

    def test_duplicate_contract_is_detected(self) -> None:
        path = self._fixture(duplicate=True)
        connection = connect_read_only(path)
        try:
            result = assert_unique_normalized_text(connection)
            self.assertFalse(result["passed"])
            self.assertEqual(1, result["duplicate_rows"])
        finally:
            connection.close()

    def test_jsonl_export_is_traceable_and_does_not_change_source(self) -> None:
        path = self._fixture()
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = export(
                path, root / "clean.jsonl", root / "quarantine.jsonl", root / "report.json",
                "jsonl", 1, None, run_manifest=root / "manifest.json",
            )
            self.assertEqual(1, result["rows_exported"])
            record = json.loads((root / "clean.jsonl").read_text(encoding="utf-8"))
            self.assertEqual("x1", record["clean_id"])
            self.assertEqual("a1", record["source_doc_id"])
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_export_fails_before_writing_on_duplicate_contract_violation(self) -> None:
        path = self._fixture(duplicate=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(RuntimeError):
                export(
                    path, root / "clean.jsonl", root / "quarantine.jsonl", root / "report.json",
                    "jsonl", 1, None, run_manifest=root / "manifest.json",
                )
            self.assertFalse((root / "clean.jsonl").exists())
            report = json.loads((root / "report.json").read_text(encoding="utf-8"))
            self.assertFalse(report["uniqueness"]["passed"])


class ImporterTests(unittest.TestCase):
    def test_importer_emits_reviewable_mapping_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tgl.tsv"
            source.write_text("sulat\tnagsulat\tV;PFV;AF\n", encoding="utf-8")
            output = root / "mapping.jsonl"
            report = root / "report.json"
            result = import_tsv(source, output, report)
            self.assertEqual(1, result["rows_emitted"])
            row = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("needs_review", row["review_status"])
            self.assertFalse(json.loads(report.read_text(encoding="utf-8"))["resource_frozen"])


if __name__ == "__main__":
    unittest.main()
