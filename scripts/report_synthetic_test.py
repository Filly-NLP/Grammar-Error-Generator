"""Report controlled diagnostics for the frozen synthetic-test split."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.geg.reporting import build_synthetic_test_diagnostics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/gec_1m/synthetic_test/final.parquet"))
    parser.add_argument("--manifest", type=Path, default=Path("data/gec_1m/manifest.json"))
    parser.add_argument("--json", type=Path, default=Path("reports/synthetic_test_diagnostics.json"))
    parser.add_argument("--markdown", type=Path, default=Path("reports/SYNTHETIC_TEST_DIAGNOSTICS.md"))
    args = parser.parse_args()
    report = build_synthetic_test_diagnostics(args.input, args.json, args.markdown, manifest_path=args.manifest)
    print(json.dumps({key: report[key] for key in ("status", "total_rows", "errorful_rows", "identity_rows")}, indent=2))


if __name__ == "__main__":
    main()
