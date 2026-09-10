from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.build_candidates import _capacity_group_quotas, _candidate_rank, aggregate_candidate_manifests, build_candidate_shard, validate_candidate_aggregate
from src.geg.config import config_hash, load_config, resolve_runtime_config
from src.geg.generators import GENERATOR_VERSION, all_tag_ids
from src.geg.hashing import generator_dependency_hash, sha256_file
from src.geg.reporting import build_synthetic_test_diagnostics
from src.geg.telemetry import RejectionTelemetry


def test_capacity_quotas_preserve_rare_groups() -> None:
    capacity = {
        "tags": [
            {"tag": "$COMMON", "status": "supported", "candidates_by_split": {"train": 10_000}},
            {"tag": "$RARE", "status": "supported", "candidates_by_split": {"train": 1}},
        ]
    }
    quotas = _capacity_group_quotas(capacity, 2, ["$COMMON", "$RARE"])
    assert quotas[("train", "$RARE")] == 1
    assert sum(quotas.values()) == 2


def test_candidate_buffer_ratio_is_resolved_and_rejects_under_one() -> None:
    config = {
        "project": {"seed": 7},
        "dataset": {"target_total_pairs": 10, "counting_mode": "balarila_total", "errorful_fraction": 0.6, "identity_fraction": 0.4},
        "splits": {"train": 0.7, "dev": 0.15, "synthetic_test": 0.15},
        "stage_views": {"dataset1_errorful_share": 0.8, "dataset2_errorful_share": 0.2},
        "morphology": {"minimum_validated_states_per_lemma": 3},
        "balarila": {"table2_tag_count": 39},
        "phase9": {"candidate_buffer_ratio": 1.25},
    }
    assert resolve_runtime_config(config)["runtime"]["candidate_buffer_ratio"] == "1.25"
    config["phase9"]["candidate_buffer_ratio"] = 0.9
    with pytest.raises(ValueError, match="candidate_buffer_ratio"):
        resolve_runtime_config(config)


def test_stable_rank_is_invariant_to_input_order() -> None:
    rows = [("c1", "train", "$TAG", "wrong", "correct"), ("c2", "train", "$TAG", "w2", "c2")]
    first = sorted(_candidate_rank(7, *row) for row in rows)
    second = sorted(_candidate_rank(7, *row) for row in reversed(rows))
    assert first == second


def test_rejection_telemetry_separates_not_applicable_and_bounds_samples() -> None:
    telemetry = RejectionTelemetry(sample_limit=2)
    telemetry.add_not_applicable(4)
    telemetry.reject("alignment_failure", 3, sample={"clean_id": "a"})
    telemetry.reject("alignment_failure", 1, sample={"clean_id": "b"})
    telemetry.reject("alignment_failure", 1, sample={"clean_id": "c"})
    report = telemetry.as_dict()
    assert report["not_applicable"] == 4
    assert report["candidate_rejected"] == 5
    assert len(report["samples"]) == 2
    assert "not_applicable" not in report["rejections"]


def test_candidate_shard_rejects_alternate_capacity_hash_bound_to_pilot_and_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    input_path = tmp_path / "split.parquet"
    input_path.write_bytes(b"fixture input")
    config_path = Path("config/filly.yaml").resolve()
    config = load_config(config_path)
    current_capacity = tmp_path / "capacity.json"
    alternate_capacity = tmp_path / "capacity-alternate.json"
    tags = [{"tag": tag, "status": "supported", "candidates": 1, "candidates_by_split": {"train": 1}} for tag in all_tag_ids()]
    payload = {
        "status": "complete", "production_ready": True,
        "input_sha256": sha256_file(input_path),
        "config_hash": config_hash(config),
        "generator_version": GENERATOR_VERSION,
        "generator_dependency_hash": generator_dependency_hash(),
        "split_report_sha256": "split", "quality_manifest_sha256": "quality", "input_sqlite_sha256": "sqlite",
        "tags": tags,
    }
    current_capacity.write_text(json.dumps(payload), encoding="utf-8")
    alternate_capacity.write_text(json.dumps({**payload, "tampered": True}), encoding="utf-8")
    original_capacity_hash = sha256_file(current_capacity)
    pilot_report = tmp_path / "pilot.json"
    pilot_report.write_text(json.dumps({
        "status": "complete", "production_ready": True,
        "capacity_report": str(alternate_capacity),
        "capacity_report_sha256": original_capacity_hash,
    }), encoding="utf-8")
    review_manifest = tmp_path / "review.json"
    review_manifest.write_text(json.dumps({"capacity_report": str(alternate_capacity), "capacity_report_sha256": original_capacity_hash}), encoding="utf-8")
    pilot_output = tmp_path / "pilot.parquet"
    review_sample = tmp_path / "sample.jsonl"
    monkeypatch.setattr(
        "scripts.build_candidates.require_review_gate",
        lambda *args, **kwargs: SimpleNamespace(
            status="complete", current_hashes={"pilot_report_sha256": sha256_file(pilot_report)}
        ),
    )
    with pytest.raises(RuntimeError, match="capacity hash"):
        build_candidate_shard(
            input_path,
            alternate_capacity,
            tmp_path / "candidates.parquet",
            review_manifest_path=review_manifest,
            pilot_report_path=pilot_report,
            pilot_output_path=pilot_output,
            review_sample_path=review_sample,
            config_path=config_path,
            max_rows=1,
        )
    # Once the pilot is changed to bind the alternate file, the still-old
    # review approval must fail independently rather than being treated as a
    # valid approval for the substituted capacity artifact.
    pilot_report.write_text(json.dumps({
        "status": "complete", "production_ready": True,
        "capacity_report": str(alternate_capacity),
        "capacity_report_sha256": sha256_file(alternate_capacity),
    }), encoding="utf-8")
    with pytest.raises(RuntimeError, match="review manifest capacity hash"):
        build_candidate_shard(
            input_path,
            alternate_capacity,
            tmp_path / "candidates-review-mismatch.parquet",
            review_manifest_path=review_manifest,
            pilot_report_path=pilot_report,
            pilot_output_path=pilot_output,
            review_sample_path=review_sample,
            config_path=config_path,
            max_rows=1,
        )


