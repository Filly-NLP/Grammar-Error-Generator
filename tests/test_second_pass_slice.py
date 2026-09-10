from __future__ import annotations

import json
from types import MappingProxyType
from pathlib import Path

import pytest

from scripts.build_pilot import _pilot_targets
from src.geg.config import resolve_runtime_config
from src.geg.config import config_hash as compute_config_hash, load_config
from src.geg.hashing import generator_dependency_hash
from src.geg.review import validate_review_manifest, review_manifest_template, ReviewGateError
from src.geg.generators import GeneratorContext, generate_candidates
from src.geg.alignment import validate_replay
from src.geg.resource_freeze import freeze_constructions, freeze_morphology, load_frozen_jsonl
from scripts.build_candidates import build_candidate_shard
from scripts.build_dataset import build_final_dataset


def test_phase8_pilot_targets_are_configured_and_split_derived() -> None:
    config = {
        "project": {"seed": 7},
        "dataset": {"target_total_pairs": 10, "counting_mode": "errorful_only"},
        "splits": {"train": 0.60, "dev": 0.20, "synthetic_test": 0.20, "group_by_document": True},
        "stage_views": {"dataset1_errorful_share": 0.8, "dataset2_errorful_share": 0.2},
        "phase8": {"pilot_total": 10},
        "phase9": {"candidate_buffer_ratio": 1},
        "morphology": {"minimum_validated_states_per_lemma": 3},
        "balarila": {"table2_tag_count": 39},
    }
    runtime = resolve_runtime_config(config)
    assert runtime["runtime"]["pilot_total"] == 10
    assert _pilot_targets(runtime) == {"train": 6, "dev": 2, "synthetic_test": 2}


def test_schema_v1_review_is_incompatible(tmp_path: Path) -> None:
    path = tmp_path / "review.json"
    path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    result = validate_review_manifest(path, root=tmp_path)
    assert result.status == "incomplete"
    assert "schema_version" in result.reason


def test_dependency_hash_is_cwd_independent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    expected = generator_dependency_hash()
    monkeypatch.chdir(tmp_path)
    assert generator_dependency_hash() == expected


def test_morphology_replay_uses_generated_source_span_length_and_suffix() -> None:
    rows = tuple(MappingProxyType(dict(row)) for row in (
        {"lemma": "sulat", "surface": "sumulat", "balarila_state": "COMPACT", "review_status": "approved"},
        {"lemma": "sulat", "surface": "magsusulat", "balarila_state": "CONTACT", "review_status": "approved"},
        {"lemma": "sulat", "surface": "sulat", "balarila_state": "BASE", "review_status": "approved"},
    ))
    context = GeneratorContext(
        morphology_rows=rows,
        morphology_manifest=MappingProxyType({"resource_version": "fixture-v2"}),
        morphology_by_lemma=MappingProxyType({"sulat": rows}),
        morphology_by_state=MappingProxyType({}),
        morphology_by_surface=MappingProxyType({"sumulat": (rows[0],), "magsusulat": (rows[1],), "sulat": (rows[2],)}),
        construction_rows=(), construction_manifest=MappingProxyType({}), constructions_by_tag=MappingProxyType({}),
        punctuation_rows=(), punctuation_manifest=MappingProxyType({}), punctuation_by_tag=MappingProxyType({}),
    )
    candidate = generate_candidates("sumulat.", "$TRANSFORM_VERB_COMPACT", context=context).candidates[0]
    operation = candidate.generation_operation
    assert operation["source_end"] - operation["source_start"] == len(operation["source_surface"])
    assert operation["source_surface"] == "magsusulat."
    assert validate_replay(candidate.source_text, candidate.target_text, operation).success


