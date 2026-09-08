"""Regression coverage for the comprehensive Phase 0-8 review."""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts import inspect_sqlite
from scripts.build_eligibility import build_report
from scripts.build_pilot import build_pilot
from scripts.export_sqlite import export
from scripts.import_unimorph_tgl import import_tsv
from scripts.split_base import split_parquet
from src.geg.artifacts import validate_destinations, verify_manifest
from src.geg.config import config_hash, load_config
from src.geg.generators import generate_candidates
from src.geg.hashing import sha256_file, sha256_files
from src.geg.ingest import RejectedSentence, connect_read_only, iter_sentence_rows, validate_row
from tests import test_phase0_4 as phase4_tests


@pytest.fixture
def database():
    path = phase4_tests.IngestTests()._fixture()
    yield path
    path.unlink()


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def test_inspector_cannot_overwrite_database(database, monkeypatch):
    before = database.read_bytes()
    monkeypatch.setattr("sys.argv", ["inspect_sqlite", str(database), "--output", str(database)])
    with pytest.raises(ValueError, match="aliases"):
        inspect_sqlite.main()
    assert database.read_bytes() == before


@pytest.mark.parametrize("collision", ["input_output", "input_report", "output_report"])
def test_importer_rejects_aliases(tmp_path, collision):
    source, output, report = (tmp_path / name for name in ("tgl.tsv", "out.jsonl", "report.json"))
    source.write_text("sulat\tnagsulat\tV;PFV;AF\n", encoding="utf-8")
    before = source.read_bytes()
    if collision == "input_output":
        output = source
    elif collision == "input_report":
        report = source
    else:
        report = output
    with pytest.raises(ValueError, match="aliases"):
        import_tsv(source, output, report)
    assert source.read_bytes() == before


@pytest.mark.parametrize("collision", ["artifact_report", "report_report", "source_report"])
def test_export_rejects_collisions_before_writing(database, tmp_path, collision):
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


def test_destination_hardlink_alias(tmp_path):
    source, alias = tmp_path / "source", tmp_path / "alias"
    source.write_bytes(b"preserve")
    try:
        alias.hardlink_to(source)
    except OSError:
        pytest.skip("filesystem does not support hard links")
    with pytest.raises(ValueError, match="aliases"):
        validate_destinations({"input": source}, {"output": alias})
    assert source.read_bytes() == b"preserve"


def test_pipeline_checks_quality_and_split_provenance(database, tmp_path, monkeypatch):
    base, manifest = tmp_path / "base.parquet", tmp_path / "manifest.json"
    export(database, base, report=tmp_path / "quality.json", run_manifest=manifest)
    changed = load_config(Path("config/filly.yaml"))
    changed["quality"]["max_characters"] = 1
    config = tmp_path / "changed.json"
    write_json(config, changed)
    split, split_report = tmp_path / "split.parquet", tmp_path / "split.json"
    with pytest.raises(RuntimeError, match="stale upstream configuration"):
        split_parquet(base, split, split_report, config, quality_manifest=manifest)
    assert not split.exists()
    split_parquet(base, split, split_report, quality_manifest=manifest)
    capacity = tmp_path / "capacity.json"
    with pytest.raises(RuntimeError, match="stale upstream configuration"):
        build_report(split, capacity, tmp_path / "capacity.md", config, split_report)
    assert not capacity.exists()
    build_report(split, capacity, tmp_path / "capacity.md", split_report=split_report)
    with monkeypatch.context() as m:
        m.setattr("scripts.build_pilot.PILOT_TARGETS", {"train": 1, "dev": 1, "synthetic_test": 1})
        result = build_pilot(split, capacity, tmp_path / "pilot.parquet", tmp_path / "pilot.json",
                             tmp_path / "pilot.md", tmp_path / "review.jsonl")
    assert result["produced_rows"] == 1
    assert result["quality_manifest_sha256"] == sha256_file(manifest)
    assert result["split_report_sha256"] == sha256_file(split_report)


@pytest.mark.parametrize("failure", ["missing", "blocked", "hash"])
def test_upstream_manifest_fail_closed(tmp_path, failure):
    artifact, manifest = tmp_path / "data", tmp_path / "manifest.json"
    artifact.write_bytes(b"data")
    if failure != "missing":
        write_json(manifest, {"status": "blocked" if failure == "blocked" else "complete",
                              "config_hash": "config", "output_sha256": "wrong"})
    with pytest.raises(RuntimeError):
        verify_manifest(manifest, artifact, "config")


