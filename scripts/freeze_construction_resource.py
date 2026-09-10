"""Freeze manually reviewed Filipino hyphen/spacing construction records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.geg.resource_freeze import freeze_constructions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--resource", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at", required=True)
    parser.add_argument("--source-resource", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--license", required=True)
    args = parser.parse_args()
    result = freeze_constructions(
        args.input, args.resource, args.manifest,
        reviewer=args.reviewer, reviewed_at=args.reviewed_at,
        source_resource=args.source_resource, source_version=args.source_version,
        license_text=args.license,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
