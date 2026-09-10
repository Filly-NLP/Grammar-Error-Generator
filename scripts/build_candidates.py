"""Phase 9 bounded/sharded candidate builder.

This command is intentionally blocked until a hash-bound linguistic review
manifest approves the Phase 8 pilot.  It writes one deterministic Parquet
shard per invocation and never mutates the primary SQLite corpus.
"""

from __future__ import annotations

import argparse
import heapq
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import math
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.geg.config import config_hash as compute_config_hash, load_config, resolve_runtime_config
from src.geg.dataset import SPLITS
from src.geg.generators import GENERATOR_VERSION, GENERATOR_POLICY_STATUS, GeneratorContext, all_tag_ids, generate_candidates
from src.geg.hashing import sha256_file, generator_dependency_hash, legacy_generator_hash
from src.geg.review import ReviewGateError, require_review_gate
from src.geg.artifacts import validate_destinations
from src.geg.schema import gec_arrow_schema


CANDIDATE_BUILDER_VERSION = "filly-phase9-sharded-v1"
REJECTION_SAMPLE_LIMIT = 25


def _pair_id(seed: int, clean_id: str, source: str, target: str, tag: str) -> str:
    payload = f"{seed}|{clean_id}|{tag}|{source}|{target}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]


def _candidate_record(clean: dict[str, Any], candidate: Any, seed: int, config_hash: str) -> dict[str, Any]:
    return {
        "pair_id": _pair_id(seed, str(clean["clean_id"]), candidate.source_text, candidate.target_text, candidate.correction_tag),
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
        "source_spans": list(candidate.source_spans),
        "target_spans": list(candidate.target_spans),
        "split": str(clean["split"]),
        "dataset_stage": "phase9_candidates",
        "source_corpus": clean.get("source_corpus"),
        "publisher": clean.get("publisher"),
        "source_doc_id": clean.get("source_doc_id"),
        "sqlite_table": clean.get("sqlite_table"),
        "sqlite_rowid": clean.get("sqlite_rowid"),
        "seed": seed,
        "generator_version": GENERATOR_VERSION,
        "candidate_builder_version": CANDIDATE_BUILDER_VERSION,
        "config_hash": config_hash,
        "alignment_success": True,
        "quality_flags": json.dumps(["automated_structural_review_passed"], ensure_ascii=False),
        "confidence": candidate.confidence,
        "morphology_source_state": getattr(candidate, "morphology_source_state", None),
        "morphology_target_state": getattr(candidate, "morphology_target_state", None),
        "morphology_lemma": getattr(candidate, "morphology_lemma", None),
        "morphology_resource_version": getattr(candidate, "morphology_resource_version", None),
    }


def _shard_for(clean_id: str, shard_count: int) -> int:
    return int(hashlib.sha256(clean_id.encode("utf-8")).hexdigest(), 16) % shard_count


def _supported_tags(capacity: dict[str, Any]) -> list[str]:
    supported = {str(item["tag"]) for item in capacity.get("tags", []) if item.get("status") == "supported" and int(item.get("candidates", 0)) > 0}
    return [tag for tag in all_tag_ids() if tag in supported]


def _candidate_rank(seed: int, clean_id: str, split: str, tag: str, source: str, target: str) -> int:
    """Stable rank independent of Parquet row/batch order."""
    payload = f"{seed}|{split}|{clean_id}|{tag}|{source}|{target}".encode("utf-8")
    return int(hashlib.sha256(payload).hexdigest(), 16)


def _capacity_group_quotas(capacity: dict[str, Any], max_rows: int, tags: list[str]) -> dict[tuple[str, str], int]:
    """Allocate a bounded buffer across split/tag groups.

    Every group with observed capacity receives one slot whenever the bound
    permits it.  This prevents common early tags from consuming the entire
    bound and starving a rare tag that appears late in the input.  Remaining
    slots are assigned to groups with the greatest remaining capacity.
    """
    capacities: dict[tuple[str, str], int] = {}
    for item in capacity.get("tags", []):
        tag = str(item.get("tag"))
        if tag not in tags or item.get("status") != "supported":
            continue
        by_split = item.get("candidates_by_split", {}) or {}
        if not by_split and int(item.get("candidates", 0) or 0) > 0:
            # Legacy/fixture capacity reports predate per-split accounting.
            # Keep them usable for development by assigning the estimate to
            # every split; actual shard rows still determine what is produced.
            by_split = {split: int(item["candidates"]) for split in SPLITS}
        for split in SPLITS:
            value = max(0, int(by_split.get(split, 0)))
            if value:
                capacities[(split, tag)] = value
    if not capacities or max_rows <= 0:
        return {}
    target = min(max_rows, sum(capacities.values()))
    quotas = {group: 0 for group in capacities}
    if target < len(capacities):
        for group in sorted(capacities, key=lambda item: (capacities[item], item[0], item[1]))[:target]:
            quotas[group] = 1
        return quotas
    for group in quotas:
        quotas[group] = 1
    remaining = target - len(quotas)
    while remaining:
        choices = [group for group, value in capacities.items() if quotas[group] < value]
        if not choices:
            break
        choices.sort(key=lambda group: (-(capacities[group] - quotas[group]), group[0], group[1]))
        for group in choices:
            if not remaining:
                break
            quotas[group] += 1
            remaining -= 1
    return quotas


