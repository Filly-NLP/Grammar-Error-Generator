"""Measure shard-local Phase 9 eligibility and publish a global plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_candidates import build_candidate_plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/interim/split_clean.parquet"))
    parser.add_argument("--capacity-report", type=Path, default=Path("reports/tag_capacity_report.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/phase9_candidate_plan.json"))
    parser.add_argument("--config", type=Path, default=Path("config/filly.yaml"))
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--target-rows", type=int, required=True)
    parser.add_argument("--max-output-rows", type=int, required=True)
    parser.add_argument("--allow-development", action="store_true")
    args = parser.parse_args()
    report = build_candidate_plan(
        args.input, args.capacity_report, args.output,
        shard_count=args.shard_count, target_rows=args.target_rows,
        max_output_rows=args.max_output_rows, config_path=args.config,
        allow_development=args.allow_development,
    )
    print(json.dumps({key: report[key] for key in ("status", "shard_count", "global_requested_rows", "plan_sha256")}, indent=2))


if __name__ == "__main__":
    main()
