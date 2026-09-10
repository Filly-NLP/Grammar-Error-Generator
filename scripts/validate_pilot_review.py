"""Validate the hash-bound Phase 8 linguistic-review manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.geg.review import validate_review_manifest, write_gate_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("reports/pilot_review_manifest.json"))
    parser.add_argument("--pilot-report", type=Path, default=Path("reports/pilot_report.json"))
    parser.add_argument("--pilot-output", type=Path, default=Path("data/pilot/gec_pilot_100k.parquet"))
    parser.add_argument("--review-sample", type=Path, default=Path("reports/pilot_review_sample.jsonl"))
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    result = validate_review_manifest(
        args.manifest,
        pilot_report_path=args.pilot_report,
        pilot_output_path=args.pilot_output,
        review_sample_path=args.review_sample,
    )
    if args.report is not None:
        write_gate_report(args.report, result)
    print(json.dumps({"status": result.status, "allowed": result.allowed, "reason": result.reason}, ensure_ascii=True, indent=2))
    raise SystemExit(0 if result.allowed else 2)


if __name__ == "__main__":
    main()