def _bounded_ranked_insert(
    buckets: dict[tuple[str, str], list[tuple[int, str]]],
    records: dict[str, dict[str, Any]],
    group: tuple[str, str],
    record: dict[str, Any],
    rank: int,
    limit: int,
) -> None:
    """Keep the lowest stable ranks for one group in a bounded heap."""
    key = str(record["pair_id"])
    if key in records:
        return
    records[key] = record
    heap = buckets.setdefault(group, [])
    # Negated rank makes the largest rank the heap root and therefore the
    # first candidate discarded when the bounded reserve is full.
    heapq.heappush(heap, (-rank, key))
    if len(heap) > limit:
        _, discarded = heapq.heappop(heap)
        records.pop(discarded, None)


def aggregate_candidate_manifests(
    manifest_paths: list[Path],
    output_path: Path | None = None,
    *,
    required_by_split: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Aggregate Phase 9 shard accounting without reading candidate rows.

    The aggregate is deliberately a separate artifact from each immutable
    shard.  It records buffer requests, produced rows, per-split/tag
    shortfalls, and bounded rejection telemetry so Phase 10 can fail closed
    before attempting an exact build.
    """
    if not manifest_paths:
        raise ValueError("at least one candidate shard manifest is required")
    manifest_paths = [Path(path) for path in manifest_paths]
    resolved_manifest_paths = [path.resolve() for path in manifest_paths]
    if len(set(resolved_manifest_paths)) != len(resolved_manifest_paths):
        raise RuntimeError("candidate aggregate contains duplicate shard manifest paths")
    if output_path is not None:
        if output_path.is_symlink() or output_path.exists():
            raise FileExistsError(f"refusing to overwrite candidate aggregate manifest: {output_path}")
        validate_destinations(
            {f"shard_manifest_{index}": path for index, path in enumerate(manifest_paths)},
            {"aggregate": output_path},
        )
    manifests = []
    for path in manifest_paths:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError(f"missing or invalid candidate shard manifest: {path}") from error
        if item.get("status") != "complete":
            raise RuntimeError(f"cannot aggregate incomplete candidate shard manifest: {path}")
        output = Path(str(item.get("output", ""))).resolve()
        if not output.is_file():
            raise RuntimeError(f"candidate shard output is missing: {output}")
        if item.get("output_sha256") != sha256_file(output):
            raise RuntimeError(f"candidate shard output hash mismatch: {output}")
        if item.get("shard_manifest_path"):
            declared = Path(str(item["shard_manifest_path"])).resolve()
            if declared != path.resolve():
                raise RuntimeError(f"candidate shard manifest path mismatch: {path}")
        item["_manifest_path"] = str(path.resolve())
        item["_output_path"] = str(output)
        manifests.append(item)
    shard_counts = {int(item.get("shard_count", 0)) for item in manifests}
    if len(shard_counts) != 1 or not next(iter(shard_counts), 0):
        raise RuntimeError("candidate shards do not agree on a positive shard_count")
    shard_count = next(iter(shard_counts))
    indices = [int(item.get("shard_index", -1)) for item in manifests]
    if len(indices) != shard_count or set(indices) != set(range(shard_count)):
        raise RuntimeError("candidate shard set is incomplete, duplicated, or out of range")
    output_paths = [item["_output_path"] for item in manifests]
    if len(set(output_paths)) != len(output_paths):
        raise RuntimeError("candidate aggregate contains duplicate shard output paths")
    required_dependencies = (
        "capacity_report_sha256", "config_hash", "quality_manifest_sha256",
        "split_report_sha256", "input_sqlite_sha256", "review_manifest_sha256",
    )
    canonical_keys = required_dependencies + (
        "generator_dependency_hash", "generator_version", "seed",
        "candidate_builder_version", "builder_version", "input_sha256",
    )
    for key in required_dependencies:
        values = {item.get(key) for item in manifests}
        if len(values) != 1 or None in values or "" in values:
            raise RuntimeError(f"candidate shards do not agree on required dependency: {key}")
    for item in manifests:
        if item.get("production_ready") is not True:
            raise RuntimeError("candidate shard aggregate requires production_ready=true")
    for key in canonical_keys:
        values = {item.get(key) for item in manifests}
        if len(values) != 1:
            raise RuntimeError(f"candidate shards do not agree on canonical dependency: {key}")
    tag_statuses = [item.get("tag_status") for item in manifests]
    if any(not isinstance(status, dict) or set(status) != set(all_tag_ids()) for status in tag_statuses):
        raise RuntimeError("candidate shard tag manifests must cover all registered tags")
    if any(status != tag_statuses[0] for status in tag_statuses[1:]):
        raise RuntimeError("candidate shards do not agree on tag status manifest")
    total_requested = sum(int(item.get("buffer_rows", item.get("requested_rows", item.get("candidate_rows", 0)))) for item in manifests)
    total_produced = sum(int(item.get("candidate_rows", 0)) for item in manifests)
    split_requested: Counter[str] = Counter()
    split_produced: Counter[str] = Counter()
    tag_requested: Counter[str] = Counter()
    tag_produced: Counter[str] = Counter()
    rejections: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    for item in manifests:
        split_produced.update({str(key): int(value) for key, value in (item.get("split_counts", {}) or {}).items()})
        for key, value in (item.get("group_quotas", {}) or {}).items():
            split, _, tag = str(key).partition(":")
            split_requested[split] += int(value)
            tag_requested[tag] += int(value)
        for key, value in (item.get("tag_counts", {}) or {}).items():
            tag_produced[key] += int(value)
        telemetry = item.get("rejection_telemetry", {}) or {}
        rejections.update({str(key): int(value) for key, value in (telemetry.get("rejections", item.get("rejections", {})) or {}).items()})
        samples.extend(telemetry.get("samples", item.get("rejection_samples", [])) or [])
        if len(samples) > REJECTION_SAMPLE_LIMIT:
            del samples[REJECTION_SAMPLE_LIMIT:]
    split_shortfalls = {
        split: max(0, int(required) - split_produced.get(split, 0))
        for split, required in (required_by_split or split_requested).items()
        if split_produced.get(split, 0) < int(required)
    }
    tag_shortfalls = {
        tag: max(0, int(required) - tag_produced.get(tag, 0))
        for tag, required in tag_requested.items()
        if tag_produced.get(tag, 0) < int(required)
    }
    report: dict[str, Any] = {
        "status": "complete",
        "shard_count": shard_count,
        "requested_rows": total_requested,
        "produced_rows": total_produced,
        "shortfall": max(0, total_requested - total_produced),
        "split_requested": dict(split_requested),
        "split_produced": dict(split_produced),
        "required_by_split": dict(required_by_split or {}),
        "split_shortfalls": split_shortfalls,
        "tag_requested": dict(tag_requested),
        "tag_produced": dict(tag_produced),
        "tag_shortfalls": tag_shortfalls,
        "phase10_capacity_adequate": not split_shortfalls and not tag_shortfalls,
        "rejections": dict(rejections),
        "rejection_telemetry": {
            "not_applicable": sum(int((item.get("rejection_telemetry", {}) or {}).get("not_applicable", item.get("not_applicable", 0))) for item in manifests),
            "candidate_selected": total_produced,
            "candidate_rejected": sum(rejections.values()),
            "rejections": dict(rejections),
            "samples": samples,
            "sample_limit": REJECTION_SAMPLE_LIMIT,
        },
        "shards": [str(path.resolve()) for path in manifest_paths],
        "shard_manifest_hashes": {str(path.resolve()): sha256_file(path) for path in manifest_paths},
        "production_ready": True,
        "capacity_report_sha256": manifests[0]["capacity_report_sha256"],
        "config_hash": manifests[0]["config_hash"],
        "quality_manifest_sha256": manifests[0]["quality_manifest_sha256"],
        "split_report_sha256": manifests[0]["split_report_sha256"],
        "input_sqlite_sha256": manifests[0]["input_sqlite_sha256"],
        "review_manifest_sha256": manifests[0]["review_manifest_sha256"],
        "generator_dependency_hash": manifests[0].get("generator_dependency_hash"),
        "generator_version": manifests[0].get("generator_version"),
        "seed": manifests[0].get("seed"),
        "candidate_builder_version": manifests[0].get("candidate_builder_version"),
    }
    if output_path is not None:
        report["aggregate_path"] = str(output_path.resolve())
    report["aggregate_sha256"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = Path(str(output_path) + ".lock")
        if lock_path.exists() or lock_path.is_symlink():
            raise FileExistsError(f"candidate aggregate is locked: {lock_path}")
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(lock_fd)
        temp_dir: Path | None = None
        try:
            temp_dir = Path(tempfile.mkdtemp(prefix=f".{output_path.name}.", dir=str(output_path.parent)))
            temp_output = temp_dir / output_path.name
            temp_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
            with temp_output.open("r+b") as stream:
                os.fsync(stream.fileno())
            if output_path.exists() or output_path.is_symlink():
                raise FileExistsError(f"refusing to overwrite candidate aggregate manifest: {output_path}")
            # Create-new hard-link publication cannot overwrite an external
            # winner between the preflight and the publication point.
            os.link(str(temp_output), str(output_path))
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
    return report


# Explicit alias for callers that prefer the phase name.
build_candidate_aggregate = aggregate_candidate_manifests


def validate_candidate_aggregate(
    aggregate_path: Path,
    shard_paths: list[Path],
    *,
    required_by_split: dict[str, int] | None = None,
    expected_dependencies: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a hash-bound aggregate before Phase 10 consumes candidates."""
    aggregate_path = aggregate_path.resolve()
    try:
        report = json.loads(aggregate_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"missing or invalid candidate aggregate manifest: {aggregate_path}") from error
    if report.get("status") != "complete" or report.get("production_ready") is not True:
        raise RuntimeError("candidate aggregate is incomplete or non-production-ready")
    payload = dict(report)
    recorded_hash = payload.pop("aggregate_sha256", None)
    calculated_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if not recorded_hash or recorded_hash != calculated_hash:
        raise RuntimeError("candidate aggregate hash mismatch")
    if Path(str(report.get("aggregate_path", ""))).resolve() != aggregate_path:
        raise RuntimeError("candidate aggregate path mismatch")
    resolved_shards = sorted(str(path.with_suffix(".manifest.json").resolve()) for path in shard_paths)
    recorded_shards = sorted(str(path).replace("\\", "/") for path in report.get("shards", []))
    if recorded_shards != sorted(path.replace("\\", "/") for path in resolved_shards):
        raise RuntimeError("candidate aggregate shard set does not match candidate directory")
    hashes = report.get("shard_manifest_hashes", {})
    for path in shard_paths:
        manifest_path = path.with_suffix(".manifest.json").resolve()
        recorded = hashes.get(str(manifest_path)) or hashes.get(str(manifest_path).replace("\\", "/"))
        if recorded != sha256_file(manifest_path):
            raise RuntimeError(f"candidate aggregate shard manifest hash mismatch: {manifest_path}")
    for key, expected in (expected_dependencies or {}).items():
        if expected is not None and report.get(key) != expected:
            raise RuntimeError(f"candidate aggregate dependency mismatch: {key}")
    if report.get("phase10_capacity_adequate") is not True:
        raise RuntimeError("candidate aggregate reports a Phase 10 capacity shortfall")
    if required_by_split:
        produced = {str(key): int(value) for key, value in (report.get("split_produced", {}) or {}).items()}
        shortfalls = {
            split: int(required) - produced.get(split, 0)
            for split, required in required_by_split.items()
            if produced.get(split, 0) < int(required)
        }
        if shortfalls:
            raise RuntimeError(f"candidate aggregate lacks exact per-split capacity: {shortfalls}")
    return report


def build_candidate_shard(
    input_path: Path,
    capacity_report_path: Path,
    output_path: Path,
    *,
    review_manifest_path: Path = Path("reports/pilot_review_manifest.json"),
    pilot_report_path: Path = Path("reports/pilot_report.json"),
    pilot_output_path: Path = Path("data/pilot/gec_pilot_100k.parquet"),
    review_sample_path: Path = Path("reports/pilot_review_sample.jsonl"),
    blocked_report_path: Path | None = None,
    seed: int | None = None,
    config_path: Path = Path("config/filly.yaml"),
    shard_index: int = 0,
    shard_count: int = 1,
    max_rows: int | None = None,
    allow_development: bool = False,
) -> dict[str, Any]:
    if shard_count < 1 or shard_index < 0 or shard_index >= shard_count:
        raise ValueError("shard_index must be in [0, shard_count)")
    output_path = output_path.resolve()
    manifest_path = output_path.with_suffix(".manifest.json")
    destinations = {
        "output": output_path,
        "manifest": manifest_path,
    }
    if blocked_report_path is not None:
        destinations["blocked_report"] = blocked_report_path
    validate_destinations(
        {
            "input": input_path,
            "capacity_report": capacity_report_path,
            "config": config_path,
            "review_manifest": review_manifest_path,
            "pilot_report": pilot_report_path,
            "pilot_output": pilot_output_path,
            "review_sample": review_sample_path,
        },
        destinations,
    )
    # Resolve the current configuration and capacity before consulting review.
    # The approval must be for the exact state this invocation will use; a
    # crafted legacy approval cannot bypass this preflight.
    input_path = input_path.resolve()
    capacity_report_path = capacity_report_path.resolve()
    config_path = config_path.resolve()
    config = load_config(config_path)
    has_full_config = "project" in config
    runtime_config = None
    if has_full_config:
        try:
            runtime_config = resolve_runtime_config(config)
        except (TypeError, ValueError):
            if not allow_development:
                raise
            has_full_config = False
    if not has_full_config and not allow_development:
        raise RuntimeError("Phase 9 requires a complete validated config; pass allow_development=True only for fixtures")
    production_mode = has_full_config and not allow_development
    resource_config = runtime_config["runtime"]["resource_paths"] if runtime_config else None
    current_generator_hash = generator_dependency_hash(resource_paths=resource_config)
    capacity = json.loads(capacity_report_path.read_text(encoding="utf-8"))
    capacity_sha256 = sha256_file(capacity_report_path)
    current_config_hash = compute_config_hash(config)
    if production_mode:
        if capacity.get("production_ready") is not True:
            raise RuntimeError("production Phase 9 requires production_ready=true in the current capacity report")
        if capacity.get("generator_dependency_hash") != current_generator_hash:
            raise RuntimeError("production capacity report must use the current generator/resource dependency hash")
        if capacity.get("config_hash") != current_config_hash:
            raise RuntimeError("production capacity report must use the current configuration hash")
    elif capacity.get("production_ready") is True:
        raise RuntimeError("development Phase 9 invocation cannot claim production readiness")

    # This is deliberately the first operation that can fail for a production
    # run. A pending or stale review therefore cannot create an output file.
    review = require_review_gate(
        review_manifest_path,
        pilot_report_path=pilot_report_path,
        pilot_output_path=pilot_output_path,
        review_sample_path=review_sample_path,
        blocked_report=blocked_report_path,
        attempted_output=output_path,
        production=production_mode,
        expected_generator_dependency_hash=current_generator_hash if production_mode else None,
        expected_config_hash=current_config_hash if production_mode else None,
        expected_capacity_report_sha256=capacity_sha256 if production_mode else None,
    )
    # Keep the review result itself bound to the exact pilot report consumed by
    # this invocation.  The JSON checks below bind the capacity artifact; this
    # check prevents a permissive/mocked gate result from silently detaching
    # the review approval from the current pilot dependency.
    current_pilot_hash = sha256_file(pilot_report_path.resolve())
    reviewed_pilot_hash = review.current_hashes.get("pilot_report_sha256")
    if review.status == "complete" and reviewed_pilot_hash != current_pilot_hash:
        raise RuntimeError("review manifest pilot-report dependency does not match supplied pilot report")
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing candidate shard: {output_path}")
    if manifest_path.exists():
        raise FileExistsError(f"refusing to overwrite existing candidate manifest: {manifest_path}")
    if max_rows is None or max_rows < 1:
        raise ValueError("max_rows is required as an explicit production shard bound")

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as error:
        raise RuntimeError("Phase 9 requires pyarrow") from error
    generator_context = GeneratorContext.load(resource_config) if resource_config else None
    if production_mode and capacity.get("production_ready") is False:
        raise RuntimeError("capacity report is not production-ready: implementation/resource coverage is incomplete")
    input_sha256 = sha256_file(input_path)
    if capacity.get("input_sha256") != input_sha256:
        raise RuntimeError("stale capacity report: split input hash does not match")
    generator_sha256 = current_generator_hash
    expected_generator = capacity.get("generator_dependency_hash", capacity.get("generator_sha256"))
    if capacity.get("production_ready") is True and expected_generator != generator_sha256:
        raise RuntimeError("production capacity report must use the canonical generator dependency hash")
    development_fixture = allow_development and "production_ready" not in capacity and "generator_dependency_hash" not in capacity
    if capacity.get("generator_version") != GENERATOR_VERSION or (
        expected_generator != generator_sha256
        and not (development_fixture and expected_generator == legacy_generator_hash())
    ):
        raise RuntimeError("stale capacity report: generator source/version does not match")
    # ``config`` is loaded above so the production/development distinction is
    # explicit before any candidate output can be published.
    if seed is None:
        seed = int(runtime_config["runtime"]["seed"]) if runtime_config else 20260905
    phase9 = config.get("phase9", {}) if isinstance(config.get("phase9", {}), dict) else {}
    dataset_settings = config.get("dataset", {}) if isinstance(config.get("dataset", {}), dict) else {}
    configured_buffer = phase9.get("candidate_buffer_ratio", dataset_settings.get("candidate_buffer_ratio"))
    candidate_buffer_ratio = float(configured_buffer) if configured_buffer is not None else 1.0
    if candidate_buffer_ratio < 1:
        raise ValueError("candidate buffer ratio must be >= 1")
    requested_rows = max_rows
    buffer_rows = max(max_rows, math.ceil(max_rows * candidate_buffer_ratio))
    if capacity.get("config_hash") != current_config_hash:
        raise RuntimeError("stale capacity report: configuration hash does not match")
    try:
        pilot_payload = json.loads(pilot_report_path.resolve().read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError("cannot read Phase 8 pilot report for capacity binding") from error
    declared_capacity_path = pilot_payload.get("capacity_report")
    if declared_capacity_path:
        declared_path = Path(str(declared_capacity_path))
        if not declared_path.is_absolute():
            declared_path = pilot_report_path.resolve().parent / declared_path
        if declared_path.resolve() != capacity_report_path:
            raise RuntimeError("pilot report capacity path does not match supplied capacity report")
    declared_pilot_capacity_hash = pilot_payload.get("capacity_report_sha256")
    if pilot_payload.get("production_ready") is True and declared_pilot_capacity_hash != capacity_sha256:
        raise RuntimeError("pilot report capacity hash does not match supplied capacity report")
    if declared_pilot_capacity_hash is not None and declared_pilot_capacity_hash != capacity_sha256:
        raise RuntimeError("pilot report capacity hash does not match supplied capacity report")
    try:
        review_payload = json.loads(review_manifest_path.resolve().read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError("cannot read Phase 8 review manifest for capacity binding") from error
    review_targets = review_payload.get("target", {}) if isinstance(review_payload.get("target", {}), dict) else {}
    declared_review_capacity_path = review_payload.get("capacity_report") or review_targets.get("capacity_report")
    if declared_review_capacity_path:
        review_capacity_path = Path(str(declared_review_capacity_path))
        if not review_capacity_path.is_absolute():
            review_capacity_path = review_manifest_path.resolve().parent / review_capacity_path
        if review_capacity_path.resolve() != capacity_report_path:
            raise RuntimeError("review manifest capacity path does not match supplied capacity report")
    review_capacity_hashes = {
        value for value in (
            review_payload.get("capacity_report_sha256"),
            review_targets.get("capacity_report_sha256"),
        ) if value is not None
    }
    if review_capacity_hashes and review_capacity_hashes != {capacity_sha256}:
        raise RuntimeError("review manifest capacity hash does not match supplied capacity report")
    if pilot_payload.get("production_ready") is True and not review_capacity_hashes:
        raise RuntimeError("production review manifest lacks capacity-report binding")
    if not capacity.get("split_report_sha256") or not capacity.get("quality_manifest_sha256") or not capacity.get("input_sqlite_sha256"):
        raise RuntimeError("capacity report is incomplete: lacks upstream provenance; rerun Phases 5 and 6")
    tags = _supported_tags(capacity)
    if not tags:
        raise RuntimeError("capacity report contains no supported tags")

    columns = ["clean_id", "text", "split", "source_corpus", "publisher", "source_doc_id", "sqlite_table", "sqlite_rowid"]
    rejected: Counter[str] = Counter()
    source_rows = 0
    tag_counts: Counter[str] = Counter({tag: 0 for tag in all_tag_ids()})
    lock_path = Path(str(output_path) + ".lock")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(lock_fd)
    except FileExistsError as error:
        raise FileExistsError(f"candidate shard is locked by another builder: {lock_path}") from error
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix=f".{output_path.name}.", dir=str(output_path.parent)))
    except Exception:
        lock_path.unlink(missing_ok=True)
        raise
    temp_output = temp_dir / output_path.name
    writer = None
    connection = None
    parquet = None
    published_output = False
    selected_count = 0
    selected_records: list[dict[str, Any]] = []
    split_counts: Counter[str] = Counter()
    not_applicable = 0
    rejection_samples: list[dict[str, Any]] = []
    try:
        if output_path.exists() or manifest_path.exists():
            raise FileExistsError(f"refusing to overwrite candidate shard or manifest: {output_path}")
        # Capacity-aware bounded reservoirs are populated by the complete
        # assigned shard.  No row-order-dependent early exit is permitted.
        group_quotas = _capacity_group_quotas(capacity, buffer_rows, tags)
        if not group_quotas:
            raise RuntimeError("capacity report contains no positive split/tag groups")
        buckets: dict[tuple[str, str], list[tuple[int, str]]] = {}
        ranked_records: dict[str, dict[str, Any]] = {}
        reserve_limits = {
            group: quota + max(8, min(1000, quota // 4))
            for group, quota in group_quotas.items()
        }

        def reject(reason: str, count: int = 1, **context: Any) -> None:
            rejected[str(reason)] += int(count)
            if len(rejection_samples) < REJECTION_SAMPLE_LIMIT:
                sample = {key: value for key, value in context.items() if value is not None}
                sample["reason"] = str(reason)
                rejection_samples.append(sample)

        parquet = pq.ParquetFile(input_path)
        for batch in parquet.iter_batches(columns=columns):
            values = {name: batch.column(name).to_pylist() for name in columns}
            for index in range(len(values["clean_id"])):
                clean_id = str(values["clean_id"][index])
                if _shard_for(clean_id, shard_count) != shard_index:
                    continue
                source_rows += 1
                split = str(values["split"][index])
                if split not in SPLITS:
                    reject("unknown_split", split=split, clean_id=clean_id)
                    continue
                clean = {name: values[name][index] for name in columns}
                for tag in tags:
                    result = generate_candidates(str(clean["text"]), tag, compute_alignment=True, context=generator_context)
                    if not result.candidates and result.status == "supported":
                        not_applicable += int(result.not_applicable or 1)
                    for reason, count in (result.rejected or {}).items():
                        reject(str(reason), int(count), split=split, clean_id=clean_id, tag=tag)
                    for candidate in result.candidates:
                        if any(not isinstance(item, dict) for spans in (candidate.source_spans, candidate.target_spans) for item in spans):
                            reject("invalid_alignment", split=split, clean_id=clean_id, tag=tag)
                            continue
                        record = _candidate_record(clean, candidate, seed, current_config_hash)
                        group = (split, tag)
                        if group not in reserve_limits:
                            reject("capacity_report_underestimate", split=split, clean_id=clean_id, tag=tag)
                            continue
                        rank = _candidate_rank(seed, clean_id, split, tag, candidate.source_text, candidate.target_text)
                        _bounded_ranked_insert(
                            buckets, ranked_records, group, record, rank, reserve_limits[group]
                        )

        # First satisfy the capacity-aware group quotas, then use the bounded
        # reserves only to repair collisions or under-estimated shard capacity.
        selected_keys: set[str] = set()
        selected_pairs: set[tuple[str, str]] = set()
        selected_by_group: Counter[tuple[str, str]] = Counter()
        ranked_by_group: dict[tuple[str, str], list[tuple[int, str]]] = {}
        for group, heap in buckets.items():
            ranked_by_group[group] = sorted(((-rank, key) for rank, key in heap), key=lambda item: (item[0], item[1]))
        for group in sorted(group_quotas):
            quota = group_quotas[group]
            for _, key in ranked_by_group.get(group, ()):
                if selected_by_group[group] >= quota:
                    break
                record = ranked_records[key]
                pair = (str(record["source_text"]), str(record["target_text"]))
                if pair in selected_pairs:
                    reject("output_pair_collision", split=group[0], tag=group[1], pair_id=key)
                    continue
                selected_keys.add(key)
                selected_pairs.add(pair)
                selected_by_group[group] += 1
                selected_records.append(record)

        if len(selected_records) < buffer_rows:
            overflow: list[tuple[int, str, tuple[str, str]]] = []
            for group, entries in ranked_by_group.items():
                for rank, key in entries:
                    if key not in selected_keys:
                        overflow.append((rank, key, group))
            overflow.sort(key=lambda item: (item[0], item[1], item[2][0], item[2][1]))
            for _, key, group in overflow:
                if len(selected_records) >= buffer_rows:
                    break
                record = ranked_records[key]
                pair = (str(record["source_text"]), str(record["target_text"]))
                if pair in selected_pairs:
                    reject("output_pair_collision", split=group[0], tag=group[1], pair_id=key)
                    continue
                selected_keys.add(key)
                selected_pairs.add(pair)
                selected_by_group[group] += 1
                selected_records.append(record)
        selected_records.sort(key=lambda row: str(row["pair_id"]))
        selected_count = len(selected_records)
        for record in selected_records:
            split_counts[str(record["split"])] += 1
            tag_counts[str(record["correction_tags"][0])] += 1
        rejected["quota_or_buffer_not_selected"] += max(0, len(ranked_records) - len(selected_records))
        if selected_records:
            table = pa.Table.from_pylist(selected_records, schema=gec_arrow_schema())
            pq.write_table(table, temp_output, compression="zstd")
        if selected_count == 0:
            raise RuntimeError("candidate shard produced zero valid candidates; no output was written")
        tag_status = {
            str(item["tag"]): {"status": item.get("status"), "reason": item.get("reason", "")}
            for item in capacity.get("tags", [])
        }
        for tag in all_tag_ids():
            tag_status.setdefault(tag, {"status": "unavailable", "reason": "not present in capacity report"})
        manifest = {
            "status": "complete",
            "builder_version": CANDIDATE_BUILDER_VERSION,
            "candidate_builder_version": CANDIDATE_BUILDER_VERSION,
            "seed": seed,
            "input": str(input_path),
            "input_sha256": input_sha256,
            "capacity_report": str(capacity_report_path),
            "capacity_report_sha256": sha256_file(capacity_report_path),
            "split_report_sha256": capacity["split_report_sha256"],
            "quality_manifest_sha256": capacity["quality_manifest_sha256"],
            "input_sqlite_sha256": capacity["input_sqlite_sha256"],
            "review_manifest": review.review_manifest,
            "review_manifest_sha256": review.manifest_hash,
            "config": str(config_path),
            "config_hash": current_config_hash,
            "generator_version": GENERATOR_VERSION,
            "generator_policy_status": GENERATOR_POLICY_STATUS,
            "generator_sha256": generator_sha256,
            "generator_dependency_hash": generator_sha256,
            "shard_index": shard_index,
            "shard_count": shard_count,
            "source_rows": source_rows,
            "candidate_rows": selected_count,
            "requested_rows": requested_rows,
            "buffer_rows": buffer_rows,
            "candidate_buffer_ratio": candidate_buffer_ratio,
            "group_quotas": {f"{split}:{tag}": value for (split, tag), value in group_quotas.items()},
            "group_produced": {f"{split}:{tag}": selected_by_group[(split, tag)] for (split, tag) in group_quotas},
            "group_shortfalls": {
                f"{split}:{tag}": max(0, value - selected_by_group[(split, tag)])
                for (split, tag), value in group_quotas.items()
                if selected_by_group[(split, tag)] < value
            },
            "split_counts": dict(split_counts),
            "tag_counts": dict(tag_counts),
            "tag_status": tag_status,
            "production_ready": bool(production_mode and capacity.get("production_ready", False)),
            "collision_store": "stable-rank bounded in-memory selection",
            "collision_rejections": rejected.get("output_pair_collision", 0),
            "rejections": dict(rejected),
            "not_applicable": not_applicable,
            "candidate_selected": selected_count,
            "candidate_rejected": sum(rejected.values()),
            "rejection_samples": rejection_samples[:REJECTION_SAMPLE_LIMIT],
            "rejection_telemetry": {
                "not_applicable": not_applicable,
                "candidate_selected": selected_count,
                "candidate_rejected": sum(rejected.values()),
                "rejections": dict(rejected),
                "samples": rejection_samples[:REJECTION_SAMPLE_LIMIT],
                "sample_limit": REJECTION_SAMPLE_LIMIT,
            },
            "output": str(output_path),
            "primary_input_deduplicated": False,
        }
        # Manifest is produced before publication; its output hash is filled
        # from the completed temp file and then both files are renamed under
        # the exclusive lock.
        manifest["output_sha256"] = sha256_file(temp_output)
        temp_manifest = temp_dir / manifest_path.name
        temp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.rename(str(temp_output), str(output_path))
        published_output = True
        os.rename(str(temp_manifest), str(manifest_path))
        return manifest
    except Exception:
        if published_output:
            for path in (output_path, manifest_path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
        raise
    finally:
        if writer is not None:
            writer.close()
        if connection is not None:
            connection.close()
        if parquet is not None:
            parquet.close()
        shutil.rmtree(temp_dir, ignore_errors=True)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/interim/split_clean.parquet"))
    parser.add_argument("--capacity-report", type=Path, default=Path("reports/tag_capacity_report.json"))
    parser.add_argument("--output", type=Path, default=Path("data/candidates/candidates_00000-of-00001.parquet"))
    parser.add_argument("--review-manifest", type=Path, default=Path("reports/pilot_review_manifest.json"))
    parser.add_argument("--pilot-report", type=Path, default=Path("reports/pilot_report.json"))
    parser.add_argument("--pilot-output", type=Path, default=Path("data/pilot/gec_pilot_100k.parquet"))
    parser.add_argument("--review-sample", type=Path, default=Path("reports/pilot_review_sample.jsonl"))
    parser.add_argument("--blocked-report", type=Path, default=Path("reports/phase9_blocked_attempt.json"))
    parser.add_argument("--config", type=Path, default=Path("config/filly.yaml"))
    parser.add_argument("--seed", type=int)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--allow-development", action="store_true", help="explicitly allow non-production fixture artifacts")
    args = parser.parse_args()
    try:
        report = build_candidate_shard(
            args.input, args.capacity_report, args.output,
            review_manifest_path=args.review_manifest,
            pilot_report_path=args.pilot_report,
            pilot_output_path=args.pilot_output,
            review_sample_path=args.review_sample,
            blocked_report_path=args.blocked_report,
            seed=args.seed,
            config_path=args.config,
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            max_rows=args.max_rows,
            allow_development=args.allow_development,
        )
    except ReviewGateError as error:
        print(json.dumps({"status": "blocked", "gate": error.result.status, "reason": error.result.reason}, ensure_ascii=True))
        raise SystemExit(2) from error
    print(json.dumps({key: report[key] for key in ("status", "shard_index", "candidate_rows", "output")}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
