"""Create blank, non-data evaluation templates.

The template contains no fabricated Filipino examples.  It is safe to commit
and is intentionally not a frozen evaluation artifact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import INFORMAL_COUNTS, CONTROL_MIN, CONTROL_MAX, SPLIT


def template_manifest(*, control_count: int = CONTROL_MIN) -> dict[str, Any]:
    if not CONTROL_MIN <= control_count <= CONTROL_MAX:
        raise ValueError(f"control_count must be {CONTROL_MIN}-{CONTROL_MAX}")
    return {
        "schema_version": "filly-evaluation-v1",
        "status": "template_only",
        "warning": "No evaluation examples are included. Populate and annotate before freezing.",
        "informal_required_rows": sum(INFORMAL_COUNTS.values()),
        "informal_category_counts": dict(INFORMAL_COUNTS),
        "clean_control_required_rows": control_count,
        "clean_control_allowed_range": [CONTROL_MIN, CONTROL_MAX],
        "required_split": SPLIT,
        "required_source_types": ["authentic", "controlled"],
        "required_fields": [
            "sample_id", "raw_informal", "gold_normalized_errorful", "gold_final_correct",
            "normalization_types", "normalization_edits", "grammar_tags", "grammar_families", "grammar_edits",
            "real_or_controlled", "source_type", "provenance", "annotator_1", "annotator_2", "adjudication_status",
            "normalization_rule_id", "normalization_rule_seen_status", "split",
        ],
        "authentic_dependency_requirements": [
            "public source identifiers and URLs", "license and attribution", "two annotator records",
            "adjudication record", "frozen normalization-rule inventory",
        ],
    }


def write_template(path: Path, *, control_count: int = CONTROL_MIN) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(template_manifest(control_count=control_count), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
