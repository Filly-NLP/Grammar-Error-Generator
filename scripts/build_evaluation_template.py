"""Write a blank end-to-end evaluation template; never fabricates examples."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation_noise.template import write_template


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--control-count", type=int, default=200)
    args = parser.parse_args()
    write_template(args.output, control_count=args.control_count)
    print(f"wrote blank evaluation template: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