def test_candidate_aggregate_validates_complete_set_hashes_and_dependencies(tmp_path: Path) -> None:
    manifests = []
    for index in range(2):
        shard = tmp_path / f"shard-{index}.parquet"
        shard.write_bytes(f"shard-{index}".encode())
        manifest = shard.with_suffix(".manifest.json")
        payload = {
            "status": "complete", "output": str(shard), "output_sha256": sha256_file(shard),
            "shard_index": index, "shard_count": 2, "production_ready": True,
            "capacity_report_sha256": "capacity", "config_hash": "config",
            "quality_manifest_sha256": "quality", "split_report_sha256": "split",
            "input_sqlite_sha256": "sqlite", "review_manifest_sha256": "review",
            "generator_dependency_hash": "generator", "generator_version": "v",
            "seed": 7, "candidate_builder_version": "builder", "builder_version": "builder",
            "input_sha256": "input", "tag_status": {tag: {"status": "supported"} for tag in all_tag_ids()},
            "group_quotas": {"train:$ADD_PUNC_PERIOD": 1},
            "split_counts": {"train": 1}, "tag_counts": {"$ADD_PUNC_PERIOD": 1},
            "candidate_rows": 1, "buffer_rows": 1,
            "rejection_telemetry": {"not_applicable": 0, "rejections": {}, "samples": []},
        }
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        manifests.append(manifest)
    aggregate = aggregate_candidate_manifests(manifests, tmp_path / "aggregate.json", required_by_split={"train": 2})
    assert aggregate["phase10_capacity_adequate"]
    validated = validate_candidate_aggregate(tmp_path / "aggregate.json", [tmp_path / "shard-0.parquet", tmp_path / "shard-1.parquet"], required_by_split={"train": 2})
    assert validated["aggregate_sha256"] == aggregate["aggregate_sha256"]
    (tmp_path / "shard-1.parquet").write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="output hash"):
        aggregate_candidate_manifests(manifests, tmp_path / "aggregate-2.json")


def test_candidate_aggregate_does_not_overwrite_external_winner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shard = tmp_path / "shard-0.parquet"
    shard.write_bytes(b"shard")
    manifest = shard.with_suffix(".manifest.json")
    payload = {
        "status": "complete", "output": str(shard), "output_sha256": sha256_file(shard),
        "shard_index": 0, "shard_count": 1, "production_ready": True,
        "capacity_report_sha256": "capacity", "config_hash": "config",
        "quality_manifest_sha256": "quality", "split_report_sha256": "split",
        "input_sqlite_sha256": "sqlite", "review_manifest_sha256": "review",
        "generator_dependency_hash": "generator", "generator_version": "v",
        "seed": 7, "candidate_builder_version": "builder", "builder_version": "builder",
        "input_sha256": "input", "tag_status": {tag: {"status": "supported"} for tag in all_tag_ids()},
        "group_quotas": {"train:$ADD_PUNC_PERIOD": 1}, "split_counts": {"train": 1},
        "tag_counts": {"$ADD_PUNC_PERIOD": 1}, "candidate_rows": 1, "buffer_rows": 1,
    }
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    aggregate_path = tmp_path / "aggregate.json"
    import scripts.build_candidates as builder
    original_link = builder.os.link

    def winner(source: str, destination: str) -> None:
        Path(destination).write_text("external winner", encoding="utf-8")
        raise FileExistsError(destination)

    monkeypatch.setattr(builder.os, "link", winner)
    with pytest.raises(FileExistsError):
        aggregate_candidate_manifests([manifest], aggregate_path)
    assert aggregate_path.read_text(encoding="utf-8") == "external winner"
    assert not Path(str(aggregate_path) + ".lock").exists()


