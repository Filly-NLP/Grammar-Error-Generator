from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from scripts.build_candidates import _global_shard_plan, _partition_shard_quotas, _resolve_plan_shard_bounds, aggregate_candidate_manifests, build_candidate_plan
from src.geg.generators import all_tag_ids
from scripts.build_dataset import _identity_row
from src.evaluation_noise.injector import NoiseInjectionError, NoiseRule, inject_informal_noise
from src.geg.config import resolve_runtime_config
from src.geg.resource_freeze import freeze_constructions


def test_errorful_only_requires_one_hundred_percent_errorful() -> None:
    config = {
        "project": {"seed": 1},
        "dataset": {"target_total_pairs": 10, "counting_mode": "errorful_only", "errorful_fraction": 0.83, "identity_fraction": 0},
        "splits": {"train": 0.7, "dev": 0.15, "synthetic_test": 0.15},
        "stage_views": {"dataset1_errorful_share": 0.8, "dataset2_errorful_share": 0.2},
        "morphology": {"minimum_validated_states_per_lemma": 3},
        "balarila": {"table2_tag_count": 39},
    }
    with pytest.raises(ValueError, match="errorful_only requires"):
        resolve_runtime_config(config)


def test_global_group_request_is_partitioned_once() -> None:
    global_plan = {("train", "$ADD_PUNC_PERIOD"): 101, ("dev", "$ADD_PUNC_PERIOD"): 3}
    parts = [_partition_shard_quotas(global_plan, shard_index=i, shard_count=3) for i in range(3)]
    assert sum(part["train", "$ADD_PUNC_PERIOD"] for part in parts) == 101
    assert sum(part["dev", "$ADD_PUNC_PERIOD"] for part in parts) == 3


def test_plan_does_not_silently_expand_explicit_cli_maximum() -> None:
    plan = {"shards": {"0": {"requested_rows": 100, "max_output_rows": 100, "group_quotas": {"train:$ADD_PUNC_PERIOD": 100}}}}
    with pytest.raises(RuntimeError, match="max_output_rows CLI value is incompatible"):
        _resolve_plan_shard_bounds(plan, shard_index=0, explicit_target_rows=None, explicit_hard_max_rows=1)
    groups, target, maximum, buffered = _resolve_plan_shard_bounds(
        plan, shard_index=0, explicit_target_rows=None, explicit_hard_max_rows=None,
    )
    assert groups["train:$ADD_PUNC_PERIOD"] == 100
    assert (target, maximum, buffered) == (100, 100, 100)


def test_global_plan_uses_skewed_shard_local_capacity() -> None:
    tag = "$ADD_PUNC_PERIOD"
    capacity = {
        "tags": [{"tag": tag, "status": "supported", "candidates": 120, "candidates_by_split": {"train": 120}}],
        "shard_capacities": {f"train:{tag}": [0, 120]},
    }
    global_plan, shards, _ = _global_shard_plan(capacity, 100, [tag], shard_count=2)
    assert global_plan[("train", tag)] == 100
    assert shards[0][("train", tag)] == 0
    assert shards[1][("train", tag)] == 100
    assert sum(shard[("train", tag)] for shard in shards.values()) == 100


