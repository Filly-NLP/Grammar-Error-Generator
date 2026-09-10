"""Freeze a manually reviewed morphology JSONL into an immutable resource."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.geg.resource_freeze import freeze_morphology
from src.geg.config import config_hash, load_config, resolve_runtime_config


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
    parser.add_argument("--minimum-validated-states", type=int)
    parser.add_argument("--config", type=Path, default=Path("config/filly.yaml"))
    parser.add_argument("--resource-version", default="tagalog-verb-paradigms-v1")
    args = parser.parse_args()
    loaded_config = load_config(args.config)
    runtime = resolve_runtime_config(loaded_config)
    minimum_states = args.minimum_validated_states
    if minimum_states is None:
        minimum_states = int(runtime["runtime"]["minimum_validated_states_per_lemma"])
    overrides = {"minimum_validated_states_per_lemma": minimum_states} if args.minimum_validated_states is not None else {}
    result = freeze_morphology(
        args.input, args.resource, args.manifest,
        reviewer=args.reviewer, reviewed_at=args.reviewed_at,
        source_resource=args.source_resource, source_version=args.source_version,
        license_text=args.license, mapping_rule_version=args.mapping_rule_version,
        mapping_rule_artifact=args.mapping_rule_artifact,
        minimum_validated_states=minimum_states,
        resource_version=args.resource_version,
        effective_config_hash=config_hash(loaded_config),
        effective_config=runtime.get("runtime", {}),
        cli_overrides=overrides,
    )
    result["minimum_validated_states_per_lemma"] = minimum_states
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
