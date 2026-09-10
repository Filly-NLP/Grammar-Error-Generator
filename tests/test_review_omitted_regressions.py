"""Regression coverage restored from the post-Phase-8 review branch."""

import json
import sqlite3
from itertools import combinations
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts import import_unimorph_tgl
from scripts.build_eligibility import build_report
from scripts.build_pilot import build_pilot
from scripts.export_sqlite import export
from scripts.split_base import split_parquet
from src.geg.config import config_hash, load_config
from src.geg.hashing import sha256_file
from src.geg.ingest import RejectedSentence, connect_read_only, iter_sentence_rows, validate_row


def _paths(tmp_path: Path, names: tuple[str, ...]) -> dict[str, Path]:
    return {name: tmp_path / f"missing-{name}" for name in names}


def _collision_outputs(paths: dict[str, Path], output_names: tuple[str, ...], first: str, second: str) -> dict[str, Path]:
    outputs = {name: paths[name] for name in output_names}
    outputs[first] = paths[second]
    return outputs


def _assert_outputs_absent(outputs: dict[str, Path]) -> None:
    assert all(not path.exists() for path in outputs.values())


@pytest.mark.parametrize(
    "first,second",
    [*combinations(("output", "report"), 2), *[(output, input_name) for output in ("output", "report") for input_name in ("config", "quality_manifest")]],
)
def test_split_destination_matrix_rejects_before_reading(tmp_path: Path, first: str, second: str) -> None:
    paths = _paths(tmp_path, ("input", "output", "report", "config", "quality_manifest"))
    outputs = _collision_outputs(paths, ("output", "report"), first, second)
    with pytest.raises(ValueError, match="aliases"):
        split_parquet(paths["input"], outputs["output"], outputs["report"], paths["config"], quality_manifest=paths["quality_manifest"])
    _assert_outputs_absent(outputs)


@pytest.mark.parametrize(
    "first,second",
    [*combinations(("json_report", "markdown_report"), 2), *[(output, input_name) for output in ("json_report", "markdown_report") for input_name in ("config", "split_report")]],
)
def test_capacity_destination_matrix_rejects_before_reading(tmp_path: Path, first: str, second: str) -> None:
    paths = _paths(tmp_path, ("input", "json_report", "markdown_report", "config", "split_report"))
    outputs = _collision_outputs(paths, ("json_report", "markdown_report"), first, second)
    with pytest.raises(ValueError, match="aliases"):
        build_report(paths["input"], outputs["json_report"], outputs["markdown_report"], paths["config"], paths["split_report"])
    _assert_outputs_absent(outputs)


@pytest.mark.parametrize(
    "first,second",
    [*combinations(("output", "json_report", "markdown_report", "review_sample"), 2), *[(output, input_name) for output in ("output", "json_report", "markdown_report", "review_sample") for input_name in ("config", "capacity_report")]],
)
def test_pilot_destination_matrix_rejects_before_reading(tmp_path: Path, first: str, second: str) -> None:
    names = ("input", "capacity_report", "output", "json_report", "markdown_report", "review_sample", "config")
    paths = _paths(tmp_path, names)
    outputs = _collision_outputs(paths, ("output", "json_report", "markdown_report", "review_sample"), first, second)
    with pytest.raises(ValueError, match="aliases"):
        build_pilot(paths["input"], paths["capacity_report"], outputs["output"], outputs["json_report"], outputs["markdown_report"], outputs["review_sample"], config_path=paths["config"])
    _assert_outputs_absent(outputs)


@pytest.mark.parametrize("collision", ("input_output", "input_report", "output_report"))
def test_importer_collision_matrix_preserves_input(tmp_path: Path, collision: str) -> None:
    source = tmp_path / "tgl.tsv"
    output = tmp_path / "out.jsonl"
    report = tmp_path / "report.json"
    source.write_text("sulat\tnagsulat\tV;PFV;AF\n", encoding="utf-8")
    before = source.read_bytes()
    if collision == "input_output":
        output = source
    elif collision == "input_report":
        report = source
    else:
        report = output
    with pytest.raises(ValueError, match="aliases"):
        import_unimorph_tgl.import_tsv(source, output, report)
    assert source.read_bytes() == before