def test_freeze_load_generate_replay_fixture_covers_target_states_and_constructions(tmp_path: Path) -> None:
    # This is synthetic test infrastructure only: it exercises the freeze and
    # replay contracts without adding any fixture rows to production resources.
    mapping = tmp_path / "mapping.jsonl"
    states = [
        ("sulat", "BASE"), ("sumulat", "COMPACT"), ("sinulat", "COMPOBJ"),
        ("susulat", "CONTACT"), ("susulatin", "CONTOBJ"),
        ("sumusulat", "INCACT"), ("sinusulat", "INCOBJ"),
        ("kakasulat", "RECCOMP"), ("magsusulat", "IMPACT"),
        ("ipasulat", "IMPOBJ"),
    ]
    mapping.write_text("".join(json.dumps({
        "lemma": "sulat", "surface": surface, "balarila_state": state,
        "review_status": "approved", "confidence": "reviewed",
    }) + "\n" for surface, state in states), encoding="utf-8")
    rule_artifact = tmp_path / "mapping-rules.txt"
    rule_artifact.write_text("reviewed fixture mapping rules", encoding="utf-8")
    morph_resource = tmp_path / "morph-v2.jsonl"
    morph_manifest = tmp_path / "morph-v2.json"
    freeze_morphology(
        mapping, morph_resource, morph_manifest, reviewer="fixture-reviewer",
        reviewed_at="2026-09-10T00:00:00+00:00", source_resource="fixture",
        source_version="2", license_text="fixture", mapping_rule_version="2",
        mapping_rule_artifact=rule_artifact, resource_version="tagalog-verb-paradigms-v2",
    )
    morph_rows, morph_meta = load_frozen_jsonl(morph_resource, morph_manifest)
    by_lemma = {"sulat": tuple(MappingProxyType(dict(row)) for row in morph_rows)}
    by_surface = {str(row["surface"]): (row,) for row in by_lemma["sulat"]}

    construction_data = [
        ("pag-aaral", "pag aaral", "$MERGE_HYPHEN", "hyphen"),
        ("araw-araw", "araw araw", "$TRANSFORM_INSERT_HYPHEN", "hyphen"),
        ("ika apat", "ika-apat", "$TRANSFORM_SPLIT_HYPHEN", "hyphen"),
        ("pa rin", "parin", "$MERGE_SPACE", "space"),
        ("pinakamalaki", "pinaka malaki", "$TRANSFORM_SPLIT_SPACE", "space"),
    ]
    construction_input = tmp_path / "constructions.jsonl"
    construction_input.write_text("".join(json.dumps({
        "correct_surface": correct, "generated_wrong_surface": wrong,
        "correction_tag": tag, "family": family, "review_status": "approved",
    }) + "\n" for correct, wrong, tag, family in construction_data), encoding="utf-8")
    construction_resource = tmp_path / "construction-v2.jsonl"
    construction_manifest = tmp_path / "construction-v2.json"
    freeze_constructions(
        construction_input, construction_resource, construction_manifest,
        reviewer="fixture-reviewer", reviewed_at="2026-09-10T00:00:00+00:00",
        source_resource="fixture", source_version="2", license_text="fixture",
        resource_version="filipino-constructions-v2",
    )
    construction_rows, construction_meta = load_frozen_jsonl(construction_resource, construction_manifest)
    construction_rows = tuple(MappingProxyType(dict(row)) for row in construction_rows)
    constructions_by_tag = {}
    for row in construction_rows:
        constructions_by_tag.setdefault(str(row["correction_tag"]), []).append(row)
    context = GeneratorContext(
        morphology_rows=by_lemma["sulat"], morphology_manifest=MappingProxyType(morph_meta),
        morphology_by_lemma=MappingProxyType(by_lemma), morphology_by_state=MappingProxyType({}),
        morphology_by_surface=MappingProxyType(by_surface), construction_rows=construction_rows,
        construction_manifest=MappingProxyType(construction_meta),
        constructions_by_tag=MappingProxyType({key: tuple(value) for key, value in constructions_by_tag.items()}),
        punctuation_rows=(), punctuation_manifest=MappingProxyType({}), punctuation_by_tag=MappingProxyType({}),
    )
    target_tags = {
        "BASE": "$TRANSFORM_VERB_BASE", "COMPACT": "$TRANSFORM_VERB_COMPACT",
        "COMPOBJ": "$TRANSFORM_VERB_COMPOBJ", "CONTACT": "$TRANSFORM_VERB_CONTACT",
        "CONTOBJ": "$TRANSFORM_VERB_CONTOBJ", "INCACT": "$TRANSFORM_VERB_INCACT",
        "INCOBJ": "$TRANSFORM_VERB_INCOBJ", "RECCOMP": "$TRANSFORM_VERB_RECCOMP",
    }
    surface_for_state = {state: surface for surface, state in states}
    for state, tag in target_tags.items():
        candidate = generate_candidates(surface_for_state[state] + ".", tag, context=context).candidates[0]
        assert candidate.morphology_resource_version == "tagalog-verb-paradigms-v2"
        assert candidate.morphology_source_state in {item[1] for item in states}
        assert validate_replay(candidate.source_text, candidate.target_text, candidate.generation_operation).success
    construction_candidates = [
        generate_candidates(correct, tag, context=context).candidates[0]
        for correct, _, tag, _ in construction_data
    ]
    assert {candidate.correction_tag for candidate in construction_candidates} == {item[2] for item in construction_data}
    assert all(validate_replay(candidate.source_text, candidate.target_text, candidate.generation_operation).success for candidate in construction_candidates)
    assert all(
        candidate.morphology_source_state not in {"IMPACT", "IMPOBJ"} or candidate.morphology_target_state not in {"IMPACT", "IMPOBJ"}
        for state, tag in target_tags.items()
        for candidate in generate_candidates(surface_for_state[state] + ".", tag, context=context).candidates
    )


