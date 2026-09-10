"""Hash-bound Phase 8 linguistic-review gate.

The pilot is an automatically structurally validated artifact, not a
linguistically approved resource.  Phase 9 and Phase 10 must therefore carry
the pilot report, output, and review-sample hashes into an explicit review
manifest.  This module intentionally has no way to infer approval from the
pilot report's ``status=complete`` field.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .hashing import generator_dependency_hash, sha256_file


REVIEW_SCHEMA_VERSION = 1
VALID_STATUSES = frozenset({"complete", "incomplete", "stale", "revise", "reject"})
APPROVING_DECISIONS = frozenset({"approve", "approved", "accept", "accepted"})
ROW_DECISIONS = APPROVING_DECISIONS | frozenset({"revise", "revision_required", "reject", "rejected"})
UNRESOLVED_DECISIONS = frozenset({"", "pending", "unresolved", "unknown"})


class ReviewGateError(RuntimeError):
    """Raised when Phase 9/10 is attempted without approved pilot review."""

    def __init__(self, result: "ReviewGateResult") -> None:
        self.result = result
        super().__init__(f"pilot linguistic review gate: {result.status}: {result.reason}")


@dataclass(frozen=True)
class ReviewGateResult:
    status: str
    reason: str
    review_manifest: str
    pilot_report: str
    pilot_output: str
    review_sample: str
    current_hashes: dict[str, str | None]
    manifest_hash: str | None = None
    checked_at: str = ""

    @property
    def allowed(self) -> bool:
        return self.status == "complete"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _hash_or_none(path: Path) -> str | None:
    return sha256_file(path) if path.exists() and path.is_file() else None


def _resolve(path_value: Any, root: Path) -> Path:
    path = Path(str(path_value))
    return path if path.is_absolute() else root / path


def _current_hashes(pilot_report: Path, pilot_output: Path, review_sample: Path) -> dict[str, str | None]:
    return {
        "pilot_report_sha256": _hash_or_none(pilot_report),
        "pilot_output_sha256": _hash_or_none(pilot_output),
        "review_sample_sha256": _hash_or_none(review_sample),
    }


def _review_sample_rows(path: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Read sample rows and return rows plus canonical per-row hashes."""

    rows: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"review sample line {line_number} is invalid JSON") from error
        if not isinstance(row, dict) or not isinstance(row.get("pair_id"), str) or not row["pair_id"]:
            raise ValueError(f"review sample line {line_number} has no pair_id")
        pair_id = row["pair_id"]
        if pair_id in hashes:
            raise ValueError(f"review sample pair_id is duplicated: {pair_id}")
        canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        import hashlib
        hashes[pair_id] = hashlib.sha256(canonical).hexdigest()
        rows.append(row)
    return rows, hashes


def _valid_review_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _result(
    status: str,
    reason: str,
    manifest: Path,
    pilot_report: Path,
    pilot_output: Path,
    review_sample: Path,
    hashes: dict[str, str | None],
    manifest_hash: str | None = None,
) -> ReviewGateResult:
    return ReviewGateResult(
        status=status,
        reason=reason,
        review_manifest=str(manifest.resolve()),
        pilot_report=str(pilot_report.resolve()),
        pilot_output=str(pilot_output.resolve()),
        review_sample=str(review_sample.resolve()),
        current_hashes=hashes,
        manifest_hash=manifest_hash,
        checked_at=_now(),
    )


