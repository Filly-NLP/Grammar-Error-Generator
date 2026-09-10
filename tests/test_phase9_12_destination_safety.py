"""Destination-alias checks for downstream builders."""

from pathlib import Path

import pytest

from scripts.build_candidates import build_candidate_shard
from scripts.build_dataset import build_final_dataset
from scripts.build_eligibility import build_report
from scripts.build_pilot import build_pilot
from scripts.split_base import split_parquet
from src.evaluation_noise.freeze import freeze_evaluation


def test_phase5_8_reject_aliases_before_missing_input_reads(tmp_path):
    paths = {name: tmp_path / name for name in ("input", "output", "report", "config", "manifest", "capacity", "sample")}
    with pytest.raises(ValueError, match="aliases"):
        split_parquet(paths["input"], paths["output"], paths["input"], paths["config"], quality_manifest=paths["manifest"])
    with pytest.raises(ValueError, match="aliases"):
        build_report(paths["input"], paths["input"], paths["report"], paths["config"], paths["manifest"])
    with pytest.raises(ValueError, match="aliases"):
        build_pilot(paths["input"], paths["capacity"], paths["output"], paths["report"], paths["report"], paths["output"], config_path=paths["config"])


def test_phase9_10_reject_aliases_before_review_gate(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="aliases"):
        build_candidate_shard(
            missing, missing, missing,
            review_manifest_path=tmp_path / "review.json",
            pilot_report_path=tmp_path / "pilot.json",
            pilot_output_path=tmp_path / "pilot.parquet",
            review_sample_path=tmp_path / "sample.jsonl",
            blocked_report_path=missing,
            max_rows=1,
        )
    with pytest.raises(ValueError, match="aliases"):
        build_final_dataset(
            missing, missing, missing,
            review_manifest_path=tmp_path / "review.json",
            pilot_report_path=tmp_path / "pilot.json",
            pilot_output_path=tmp_path / "pilot.parquet",
            review_sample_path=tmp_path / "sample.jsonl",
            blocked_report_path=missing,
        )


def test_phase10_rejects_blocked_or_failure_reports_inside_output(tmp_path):
    missing = tmp_path / "missing"
    output = tmp_path / "final"
    for report_parameter, report_name in (
        ("blocked_report_path", Path("blocked.json")),
        ("failure_report_path", Path("nested") / "failure.json"),
    ):
        with pytest.raises(ValueError, match="inside output_dir"):
            build_final_dataset(
                missing, missing, output,
                review_manifest_path=tmp_path / "review.json",
                pilot_report_path=tmp_path / "pilot.json",
                pilot_output_path=tmp_path / "pilot.parquet",
                review_sample_path=tmp_path / "sample.jsonl",
                **{report_parameter: output / report_name},
            )


def test_phase11_freeze_rejects_output_alias(tmp_path):
    source = tmp_path / "source.jsonl"
    source.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="aliases"):
        freeze_evaluation(
            informal_path=source,
            controls_path=tmp_path / "controls.jsonl",
            rule_inventory_path=tmp_path / "rules.json",
            output_path=source,
            blocked_report=tmp_path / "blocked.json",
            require_full_composition=False,
        )
