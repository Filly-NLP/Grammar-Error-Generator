"""Deterministic article-aware splitting of validated clean targets."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping


SPLIT_NAMES = ("train", "dev", "synthetic_test")


@dataclass(frozen=True)
class SplitAssignment:
    group_key: str
    split: str
    row_count: int


def group_key(clean_id: str, source_doc_id: str | None, *, group_by_document: bool = True) -> str:
    """Return the stable grouping key required by the Phase 5 contract."""

    if group_by_document and source_doc_id is not None and str(source_doc_id).strip():
        return f"document:{source_doc_id}"
    return f"sentence:{clean_id}"


def _tie_hash(seed: int, key: str) -> str:
    return hashlib.sha256(f"{seed}\0{key}".encode("utf-8")).hexdigest()


def assign_group_splits(
    group_counts: Mapping[str, int],
    fractions: Mapping[str, float],
    seed: int,
) -> dict[str, SplitAssignment]:
    """Assign whole groups while minimizing deviation from requested ratios.

    Groups are processed largest-first so a large article cannot be stranded
    in a nearly-full split. Ties are resolved by a seed-derived stable hash.
    No random module or process-dependent ordering is used.
    """

    if tuple(fractions) != SPLIT_NAMES:
        raise ValueError(f"fractions must contain {SPLIT_NAMES} in order")
    if any(value <= 0 for value in fractions.values()):
        raise ValueError("split fractions must be positive")
    if abs(sum(fractions.values()) - 1.0) > 1e-9:
        raise ValueError("split fractions must sum to 1")
    if any(count <= 0 for count in group_counts.values()):
        raise ValueError("group counts must be positive")

    total = sum(group_counts.values())
    targets = {name: total * fractions[name] for name in SPLIT_NAMES}
    current = {name: 0 for name in SPLIT_NAMES}
    assignments: dict[str, SplitAssignment] = {}
    ordered = sorted(
        group_counts.items(),
        key=lambda item: (-item[1], _tie_hash(seed, item[0]), item[0]),
    )
    for key, count in ordered:
        # Choose the split with the lowest current/target ratio. The hash tie
        # break makes equal-sized groups reproducible across Python versions.
        ranked = sorted(
            SPLIT_NAMES,
            key=lambda name: (
                current[name] / targets[name],
                _tie_hash(seed, f"{key}\0{name}"),
                name,
            ),
        )
        chosen = ranked[0]
        current[chosen] += count
        assignments[key] = SplitAssignment(key, chosen, count)
    return assignments


def count_groups(rows: Iterable[tuple[str, str | None, int]]) -> dict[str, int]:
    """Count rows by grouping key from ``(clean_id, source_doc_id, count)``."""

    result: dict[str, int] = defaultdict(int)
    for clean_id, source_doc_id, count in rows:
        result[group_key(clean_id, source_doc_id)] += int(count)
    return dict(result)
