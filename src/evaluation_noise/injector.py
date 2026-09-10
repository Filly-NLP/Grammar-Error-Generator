"""Controlled, resource-driven informal-noise injection.

This module is intentionally independent of :mod:`src.geg`.  It operates on
an already-created ``N*`` (normalized-but-grammar-errorful) sentence and
only applies explicitly reviewed lexical rules in the reverse direction:

    normalized target -> informal source

The module creates pending annotation rows for controlled evaluation data;
it never marks a row reviewed or freezes an evaluation set.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

NOISE_CATEGORIES = frozenset({"slang", "abbreviation", "spelling_variation", "mixed_noise"})
APPROVED = "approved"


class NoiseResourceError(ValueError):
    """Raised when a noise resource is absent, unreviewed, or malformed."""


@dataclass(frozen=True)
class NoiseRule:
    """One reviewed literal transformation used by the controlled injector.

    ``source`` is the informal form and ``target`` is the normalized form.
    The injector searches for ``target`` in ``N*`` and replaces it with
    ``source`` while recording the reverse replay edit ``source -> target``.
    """

    rule_id: str
    category: str
    source: str
    target: str
    resource_version: str
    review_status: str = APPROVED
    pattern_id: str | None = None
    notes: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, resource_version: str) -> "NoiseRule":
        try:
            rule_id = str(value["id"])
            category = str(value["category"])
            source = str(value["source"])
            target = str(value["target"])
        except (KeyError, TypeError) as error:
            raise NoiseResourceError("noise rule requires id/category/source/target") from error
        if not rule_id or not category or not source or not target:
            raise NoiseResourceError("noise rule id/category/source/target must be non-empty")
        if category not in NOISE_CATEGORIES - {"mixed_noise"} and category != "mixed_noise":
            raise NoiseResourceError(f"unknown noise category: {category}")
        if source == target:
            raise NoiseResourceError(f"noise rule is a no-op: {rule_id}")
        return cls(
            rule_id=rule_id,
            category=category,
            source=source,
            target=target,
            resource_version=resource_version,
            review_status=str(value.get("review_status", "needs_review")),
            pattern_id=None if value.get("pattern_id") is None else str(value["pattern_id"]),
            notes=str(value.get("notes", "")),
        )


def _read_resource(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise NoiseResourceError(f"noise resource does not exist: {path}")
    try:
        if path.suffix.lower() in {".yaml", ".yml"}:
            try:
                import yaml  # type: ignore
            except ImportError as error:
                raise NoiseResourceError("YAML noise resources require PyYAML") from error
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
        else:
            value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as error:
        raise NoiseResourceError(f"could not parse noise resource: {path}") from error
    if not isinstance(value, dict):
        raise NoiseResourceError("noise resource must be an object")
    return value


def _resource_rules(value: Mapping[str, Any], *, require_frozen: bool = True) -> tuple[str, list[NoiseRule]]:
    status = str(value.get("status", ""))
    if require_frozen and status != "frozen":
        raise NoiseResourceError("noise resource status must be frozen")
    version = str(value.get("resource_version", ""))
    if not version:
        raise NoiseResourceError("noise resource requires resource_version")
    if require_frozen:
        if not str(value.get("source", "")).strip() or not str(value.get("license", "")).strip():
            raise NoiseResourceError("frozen noise resource requires source and license")
    rules_value = value.get("rules")
    if not isinstance(rules_value, list) or not rules_value:
        raise NoiseResourceError("noise resource requires a non-empty rules list")
    rules = [NoiseRule.from_mapping(item, resource_version=version) for item in rules_value if isinstance(item, Mapping)]
    if len(rules) != len(rules_value):
        raise NoiseResourceError("noise resource rules must be objects")
    ids: set[str] = set()
    for rule in rules:
        if rule.rule_id in ids:
            raise NoiseResourceError(f"duplicate noise rule id: {rule.rule_id}")
        ids.add(rule.rule_id)
        if rule.review_status != APPROVED:
            raise NoiseResourceError(f"noise rule is not approved: {rule.rule_id}")
    return version, rules


def load_frozen_noise_rules(path: Path) -> tuple[str, list[NoiseRule]]:
    """Load only a frozen, fully approved rule resource."""

    return _resource_rules(_read_resource(path), require_frozen=True)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def freeze_noise_rules(
    input_path: Path,
    output_path: Path,
    *,
    reviewer: str,
    reviewed_at: str,
    source: str | None = None,
    license_text: str | None = None,
) -> dict[str, Any]:
    """Freeze a reviewed rule resource without fabricating review metadata.

    Every rule must already carry ``review_status=approved``.  Reviewer,
    review date, source, and license are explicit operator inputs.  Existing
    output is never overwritten.
    """

    if not reviewer.strip() or not reviewed_at.strip():
        raise NoiseResourceError("reviewer and reviewed_at are required")
    value = _read_resource(input_path)
    source_value = source or str(value.get("source", ""))
    license_value = license_text or str(value.get("license", ""))
    version, rules = _resource_rules({**value, "status": "frozen", "source": source_value, "license": license_value}, require_frozen=True)
    if not source_value.strip() or not license_value.strip():
        raise NoiseResourceError("source and license are required to freeze a noise resource")
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite frozen noise resource: {output_path}")
    manifest: dict[str, Any] = {
        "schema_version": "filly-evaluation-noise-resource-v1",
        "status": "frozen",
        "resource_version": version,
        "source": source_value,
        "license": license_value,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "input_sha256": _file_sha256(input_path),
        "rules": [
            {
                "id": rule.rule_id,
                "category": rule.category,
                "source": rule.source,
                "target": rule.target,
                "pattern_id": rule.pattern_id,
                "review_status": rule.review_status,
                "notes": rule.notes,
            }
            for rule in rules
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{output_path.name}.", suffix=".tmp", dir=str(output_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, output_path)
        except FileExistsError:
            raise FileExistsError(f"refusing to overwrite frozen noise resource: {output_path}")
        return manifest
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _normalizer_inventory(value: Mapping[str, Any] | Path | None) -> dict[str, Any]:
    """Load and validate the frozen normalizer inventory contract.

    An arbitrary set/list of IDs is deliberately not accepted: seen/unseen
    labels are meaningful only relative to a frozen, provenance-bearing
    inventory.  A rule without ``pattern_id`` uses its rule ID as its stable
    pattern identity for backwards-compatible inventories.
    """

    if value is None:
        raise NoiseResourceError("a frozen normalizer-rule inventory is required")
    if isinstance(value, Path):
        value = _read_resource(value)
    if not isinstance(value, Mapping):
        raise NoiseResourceError("normalizer-rule inventory must be a frozen resource object or path")
    if str(value.get("status", "")) != "frozen":
        raise NoiseResourceError("normalizer-rule inventory status must be frozen")
    if not str(value.get("version", "")).strip():
        raise NoiseResourceError("normalizer-rule inventory requires version")
    if not str(value.get("source", "")).strip() or not str(value.get("license", "")).strip():
        raise NoiseResourceError("normalizer-rule inventory requires source and license")
    rules = value.get("rules")
    if not isinstance(rules, list) or not rules:
        raise NoiseResourceError("normalizer-rule inventory requires a non-empty rules list")
    rule_ids: set[str] = set()
    patterns_by_rule: dict[str, set[str]] = {}
    pattern_ids: set[str] = set()
    for index, item in enumerate(rules):
        if not isinstance(item, Mapping):
            raise NoiseResourceError(f"normalizer-rule inventory rule {index} must be an object")
        rule_id = str(item.get("id", ""))
        if not rule_id:
            raise NoiseResourceError(f"normalizer-rule inventory rule {index} requires id")
        review_status = str(item.get("review_status", APPROVED))
        if review_status != APPROVED:
            raise NoiseResourceError(f"normalizer-rule inventory rule is not approved: {rule_id}")
        if rule_id in rule_ids:
            raise NoiseResourceError(f"duplicate normalizer-rule inventory id: {rule_id}")
        raw_patterns = item.get("pattern_ids")
        if raw_patterns is None:
            raw_patterns = [item.get("pattern_id", rule_id)]
        if not isinstance(raw_patterns, list) or not raw_patterns or any(not str(pattern).strip() for pattern in raw_patterns):
            raise NoiseResourceError(f"normalizer-rule inventory rule requires pattern_id(s): {rule_id}")
        patterns = {str(pattern) for pattern in raw_patterns}
        rule_ids.add(rule_id)
        patterns_by_rule[rule_id] = patterns
        pattern_ids.update(patterns)
    return {"rule_ids": rule_ids, "patterns_by_rule": patterns_by_rule, "pattern_ids": pattern_ids}


def normalizer_rule_ids(value: Mapping[str, Any] | Path | None) -> set[str]:
    """Return IDs from a validated frozen normalizer inventory.

    This compatibility helper returns the union of rule and pattern IDs, but
    still performs the full frozen/approved schema validation first.
    """

    inventory = _normalizer_inventory(value)
    return set(inventory["rule_ids"]) | set(inventory["pattern_ids"])


def _overlaps(start: int, end: int, protected_spans: Sequence[tuple[int, int]]) -> bool:
    return any(start < protected_end and end > protected_start for protected_start, protected_end in protected_spans)


def inject_informal_noise(
    normalized_errorful: str,
    rules: Sequence[NoiseRule],
    *,
    category: str,
    sample_id: str,
    seed: int,
    normalizer_training_rule_ids: Mapping[str, Any] | Path | None = None,
    protected_spans: Sequence[tuple[int, int]] = (),
) -> dict[str, Any]:
    """Inject deterministic informal noise into ``N*``.

    The returned ``normalization_edits`` replay ``R -> N*``.  Only literal
    reviewed rules are considered, and grammar spans may be protected to
    ensure the designated GEC error is not modified by the noise pass.
    """

    if not isinstance(normalized_errorful, str) or not normalized_errorful:
        raise NoiseInjectionError("normalized_errorful must be non-empty")
    if category not in NOISE_CATEGORIES:
        raise NoiseInjectionError(f"unknown noise category: {category}")
    inventory = _normalizer_inventory(normalizer_training_rule_ids)
    candidates: list[tuple[int, str, NoiseRule, int]] = []
    category_rules = [
        rule for rule in rules
        if rule.review_status == APPROVED
        and (rule.category == category or (category == "mixed_noise" and rule.category in {"slang", "abbreviation", "spelling_variation", "mixed_noise"}))
    ]
    for rule in category_rules:
        pattern_id = rule.pattern_id or rule.rule_id
        # A rule's pattern, rather than its arbitrary row position, defines
        # seen/unseen status.  Callers can therefore hold out a pattern while
        # retaining a related resource row.
        known_rule_patterns = inventory["patterns_by_rule"].get(rule.rule_id)
        if known_rule_patterns is None:
            seen = pattern_id in inventory["pattern_ids"]
        else:
            seen = pattern_id in known_rule_patterns
        for start in range(len(normalized_errorful)):
            if normalized_errorful.startswith(rule.target, start):
                end = start + len(rule.target)
                if not _overlaps(start, end, protected_spans):
                    digest = hashlib.sha256(f"{seed}|{sample_id}|{category}|{rule.rule_id}|{start}".encode("utf-8")).hexdigest()
                    candidates.append((int(digest, 16), "seen_rule" if seen else "unseen_pattern", rule, start))
    if not candidates:
        raise NoiseInjectionError(f"no applicable reviewed noise rule for category {category}")
    candidates.sort(key=lambda item: (item[0], item[2].rule_id, item[3]))
    selected: list[tuple[str, NoiseRule, int]] = []
    if category == "mixed_noise":
        # A row has one overall seen/unseen status.  Choose two compatible
        # rules from the same status bucket; a mixed-status row is rejected
        # instead of being silently coerced to seen_rule.
        for desired_status in ("seen_rule", "unseen_pattern"):
            trial: list[tuple[str, NoiseRule, int]] = []
            for _, status, rule, start in candidates:
                if status != desired_status:
                    continue
                if any(other.category == rule.category for _, other, _ in trial):
                    continue
                end = start + len(rule.target)
                prior_spans = tuple((other_start, other_start + len(other.target)) for _, other, other_start in trial)
                if _overlaps(start, end, prior_spans):
                    continue
                trial.append((status, rule, start))
                if len(trial) >= 2:
                    selected = trial
                    break
            if selected:
                break
    else:
        for _, status, rule, start in candidates:
            selected.append((status, rule, start))
            break
    if category == "mixed_noise" and (len(selected) < 2 or len({rule.category for _, rule, _ in selected}) < 2):
        raise NoiseInjectionError("mixed_noise requires two non-overlapping reviewed rules from distinct categories")

    raw = normalized_errorful
    edits: list[dict[str, Any]] = []
    selected_sorted = sorted(selected, key=lambda item: item[2])
    for status, rule, start in sorted(selected, key=lambda item: item[2], reverse=True):
        end = start + len(rule.target)
        raw = raw[:start] + rule.source + raw[end:]
        shift = sum(len(previous.source) - len(previous.target) for _, previous, previous_start in selected_sorted if previous_start < start)
        final_start = start + shift
        edits.append({
            "start": final_start,
            "end": final_start + len(rule.source),
            "source": rule.source,
            "target": rule.target,
            "kind": "informal_noise",
            "rule_id": rule.rule_id,
            "pattern_id": rule.pattern_id or rule.rule_id,
            "category": rule.category,
            "seen_status": status,
        })
    edits.sort(key=lambda item: (item["start"], item["end"]))
    statuses = {str(item["seen_status"]) for item in edits}
    overall_status = "unseen_pattern" if statuses == {"unseen_pattern"} else "seen_rule"
    rule_ids = [str(item["rule_id"]) for item in edits]
    return {
        "raw_informal": raw,
        "normalization_edits": edits,
        "normalization_rule_id": rule_ids[0],
        "normalization_rule_ids": rule_ids,
        "normalization_rule_seen_status": overall_status,
        "normalization_pattern_id": str(edits[0]["pattern_id"]),
        "normalization_pattern_ids": [str(item["pattern_id"]) for item in edits],
        "resource_version": selected[0][1].resource_version,
    }


class NoiseInjectionError(ValueError):
    """Raised when no safe deterministic controlled-noise application exists."""


def _replay_edits(source_text: str, edits: Sequence[Mapping[str, Any]]) -> str:
    """Small local replay guard so the injector remains independent of GEG."""

    ordered = sorted((dict(edit) for edit in edits), key=lambda item: (int(item["start"]), int(item["end"])))
    previous_end = 0
    for edit in ordered:
        start, end = int(edit["start"]), int(edit["end"])
        source = str(edit["source"])
        if start < 0 or end < start or end > len(source_text) or start < previous_end:
            raise NoiseInjectionError("noise edit span is invalid or overlapping")
        if source_text[start:end] != source:
            raise NoiseInjectionError("noise edit source does not match raw text")
        if source == str(edit["target"]):
            raise NoiseInjectionError("noise edit is a no-op")
        previous_end = end
    for edit in reversed(ordered):
        start, end = int(edit["start"]), int(edit["end"])
        source_text = source_text[:start] + str(edit["target"]) + source_text[end:]
    return source_text


def build_controlled_row(
    *,
    sample_id: str,
    base_clean_id: str,
    gold_normalized_errorful: str,
    gold_final_correct: str,
    grammar_tags: Sequence[str],
    grammar_families: Sequence[str],
    grammar_edits: Sequence[Mapping[str, Any]],
    rules: Sequence[NoiseRule],
    category: str,
    seed: int,
    provenance: Mapping[str, Any],
    normalizer_training_rule_ids: Mapping[str, Any] | Path | None = None,
) -> dict[str, Any]:
    """Build a pending controlled row; annotation must be supplied later."""

    if not provenance:
        raise NoiseInjectionError("controlled rows require operator-supplied provenance")
    protected = [(int(edit["start"]), int(edit["end"])) for edit in grammar_edits]
    injected = inject_informal_noise(
        gold_normalized_errorful,
        rules,
        category=category,
        sample_id=sample_id,
        seed=seed,
        normalizer_training_rule_ids=normalizer_training_rule_ids,
        protected_spans=protected,
    )
    try:
        if _replay_edits(injected["raw_informal"], injected["normalization_edits"]) != gold_normalized_errorful:
            raise NoiseInjectionError("normalization edits do not replay raw_informal -> gold_normalized_errorful")
        if _replay_edits(gold_normalized_errorful, grammar_edits) != gold_final_correct:
            raise NoiseInjectionError("grammar edits do not replay gold_normalized_errorful -> gold_final_correct")
    except NoiseInjectionError as error:
        raise NoiseInjectionError(str(error)) from error
    return {
        "sample_id": sample_id,
        "base_clean_id": base_clean_id,
        "raw_informal": injected["raw_informal"],
        "gold_normalized_errorful": gold_normalized_errorful,
        "gold_final_correct": gold_final_correct,
        "normalization_types": [category],
        "normalization_edits": injected["normalization_edits"],
        "normalization_rule_id": injected["normalization_rule_id"],
        "normalization_rule_ids": injected["normalization_rule_ids"],
        "normalization_pattern_id": injected["normalization_pattern_id"],
        "normalization_pattern_ids": injected["normalization_pattern_ids"],
        "normalization_rule_seen_status": injected["normalization_rule_seen_status"],
        "grammar_tags": list(grammar_tags),
        "grammar_families": list(grammar_families),
        "grammar_edits": [dict(edit) for edit in grammar_edits],
        "source_type": "controlled",
        "real_or_controlled": "controlled",
        "provenance": dict(provenance),
        # These are intentionally pending.  Freeze validation rejects them
        # until a human supplies two distinct annotators and adjudication.
        "annotator_1": "",
        "annotator_2": "",
        "adjudication_status": "pending",
        "split": "test_only",
        "notes": "controlled noise generated; pending independent annotation and adjudication",
        "generation_status": "pending_annotation",
        "noise_resource_version": injected["resource_version"],
    }


__all__ = [
    "NOISE_CATEGORIES",
    "NoiseInjectionError",
    "NoiseResourceError",
    "NoiseRule",
    "build_controlled_row",
    "freeze_noise_rules",
    "inject_informal_noise",
    "load_frozen_noise_rules",
    "normalizer_rule_ids",
]
