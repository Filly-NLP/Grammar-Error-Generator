"""Validate and freeze annotated evaluation data, or record a clean blocker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation_noise.freeze import freeze_evaluation
from src.evaluation_noise.schema import EvaluationValidationError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--informal", type=Path, required=True)
    parser.add_argument("--controls", type=Path, required=True)
    parser.add_argument("--rule-inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gec-train", type=Path)
    parser.add_argument("--gec-dev", type=Path)
    parser.add_argument("--normalizer-train", type=Path)
    parser.add_argument("--blocked-report", type=Path)
    parser.add_argument("--allow-fixture-size", action="store_true", help="Only for deterministic tests; never claims a production freeze.")
    args = parser.parse_args()
    try:
        result = freeze_evaluation(
            informal_path=args.informal,
            controls_path=args.controls,
            rule_inventory_path=args.rule_inventory,
            output_path=args.output,
            gec_train=args.gec_train,
            gec_dev=args.gec_dev,
            normalizer_train=args.normalizer_train,
            blocked_report=args.blocked_report,
            require_full_composition=not args.allow_fixture_size,
        )
    except (EvaluationValidationError, FileNotFoundError, FileExistsError) as error:
        print(f"evaluation freeze blocked: {error}", file=sys.stderr)
        return 2
    print(f"frozen evaluation manifest: {result['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
