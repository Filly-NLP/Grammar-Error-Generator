"""Compact rejection telemetry shared by the generation phases.

Generation is intentionally conservative.  A sentence that simply has no
eligible occurrence for a tag is *not* a rejected candidate; it is
``not_applicable``.  Constructed candidates that fail a policy or structural
check are counted under an explicit reason and a small diagnostic sample is
retained so reports remain useful without growing with the corpus.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping


REJECTION_SAMPLE_LIMIT = 25


class RejectionTelemetry:
    """Bounded counters and examples for one phase or tag.

    The object is deliberately dependency-free and serializes to ordinary JSON
    data through :meth:`as_dict`.
    """

    def __init__(self, *, sample_limit: int = REJECTION_SAMPLE_LIMIT) -> None:
        if sample_limit < 0:
            raise ValueError("sample_limit must be non-negative")
        self.sample_limit = sample_limit
        self.not_applicable = 0
        self.candidate_selected = 0
        self.rejections: Counter[str] = Counter()
        self.samples: list[dict[str, Any]] = []

    @property
    def candidate_rejected(self) -> int:
        return sum(self.rejections.values())

    def add_not_applicable(self, count: int = 1) -> None:
        if count < 0:
            raise ValueError("not-applicable count must be non-negative")
        self.not_applicable += int(count)

    def add_selected(self, count: int = 1) -> None:
        if count < 0:
            raise ValueError("selected count must be non-negative")
        self.candidate_selected += int(count)

    def reject(self, reason: str, count: int = 1, sample: Mapping[str, Any] | None = None) -> None:
        if not reason:
            raise ValueError("rejection reason must be non-empty")
        if count < 0:
            raise ValueError("rejection count must be non-negative")
        self.rejections[str(reason)] += int(count)
        if sample is not None and len(self.samples) < self.sample_limit:
            item = {str(key): value for key, value in sample.items()}
            item.setdefault("reason", str(reason))
            self.samples.append(item)

    def merge_counts(self, counts: Mapping[str, int], *, sample: Mapping[str, Any] | None = None) -> None:
        for reason, count in counts.items():
            self.reject(str(reason), int(count), sample=sample if count else None)

    def merge(self, other: "RejectionTelemetry") -> None:
        self.not_applicable += other.not_applicable
        self.candidate_selected += other.candidate_selected
        for reason, count in other.rejections.items():
            self.rejections[reason] += count
        remaining = self.sample_limit - len(self.samples)
        if remaining > 0:
            self.samples.extend(other.samples[:remaining])

    def as_dict(self) -> dict[str, Any]:
        return {
            "not_applicable": self.not_applicable,
            "candidate_selected": self.candidate_selected,
            "candidate_rejected": self.candidate_rejected,
            "rejections": dict(sorted(self.rejections.items())),
            "samples": list(self.samples),
            "sample_limit": self.sample_limit,
        }


def telemetry_from_result(result: Any, *, context: Mapping[str, Any] | None = None) -> RejectionTelemetry:
    """Convert a ``GenerationResult``-like object into bounded telemetry."""

    telemetry = RejectionTelemetry()
    count = int(getattr(result, "not_applicable", 0) or 0)
    candidates = tuple(getattr(result, "candidates", ()) or ())
    if not candidates and getattr(result, "status", None) == "supported" and count == 0:
        count = 1
    telemetry.add_not_applicable(count)
    telemetry.add_selected(len(candidates))
    sample = dict(context or {})
    for reason, value in (getattr(result, "rejected", {}) or {}).items():
        telemetry.reject(str(reason), int(value), sample=sample or None)
    return telemetry


def merge_report_telemetry(report: Mapping[str, Any]) -> RejectionTelemetry:
    """Read either the new or legacy report telemetry shape."""

    value = report.get("rejection_telemetry")
    if not isinstance(value, Mapping):
        value = {
            "not_applicable": report.get("not_applicable", 0),
            "candidate_selected": report.get("candidate_selected", 0),
            "candidate_rejected": report.get("candidate_rejected", 0),
            "rejections": report.get("rejections", {}),
            "samples": report.get("rejection_samples", []),
        }
    telemetry = RejectionTelemetry(sample_limit=int(value.get("sample_limit", REJECTION_SAMPLE_LIMIT)))
    telemetry.not_applicable = int(value.get("not_applicable", 0) or 0)
    telemetry.candidate_selected = int(value.get("candidate_selected", 0) or 0)
    for reason, count in (value.get("rejections", {}) or {}).items():
        telemetry.rejections[str(reason)] = int(count)
    telemetry.samples = [dict(item) for item in (value.get("samples", []) or []) if isinstance(item, Mapping)][:telemetry.sample_limit]
    return telemetry