def validate_review_manifest(
    manifest_path: Path,
    *,
    pilot_report_path: Path | None = None,
    pilot_output_path: Path | None = None,
    review_sample_path: Path | None = None,
    root: Path | None = None,
) -> ReviewGateResult:
    """Validate the review manifest against the exact current pilot files.

    ``status`` is intentionally more specific than a boolean: an absent or
    malformed manifest is ``incomplete``; hash drift is ``stale``; reviewer
    decisions are ``revise`` or ``reject``; only a complete, approving,
    row-count-matching manifest is allowed through.
    """

    manifest_path = manifest_path.resolve()
    root = (root or Path.cwd()).resolve()
    if not manifest_path.exists():
        report = (pilot_report_path or root / "reports/pilot_report.json").resolve()
        output = (pilot_output_path or root / "data/pilot/gec_pilot_100k.parquet").resolve()
        sample = (review_sample_path or root / "reports/pilot_review_sample.jsonl").resolve()
        return _result("incomplete", "review manifest does not exist", manifest_path, report, output, sample, _current_hashes(report, output, sample))

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        missing = (pilot_report_path or root / "reports/pilot_report.json").resolve()
        output = (pilot_output_path or root / "data/pilot/gec_pilot_100k.parquet").resolve()
        sample = (review_sample_path or root / "reports/pilot_review_sample.jsonl").resolve()
        return _result("incomplete", f"cannot read review manifest: {error}", manifest_path, missing, output, sample, _current_hashes(missing, output, sample))
    if not isinstance(payload, dict):
        report = (pilot_report_path or root / "reports/pilot_report.json").resolve()
        output = (pilot_output_path or root / "data/pilot/gec_pilot_100k.parquet").resolve()
        sample = (review_sample_path or root / "reports/pilot_review_sample.jsonl").resolve()
        return _result("incomplete", "review manifest root must be an object", manifest_path, report, output, sample, _current_hashes(report, output, sample))

    target = payload.get("target", {})
    if not isinstance(target, dict):
        target = {}
    report = _resolve(pilot_report_path or target.get("pilot_report", root / "reports/pilot_report.json"), root).resolve()
    output = _resolve(pilot_output_path or target.get("pilot_output", root / "data/pilot/gec_pilot_100k.parquet"), root).resolve()
    sample = _resolve(review_sample_path or target.get("review_sample", root / "reports/pilot_review_sample.jsonl"), root).resolve()
    current = _current_hashes(report, output, sample)
    manifest_hash = sha256_file(manifest_path)
    if payload.get("schema_version") != REVIEW_SCHEMA_VERSION:
        return _result("incomplete", f"unsupported review schema_version={payload.get('schema_version')!r}", manifest_path, report, output, sample, current, manifest_hash)
    for name, value in current.items():
        if value is None:
            return _result("incomplete", f"review dependency missing: {name}", manifest_path, report, output, sample, current, manifest_hash)
        if payload.get(name) != value and target.get(name) != value:
            return _result("stale", f"hash mismatch for {name}", manifest_path, report, output, sample, current, manifest_hash)

    try:
        pilot_report = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return _result("incomplete", f"cannot read pilot report: {error}", manifest_path, report, output, sample, current, manifest_hash)
    if pilot_report.get("status") != "complete":
        return _result("incomplete", "pilot report is not complete", manifest_path, report, output, sample, current, manifest_hash)
    # New production pilots carry the canonical generator/resource dependency
    # and the exact Phase 6 capacity hash.  Older fixture manifests may omit
    # these fields only as an explicit compatibility/dev path; they cannot be
    # marked production-ready by the Phase 9/10 preflights.
    strict_production = "production_ready" in pilot_report or payload.get("production_ready") is not None
    if strict_production:
        if pilot_report.get("production_ready") is not True:
            return _result("incomplete", "pilot report is not production-ready", manifest_path, report, output, sample, current, manifest_hash)
        current_generator = generator_dependency_hash()
        declared_generator = pilot_report.get("generator_dependency_hash")
        if declared_generator != current_generator:
            return _result("stale", "generator/resource dependency hash changed", manifest_path, report, output, sample, current, manifest_hash)
        if payload.get("generator_dependency_hash") != current_generator or target.get("generator_dependency_hash") != current_generator:
            return _result("stale", "review manifest generator/resource dependency hash mismatch", manifest_path, report, output, sample, current, manifest_hash)
        capacity_path_value = pilot_report.get("capacity_report")
        capacity_path = _resolve(capacity_path_value, report.parent) if capacity_path_value else None
        capacity_hash = sha256_file(capacity_path) if capacity_path and capacity_path.is_file() else None
        if capacity_hash is None or pilot_report.get("capacity_report_sha256") != capacity_hash:
            return _result("stale", "capacity report dependency changed or is missing", manifest_path, report, output, sample, current, manifest_hash)
        if payload.get("capacity_report_sha256") != capacity_hash or target.get("capacity_report_sha256") != capacity_hash:
            return _result("stale", "review manifest capacity dependency mismatch", manifest_path, report, output, sample, current, manifest_hash)
    if pilot_report.get("human_linguistic_review") == "pending" or not pilot_report.get("pilot_review_complete", False):
        # A pending pilot report may be accompanied by an external review
        # manifest, but the reviewer must explicitly account for all sampled
        # rows.  Do not infer approval from the automated report.
        pass
    try:
        sample_records, sample_hashes = _review_sample_rows(sample)
        sample_rows = len(sample_records)
    except (OSError, UnicodeError, ValueError) as error:
        return _result("incomplete", f"cannot read review sample: {error}", manifest_path, report, output, sample, current, manifest_hash)
    row_decisions = payload.get("row_decisions", payload.get("decisions"))
    if not isinstance(row_decisions, list):
        return _result("incomplete", "row_decisions must be a list covering the review sample", manifest_path, report, output, sample, current, manifest_hash)
    decisions_by_pair: dict[str, dict[str, Any]] = {}
    for item in row_decisions:
        if not isinstance(item, dict) or not isinstance(item.get("pair_id"), str) or not item["pair_id"]:
            return _result("incomplete", "every row decision must contain a pair_id", manifest_path, report, output, sample, current, manifest_hash)
        pair_id = item["pair_id"]
        if pair_id in decisions_by_pair:
            return _result("incomplete", f"row decision pair_id is duplicated: {pair_id}", manifest_path, report, output, sample, current, manifest_hash)
        if pair_id not in sample_hashes:
            return _result("incomplete", f"row decision references unknown sample pair_id: {pair_id}", manifest_path, report, output, sample, current, manifest_hash)
        if item.get("sample_row_sha256") != sample_hashes[pair_id]:
            return _result("stale", f"row decision hash mismatch for pair_id={pair_id}", manifest_path, report, output, sample, current, manifest_hash)
        decision = str(item.get("decision", "")).lower()
        notes = item.get("notes")
        if decision in UNRESOLVED_DECISIONS or decision not in ROW_DECISIONS or not isinstance(notes, str) or not notes.strip():
            return _result("incomplete", f"unresolved row decision for pair_id={pair_id}", manifest_path, report, output, sample, current, manifest_hash)
        decisions_by_pair[pair_id] = item
    if set(decisions_by_pair) != set(sample_hashes) or len(decisions_by_pair) != sample_rows:
        return _result("incomplete", "row decisions do not uniquely cover every review-sample pair_id", manifest_path, report, output, sample, current, manifest_hash)
    reviewer = payload.get("reviewer")
    adjudicator = payload.get("adjudicator")
    if not isinstance(reviewer, str) or not reviewer.strip():
        return _result("incomplete", "reviewer identity is required", manifest_path, report, output, sample, current, manifest_hash)
    if not _valid_review_timestamp(payload.get("reviewed_at")):
        return _result("incomplete", "reviewed_at must be a timezone-aware ISO-8601 timestamp", manifest_path, report, output, sample, current, manifest_hash)
    status = str(payload.get("status", "incomplete"))
    decision = str(payload.get("decision", "")).lower()
    if status == "complete" or decision in APPROVING_DECISIONS:
        if not isinstance(adjudicator, str) or not adjudicator.strip():
            return _result("incomplete", "adjudicator identity is required for an approval", manifest_path, report, output, sample, current, manifest_hash)
        if adjudicator.strip() == reviewer.strip():
            return _result("incomplete", "reviewer and adjudicator must be distinct", manifest_path, report, output, sample, current, manifest_hash)
    expected = payload.get("expected_review_rows", target.get("expected_review_rows"))
    reviewed = payload.get("reviewed_rows")
    if not isinstance(expected, int) or not isinstance(reviewed, int) or expected != sample_rows or reviewed != expected:
        return _result("incomplete", f"reviewed row count is incomplete (expected sample={sample_rows}, expected_review_rows={expected!r}, reviewed_rows={reviewed!r})", manifest_path, report, output, sample, current, manifest_hash)
    accepted = payload.get("accepted_rows")
    revised = payload.get("revised_rows")
    rejected = payload.get("rejected_rows")
    if not all(isinstance(value, int) and value >= 0 for value in (accepted, revised, rejected)):
        return _result("incomplete", "review decision counts are missing or invalid", manifest_path, report, output, sample, current, manifest_hash)
    if accepted + revised + rejected != reviewed:
        return _result("incomplete", "review decision counts do not cover every reviewed row", manifest_path, report, output, sample, current, manifest_hash)
    if status not in VALID_STATUSES:
        return _result("incomplete", f"unknown review status={status!r}", manifest_path, report, output, sample, current, manifest_hash)
    row_counts = Counter(str(item["decision"]).lower() for item in decisions_by_pair.values())
    derived_accepted = sum(row_counts[key] for key in APPROVING_DECISIONS)
    derived_revised = sum(row_counts[key] for key in {"revise", "revision_required"})
    derived_rejected = sum(row_counts[key] for key in {"reject", "rejected"})
    if (accepted, revised, rejected) != (derived_accepted, derived_revised, derived_rejected):
        return _result("incomplete", "declared review counts do not match row-level decisions", manifest_path, report, output, sample, current, manifest_hash)
    if status == "reject" or decision in {"reject", "rejected"}:
        return _result("reject", "linguistic reviewer rejected the pilot", manifest_path, report, output, sample, current, manifest_hash)
    if status == "revise" or decision in {"revise", "revision_required"}:
        return _result("revise", "linguistic reviewer requested revisions", manifest_path, report, output, sample, current, manifest_hash)
    if revised or rejected or accepted != expected:
        return _result("revise", "not every reviewed row was approved", manifest_path, report, output, sample, current, manifest_hash)
    if status != "complete" or decision not in APPROVING_DECISIONS:
        return _result("incomplete", "review is not complete and approving", manifest_path, report, output, sample, current, manifest_hash)
    return _result("complete", "hash-bound linguistic review approved", manifest_path, report, output, sample, current, manifest_hash)


