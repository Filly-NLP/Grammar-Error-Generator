"""Freeze an explicitly reviewed controlled-noise rule resource."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation_noise.injector import NoiseResourceError, freeze_noise_rules


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at", required=True)
    parser.add_argument("--source")
    parser.add_argument("--license", dest="license_text")
    args = parser.parse_args()
    try:
        result = freeze_noise_rules(
            args.input,
            args.output,
            reviewer=args.reviewer,
            reviewed_at=args.reviewed_at,
            source=args.source,
            license_text=args.license_text,
        )
    except (NoiseResourceError, FileExistsError, OSError) as error:
        print(f"noise resource freeze blocked: {error}", file=sys.stderr)
        return 2
    print(f"frozen controlled-noise resource: {result['resource_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