def test_candidate_plan_artifact_measures_and_partitions_real_shards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The pre-shard controller must measure local capacity, not copy a global quota."""
    import scripts.build_candidates as builder

    tag = "$ADD_PUNC_PERIOD"
    config = {
        "project": {"seed": 7},
        "dataset": {"target_total_pairs": 10, "counting_mode": "errorful_only"},
        "splits": {"train": 0.7, "dev": 0.15, "synthetic_test": 0.15},
        "stage_views": {"dataset1_errorful_share": 0.8, "dataset2_errorful_share": 0.2},
        "morphology": {"minimum_validated_states_per_lemma": 3},
        "balarila": {"table2_tag_count": 39},
        "phase9": {"candidate_buffer_ratio": 1.0},
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    input_path = tmp_path / "split.parquet"
    pq.write_table(pa.table({"clean_id": ["zero", "full"], "text": ["a", "b"], "split": ["train", "train"]}), input_path)
    capacity_path = tmp_path / "capacity.json"
    capacity_path.write_text(json.dumps({
        "status": "complete",
        "tags": [{"tag": tag, "status": "supported", "candidates": 120, "candidates_by_split": {"train": 120}}],
    }), encoding="utf-8")
    monkeypatch.setattr(builder, "_shard_for", lambda clean_id, shard_count: 0 if clean_id == "zero" else 1)
    monkeypatch.setattr(builder.GeneratorContext, "load", lambda _paths: object())
    monkeypatch.setattr(builder, "generate_candidates", lambda *args, **kwargs: SimpleNamespace(candidates=[object()] * (120 if args[0] == "b" else 0)))

    plan_path = tmp_path / "candidate-plan.json"
    plan = build_candidate_plan(
        input_path, capacity_path, plan_path, shard_count=2, target_rows=100,
        max_output_rows=100, config_path=config_path, allow_development=True,
    )
    assert plan["shard_capacity_by_group"][f"train:{tag}"] == [0, 120]
    assert plan["global_group_quotas"][f"train:{tag}"] == 100
    assert plan["shards"]["0"]["group_quotas"][f"train:{tag}"] == 0
    assert plan["shards"]["1"]["group_quotas"][f"train:{tag}"] == 100
    assert sum(plan["shards"][str(index)]["requested_rows"] for index in range(2)) == 100
    stored = json.loads(plan_path.read_text(encoding="utf-8"))
    recorded = stored.pop("plan_sha256")
    import hashlib
    expected = hashlib.sha256(json.dumps(stored, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert recorded == expected


def test_aggregate_recomputes_plan_and_rejects_global_output_overflow(tmp_path: Path) -> None:
    """Shard manifests cannot inflate local quotas or the global requested ceiling."""
    import hashlib

    tag = "$ADD_PUNC_PERIOD"
    plan = {
        "schema_version": "filly-phase9-candidate-plan-v1", "status": "complete",
        "capacity_report_sha256": "capacity", "config_hash": "config",
        "generator_dependency_hash": "generator", "input_sha256": "input", "shard_count": 2,
        "max_output_rows": 2, "global_requested_rows": 2,
        "global_capacity_by_group": {f"train:{tag}": 2},
        "shard_capacity_by_group": {f"train:{tag}": [0, 2]},
        "global_group_quotas": {f"train:{tag}": 2},
        "shards": {
            "0": {"requested_rows": 0, "max_output_rows": 0, "group_quotas": {f"train:{tag}": 0}},
            "1": {"requested_rows": 2, "max_output_rows": 2, "group_quotas": {f"train:{tag}": 2}},
        },
    }
    plan_payload = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
    plan["plan_sha256"] = hashlib.sha256(plan_payload).hexdigest()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    manifests = []
    for index, rows in ((0, 0), (1, 2)):
        output = tmp_path / f"shard-{index}.parquet"
        output.write_bytes(f"shard-{index}".encode())
        manifest = output.with_suffix(".manifest.json")
        payload = {
            "status": "complete", "output": str(output), "output_sha256": __import__("src.geg.hashing", fromlist=["sha256_file"]).sha256_file(output),
            "shard_index": index, "shard_count": 2, "production_ready": True,
            "capacity_report_sha256": "capacity", "config_hash": "config", "quality_manifest_sha256": "quality",
            "split_report_sha256": "split", "input_sqlite_sha256": "sqlite", "review_manifest_sha256": "review",
            "generator_dependency_hash": "generator", "generator_version": "v", "seed": 7,
            "candidate_builder_version": "builder", "builder_version": "builder", "input_sha256": "input",
            "tag_status": {tag_id: {"status": "supported"} for tag_id in all_tag_ids()},
            "group_quotas": {f"train:{tag}": rows}, "global_group_quotas": {f"train:{tag}": 2},
            "global_shard_plan_sha256": plan["plan_sha256"], "candidate_plan": str(plan_path.resolve()),
            "candidate_plan_sha256": plan["plan_sha256"], "max_output_rows": rows,
            "split_counts": {"train": rows}, "tag_counts": {tag: rows}, "candidate_rows": rows,
            "buffer_rows": rows, "rejection_telemetry": {"not_applicable": 0, "rejections": {}, "samples": []},
        }
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        manifests.append(manifest)

    report = aggregate_candidate_manifests(manifests, tmp_path / "aggregate.json", required_by_split={"train": 2})
    assert report["phase10_capacity_adequate"] is True
    original_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    original_plan_hash = original_plan["plan_sha256"]
    tampered_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    tampered_plan["input_sha256"] = "different-input"
    unsigned = dict(tampered_plan)
    unsigned.pop("plan_sha256", None)
    import hashlib
    tampered_plan["plan_sha256"] = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    plan_path.write_text(json.dumps(tampered_plan), encoding="utf-8")
    for manifest_path in manifests:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_payload["candidate_plan_sha256"] = tampered_plan["plan_sha256"]
        manifest_payload["global_shard_plan_sha256"] = tampered_plan["plan_sha256"]
        manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="input dependency"):
        aggregate_candidate_manifests(manifests)

    # Restore the valid plan identity before checking the independent output
    # ceiling invariant.
    plan_path.write_text(json.dumps(original_plan), encoding="utf-8")
    for manifest_path in manifests:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_payload["candidate_plan_sha256"] = original_plan_hash
        manifest_payload["global_shard_plan_sha256"] = original_plan_hash
        manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
    tampered = json.loads(manifests[1].read_text(encoding="utf-8"))
    tampered["candidate_rows"] = 3
    manifests[1].write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(RuntimeError, match="hard ceiling"):
        aggregate_candidate_manifests(manifests)


def test_identity_rows_keep_config_hash() -> None:
    row = _identity_row({"clean_id": "c1", "text": "Maayos.", "split": "train"}, 7, "a" * 64)
    assert row["config_hash"] == "a" * 64
    assert row["source_text"] == row["target_text"]
    assert row["morphology_resource_version"] is None


def test_construction_freeze_rejects_lexical_substitution(tmp_path: Path) -> None:
    source = tmp_path / "input.jsonl"
    source.write_text(json.dumps({
        "correct_surface": "maganda",
        "generated_wrong_surface": "pangit",
        "correction_tag": "$MERGE_SPACE",
        "family": "space",
        "review_status": "approved",
    }) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="lexical content"):
        freeze_constructions(
            source, tmp_path / "resource.jsonl", tmp_path / "manifest.json",
            reviewer="reviewer", reviewed_at="2026-09-10T00:00:00+00:00",
            source_resource="fixture", source_version="1", license_text="fixture",
        )


def test_construction_freeze_enforces_direction_for_all_five_tags(tmp_path: Path) -> None:
    rows = [
        ("pag-aaral", "pag aaral", "$MERGE_HYPHEN", "hyphen"),
        ("araw-araw", "arawaraw", "$TRANSFORM_INSERT_HYPHEN", "hyphen"),
        ("ika apat", "ika-apat", "$TRANSFORM_SPLIT_HYPHEN", "hyphen"),
        ("pa rin", "parin", "$MERGE_SPACE", "space"),
        ("pinakamalaki", "pinaka malaki", "$TRANSFORM_SPLIT_SPACE", "space"),
    ]
    source = tmp_path / "input.jsonl"
    source.write_text("".join(json.dumps({"correct_surface": c, "generated_wrong_surface": w, "correction_tag": t, "family": f, "review_status": "approved"}) + "\n" for c, w, t, f in rows), encoding="utf-8")
    freeze_constructions(source, tmp_path / "resource.jsonl", tmp_path / "manifest.json", reviewer="r", reviewed_at="2026-09-10T00:00:00+00:00", source_resource="fixture", source_version="1", license_text="fixture")

    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"correct_surface": "araw-araw", "generated_wrong_surface": "arawaraw", "correction_tag": "$MERGE_SPACE", "family": "space", "review_status": "approved"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="delimiter"):
        freeze_constructions(bad, tmp_path / "bad-resource.jsonl", tmp_path / "bad-manifest.json", reviewer="r", reviewed_at="2026-09-10T00:00:00+00:00", source_resource="fixture", source_version="1", license_text="fixture")


def test_noise_token_matching_does_not_mutate_substrings() -> None:
    rule = NoiseRule("ako", "abbreviation", "aq", "ako", "v1", match_mode="token")
    inventory = {"status": "frozen", "version": "v1", "source": "fixture", "license": "fixture", "rules": [{"id": "ako", "pattern_id": "p1", "review_status": "approved"}]}
    with pytest.raises(NoiseInjectionError, match="no applicable"):
        inject_informal_noise("Takot siya.", [rule], category="abbreviation", sample_id="x", seed=1, normalizer_training_rule_ids=inventory)
    result = inject_informal_noise("ako ay.", [rule], category="abbreviation", sample_id="x", seed=1, normalizer_training_rule_ids=inventory)
    assert result["raw_informal"] == "aq ay."


def test_noise_token_matching_treats_underscore_as_word_character() -> None:
    rule = NoiseRule("ako", "abbreviation", "aq", "ako", "v1", match_mode="token")
    inventory = {"status": "frozen", "version": "v1", "source": "fixture", "license": "fixture", "rules": [{"id": "ako", "pattern_id": "p1", "review_status": "approved"}]}
    with pytest.raises(NoiseInjectionError, match="no applicable"):
        inject_informal_noise("x_ako y", [rule], category="abbreviation", sample_id="x", seed=1, normalizer_training_rule_ids=inventory)