def _fixture_database(tmp_path: Path) -> Path:
    database = tmp_path / "corpus.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """CREATE TABLE sentences (
              sentence_id TEXT PRIMARY KEY, article_id TEXT NOT NULL, source_id TEXT NOT NULL,
              sentence_index INTEGER NOT NULL, paragraph_index INTEGER NOT NULL,
              sentence_text TEXT NOT NULL, normalized_text TEXT NOT NULL, language TEXT,
              language_confidence REAL, token_count INTEGER NOT NULL, quality_score REAL NOT NULL,
              is_quote INTEGER NOT NULL, is_headline INTEGER NOT NULL, content_hash TEXT NOT NULL,
              is_duplicate INTEGER NOT NULL, duplicate_group_id TEXT, created_at TEXT NOT NULL,
              publication_date TEXT, source_name TEXT, source_domain TEXT, canonical_url TEXT,
              article_url TEXT
            );
            CREATE TABLE articles (
              article_id TEXT PRIMARY KEY, url TEXT, canonical_url TEXT,
              publication_date TEXT, headline TEXT
            );
            CREATE TABLE sources (
              source_id TEXT PRIMARY KEY, name TEXT, domain TEXT
            );
            INSERT INTO articles VALUES ('a1', NULL, NULL, '2026-01-01', NULL);
            INSERT INTO sources VALUES ('src', 'publisher', 'example.test');
            INSERT INTO sentences VALUES
            ('s1','a1','src',0,0,'Maayos.','Maayos.','FILIPINO',0.99,1,1,0,0,'h1',0,NULL,'2026-01-01',NULL,NULL,'publisher',NULL,NULL);
            """
        )
    return database


@pytest.mark.parametrize("collision", ("artifact_report", "report_report", "source_report"))
def test_export_collision_matrix_rejects_before_writing(tmp_path: Path, collision: str) -> None:
    database = _fixture_database(tmp_path)
    output = tmp_path / "clean.parquet"
    report = tmp_path / "quality.json"
    manifest = tmp_path / "manifest.json"
    if collision == "artifact_report":
        report = output
    elif collision == "report_report":
        manifest = report
    else:
        report = database
    before = database.read_bytes()
    with pytest.raises(ValueError, match="aliases"):
        export(database, output, report=report, run_manifest=manifest)
    assert database.read_bytes() == before
    assert not output.exists()


@pytest.mark.parametrize("ending,reject", (("lol", True), ("lol.", True), ("(LOL)!", True), ("omg!", True), ("lola.", False), ("Lolita.", False)))
def test_formality_markers_are_punctuation_safe(tmp_path: Path, ending: str, reject: bool) -> None:
    database = _fixture_database(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE sentences SET sentence_text=?, normalized_text=?", (f"Masaya ang bata {ending}", f"Masaya ang bata {ending}"))
    connection = connect_read_only(database)
    try:
        result = validate_row(next(iter_sentence_rows(connection)), quality_rules=load_config(Path("config/filly.yaml"))["quality"])
        assert isinstance(result, RejectedSentence) == reject
        if reject:
            assert "informal_marker" in result.reason_codes
    finally:
        connection.close()


@pytest.mark.parametrize("requested", (3000, 3500))
def test_pilot_refills_after_structural_rejections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, requested: int) -> None:
    rows = [dict(clean_id=str(i), text=f"Bata {i} .", split="train", source_corpus="test", publisher="p", source_doc_id=str(i), sqlite_table="sentences", sqlite_rowid=i) for i in range(3000)]
    source, split_report = tmp_path / "split.parquet", tmp_path / "split.json"
    pq.write_table(pa.Table.from_pylist(rows), source)
    write = lambda path, value: path.write_text(json.dumps(value), encoding="utf-8")
    write(split_report, {"status": "complete", "config_hash": config_hash(load_config(Path("config/filly.yaml"))), "output_sha256": sha256_file(source), "quality_manifest_sha256": "fixture", "input_sqlite_sha256": "sqlite"})
    tags = ("$ADD_PUNC_PERIOD", "$TRANSFORM_CASE_CAPITAL")
    monkeypatch.setattr("scripts.build_eligibility.all_tag_ids", lambda: tags)
    capacity = tmp_path / "capacity.json"
    census = build_report(source, capacity, tmp_path / "capacity.md", split_report=split_report)
    assert all(row["candidates_by_split"] == {"train": 3000} for row in census["tags"])
    monkeypatch.setattr("scripts.build_pilot.PILOT_TARGETS", {"train": requested})
    result = build_pilot(source, capacity, tmp_path / "pilot.parquet", tmp_path / "pilot.json", tmp_path / "pilot.md", tmp_path / "review.jsonl")
    assert result["refill_performed"]
    assert result["status"] == ("complete" if requested == 3000 else "shortfall")
    assert result["shortfall"] == requested - 3000
    assert result["produced_rows"] == result["split_counts"]["train"] == 3000
    table = pq.read_table(tmp_path / "pilot.parquet").to_pylist()
    assert len({(row["source_text"], row["target_text"]) for row in table}) == 3000
