"""Import a local UniMorph Tagalog TSV into a reviewable mapping report.

The importer intentionally does not download or silently accept a remote
resource. UniMorph files must be supplied explicitly by the caller and every
mapped row is marked ``needs_review`` before it can become a frozen resource.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# Support both ``python -m scripts.import_unimorph_tgl`` and direct invocation.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.geg.morphology import map_unimorph_features


def import_tsv(input_path: Path, output_path: Path, report_path: Path) -> dict[str, object]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    emitted = 0
    malformed = 0
    with input_path.open("r", encoding="utf-8") as source, output_path.open(
        "w", encoding="utf-8", newline="\n"
    ) as destination:
        for line_number, line in enumerate(source, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split("\t")
            if len(fields) < 3:
                malformed += 1
                counts["malformed_row"] += 1
                continue
            lemma, surface, features = fields[:3]
            mapping = map_unimorph_features(features)
            counts[mapping.reason] += 1
            if mapping.state is None:
                continue
            record = {
                "lemma": lemma,
                "surface": surface,
                "unimorph_features": features,
                "balarila_state_candidate": mapping.state,
                "aspect": mapping.aspect,
                "focus": mapping.focus,
                "mapping_confidence": mapping.confidence,
                "resource_source": "unimorph_tgl",
                "review_status": "needs_review",
                "source_line": line_number,
            }
            destination.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            emitted += 1

    report: dict[str, object] = {
        "input": str(input_path.resolve()),
        "output": str(output_path.resolve()),
        "rows_emitted": emitted,
        "rows_malformed": malformed,
        "mapping_reasons": dict(sorted(counts.items())),
        "review_required": True,
        "resource_frozen": False,
        "notes": [
            "UniMorph features use a provisional mapping into Table 3.",
            "IMPACT and IMPOBJ are source/corruption states only in the Table 2 contract.",
            "No generated row is accepted as gold without manual review.",
        ],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="local UniMorph TSV")
    parser.add_argument("--output", type=Path, required=True, help="review JSONL output")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(import_tsv(args.input, args.output, args.report), indent=2))


if __name__ == "__main__":
    main()