def test_downstream_destinations_are_checked_before_input_reads(tmp_path):
    source = tmp_path / "missing.parquet"
    with pytest.raises(ValueError, match="aliases"):
        split_parquet(source, tmp_path / "out.parquet", source)
    with pytest.raises(ValueError, match="aliases"):
        build_report(source, source, tmp_path / "capacity.md")
    with pytest.raises(ValueError, match="aliases"):
        build_pilot(source, tmp_path / "capacity.json", tmp_path / "out.parquet",
                    tmp_path / "report.json", tmp_path / "report.md", source)


@pytest.mark.parametrize("target,tag", [
    ("Ikaw rin.", "$REPLACE_rin"), ("Okey raw.", "$REPLACE_raw"),
    ("Maaari din.", "$REPLACE_din"), ("Kapara daw.", "$REPLACE_daw"),
    ("Araw daw.", "$REPLACE_daw"), ("Biray din.", "$REPLACE_din"),
])
def test_enclitic_glides_and_exceptions(target, tag):
    candidates = generate_candidates(target, tag).candidates
    assert len(candidates) == 1
    assert candidates[0].target_text == target


def test_enclitic_wrong_target_is_not_accepted():
    assert not generate_candidates("Ikaw din.", "$REPLACE_din").candidates
    assert not generate_candidates("Okey daw.", "$REPLACE_daw").candidates
    assert not generate_candidates("Maaari rin.", "$REPLACE_rin").candidates


@pytest.mark.parametrize("ending,reject", [("lol", True), ("lol.", True), ("(LOL)!", True),
                                           ("omg!", True), ("lola.", False), ("Lolita.", False)])
def test_formality_punctuation(ending, reject):
    text = "Masaya ang bata " + ending
    path = phase4_tests.IngestTests()._fixture(sentence_text=text, normalized_text=text)
    connection = connect_read_only(path)
    try:
        row = next(iter_sentence_rows(connection))
        result = validate_row(row, quality_rules=load_config(Path("config/filly.yaml"))["quality"])
        assert isinstance(result, RejectedSentence) == reject
        if reject:
            assert "informal_marker" in result.reason_codes
    finally:
        connection.close()
        path.unlink()


def test_source_hash_is_relocatable_and_content_sensitive(tmp_path):
    first, second = tmp_path / "checkout-a", tmp_path / "checkout-b"
    for root in (first, second):
        (root / "src").mkdir(parents=True)
        (root / "src/a.py").write_bytes(b"a")
        (root / "src/b.py").write_bytes(b"b")
    paths = lambda root: (root / "src/a.py", root / "src/b.py")
    original = sha256_files(paths(first), root=first)
    assert original == sha256_files(tuple(reversed(paths(second))), root=second)
    (second / "src/a.py").write_bytes(b"changed")
    assert original != sha256_files(paths(second), root=second)


@pytest.mark.parametrize("requested", [3000, 3500])
def test_pilot_refills_after_structural_rejections(tmp_path, monkeypatch, requested):
    # ADD_PERIOD has 3,000 census positions, but removing the detached period
    # leaves trailing whitespace. CASE_CAPITAL has 3,000 valid unique pairs.
    rows = [dict(clean_id=str(i), text=f"Bata {i} .", split="train", source_corpus="test",
                 publisher="p", source_doc_id=str(i), sqlite_table="sentences", sqlite_rowid=i)
            for i in range(3000)]
    source, split_report = tmp_path / "split.parquet", tmp_path / "split.json"
    pq.write_table(pa.Table.from_pylist(rows), source)
    write_json(split_report, {"status": "complete", "config_hash": config_hash(load_config(Path("config/filly.yaml"))),
                              "output_sha256": sha256_file(source), "quality_manifest_sha256": "fixture"})
    tags = ("$ADD_PUNC_PERIOD", "$TRANSFORM_CASE_CAPITAL")
    monkeypatch.setattr("scripts.build_eligibility.all_tag_ids", lambda: tags)
    capacity = tmp_path / "capacity.json"
    census = build_report(source, capacity, tmp_path / "capacity.md", split_report=split_report)
    assert all(row["candidates_by_split"] == {"train": 3000} for row in census["tags"])
    monkeypatch.setattr("scripts.build_pilot.PILOT_TARGETS", {"train": requested})
    output = tmp_path / "pilot.parquet"
    result = build_pilot(source, capacity, output, tmp_path / "pilot.json", tmp_path / "pilot.md", tmp_path / "review.jsonl")
    assert result["refill_performed"]
    assert result["status"] == ("complete" if requested == 3000 else "shortfall")
    assert result["shortfall"] == requested - 3000
    assert result["produced_rows"] == result["split_counts"]["train"] == 3000
    table = pq.read_table(output).to_pylist()
    assert len({(row["source_text"], row["target_text"]) for row in table}) == 3000
