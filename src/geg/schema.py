"""Stable Arrow schemas for generated GEC artifacts.

The schema is intentionally explicit: nullable morphology provenance columns
are present on every pilot, candidate, and final row, including identity rows.
"""

from __future__ import annotations

from typing import Any


GEC_MORPHOLOGY_FIELDS = (
    "morphology_source_state",
    "morphology_target_state",
    "morphology_lemma",
    "morphology_resource_version",
)


def ensure_morphology_fields(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for field in GEC_MORPHOLOGY_FIELDS:
        result.setdefault(field, None)
    return result


def gec_arrow_schema():
    """Return a deterministic PyArrow schema when PyArrow is installed."""
    try:
        import pyarrow as pa
    except ImportError as error:  # pragma: no cover - optional data dependency
        raise RuntimeError("stable artifact schemas require pyarrow") from error
    span_type = pa.list_(pa.struct([
        pa.field("start", pa.int64()), pa.field("end", pa.int64()), pa.field("text", pa.string()),
    ]))
    fields = [
        pa.field("pair_id", pa.string(), nullable=False),
        pa.field("clean_id", pa.string(), nullable=False),
        pa.field("source_text", pa.string(), nullable=False),
        pa.field("target_text", pa.string(), nullable=False),
        pa.field("is_errorful", pa.bool_(), nullable=False),
        pa.field("correction_tags", pa.list_(pa.string())),
        pa.field("error_families", pa.list_(pa.string())),
        pa.field("num_errors", pa.int64()),
        pa.field("generation_operation", pa.string()),
        pa.field("source_spans", span_type),
        pa.field("target_spans", span_type),
        pa.field("split", pa.string()),
        pa.field("dataset_stage", pa.string()),
        *[pa.field(name, pa.string()) for name in GEC_MORPHOLOGY_FIELDS],
        pa.field("target_token_index", pa.int64()),
        pa.field("source_token_index", pa.int64()),
        pa.field("source_corpus", pa.string()),
        pa.field("publisher", pa.string()),
        pa.field("source_doc_id", pa.string()),
        pa.field("sqlite_table", pa.string()),
        pa.field("sqlite_rowid", pa.int64()),
        pa.field("seed", pa.int64()),
        pa.field("generator_version", pa.string()),
        pa.field("candidate_builder_version", pa.string()),
        pa.field("dataset_builder_version", pa.string()),
        pa.field("config_hash", pa.string()),
        pa.field("alignment_success", pa.bool_()),
        pa.field("quality_flags", pa.string()),
        pa.field("confidence", pa.string()),
    ]
    return pa.schema(fields)