def write_gate_report(path: Path, result: ReviewGateResult, *, attempted_output: Path | None = None) -> None:
    """Write a machine-readable blocked/accepted gate record."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(result)
    payload["allowed"] = result.allowed
    if attempted_output is not None:
        payload["attempted_output"] = str(attempted_output.resolve())
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_review_gate(
    manifest_path: Path,
    *,
    pilot_report_path: Path | None = None,
    pilot_output_path: Path | None = None,
    review_sample_path: Path | None = None,
    root: Path | None = None,
    blocked_report: Path | None = None,
    attempted_output: Path | None = None,
) -> ReviewGateResult:
    result = validate_review_manifest(
        manifest_path,
        pilot_report_path=pilot_report_path,
        pilot_output_path=pilot_output_path,
        review_sample_path=review_sample_path,
        root=root,
    )
    if blocked_report is not None:
        write_gate_report(blocked_report, result, attempted_output=attempted_output)
    if not result.allowed:
        raise ReviewGateError(result)
    return result


def review_manifest_template(
    pilot_report: Path,
    pilot_output: Path,
    review_sample: Path,
    *,
    expected_review_rows: int,
) -> dict[str, Any]:
    """Return a reviewer-facing manifest template with current hashes."""

    hashes = _current_hashes(pilot_report.resolve(), pilot_output.resolve(), review_sample.resolve())
    try:
        _, sample_hashes = _review_sample_rows(review_sample.resolve())
    except (OSError, UnicodeError, ValueError):
        sample_hashes = {}
    payload = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "status": "incomplete",
        "decision": "",
        "reviewer": "",
        "adjudicator": "",
        "reviewed_at": "",
        "target": {
            "pilot_report": str(pilot_report),
            "pilot_output": str(pilot_output),
            "review_sample": str(review_sample),
            **hashes,
        },
        **hashes,
        "expected_review_rows": expected_review_rows,
        "reviewed_rows": 0,
        "accepted_rows": 0,
        "revised_rows": 0,
        "rejected_rows": 0,
        "row_decisions": [
            {"pair_id": pair_id, "sample_row_sha256": row_hash, "decision": "", "notes": ""}
            for pair_id, row_hash in sample_hashes.items()
        ],
        "notes": "Complete only after every sampled candidate has been linguistically reviewed.",
    }
    try:
        report_payload = json.loads(pilot_report.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        report_payload = {}
    if isinstance(report_payload, dict):
        for name in ("production_ready", "generator_dependency_hash", "capacity_report_sha256"):
            if name in report_payload:
                payload[name] = report_payload[name]
                payload["target"][name] = report_payload[name]
    return payload
