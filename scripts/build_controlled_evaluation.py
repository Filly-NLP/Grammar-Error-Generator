"""Build pending controlled evaluation rows from reviewed noise rules.

The input must contain held-out correct/grammar-errorful text and the
operator-supplied grammar edits.  This command creates no annotations and
cannot freeze the resulting rows.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation_noise.injector import NoiseResourceError, build_controlled_row, load_frozen_noise_rules


def _rows(path: Path) -> list[dict]:
    result: list[dict] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON on {path}:{line_number}") from error
        if not isinstance(value, dict):
            raise ValueError(f"input row is not an object on {path}:{line_number}")
        result.append(value)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="held-out rows containing G/N* and grammar edits")
    parser.add_argument("--rules", type=Path, required=True, help="frozen reviewed noise resource")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--normalizer-rule-inventory", type=Path, required=True)
    args = parser.parse_args()
    try:
        _, rules = load_frozen_noise_rules(args.rules)
        inventory = args.normalizer_rule_inventory
        rows = _rows(args.input)
        generated = []
        for row in rows:
            generated.append(build_controlled_row(
                sample_id=str(row["sample_id"]),
                base_clean_id=str(row["base_clean_id"]),
                gold_normalized_errorful=str(row["gold_normalized_errorful"]),
                gold_final_correct=str(row["gold_final_correct"]),
                grammar_tags=[str(tag) for tag in row["grammar_tags"]],
                grammar_families=[str(family) for family in row["grammar_families"]],
                grammar_edits=row["grammar_edits"],
                rules=rules,
                category=str(row.get("noise_category") or ("mixed_noise" if len(row["normalization_types"]) > 1 else row["normalization_types"][0])),
                seed=args.seed,
                provenance=row["provenance"],
                normalizer_training_rule_ids=inventory,
            ))
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite controlled evaluation output: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{args.output.name}.", suffix=".tmp", dir=str(args.output.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                for row in generated:
                    stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, args.output)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    except (KeyError, TypeError, ValueError, OSError, NoiseResourceError) as error:
        print(f"controlled evaluation generation blocked: {error}", file=sys.stderr)
        return 2
    print(f"wrote {len(generated)} pending controlled rows: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
