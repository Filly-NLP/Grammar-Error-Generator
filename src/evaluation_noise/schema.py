"""Schema and integrity checks for the frozen FILLY end-to-end evaluation set.

The end-to-end set is intentionally more strict than a convenience JSONL
format.  Every sample must be traceable, annotated by two people (or two
explicit fixture annotators), and replayable from raw text through the gold
intermediate and final text.  The validator never repairs rows or silently
changes their labels.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.geg.alignment import diff_spans
from src.geg.tags import require_registered


INFORMAL_COUNTS = {
    "slang": 300,
    "abbreviation": 300,
    "spelling_variation": 300,
    "mixed_noise": 100,
}
CONTROL_MIN = 200
CONTROL_MAX = 500
SPLIT = "test_only"
RULE_STATUSES = frozenset({"seen_rule", "unseen_pattern"})
SOURCE_TYPES = frozenset({"authentic", "controlled", "clean_control"})


class EvaluationValidationError(ValueError):
    """Raised when evaluation data is incomplete or unsafe to freeze."""


@dataclass(frozen=True)
class ValidationSummary:
    informal_count: int
    clean_control_count: int
    informal_by_type: dict[str, int]
    source_types: dict[str, int]
    rule_statuses: dict[str, int]
    tag_counts: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "informal_count": self.informal_count,
            "clean_control_count": self.clean_control_count,
            "informal_by_type": dict(self.informal_by_type),
            "source_types": dict(self.source_types),
            "rule_statuses": dict(self.rule_statuses),
            "tag_counts": dict(self.tag_counts),
        }


def _text(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise EvaluationValidationError(f"{field} must be a string")
    if not allow_empty and not value:
        raise EvaluationValidationError(f"{field} must be non-empty")
    if "\x00" in value:
        raise EvaluationValidationError(f"{field} contains NUL")
    return value


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise EvaluationValidationError(f"{field} must be a list")
    return value


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvaluationValidationError(f"{field} must be an object")
    return value


def stable_rule_id(edit: Mapping[str, Any]) -> str:
    """Return a deterministic rule id for one normalization edit."""

    payload = {
        "source": edit.get("source"),
        "target": edit.get("target"),
        "kind": edit.get("kind", "text_edit"),
    }
    return "rule_" + hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _validate_edit(edit: Any, field: str) -> dict[str, Any]:
    item = dict(_object(edit, field))
    try:
        start = int(item["start"])
        end = int(item["end"])
    except (KeyError, TypeError, ValueError) as error:
        raise EvaluationValidationError(f"{field} requires integer start/end") from error
    if start < 0 or end < start:
        raise EvaluationValidationError(f"{field} has invalid span {start}:{end}")
    source = _text(item.get("source"), f"{field}.source", allow_empty=True)
    target = _text(item.get("target"), f"{field}.target", allow_empty=True)
    if source == target:
        raise EvaluationValidationError(f"{field} is a no-op: source and target must differ")
    result = {**item, "start": start, "end": end, "source": source, "target": target}
    if "tag" in result and result["tag"] is not None:
        try:
            require_registered(str(result["tag"]))
        except ValueError as error:
            raise EvaluationValidationError(str(error)) from error
    return result


def replay_edits(source_text: str, edits: Sequence[Mapping[str, Any]]) -> str:
    """Apply non-overlapping source-offset edits and fail on stale spans."""

    ordered = [_validate_edit(edit, "edit") for edit in edits]
    ordered.sort(key=lambda edit: (edit["start"], edit["end"]))
    previous_end = 0
    for edit in ordered:
        if edit["start"] > len(source_text) or edit["end"] > len(source_text):
            raise EvaluationValidationError(
                f"edit span {edit['start']}:{edit['end']} is outside source length {len(source_text)}"
            )
        if edit["start"] < previous_end:
            raise EvaluationValidationError("edits overlap")
        if source_text[edit["start"]:edit["end"]] != edit["source"]:
            raise EvaluationValidationError(
                f"edit source mismatch at {edit['start']}:{edit['end']}: "
                f"expected {source_text[edit['start']:edit['end']]!r}, got {edit['source']!r}"
            )
        previous_end = edit["end"]
    for edit in sorted(ordered, key=lambda item: (item["start"], item["end"]), reverse=True):
        source_text = source_text[:edit["start"]] + edit["target"] + source_text[edit["end"]:]
    return source_text


def _require_annotation(record: Mapping[str, Any]) -> None:
    for field in ("annotator_1", "annotator_2", "adjudication_status"):
        _text(record.get(field), field)
    if str(record["annotator_1"]).strip() == str(record["annotator_2"]).strip():
        raise EvaluationValidationError("annotator_1 and annotator_2 must be distinct")
    if str(record["adjudication_status"]).lower() not in {"approved", "adjudicated", "fixture_approved"}:
        raise EvaluationValidationError("adjudication_status must be approved/adjudicated")


def _require_provenance(record: Mapping[str, Any]) -> None:
    provenance = _object(record.get("provenance"), "provenance")
    for field in ("source_id", "source_type", "license"):
        _text(provenance.get(field), f"provenance.{field}")
    if not provenance.get("attribution"):
        raise EvaluationValidationError("provenance.attribution must be non-empty")
    if not provenance.get("captured_at"):
        raise EvaluationValidationError("provenance.captured_at must be non-empty")


def _validate_rule_inventory(inventory: Mapping[str, Any]) -> set[str]:
    inventory = _object(inventory, "rule_inventory")
    if inventory.get("status") != "frozen":
        raise EvaluationValidationError("rule_inventory.status must be 'frozen'")
    _text(inventory.get("version"), "rule_inventory.version")
    rules = _list(inventory.get("rules"), "rule_inventory.rules")
    ids: set[str] = set()
    for index, rule in enumerate(rules):
        item = _object(rule, f"rule_inventory.rules[{index}]")
        rule_id = _text(item.get("id"), f"rule_inventory.rules[{index}].id")
        if rule_id in ids:
            raise EvaluationValidationError(f"duplicate normalizer rule id: {rule_id}")
        ids.add(rule_id)
    if not ids:
        raise EvaluationValidationError("rule_inventory.rules must contain at least one frozen rule")
    _text(inventory.get("source"), "rule_inventory.source")
    _text(inventory.get("license"), "rule_inventory.license")
    return ids


def _validate_record(record: Mapping[str, Any], rule_ids: set[str], *, index: int) -> tuple[str, bool, set[str]]:
    prefix = f"record[{index}]"
    sample_id = _text(record.get("sample_id"), f"{prefix}.sample_id")
    raw = _text(record.get("raw_informal"), f"{prefix}.raw_informal")
    normalized = _text(record.get("gold_normalized_errorful"), f"{prefix}.gold_normalized_errorful")
    final = _text(record.get("gold_final_correct"), f"{prefix}.gold_final_correct")
    if record.get("split") != SPLIT:
        raise EvaluationValidationError(f"{prefix}.split must be {SPLIT!r}")
    source_type = _text(record.get("source_type"), f"{prefix}.source_type")
    if source_type not in SOURCE_TYPES:
        raise EvaluationValidationError(f"{prefix}.source_type is not recognized: {source_type!r}")
    if source_type == "controlled":
        _text(record.get("base_clean_id"), f"{prefix}.base_clean_id")
    if source_type != "clean_control":
        normalization_types = _list(record.get("normalization_types"), f"{prefix}.normalization_types")
        if not normalization_types:
            raise EvaluationValidationError(f"{prefix}.normalization_types must be non-empty")
        types = {str(value) for value in normalization_types}
        if not types.issubset(INFORMAL_COUNTS):
            raise EvaluationValidationError(f"{prefix}.normalization_types contains unknown category")
    else:
        types = set()
        if raw != normalized or normalized != final:
            raise EvaluationValidationError(f"{prefix} clean control must have identical raw/normalized/final text")
    _require_annotation(record)
    _require_provenance(record)
    normalization_edits = [_validate_edit(edit, f"{prefix}.normalization_edits[{i}]") for i, edit in enumerate(_list(record.get("normalization_edits"), f"{prefix}.normalization_edits"))]
    grammar_edits = [_validate_edit(edit, f"{prefix}.grammar_edits[{i}]") for i, edit in enumerate(_list(record.get("grammar_edits"), f"{prefix}.grammar_edits"))]
    if source_type != "clean_control" and not normalization_edits:
        raise EvaluationValidationError(f"{prefix} primary informal row requires nonempty normalization_edits")
    if source_type != "clean_control" and not grammar_edits:
        raise EvaluationValidationError(f"{prefix} primary informal row requires tagged grammar_edits")
    if source_type != "clean_control" and raw == normalized:
        raise EvaluationValidationError(f"{prefix} raw_informal must differ from gold_normalized_errorful")
    if source_type != "clean_control" and normalized == final:
        raise EvaluationValidationError(f"{prefix} gold_normalized_errorful must differ from gold_final_correct")
    if replay_edits(raw, normalization_edits) != normalized:
        raise EvaluationValidationError(f"{prefix} normalization edits do not replay to gold intermediate")
    if replay_edits(normalized, grammar_edits) != final:
        raise EvaluationValidationError(f"{prefix} grammar edits do not replay to gold final")
    tags = {str(tag) for tag in _list(record.get("grammar_tags"), f"{prefix}.grammar_tags")}
    for tag in tags:
        try:
            require_registered(tag)
        except ValueError as error:
            raise EvaluationValidationError(str(error)) from error
    if any(edit.get("tag") is None for edit in grammar_edits):
        raise EvaluationValidationError(f"{prefix}.grammar_edits must tag every grammar edit")
    edit_tags = {str(edit["tag"]) for edit in grammar_edits}
    if edit_tags != tags:
        raise EvaluationValidationError(f"{prefix}.grammar_tags do not match tagged grammar edits")
    if source_type == "clean_control" and (normalization_edits or grammar_edits or tags):
        raise EvaluationValidationError(f"{prefix} clean control must have no correction edits/tags")
    if source_type != "clean_control":
        rule_id = _text(record.get("normalization_rule_id"), f"{prefix}.normalization_rule_id")
        status = _text(record.get("normalization_rule_seen_status"), f"{prefix}.normalization_rule_seen_status")
        if status not in RULE_STATUSES:
            raise EvaluationValidationError(f"{prefix} has unknown normalization rule status")
        expected = "seen_rule" if rule_id in rule_ids else "unseen_pattern"
        if expected != status:
            raise EvaluationValidationError(f"{prefix} rule status is {status!r}; inventory implies {expected!r}")
    else:
        rule_id = ""
    _text(record.get("notes"), f"{prefix}.notes", allow_empty=True)
    return sample_id, source_type == "clean_control", types


def _read_jsonl_bytes(data: bytes, source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvaluationValidationError(f"evaluation input is not UTF-8: {source}") from error
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise EvaluationValidationError(f"invalid JSON on {source}:{line_number}") from error
        if not isinstance(item, dict):
            raise EvaluationValidationError(f"JSONL row is not an object on {source}:{line_number}")
        rows.append(item)
    return rows


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise EvaluationValidationError(f"evaluation input does not exist: {path}")
    return _read_jsonl_bytes(path.read_bytes(), str(path))


def load_records_bytes(data: bytes, *, source: str = "<bytes>") -> list[dict[str, Any]]:
    """Parse a JSONL snapshot without reopening a mutable path."""

    return _read_jsonl_bytes(data, source)


def load_records(path: Path) -> list[dict[str, Any]]:
    return _read_jsonl(path)


def _extract_external_records(path: Path) -> tuple[set[str], set[str]]:
    """Read only IDs/texts needed for the no-leakage check."""

    if not path.exists():
        raise EvaluationValidationError(f"GEC leakage dependency does not exist: {path}")
    if path.is_dir():
        ids: set[str] = set()
        texts: set[str] = set()
        children = sorted(item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in {".jsonl", ".json", ".parquet"})
        if not children:
            raise EvaluationValidationError(f"leakage dependency directory has no JSON/JSONL/Parquet views: {path}")
        for child in children:
            child_ids, child_texts = _extract_external_records(child)
            ids.update(child_ids)
            texts.update(child_texts)
        return ids, texts
    ids: set[str] = set()
    texts: set[str] = set()
    if path.suffix.lower() in {".jsonl", ".json"}:
        rows = _read_jsonl(path) if path.suffix.lower() == ".jsonl" else json.loads(path.read_text(encoding="utf-8"))
        if isinstance(rows, dict):
            rows = rows.get("rows", [])
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            for key in ("clean_id", "source_clean_id", "base_clean_id"):
                if row.get(key):
                    ids.add(str(row[key]))
            for key in (
                "source_text", "target_text", "text", "raw", "normalized", "source", "target",
                "nonstandard", "standardized", "raw_informal", "gold_normalized_errorful",
            ):
                if row.get(key):
                    texts.add(str(row[key]))
        return ids, texts
    try:
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(path)
        columns = [column for column in (
            "clean_id", "source_clean_id", "base_clean_id", "source_text", "target_text", "text",
            "raw", "normalized", "source", "target", "nonstandard", "standardized",
            "raw_informal", "gold_normalized_errorful",
        ) if column in parquet.schema_arrow.names]
        for batch in parquet.iter_batches(columns=columns):
            for row_index in range(batch.num_rows):
                for column in columns:
                    value = batch.column(column)[row_index].as_py()
                    if value is None:
                        continue
                    if column in {"clean_id", "source_clean_id", "base_clean_id"}:
                        ids.add(str(value))
                    else:
                        texts.add(str(value))
        return ids, texts
    except ImportError as error:
        raise EvaluationValidationError("Parquet leakage checks require pyarrow") from error


def validate_no_gec_leakage(records: Sequence[Mapping[str, Any]], *, forbidden_clean_ids: set[str] | None = None, forbidden_texts: set[str] | None = None, gec_train: Path | None = None, gec_dev: Path | None = None, normalizer_train: Path | None = None) -> None:
    ids = set(forbidden_clean_ids or ())
    texts = set(forbidden_texts or ())
    normalizer_texts: set[str] = set()
    for path in (gec_train, gec_dev):
        if path is not None:
            other_ids, other_texts = _extract_external_records(path)
            if path in (gec_train, gec_dev) and not other_ids:
                raise EvaluationValidationError(f"GEC leakage dependency contains no clean IDs: {path}")
            ids.update(other_ids)
            texts.update(other_texts)
    if normalizer_train is not None:
        _, normalizer_texts = _extract_external_records(normalizer_train)
        if not normalizer_texts:
            raise EvaluationValidationError(f"normalizer-example training dependency contains no examples: {normalizer_train}")
    for index, record in enumerate(records):
        record_ids = {str(record[key]) for key in ("clean_id", "base_clean_id", "source_clean_id") if record.get(key)}
        record_texts = {str(record[key]) for key in ("raw_informal", "gold_normalized_errorful", "gold_final_correct") if record.get(key)}
        if record_ids & ids:
            raise EvaluationValidationError(f"record[{index}] leaks a GEC clean_id")
        if record_texts & normalizer_texts:
            raise EvaluationValidationError(f"record[{index}] leaks a normalizer training example")
        if record_texts & texts:
            raise EvaluationValidationError(f"record[{index}] leaks a GEC sentence text")


def validate_dataset(records: Sequence[Mapping[str, Any]], rule_inventory: Mapping[str, Any], *, clean_controls: Sequence[Mapping[str, Any]] = (), forbidden_clean_ids: set[str] | None = None, forbidden_texts: set[str] | None = None, gec_train: Path | None = None, gec_dev: Path | None = None, normalizer_train: Path | None = None, require_full_composition: bool = True) -> ValidationSummary:
    rule_ids = _validate_rule_inventory(rule_inventory)
    if not records:
        raise EvaluationValidationError("informal evaluation set is empty")
    seen_ids: set[str] = set()
    type_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    for index, record in enumerate(records):
        sample_id, is_control, types = _validate_record(record, rule_ids, index=index)
        if is_control:
            raise EvaluationValidationError("clean controls must be supplied separately from informal records")
        if sample_id in seen_ids:
            raise EvaluationValidationError(f"duplicate sample_id: {sample_id}")
        seen_ids.add(sample_id)
        for category in types:
            type_counts[category] += 1
        source_counts[str(record["source_type"])] += 1
        statuses[str(record["normalization_rule_seen_status"])] += 1
        tag_counts.update(str(tag) for tag in record.get("grammar_tags", []))
    controls = list(clean_controls)
    control_ids: set[str] = set()
    for index, record in enumerate(controls):
        sample_id, is_control, _ = _validate_record(record, rule_ids, index=index)
        if not is_control:
            raise EvaluationValidationError("clean control rows must have source_type=clean_control")
        if sample_id in seen_ids or sample_id in control_ids:
            raise EvaluationValidationError(f"duplicate evaluation sample_id: {sample_id}")
        control_ids.add(sample_id)
    if require_full_composition:
        if len(records) != sum(INFORMAL_COUNTS.values()):
            raise EvaluationValidationError(f"informal evaluation set must contain exactly 1000 rows, got {len(records)}")
        if dict(type_counts) != INFORMAL_COUNTS:
            raise EvaluationValidationError(f"informal category composition mismatch: {dict(type_counts)}")
        if not {"authentic", "controlled"}.issubset(source_counts):
            raise EvaluationValidationError("informal evaluation set must contain authentic and controlled rows")
        if not CONTROL_MIN <= len(controls) <= CONTROL_MAX:
            raise EvaluationValidationError(f"clean control count must be {CONTROL_MIN}-{CONTROL_MAX}, got {len(controls)}")
    validate_no_gec_leakage(records + controls, forbidden_clean_ids=forbidden_clean_ids, forbidden_texts=forbidden_texts, gec_train=gec_train, gec_dev=gec_dev, normalizer_train=normalizer_train)
    return ValidationSummary(len(records), len(controls), dict(type_counts), dict(source_counts), dict(statuses), dict(tag_counts))


def make_edit(source: str, target: str, *, tag: str | None = None, kind: str = "text_edit") -> dict[str, Any]:
    """Build a replayable edit list for deterministic fixtures/templates."""

    source_spans, target_spans = diff_spans(source, target)
    if len(source_spans) != len(target_spans):
        raise EvaluationValidationError("diff produced incompatible source/target edit spans")
    edits: list[dict[str, Any]] = []
    for source_span, target_span in zip(source_spans, target_spans):
        item = {"start": source_span["start"], "end": source_span["end"], "source": source_span["text"], "target": target_span["text"], "kind": kind}
        if tag is not None:
            require_registered(tag)
            item["tag"] = tag
        edits.append(item)
    return edits
