"""Evaluate a frozen sample manifest against prediction-artifact JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.artifacts import load_prediction_artifact
from src.evaluation.metrics import evaluate_predictions
from src.geg.hashing import sha256_file
from src.geg.artifacts import validate_destinations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-evaluation", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-resamples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260905)
    parser.add_argument("--include-per-tag", action="store_true")
    parser.add_argument("--normalizer-version")
    parser.add_argument("--gec-version")
    args = parser.parse_args()
    validate_destinations(
        {"frozen_evaluation": args.frozen_evaluation, "predictions": args.predictions},
        {"report": args.output},
    )
    frozen = json.loads(args.frozen_evaluation.read_text(encoding="utf-8"))
    if frozen.get("status") != "frozen":
        raise SystemExit("prediction evaluation requires a frozen evaluation manifest")
    metadata, predictions = load_prediction_artifact(args.predictions)
    samples = list(frozen.get("informal_rows", [])) + list(frozen.get("clean_control_rows", []))
    report = evaluate_predictions(
        samples,
        predictions,
        include_per_tag=args.include_per_tag,
        bootstrap_resamples=args.bootstrap_resamples,
        seed=args.seed,
        frozen_evaluation_sha256=sha256_file(args.frozen_evaluation),
        normalizer_version=args.normalizer_version or metadata.get("normalizer_version"),
        gec_version=args.gec_version or metadata.get("gec_version"),
        metadata=metadata,
    )
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite evaluation report: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote prediction evaluation report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
