"""Freeze a manually reviewed morphology JSONL into an immutable resource."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.geg.resource_freeze import freeze_morphology


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
    parser.add_argument("--mapping-rule-version", required=True)
    parser.add_argument("--mapping-rule-artifact", type=Path, required=True)
    parser.add_argument("--minimum-validated-states", type=int, default=3)
    parser.add_argument("--resource-version", default="tagalog-verb-paradigms-v1")
    args = parser.parse_args()
    result = freeze_morphology(
        args.input, args.resource, args.manifest,
        reviewer=args.reviewer, reviewed_at=args.reviewed_at,
        source_resource=args.source_resource, source_version=args.source_version,
        license_text=args.license, mapping_rule_version=args.mapping_rule_version,
        mapping_rule_artifact=args.mapping_rule_artifact,
        minimum_validated_states=args.minimum_validated_states,
        resource_version=args.resource_version,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
