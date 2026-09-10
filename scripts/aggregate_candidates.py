"""Aggregate immutable Phase 9 shard manifests before Phase 10."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_candidates import aggregate_candidate_manifests
from src.geg.config import load_config
from src.geg.dataset import split_composition, total_composition, SPLITS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/phase9_candidate_aggregate.json"))
    parser.add_argument("--required-by-split", type=Path)
    parser.add_argument("--config", type=Path, default=Path("config/filly.yaml"))
    parser.add_argument("--allow-development", action="store_true", help="allow explicit non-production planless fixture aggregation")
    args = parser.parse_args()
    required = None
    if args.required_by_split:
        required = json.loads(args.required_by_split.read_text(encoding="utf-8"))
    else:
        config = load_config(args.config)
        comp = total_composition(config)
        split_settings = config.get("splits", {})
        fractions = {split: split_settings.get(split, {"train": "0.70", "dev": "0.15", "synthetic_test": "0.15"}[split]) for split in SPLITS}
        required = split_composition(comp["errorful"], fractions)
    report = aggregate_candidate_manifests(args.manifest, args.output, required_by_split=required, allow_development=args.allow_development)
    print(json.dumps({key: report[key] for key in ("status", "requested_rows", "produced_rows", "shortfall", "phase10_capacity_adequate")}, indent=2))


if __name__ == "__main__":
    main()