def test_synthetic_diagnostics_has_all_registry_categories_and_checks_manifest(tmp_path: Path) -> None:
    artifact = tmp_path / "synthetic.parquet"
    rows = [
        {
            "source_text": "Maayos", "target_text": "Maayos.", "is_errorful": True,
            "correction_tags": ["$ADD_PUNC_PERIOD"], "error_families": ["punctuation"],
            "publisher": "fixture", "morphology_source_state": None, "morphology_target_state": None,
        },
        {
            "source_text": "Maayos.", "target_text": "Maayos.", "is_errorful": False,
            "correction_tags": [], "error_families": [], "publisher": None,
            "morphology_source_state": None, "morphology_target_state": None,
        },
    ]
    pq.write_table(pa.Table.from_pylist(rows), artifact)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "status": "complete", "split_counts": {"synthetic_test": 2},
        "outputs": {"synthetic_test/final.parquet": {"sha256": sha256_file(artifact)}},
    }), encoding="utf-8")
    report = build_synthetic_test_diagnostics(artifact, tmp_path / "report.json", tmp_path / "report.md", manifest_path=manifest)
    assert len(report["tag_counts_all_39"]) == 39
    assert len(report["family_counts_all_10"]) == 10
    assert report["errorful_rows"] + report["identity_rows"] == report["total_rows"]
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    with pytest.raises(RuntimeError, match="hash"):
        build_synthetic_test_diagnostics(artifact, tmp_path / "bad.json", tmp_path / "bad.md", manifest_path=manifest)


def test_synthetic_diagnostics_refuses_existing_or_alias_outputs(tmp_path: Path) -> None:
    artifact = tmp_path / "synthetic.parquet"
    rows = [{
        "source_text": "Maayos.", "target_text": "Maayos.", "is_errorful": False,
        "correction_tags": [], "error_families": [], "publisher": "p",
    }]
    pq.write_table(pa.Table.from_pylist(rows), artifact)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "status": "complete", "split_counts": {"synthetic_test": 1},
        "outputs": {"synthetic_test/final.parquet": {"sha256": sha256_file(artifact)}},
    }), encoding="utf-8")
    existing = tmp_path / "existing.json"
    existing.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        build_synthetic_test_diagnostics(artifact, existing, tmp_path / "report.md", manifest_path=manifest)
    alias = tmp_path / "alias.json"
    try:
        alias.hardlink_to(artifact)
    except (OSError, NotImplementedError):
        alias = None
    if alias is not None:
        with pytest.raises(ValueError, match="aliases"):
            build_synthetic_test_diagnostics(artifact, alias, tmp_path / "report2.md", manifest_path=manifest)


def test_synthetic_diagnostics_rolls_back_when_second_output_loses_race(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = tmp_path / "synthetic.parquet"
    pq.write_table(pa.Table.from_pylist([{
        "source_text": "Maayos.", "target_text": "Maayos.", "is_errorful": False,
        "correction_tags": [], "error_families": [], "publisher": "p",
    }]), artifact)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "status": "complete", "split_counts": {"synthetic_test": 1},
        "outputs": {"synthetic_test/final.parquet": {"sha256": sha256_file(artifact)}},
    }), encoding="utf-8")
    output_json, output_md = tmp_path / "report.json", tmp_path / "report.md"
    original_link = __import__("src.geg.reporting", fromlist=["os"]).os.link
    calls = {"count": 0}

    def external_winner(source: str, destination: str) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            Path(destination).write_text("external winner", encoding="utf-8")
            raise FileExistsError(destination)
        original_link(source, destination)

    monkeypatch.setattr("src.geg.reporting.os.link", external_winner)
    with pytest.raises(FileExistsError):
        build_synthetic_test_diagnostics(artifact, output_json, output_md, manifest_path=manifest)
    assert not output_json.exists()
    assert output_md.read_text(encoding="utf-8") == "external winner"
    assert not Path(str(output_json) + ".lock").exists()
    assert not Path(str(output_md) + ".lock").exists()
