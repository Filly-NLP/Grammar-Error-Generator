"""Build the deterministic, single-error Phase 8 pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.geg.alignment import AlignmentResult, validate_replay
from src.geg.config import config_hash as compute_config_hash, load_config
from src.geg.generators import GENERATOR_VERSION, Candidate, all_tag_ids, generate_candidates
from src.geg.hashing import sha256_file, sha256_files
from src.geg.ingest import normalize_text
from src.geg.tags import require_registered, registry


PILOT_TARGETS = {"train": 70_000, "dev": 15_000, "synthetic_test": 15_000}
SPLIT_ORDER = {name: index for index, name in enumerate(PILOT_TARGETS)}
PILOT_BUILDER_VERSION = "filly-phase8-pilot-v2"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _allocate_quotas(capacities: dict[str, int], target: int) -> dict[str, int]:
    """Allocate a near-balanced tag quota without exceeding estimated capacity."""

    if not capacities:
        return {}
    quotas = {tag: min(capacity, target // len(capacities)) for tag, capacity in capacities.items()}
    remaining = target - sum(quotas.values())
    while remaining > 0:
        available = [tag for tag in capacities if quotas[tag] < capacities[tag]]
        if not available:
            break
        chosen = max(available, key=lambda tag: (capacities[tag] - quotas[tag], tag))
        quotas[chosen] += 1
        remaining -= 1
    return quotas


def _pair_id(seed: int, split: str, clean_id: str, candidate: Candidate) -> str:
    value = json.dumps(
        [seed, split, clean_id, candidate.correction_tag, candidate.source_text, candidate.target_text],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _structurally_valid(candidate: Candidate) -> tuple[bool, str, AlignmentResult]:
    try:
        require_registered(candidate.correction_tag)
    except ValueError:
        return False, "unregistered_tag", AlignmentResult(False, (), (), None, "unregistered_tag")
    if candidate.source_text == candidate.target_text:
        return False, "source_equals_target", AlignmentResult(False, (), (), None, "source_equals_target")
    if candidate.target_text != normalize_text(candidate.target_text):
        return False, "target_not_normalized", AlignmentResult(False, (), (), None, "target_not_normalized")
    if candidate.source_text != normalize_text(candidate.source_text):
        return False, "source_not_normalized", AlignmentResult(False, (), (), None, "source_not_normalized")
    if candidate.generation_operation.get("type") not in {
        "replace", "duplicate", "append", "add_punctuation", "change_punctuation", "case",
    }:
        return False, "unknown_operation", AlignmentResult(False, (), (), None, "unknown_operation")
    if candidate.generation_operation.get("type") == "append":
        operation = candidate.generation_operation
        anchor = operation.get("anchor")
        if anchor == "$START":
            if operation.get("position") != "prepend" or candidate.source_token_index is not None:
                return False, "append_anchor_index_mismatch", AlignmentResult(False, (), (), None, "append_anchor_index_mismatch")
            if operation.get("source_token_index_sentinel") != "$START":
                return False, "append_start_sentinel_missing", AlignmentResult(False, (), (), None, "append_start_sentinel_missing")
        elif anchor == "previous_token":
            expected = candidate.target_token_index - 1 if candidate.target_token_index is not None else None
            if expected is None or candidate.source_token_index != expected:
                return False, "append_anchor_index_mismatch", AlignmentResult(False, (), (), None, "append_anchor_index_mismatch")
            if operation.get("source_token_index_anchor") != expected:
                return False, "append_anchor_index_mismatch", AlignmentResult(False, (), (), None, "append_anchor_index_mismatch")
        else:
            return False, "append_anchor_missing", AlignmentResult(False, (), (), None, "append_anchor_missing")
    alignment = validate_replay(candidate.source_text, candidate.target_text, candidate.generation_operation)
    if not alignment.success:
        return False, "alignment_replay_failed", alignment
    if candidate.source_spans and (
        alignment.source_spans != candidate.source_spans or alignment.target_spans != candidate.target_spans
    ):
        return False, "alignment_span_mismatch", alignment
    return True, "", alignment


def _record(
    clean: dict[str, Any],
    candidate: Candidate,
    seed: int,
    config_hash: str,
    alignment: AlignmentResult,
) -> dict[str, Any]:
    split = str(clean["split"])
    return {
        "pair_id": _pair_id(seed, split, str(clean["clean_id"]), candidate),
        "clean_id": str(clean["clean_id"]),
        "source_text": candidate.source_text,
        "target_text": candidate.target_text,
        "is_errorful": True,
        "correction_tags": [candidate.correction_tag],
        "error_families": [candidate.family],
        "num_errors": 1,
        "generation_operation": json.dumps(candidate.generation_operation, ensure_ascii=False, sort_keys=True),
        "target_token_index": candidate.target_token_index,
        "source_token_index": candidate.source_token_index,
        "source_spans": list(alignment.source_spans),
        "target_spans": list(alignment.target_spans),
        "split": split,
        "dataset_stage": "phase8_pilot",
        "source_corpus": clean.get("source_corpus"),
        "publisher": clean.get("publisher"),
        "source_doc_id": clean.get("source_doc_id"),
        "sqlite_table": clean.get("sqlite_table"),
        "sqlite_rowid": clean.get("sqlite_rowid"),
        "seed": seed,
        "generator_version": GENERATOR_VERSION,
        "pilot_builder_version": PILOT_BUILDER_VERSION,
        "config_hash": config_hash,
        "alignment_success": alignment.success,
        "quality_flags": json.dumps(["automated_structural_review_passed"], ensure_ascii=False),
        "confidence": candidate.confidence,
    }


def _review_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 8 pilot report",
        "",
        "The pilot uses one conservative inverse corruption per errorful pair.",
        "Generated output pairs are deduplicated by exact `(source_text,",
        "target_text)` collision only; the validated primary input is never",
        "deduplicated or reclustered here.",
        "",
        f"- Status: **{report['status']}**",
        f"- Requested rows: **{report['requested_rows']}**",
        f"- Produced rows: **{report['produced_rows']}**",
        f"- Shortfall: **{report['shortfall']}**",
        f"- Collision rejections: **{report['collision_rejections']}**",
        f"- Automated structural review: **{report['automated_structural_review']}**",
        f"- Human linguistic review: **{report['human_linguistic_review']}**",
        "",
        "## Split counts",
        "",
        "| Split | Requested | Produced |",
        "|---|---:|---:|",
    ]
    for split in PILOT_TARGETS:
        lines.append(f"| {split} | {PILOT_TARGETS[split]} | {report['split_counts'].get(split, 0)} |")
    lines.extend([
        "",
        "## Review state",
        "",
        "`reports/pilot_review_sample.jsonl` is a stratified sample by split,",
        "error family, and registered tag. Structural checks are complete, but",
        "the sample still requires human linguistic review. This report does not",
        "claim the pilot is linguistically reviewed or production-ready.",
        "",
    ])
    return "\n".join(lines)


def build_pilot(
    input_path: Path,
    capacity_report_path: Path,
    output_path: Path,
    report_json: Path,
    report_markdown: Path,
    review_sample_path: Path,
    seed: int = 20260905,
    config_hash: str = "",
    config_path: Path = Path("config/filly.yaml"),
) -> dict[str, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as error:
        raise RuntimeError("Phase 8 requires pyarrow") from error
    input_path = input_path.resolve()
    output_path = output_path.resolve()
    if input_path == output_path:
        raise ValueError("pilot output must be distinct from split input")
    capacity = json.loads(capacity_report_path.resolve().read_text(encoding="utf-8"))
    input_sha256 = sha256_file(input_path)
    generator_sha256 = sha256_files((Path("src/geg/generators.py").resolve(), Path("src/geg/alignment.py").resolve()))
    if capacity.get("input_sha256") != input_sha256:
        raise RuntimeError("stale capacity report: split input hash does not match; rerun Phase 6")
    if capacity.get("generator_version") != GENERATOR_VERSION or capacity.get("generator_sha256") != generator_sha256:
        raise RuntimeError("stale capacity report: generator version/hash does not match; rerun Phase 6")
    current_config_hash = compute_config_hash(load_config(config_path.resolve()))
    if capacity.get("config_hash") != current_config_hash:
        raise RuntimeError("stale capacity report: config hash does not match; rerun Phase 6")
    if config_hash and config_hash != current_config_hash:
        raise RuntimeError("stale pilot configuration hash; regenerate dependent artifacts")
    config_hash = current_config_hash
    capacity_report_sha256 = sha256_file(capacity_report_path.resolve())
    rows = {row["tag"]: row for row in capacity["tags"] if row["status"] == "supported" and row["candidates"] > 0}
    tags = [tag_id for tag_id in all_tag_ids() if tag_id in rows]
    capacities_by_split: dict[str, dict[str, int]] = {}
    quotas: dict[str, dict[str, int]] = {}
    for split, target in PILOT_TARGETS.items():
        capacities_by_split[split] = {}
        for tag in tags:
            row = rows[tag]
            # The census records total candidate positions and per-split
            # eligible sentence counts. Use a conservative proportional cap.
            sentences = max(int(row["eligible_clean_sentences"]), 1)
            estimated = int(row["candidates"] * int(row.get(split, 0)) / sentences * 0.95)
            capacities_by_split[split][tag] = max(0, estimated)
        quotas[split] = _allocate_quotas(capacities_by_split[split], target)

    import pyarrow.parquet as pq
    # Candidate construction is count-heavy; replay validation below computes
    # authoritative spans only for candidates that enter the pilot artifact.
    parquet = pq.ParquetFile(input_path)
    selected: list[dict[str, Any]] = []
    selected_pairs: set[tuple[str, str]] = set()
    selected_by_tag: Counter[tuple[str, str]] = Counter()
    selected_by_split: Counter[str] = Counter()
    fallback: dict[str, list[tuple[dict[str, Any], Candidate]]] = defaultdict(list)
    fallback_seen: set[tuple[str, str]] = set()
    rejected: Counter[str] = Counter()

    columns = [
        "clean_id", "text", "split", "source_corpus", "publisher", "source_doc_id",
        "sqlite_table", "sqlite_rowid",
    ]
    for batch in parquet.iter_batches(columns=columns):
        values = {name: batch.column(name).to_pylist() for name in columns}
        for index in range(len(values["clean_id"])):
            split = str(values["split"][index])
            if split not in PILOT_TARGETS:
                rejected["unknown_split"] += 1
                continue
            clean = {name: values[name][index] for name in columns}
            for tag in tags:
                # Once a tag quota is satisfied, a bounded overflow reserve is
                # enough to repair small split/collision estimation gaps. This
                # keeps the full-corpus pilot pass tractable.
                if (
                    selected_by_tag[(split, tag)] >= quotas[split].get(tag, 0)
                    and len(fallback[split]) >= 1_000
                ):
                    continue
                result = generate_candidates(str(clean["text"]), tag, compute_alignment=False)
                for candidate in result.candidates:
                    valid, reason, alignment = _structurally_valid(candidate)
                    if not valid:
                        rejected[reason] += 1
                        continue
                    pair_key = (candidate.source_text, candidate.target_text)
                    if pair_key in selected_pairs or pair_key in fallback_seen:
                        rejected["output_pair_collision"] += 1
                        continue
                    current_tag = selected_by_tag[(split, tag)]
                    if current_tag < quotas[split].get(tag, 0) and selected_by_split[split] < PILOT_TARGETS[split]:
                        selected_pairs.add(pair_key)
                        selected_by_tag[(split, tag)] += 1
                        selected_by_split[split] += 1
                        selected.append(_record(clean, candidate, seed, config_hash, alignment))
                    elif len(fallback[split]) < 20_000 and selected_by_split[split] < PILOT_TARGETS[split]:
                        fallback[split].append((clean, candidate))
                        fallback_seen.add(pair_key)

    # Fill any capacity-estimation gaps with deterministic overflow candidates.
    for split in PILOT_TARGETS:
        for clean, candidate in fallback[split]:
            if selected_by_split[split] >= PILOT_TARGETS[split]:
                break
            pair_key = (candidate.source_text, candidate.target_text)
            if pair_key in selected_pairs:
                continue
            selected_pairs.add(pair_key)
            selected_by_split[split] += 1
            selected_by_tag[(split, candidate.correction_tag)] += 1
            valid, reason, alignment = _structurally_valid(candidate)
            if not valid:
                rejected[reason] += 1
                continue
            selected.append(_record(clean, candidate, seed, config_hash, alignment))

    selected.sort(key=lambda row: (SPLIT_ORDER[row["split"]], row["correction_tags"][0], row["clean_id"], row["pair_id"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(selected)
    pq.write_table(table, output_path)

    # Five examples per available tag and split, deterministic after sorting.
    review_sample_path.parent.mkdir(parents=True, exist_ok=True)
    review_counts: Counter[tuple[str, str]] = Counter()
    with review_sample_path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in selected:
            key = (row["split"], row["correction_tags"][0])
            if review_counts[key] >= 5:
                continue
            review_counts[key] += 1
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    requested = sum(PILOT_TARGETS.values())
    report: dict[str, Any] = {
        "status": "complete" if len(selected) == requested else "shortfall",
        "input": str(input_path),
        "input_sha256": input_sha256,
        "capacity_report": str(capacity_report_path.resolve()),
        "capacity_report_sha256": capacity_report_sha256,
        "generator_version": GENERATOR_VERSION,
        "generator_sha256": generator_sha256,
        "pilot_builder_version": PILOT_BUILDER_VERSION,
        "output": str(output_path),
        "requested_rows": requested,
        "produced_rows": len(selected),
        "shortfall": requested - len(selected),
        "split_counts": dict(selected_by_split),
        "tag_counts": {f"{split}:{tag}": selected_by_tag[(split, tag)] for split in PILOT_TARGETS for tag in tags},
        "quotas": quotas,
        "collision_rejections": rejected.get("output_pair_collision", 0),
        "rejections": dict(rejected),
        "automated_structural_review": "complete",
        "human_linguistic_review": "pending",
        "pilot_review_complete": False,
        "one_error_per_errorful_pair": all(row["num_errors"] == 1 for row in selected),
        "normalization_noise_injected": False,
        "primary_input_deduplicated": False,
        "generator_version": GENERATOR_VERSION,
        "generator_sha256": generator_sha256,
        "seed": seed,
        "config_hash": config_hash,
        "output_sha256": sha256_file(output_path),
    }
    _write_json(report_json, report)
    report_markdown.parent.mkdir(parents=True, exist_ok=True)
    report_markdown.write_text(_review_markdown(report), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/interim/split_clean.parquet"))
    parser.add_argument("--capacity-report", type=Path, default=Path("reports/tag_capacity_report.json"))
    parser.add_argument("--output", type=Path, default=Path("data/pilot/gec_pilot_100k.parquet"))
    parser.add_argument("--report-json", type=Path, default=Path("reports/pilot_report.json"))
    parser.add_argument("--report-markdown", type=Path, default=Path("reports/pilot_report.md"))
    parser.add_argument("--review-sample", type=Path, default=Path("reports/pilot_review_sample.jsonl"))
    parser.add_argument("--seed", type=int, default=20260905)
    parser.add_argument("--config-hash", default="")
    parser.add_argument("--config", type=Path, default=Path("config/filly.yaml"))
    args = parser.parse_args()
    report = build_pilot(
        args.input, args.capacity_report, args.output, args.report_json,
        args.report_markdown, args.review_sample, args.seed, args.config_hash,
        args.config,
    )
    print(json.dumps({key: report[key] for key in ("status", "requested_rows", "produced_rows", "shortfall")}, indent=2))


if __name__ == "__main__":
    main()