def test_production_missing_review_identities_create_no_phase9_or_phase10_output(tmp_path: Path) -> None:
    config_path = Path("config/filly.yaml").resolve()
    config = load_config(config_path)
    config_digest = compute_config_hash(config)
    generator_digest = generator_dependency_hash()
    capacity = tmp_path / "capacity.json"
    capacity.write_text(json.dumps({
        "status": "complete", "production_ready": True,
        "config_hash": config_digest, "generator_dependency_hash": generator_digest,
        "generator_version": "filly-generators-v3-enclitic-context",
        "input_sha256": "not-read-before-review", "tags": [],
    }), encoding="utf-8")
    pilot_report = tmp_path / "pilot.json"
    pilot_output = tmp_path / "pilot.parquet"
    review_sample = tmp_path / "sample.jsonl"
    pilot_output.write_bytes(b"pilot")
    review_sample.write_text('{"pair_id":"fixture"}\n', encoding="utf-8")
    pilot_report.write_text(json.dumps({
        "status": "complete", "production_ready": True,
        "generator_dependency_hash": generator_digest, "config_hash": config_digest,
        "capacity_report": str(capacity),
        "capacity_report_sha256": __import__("src.geg.hashing", fromlist=["sha256_file"]).sha256_file(capacity),
    }), encoding="utf-8")
    review = review_manifest_template(pilot_report, pilot_output, review_sample, expected_review_rows=1,
        expected_generator_dependency_hash=generator_digest, expected_config_hash=config_digest,
        expected_capacity_report_sha256=__import__("src.geg.hashing", fromlist=["sha256_file"]).sha256_file(capacity))
    review.update({"status": "complete", "decision": "approve", "reviewer": "reviewer",
                   "adjudicator": "adjudicator", "reviewed_at": "2026-09-10T00:00:00+00:00",
                   "reviewed_rows": 1, "accepted_rows": 1})
    review["row_decisions"][0].update({"decision": "approve", "notes": "fixture"})
    # Remove every production identity at both manifest levels.  A hostile
    # production_ready flag must not turn this into a trusted approval.
    for name in ("generator_dependency_hash", "config_hash", "capacity_report_sha256"):
        review.pop(name, None)
        review["target"].pop(name, None)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    candidate_output = tmp_path / "candidate.parquet"
    with pytest.raises(ReviewGateError):
        build_candidate_shard(
            tmp_path / "missing-input.parquet", capacity, candidate_output,
            review_manifest_path=review_path, pilot_report_path=pilot_report,
            pilot_output_path=pilot_output, review_sample_path=review_sample,
            config_path=config_path, max_rows=1,
        )
    assert not candidate_output.exists()
    final_output = tmp_path / "final"
    with pytest.raises(ReviewGateError):
        build_final_dataset(
            tmp_path / "missing-candidates", tmp_path / "missing-split.parquet", final_output,
            review_manifest_path=review_path, pilot_report_path=pilot_report,
            pilot_output_path=pilot_output, review_sample_path=review_sample,
            config_path=config_path,
        )
    assert not final_output.exists()


