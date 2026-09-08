"""Character-span alignment and source-to-target operation replay."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AlignmentResult:
    success: bool
    source_spans: tuple[dict[str, Any], ...]
    target_spans: tuple[dict[str, Any], ...]
    replayed_target: str | None
    reason: str | None = None


def diff_spans(source: str, target: str) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    source_spans: list[dict[str, Any]] = []
    target_spans: list[dict[str, Any]] = []
    matcher = difflib.SequenceMatcher(None, source, target, autojunk=False)
    for opcode, source_start, source_end, target_start, target_end in matcher.get_opcodes():
        if opcode == "equal":
            continue
        source_spans.append({"start": source_start, "end": source_end, "text": source[source_start:source_end]})
        target_spans.append({"start": target_start, "end": target_end, "text": target[target_start:target_end]})
    return tuple(source_spans), tuple(target_spans)


def replay_source_to_target(source: str, operation: dict[str, Any]) -> str:
    """Replay one generated correction operation from erroneous to gold text."""

    kind = operation.get("type")
    if kind in {"replace", "case"}:
        start = int(operation["source_start"])
        end = int(operation["source_end"])
        expected = str(operation["source_surface"])
        if source[start:end] != expected:
            raise ValueError("source replacement span does not match source surface")
        return source[:start] + str(operation["target_surface"]) + source[end:]
    if kind == "duplicate":
        start = int(operation["source_remove_start"])
        end = int(operation["source_remove_end"])
        if source[start:end] != str(operation["source_duplicate_surface"]):
            raise ValueError("duplicate removal span does not match source surface")
        return source[:start] + source[end:]
    if kind == "append":
        correct = str(operation["target_surface"])
        if operation.get("anchor") == "$START":
            return correct + (" " if source else "") + source
        start = int(operation["source_anchor_end"])
        expected = str(operation["source_anchor_surface"])
        anchor_start = int(operation["source_anchor_start"])
        if source[anchor_start:start] != expected:
            raise ValueError("append anchor does not match source surface")
        return source[:start] + " " + correct + source[start:]
    if kind == "add_punctuation":
        return source + str(operation["target_surface"])
    if kind == "change_punctuation":
        start = int(operation["source_start"])
        end = int(operation["source_end"])
        if source[start:end] != str(operation["source_surface"]):
            raise ValueError("punctuation source span does not match source surface")
        return source[:start] + str(operation["target_surface"]) + source[end:]
    raise ValueError(f"unsupported operation type: {kind}")


def validate_replay(source: str, target: str, operation: dict[str, Any]) -> AlignmentResult:
    try:
        replayed = replay_source_to_target(source, operation)
    except (KeyError, TypeError, ValueError) as error:
        return AlignmentResult(False, (), (), None, str(error))
    source_spans, target_spans = diff_spans(source, target)
    if replayed != target:
        return AlignmentResult(False, source_spans, target_spans, replayed, "operation replay did not recover target")
    if not source_spans and not target_spans:
        return AlignmentResult(False, source_spans, target_spans, replayed, "no aligned edit span")
    return AlignmentResult(True, source_spans, target_spans, replayed)
