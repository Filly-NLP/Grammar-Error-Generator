"""Focused regression coverage for the post-Phase-8 review integration."""

import json
from pathlib import Path

import pytest

from scripts import inspect_sqlite
from scripts.evaluate_predictions import main as evaluate_predictions_main
from src.geg.artifacts import validate_destinations
from src.geg.generators import generate_candidates
from src.geg.hashing import sha256_files


@pytest.mark.parametrize(
    "target,tag",
    [
        ("Ikaw rin.", "$REPLACE_rin"),
        ("Okey raw.", "$REPLACE_raw"),
        ("Maaari din.", "$REPLACE_din"),
        ("Kapara daw.", "$REPLACE_daw"),
        ("Araw daw.", "$REPLACE_daw"),
        ("Biray din.", "$REPLACE_din"),
    ],
)
def test_enclitic_glides_and_exceptions(target, tag):
    candidates = generate_candidates(target, tag).candidates
    assert len(candidates) == 1
    assert candidates[0].target_text == target


def test_enclitic_opposite_forms_are_rejected():
    assert not generate_candidates("Ikaw din.", "$REPLACE_din").candidates
    assert not generate_candidates("Okey daw.", "$REPLACE_daw").candidates
    assert not generate_candidates("Maaari rin.", "$REPLACE_rin").candidates


def test_destination_hardlink_alias_is_rejected(tmp_path):
    source, alias = tmp_path / "source", tmp_path / "alias"
    source.write_bytes(b"preserve")
    try:
        alias.hardlink_to(source)
    except OSError:
        pytest.skip("filesystem does not support hard links")
    with pytest.raises(ValueError, match="aliases"):
        validate_destinations({"input": source}, {"output": alias})
    assert source.read_bytes() == b"preserve"


def test_destination_symlink_alias_is_rejected(tmp_path):
    source, alias = tmp_path / "source", tmp_path / "alias"
    source.write_bytes(b"preserve")
    try:
        alias.symlink_to(source)
    except OSError:
        pytest.skip("filesystem does not support symlinks")
    with pytest.raises(ValueError, match="aliases"):
        validate_destinations({"input": source}, {"output": alias})
    assert source.read_bytes() == b"preserve"


def test_source_hash_is_relocatable_and_content_sensitive(tmp_path):
    first, second = tmp_path / "checkout-a", tmp_path / "checkout-b"
    for root in (first, second):
        (root / "src").mkdir(parents=True)
        (root / "src/a.py").write_bytes(b"a")
        (root / "src/b.py").write_bytes(b"b")
    original = sha256_files((first / "src/a.py", first / "src/b.py"), root=first)
    assert original == sha256_files((second / "src/b.py", second / "src/a.py"), root=second)
    (second / "src/a.py").write_bytes(b"changed")
    assert original != sha256_files((second / "src/a.py", second / "src/b.py"), root=second)


def test_inspector_rejects_database_as_report(tmp_path, monkeypatch):
    import sqlite3

    database = tmp_path / "corpus.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sentences (normalized_text TEXT, is_duplicate INTEGER)")
        connection.execute("INSERT INTO sentences VALUES ('Maayos.', 0)")
    before = database.read_bytes()
    monkeypatch.setattr("sys.argv", ["inspect_sqlite", str(database), "--output", str(database)])
    with pytest.raises(ValueError, match="aliases"):
        inspect_sqlite.main()
    assert database.read_bytes() == before