def test_phase9_actual_reversed_parquet_is_order_independent_and_keeps_late_rare_tag(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    from scripts.build_candidates import build_candidate_shard
    from src.geg.generators import GENERATOR_VERSION
    from src.geg.hashing import legacy_generator_hash, sha256_file

    rows = [
        {"clean_id": "common", "text": "Maayos.", "split": "train", "source_corpus": "fixture", "publisher": "fixture", "source_doc_id": "common", "sqlite_table": "s", "sqlite_rowid": 1},
        {"clean_id": "rare-late", "text": "Umalis siya kahapon.", "split": "train", "source_corpus": "fixture", "publisher": "fixture", "source_doc_id": "rare-late", "sqlite_table": "s", "sqlite_rowid": 2},
    ]
    config = {"dataset": {"target_total_pairs": 10, "counting_mode": "errorful_only", "errorful_fraction": 1.0}}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    forward = tmp_path / "forward.parquet"
    reverse = tmp_path / "reverse.parquet"
    pq.write_table(pa.Table.from_pylist(rows), forward)
    pq.write_table(pa.Table.from_pylist(list(reversed(rows))), reverse)
    tags = [
        {"tag": "$ADD_PUNC_PERIOD", "status": "supported", "candidates": 1, "candidates_by_split": {"train": 1}, "reason": "fixture"},
        {"tag": "$REPLACE_siya", "status": "supported", "candidates": 1, "candidates_by_split": {"train": 1}, "reason": "fixture"},
    ]
    capacity = tmp_path / "capacity.json"
    capacity_payload = {
        "status": "complete", "input_sha256": sha256_file(forward), "config_hash": compute_config_hash(config),
        "generator_version": GENERATOR_VERSION, "generator_sha256": legacy_generator_hash(),
        "quality_manifest_sha256": "quality", "split_report_sha256": "split", "input_sqlite_sha256": "sqlite",
        "tags": tags,
    }
    capacity.write_text(json.dumps(capacity_payload), encoding="utf-8")
    reverse_capacity = tmp_path / "capacity-reverse.json"
    reverse_capacity.write_text(json.dumps({**capacity_payload, "input_sha256": sha256_file(reverse)}), encoding="utf-8")
    report = tmp_path / "pilot.json"
    pilot_output = tmp_path / "pilot.parquet"
    sample = tmp_path / "sample.jsonl"
    report.write_text(json.dumps({"status": "complete"}), encoding="utf-8")
    pilot_output.write_bytes(b"pilot")
    sample.write_text('{"pair_id":"fixture"}\n', encoding="utf-8")
    review = review_manifest_template(report, pilot_output, sample, expected_review_rows=1)
    review.update({"status": "complete", "decision": "approve", "reviewer": "r", "adjudicator": "a",
                   "reviewed_at": "2026-09-10T00:00:00+00:00", "reviewed_rows": 1, "accepted_rows": 1})
    review["row_decisions"][0].update({"decision": "approve", "notes": "fixture"})
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    outputs = []
    for source, cap, name in ((forward, capacity, "candidate-forward.parquet"), (reverse, reverse_capacity, "candidate-reverse.parquet")):
        output = tmp_path / name
        build_candidate_shard(
            source, cap, output, review_manifest_path=review_path,
            pilot_report_path=report, pilot_output_path=pilot_output,
            review_sample_path=sample, config_path=config_path,
            max_rows=2, allow_development=True,
        )
        outputs.append(set(pq.read_table(output, columns=["pair_id", "correction_tags"]).to_pylist()[i]["pair_id"] for i in range(2)))
        records = pq.read_table(output).to_pylist()
        assert any(record["correction_tags"] == ["$REPLACE_siya"] for record in records)
    assert outputs[0] == outputs[1]


def test_phase9_phase10_require_explicit_development_override_for_minimal_config(tmp_path: Path) -> None:
    minimal = tmp_path / "minimal.json"
    minimal.write_text(json.dumps({"dataset": {"target_total_pairs": 1}}), encoding="utf-8")
    capacity = tmp_path / "capacity.json"
    capacity.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="complete validated config"):
        build_candidate_shard(tmp_path / "input", capacity, tmp_path / "candidate.parquet", config_path=minimal, max_rows=1)
    with pytest.raises(RuntimeError, match="complete validated config"):
        build_final_dataset(tmp_path / "candidates", tmp_path / "split.parquet", tmp_path / "final", config_path=minimal)


def test_resolved_v2_resource_paths_load_context_and_bind_dependency_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.geg.config import resource_paths
    from src.geg.generators import GeneratorContext
    from src.geg.hashing import generator_dependency_hash
    from src.geg.resource_freeze import freeze_punctuation_context

    root = tmp_path
    for folder in ("morphology", "constructions", "punctuation"):
        (root / "resources" / folder).mkdir(parents=True)
    mapping = root / "mapping.jsonl"
    mapping.write_text("".join(json.dumps({"lemma": "sulat", "surface": surface, "balarila_state": state,
        "review_status": "approved", "confidence": "reviewed"}) + "\n" for surface, state in
        (("sulat", "BASE"), ("sumulat", "COMPACT"), ("susulat", "CONTACT"))), encoding="utf-8")
    rules = root / "rules.txt"
    rules.write_text("v2", encoding="utf-8")
    freeze_morphology(mapping, root / "resources/morphology/verbs-v2.jsonl", root / "resources/morphology/verbs-v2.json",
        reviewer="r", reviewed_at="2026-09-10T00:00:00+00:00", source_resource="fixture", source_version="2",
        license_text="fixture", mapping_rule_version="2", mapping_rule_artifact=rules,
        resource_version="tagalog-verb-paradigms-v2")
    constructions = root / "constructions.jsonl"
    constructions.write_text(json.dumps({"correct_surface": "pag-aaral", "generated_wrong_surface": "pag aaral",
        "correction_tag": "$MERGE_HYPHEN", "family": "hyphen", "review_status": "approved"}) + "\n", encoding="utf-8")
    freeze_constructions(constructions, root / "resources/constructions/words-v2.jsonl", root / "resources/constructions/words-v2.json",
        reviewer="r", reviewed_at="2026-09-10T00:00:00+00:00", source_resource="fixture", source_version="2",
        license_text="fixture", resource_version="filipino-constructions-v2")
    punctuation = root / "punctuation.jsonl"
    punctuation.write_text(json.dumps({"context": "Masaya", "correct_surface": ".", "generated_wrong_surface": "?",
        "correction_tag": "$CHANGE_PUNC_PERIOD", "review_status": "approved"}) + "\n", encoding="utf-8")
    freeze_punctuation_context(punctuation, root / "resources/punctuation/punctuation-v2.jsonl", root / "resources/punctuation/punctuation-v2.json",
        reviewer="r", reviewed_at="2026-09-10T00:00:00+00:00", source_resource="fixture", source_version="2",
        license_text="fixture", resource_version="filipino-punctuation-context-v2")
    config = {
        "project": {"seed": 7}, "dataset": {"target_total_pairs": 10, "counting_mode": "errorful_only"},
        "splits": {"train": .7, "dev": .15, "synthetic_test": .15},
        "stage_views": {"dataset1_errorful_share": .8, "dataset2_errorful_share": .2},
        "morphology": {"minimum_validated_states_per_lemma": 3}, "balarila": {"table2_tag_count": 39},
        "resources": {"morphology": {"resource": "resources/morphology/verbs-v2.jsonl", "manifest": "resources/morphology/verbs-v2.json"},
            "constructions": {"resource": "resources/constructions/words-v2.jsonl", "manifest": "resources/constructions/words-v2.json"},
            "punctuation": {"resource": "resources/punctuation/punctuation-v2.jsonl", "manifest": "resources/punctuation/punctuation-v2.json"}},
    }
    resolved = resolve_runtime_config(config)
    selected = resource_paths(resolved)
    monkeypatch.setattr("src.geg.morphology.project_root", lambda: root)
    monkeypatch.setattr("src.geg.resources.project_root", lambda: root)
    context = GeneratorContext.load(selected)
    assert context.morphology_manifest["resource_version"] == "tagalog-verb-paradigms-v2"
    assert context.construction_manifest["resource_version"] == "filipino-constructions-v2"
    assert context.punctuation_manifest["resource_version"] == "filipino-punctuation-context-v2"
    digest = generator_dependency_hash(root=root, resource_paths=selected)
    assert digest != generator_dependency_hash(root=root)
