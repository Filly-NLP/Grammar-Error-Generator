"""Phase 10 exact Balarila-total dataset builder.

The builder consumes Phase 9 candidate shards and the already split clean
targets. It performs exact integer allocation, validates every selected
operation by replay, rejects generated output collisions, and adds identity
rows only for the configured Stage-3 share. The review gate runs before any
final output directory is created.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.geg.config import config_hash as compute_config_hash, load_config, resolve_runtime_config
from src.geg.dataset import (
    SPLITS,
    bounded_quotas,
    parse_json_field,
    split_composition,
    stage_composition,
    total_composition,
    validate_candidate_row,
    validate_identity_row,
)
from src.geg.hashing import sha256_file, sha256_files, generator_dependency_hash
from src.geg.generators import GENERATOR_VERSION, all_tag_ids
from scripts.build_candidates import CANDIDATE_BUILDER_VERSION, validate_candidate_aggregate
from src.geg.review import ReviewGateError, require_review_gate
from src.geg.artifacts import validate_destinations
from src.geg.schema import gec_arrow_schema
from src.geg.morphology import load_frozen_morphology
from src.geg.telemetry import REJECTION_SAMPLE_LIMIT


DATASET_BUILDER_VERSION = "filly-phase10-exact-v1"


def _identity_pair_id(seed: int, clean_id: str) -> str:
    return hashlib.sha256(f"identity|{seed}|{clean_id}".encode("utf-8")).hexdigest()[:32]


def _as_row(batch: Any, columns: list[str], index: int) -> dict[str, Any]:
    return {name: batch.column(name)[index].as_py() for name in columns}


def _candidate_paths(candidate_dir: Path) -> list[Path]:
    paths = sorted(path for path in candidate_dir.glob("*.parquet") if path.is_file())
    if not paths:
        raise RuntimeError(f"no candidate Parquet shards found in {candidate_dir}")
    return paths


def _verify_candidate_manifests(
    paths: list[Path],
    *,
    split_input: Path,
    config_path: Path,
    review_manifest_path: Path,
    config_hash: str,
    review_manifest_sha256: str | None,
    seed: int,
    candidate_builder_version: str = CANDIDATE_BUILDER_VERSION,
) -> dict[str, Any]:
    expected_input_sha256 = sha256_file(split_input)
    expected_generator_sha256 = generator_dependency_hash()
    legacy_generator_sha256 = sha256_files((Path(__file__).resolve().parents[1] / "src/geg/generators.py", Path(__file__).resolve().parents[1] / "src/geg/alignment.py"))
    manifests: list[dict[str, Any]] = []
    for path in paths:
        manifest_path = path.with_suffix(".manifest.json")
        if not manifest_path.exists():
            raise RuntimeError(f"candidate shard manifest is missing: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "complete":
            raise RuntimeError(f"candidate shard is not complete: {path}")
        if manifest.get("output_sha256") != sha256_file(path):
            raise RuntimeError(f"candidate shard hash mismatch: {path}")
        if Path(str(manifest.get("output", ""))).resolve() != path.resolve():
            raise RuntimeError(f"candidate shard manifest output path mismatch: {path}")
        if Path(str(manifest.get("input", ""))).resolve() != split_input.resolve():
            raise RuntimeError(f"candidate shard input path mismatch: {path}")
        if manifest.get("input_sha256") != expected_input_sha256:
            raise RuntimeError(f"candidate shard input dependency mismatch: {path}")
        if not manifest.get("quality_manifest_sha256") or not manifest.get("split_report_sha256"):
            raise RuntimeError(f"candidate shard lacks Phase 4/5 provenance: {path}")
        if not manifest.get("input_sqlite_sha256"):
            raise RuntimeError(f"candidate shard lacks input SQLite provenance: {path}")
        if Path(str(manifest.get("config", ""))).resolve() != config_path.resolve():
            raise RuntimeError(f"candidate shard configuration path mismatch: {path}")
        if manifest.get("config_hash") != config_hash:
            raise RuntimeError(f"candidate shard configuration dependency mismatch: {path}")
        manifest_generator = manifest.get("generator_dependency_hash", manifest.get("generator_sha256"))
        legacy_allowed = "production_ready" not in manifest and "generator_dependency_hash" not in manifest
        if manifest.get("production_ready") is True and manifest_generator != expected_generator_sha256:
            raise RuntimeError(f"production candidate shard must use the canonical generator dependency hash: {path}")
        if manifest.get("generator_version") != GENERATOR_VERSION or manifest_generator != expected_generator_sha256 and not (legacy_allowed and manifest_generator == legacy_generator_sha256):
            raise RuntimeError(f"candidate shard generator dependency mismatch: {path}")
        if "production_ready" in manifest and manifest.get("production_ready") is not True:
            raise RuntimeError(f"candidate shard is non-production-ready: {path}")
        if manifest.get("production_ready") is True:
            import pyarrow.parquet as pq
            required_morphology = {"morphology_source_state", "morphology_target_state", "morphology_lemma", "morphology_resource_version"}
            available_columns = set(pq.ParquetFile(path).schema_arrow.names)
            missing_morphology = sorted(required_morphology - available_columns)
            if missing_morphology:
                raise RuntimeError(f"production candidate shard is missing morphology schema columns {missing_morphology}: {path}")
        if manifest.get("seed") != seed or manifest.get("candidate_builder_version") != candidate_builder_version or manifest.get("builder_version") != candidate_builder_version:
            raise RuntimeError(f"candidate shard seed/builder-version dependency mismatch: {path}")
        if review_manifest_sha256 and manifest.get("review_manifest_sha256") != review_manifest_sha256:
            raise RuntimeError(f"candidate shard review dependency mismatch: {path}")
        if Path(str(manifest.get("review_manifest", ""))).resolve() != review_manifest_path.resolve():
            raise RuntimeError(f"candidate shard review path mismatch: {path}")
        if not isinstance(manifest.get("shard_index"), int) or not isinstance(manifest.get("shard_count"), int):
            raise RuntimeError(f"candidate shard is missing shard index/count: {path}")
        manifests.append(manifest)
    shard_counts = {manifest["shard_count"] for manifest in manifests}
    if len(shard_counts) != 1:
        raise RuntimeError("candidate shards do not agree on shard_count")
    shard_count = shard_counts.pop()
    capacity_hashes = {manifest.get("capacity_report_sha256") for manifest in manifests}
    if len(capacity_hashes) != 1 or None in capacity_hashes:
        raise RuntimeError("candidate shards do not agree on capacity-report dependency")
    quality_hashes = {manifest.get("quality_manifest_sha256") for manifest in manifests}
    split_hashes = {manifest.get("split_report_sha256") for manifest in manifests}
    if len(quality_hashes) != 1 or None in quality_hashes:
        raise RuntimeError("candidate shards do not agree on quality-manifest dependency")
    if len(split_hashes) != 1 or None in split_hashes:
        raise RuntimeError("candidate shards do not agree on split-report dependency")
    sqlite_hashes = {manifest.get("input_sqlite_sha256") for manifest in manifests}
    if len(sqlite_hashes) != 1 or None in sqlite_hashes:
        raise RuntimeError("candidate shards do not agree on input SQLite dependency")
    tag_statuses = [manifest.get("tag_status") for manifest in manifests]
    if any(not isinstance(status, dict) or set(status) != set(all_tag_ids()) for status in tag_statuses):
        raise RuntimeError("candidate shard tag manifests must cover all 39 registered tags")
    if any(status != tag_statuses[0] for status in tag_statuses[1:]):
        raise RuntimeError("candidate shards do not agree on tag status/reason manifest")
    if shard_count < 1 or {manifest["shard_index"] for manifest in manifests} != set(range(shard_count)):
        raise RuntimeError("candidate shard set is incomplete or contains duplicate/out-of-range indices")
    return {
        "shard_count": shard_count,
        "manifests": manifests,
        "generator_sha256": expected_generator_sha256,
        "generator_dependency_hash": expected_generator_sha256,
        "tag_status": tag_statuses[0],
        "quality_manifest_sha256": quality_hashes.pop(),
        "split_report_sha256": split_hashes.pop(),
        "input_sqlite_sha256": sqlite_hashes.pop(),
    }


def _validate_candidate_provenance(row: dict[str, Any], clean_lookup: dict[str, dict[str, Any]]) -> None:
    clean_id = str(row.get("clean_id", ""))
    clean = clean_lookup.get(clean_id)
    if clean is None:
        raise RuntimeError(f"candidate clean_id is absent from current split input: {clean_id}")
    if row.get("target_text") != clean.get("text"):
        raise RuntimeError(f"candidate target_text does not match clean target for clean_id={clean_id}")
    for field in ("split", "source_corpus", "publisher", "source_doc_id", "sqlite_table", "sqlite_rowid"):
        if row.get(field) != clean.get(field):
            raise RuntimeError(f"candidate provenance mismatch for clean_id={clean_id}: {field}")


def _validate_candidate_dependencies(row: dict[str, Any], *, seed: int, config_hash: str) -> None:
    if row.get("seed") != seed:
        raise RuntimeError(f"candidate seed mismatch for pair_id={row.get('pair_id')}")
    if row.get("generator_version") != GENERATOR_VERSION:
        raise RuntimeError(f"candidate generator version mismatch for pair_id={row.get('pair_id')}")
    if row.get("candidate_builder_version") != CANDIDATE_BUILDER_VERSION:
        raise RuntimeError(f"candidate builder version mismatch for pair_id={row.get('pair_id')}")
    if row.get("config_hash") != config_hash:
        raise RuntimeError(f"candidate configuration hash mismatch for pair_id={row.get('pair_id')}")


def _iter_candidate_rows(paths: list[Path]) -> Iterable[dict[str, Any]]:
    import pyarrow.parquet as pq

    columns = [
        "pair_id", "clean_id", "source_text", "target_text", "is_errorful", "correction_tags",
        "error_families", "num_errors", "generation_operation", "source_spans", "target_spans",
        "split", "source_corpus", "publisher", "source_doc_id", "sqlite_table", "sqlite_rowid",
        "seed", "generator_version", "candidate_builder_version", "config_hash", "alignment_success", "quality_flags", "confidence",
        "morphology_source_state", "morphology_target_state", "morphology_lemma", "morphology_resource_version",
    ]
    for path in paths:
        with pq.ParquetFile(path) as parquet:
            available = set(parquet.schema_arrow.names)
            morphology_columns = {"morphology_source_state", "morphology_target_state", "morphology_lemma", "morphology_resource_version"}
            missing = sorted((set(columns) - morphology_columns) - available)
            if missing:
                raise RuntimeError(f"candidate shard missing required columns {missing}: {path}")
            selected_columns = [column for column in columns if column in available]
            for batch in parquet.iter_batches(columns=selected_columns):
                for index in range(batch.num_rows):
                    row = _as_row(batch, selected_columns, index)
                    for column in morphology_columns:
                        row.setdefault(column, None)
                    yield row


def _identity_row(clean: dict[str, Any], seed: int) -> dict[str, Any]:
    text = str(clean["text"])
    return {
        "pair_id": _identity_pair_id(seed, str(clean["clean_id"])),
        "clean_id": str(clean["clean_id"]),
        "source_text": text,
        "target_text": text,
        "is_errorful": False,
        "correction_tags": [],
        "error_families": [],
        "num_errors": 0,
        "generation_operation": "{}",
        "target_token_index": None,
        "source_token_index": None,
        "source_spans": [],
        "target_spans": [],
        "split": str(clean["split"]),
        "dataset_stage": "phase10_final",
        "source_corpus": clean.get("source_corpus"),
        "publisher": clean.get("publisher"),
        "source_doc_id": clean.get("source_doc_id"),
        "sqlite_table": clean.get("sqlite_table"),
        "sqlite_rowid": clean.get("sqlite_rowid"),
        "seed": seed,
        "generator_version": None,
        "candidate_builder_version": None,
        "dataset_builder_version": DATASET_BUILDER_VERSION,
        "config_hash": None,
        "alignment_success": True,
        "quality_flags": json.dumps(["identity_row"], ensure_ascii=False),
        "confidence": "gold_identity",
        "morphology_source_state": None,
        "morphology_target_state": None,
        "morphology_lemma": None,
        "morphology_resource_version": None,
    }


def _write_table(path: Path, rows: list[dict[str, Any]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not rows:
        raise RuntimeError(f"refusing to write empty dataset view: {path}")
    pq.write_table(pa.Table.from_pylist(rows, schema=gec_arrow_schema()), path)


def build_final_dataset(
    candidate_dir: Path,
    split_input: Path,
    output_dir: Path,
    *,
    review_manifest_path: Path = Path("reports/pilot_review_manifest.json"),
    pilot_report_path: Path = Path("reports/pilot_report.json"),
    pilot_output_path: Path = Path("data/pilot/gec_pilot_100k.parquet"),
    review_sample_path: Path = Path("reports/pilot_review_sample.jsonl"),
    blocked_report_path: Path | None = None,
    failure_report_path: Path | None = None,
    seed: int | None = None,
    config_path: Path = Path("config/filly.yaml"),
    candidate_aggregate_path: Path | None = None,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    for name, report_path in (("blocked_report", blocked_report_path), ("failure_report", failure_report_path)):
        if report_path is None:
            continue
        report_resolved = report_path.resolve()
        if report_resolved == output_dir or output_dir in report_resolved.parents:
            raise ValueError(f"{name} must not be inside output_dir: {report_resolved}")
    destinations = {"output_dir": output_dir}
    if blocked_report_path is not None:
        destinations["blocked_report"] = blocked_report_path
    if failure_report_path is not None:
        destinations["failure_report"] = failure_report_path
    input_destinations = {
            "candidate_dir": candidate_dir,
            "split_input": split_input,
            "config": config_path,
            "review_manifest": review_manifest_path,
            "pilot_report": pilot_report_path,
            "pilot_output": pilot_output_path,
            "review_sample": review_sample_path,
    }
    if candidate_aggregate_path is not None:
        input_destinations["candidate_aggregate"] = candidate_aggregate_path
    validate_destinations(
        input_destinations,
        destinations,
    )
    # Gate before checking/creating the output directory. A pending review
    # must leave no candidate/final artifacts behind.
    review = require_review_gate(
        review_manifest_path,
        pilot_report_path=pilot_report_path,
        pilot_output_path=pilot_output_path,
        review_sample_path=review_sample_path,
        blocked_report=blocked_report_path,
        attempted_output=output_dir,
    )
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing final dataset directory: {output_dir}")
    try:
        import pyarrow.parquet as pq  # noqa: F401
    except ImportError as error:
        raise RuntimeError("Phase 10 requires pyarrow") from error

    candidate_dir = candidate_dir.resolve()
    split_input = split_input.resolve()
    config_path = config_path.resolve()
    config = load_config(config_path)
    runtime_config = resolve_runtime_config(config) if "project" in config else None
    if seed is None:
        seed = int(resolve_runtime_config(config)["runtime"]["seed"]) if "project" in config else 20260905
    current_config_hash = compute_config_hash(config)
    comp = total_composition(config)
    split_settings = config.get("splits", {})
    split_fractions = {
        split: split_settings.get(split, {"train": "0.70", "dev": "0.15", "synthetic_test": "0.15"}[split])
        for split in SPLITS
    }
    split_errorful = split_composition(comp["errorful"], split_fractions)
    split_identity = split_composition(comp["identity"], split_fractions)
    stage = stage_composition(comp["errorful"], comp["identity"], errorful_share=Decimal(str(config.get("stage_views", {}).get("dataset1_errorful_share", "0.80"))))
    phase9_settings = config.get("phase9", {}) if isinstance(config.get("phase9", {}), dict) else {}
    require_aggregate = bool(phase9_settings.get("require_aggregate_manifest", False))
    if candidate_aggregate_path is None and require_aggregate:
        candidate_aggregate_path = Path("reports/phase9_candidate_aggregate.json")
    if candidate_aggregate_path is not None:
        candidate_aggregate_path = candidate_aggregate_path.resolve()
    _, morphology_manifest = load_frozen_morphology()
    expected_morphology_resource_version = str(morphology_manifest.get("resource_version", "")).strip() or None

    try:
        # Stream the current split once into a provenance lookup. Candidate
        # rows are checked against this lookup before capacity/selection, so a
        # stale shard cannot smuggle an altered target or metadata through.
        split_columns = ["clean_id", "text", "split", "source_corpus", "publisher", "source_doc_id", "sqlite_table", "sqlite_rowid"]
        clean_by_split: dict[str, list[dict[str, Any]]] = {split: [] for split in SPLITS}
        clean_lookup: dict[str, dict[str, Any]] = {}
        clean_texts: set[str] = set()
        with pq.ParquetFile(split_input) as parquet:
            available = set(parquet.schema_arrow.names)
            missing = sorted(set(split_columns) - available)
            if missing:
                raise RuntimeError(f"split input missing required columns: {missing}")
            for batch in parquet.iter_batches(columns=split_columns):
                for index in range(batch.num_rows):
                    clean = _as_row(batch, split_columns, index)
                    clean_id = str(clean["clean_id"])
                    text = str(clean["text"])
                    if clean_id in clean_lookup or text in clean_texts:
                        raise RuntimeError("split input violates unique clean identity invariant")
                    clean_texts.add(text)
                    split = str(clean["split"])
                    if split not in SPLITS:
                        raise RuntimeError(f"split input has unknown split: {split}")
                    clean_lookup[clean_id] = clean
                    clean_by_split[split].append(clean)
        candidate_paths = _candidate_paths(candidate_dir)
        shard_info = _verify_candidate_manifests(
            candidate_paths,
            split_input=split_input,
            config_path=config_path,
            review_manifest_path=Path(review.review_manifest),
            config_hash=current_config_hash,
            review_manifest_sha256=review.manifest_hash,
            seed=seed,
        )
        if candidate_aggregate_path is not None:
            validate_candidate_aggregate(
                candidate_aggregate_path,
                candidate_paths,
                required_by_split=split_errorful,
                expected_dependencies={
                    "config_hash": current_config_hash,
                    "quality_manifest_sha256": shard_info["quality_manifest_sha256"],
                    "split_report_sha256": shard_info["split_report_sha256"],
                    "input_sqlite_sha256": shard_info["input_sqlite_sha256"],
                    "review_manifest_sha256": review.manifest_hash,
                    "generator_dependency_hash": shard_info["generator_dependency_hash"],
                    "seed": seed,
                    "candidate_builder_version": CANDIDATE_BUILDER_VERSION,
                },
            )
        # Pass 1 validates every row, records exact capacities, and rejects
        # collisions across shards before any row can be selected.
        capacities: dict[str, Counter[str]] = {split: Counter() for split in SPLITS}
        first_seen_pairs: set[tuple[str, str]] = set()
        candidate_collisions = 0
        candidate_rows_seen = 0
        rejection_samples: list[dict[str, Any]] = []
        phase10_rejections: Counter[str] = Counter()

        def reject(reason: str, count: int = 1, **context: Any) -> None:
            phase10_rejections[str(reason)] += int(count)
            if len(rejection_samples) < REJECTION_SAMPLE_LIMIT:
                sample = {key: value for key, value in context.items() if value is not None}
                sample["reason"] = str(reason)
                rejection_samples.append(sample)

        for row in _iter_candidate_rows(candidate_paths):
            _validate_candidate_dependencies(row, seed=seed, config_hash=current_config_hash)
            candidate_rows_seen += 1
            _validate_candidate_provenance(row, clean_lookup)
            try:
                key = validate_candidate_row(row, expected_morphology_resource_version=expected_morphology_resource_version)
            except (TypeError, ValueError) as error:
                raise RuntimeError(f"invalid candidate row {row.get('pair_id')}: {error}") from error
            assert key is not None
            if key in first_seen_pairs:
                candidate_collisions += 1
                reject("output_pair_collision", split=row.get("split"), pair_id=row.get("pair_id"))
                continue
            first_seen_pairs.add(key)
            capacities[str(row["split"])][str(parse_json_field(row["correction_tags"], "correction_tags")[0])] += 1
        quotas = {split: bounded_quotas(dict(capacities[split]), split_errorful[split]) for split in SPLITS}
        selected: dict[str, list[dict[str, Any]]] = {split: [] for split in SPLITS}
        selected_by_tag: Counter[tuple[str, str]] = Counter()
        second_seen_pairs: set[tuple[str, str]] = set()
        for row in _iter_candidate_rows(candidate_paths):
            _validate_candidate_dependencies(row, seed=seed, config_hash=current_config_hash)
            _validate_candidate_provenance(row, clean_lookup)
            key = validate_candidate_row(row, expected_morphology_resource_version=expected_morphology_resource_version)
            assert key is not None
            if key in second_seen_pairs:
                continue
            second_seen_pairs.add(key)
            split = str(row["split"])
            tag = str(parse_json_field(row["correction_tags"], "correction_tags")[0])
            if selected_by_tag[(split, tag)] >= quotas[split].get(tag, 0):
                reject("quota_or_buffer_not_selected", split=split, tag=tag, pair_id=row.get("pair_id"))
                continue
            selected_by_tag[(split, tag)] += 1
            record = dict(row)
            record["dataset_stage"] = "phase10_final"
            record["dataset_builder_version"] = DATASET_BUILDER_VERSION
            selected[split].append(record)
        for split in SPLITS:
            if len(selected[split]) != split_errorful[split]:
                raise RuntimeError(f"errorful shortfall in {split}: {len(selected[split])} < {split_errorful[split]}")

        # Identity rows are drawn from the pre-split clean input. We preserve
        # source metadata and never re-split or deduplicate primary targets.
        identities: dict[str, list[dict[str, Any]]] = {}
        for split in SPLITS:
            if len(clean_by_split[split]) < split_identity[split]:
                raise RuntimeError(f"identity capacity shortfall in {split}: {len(clean_by_split[split])} < {split_identity[split]}")
            ordered = sorted(clean_by_split[split], key=lambda row: str(row["clean_id"]))
            identities[split] = [_identity_row(clean, seed) for clean in ordered[: split_identity[split]]]
            for row in identities[split]:
                validate_identity_row(row, split)

        final_rows: dict[str, list[dict[str, Any]]] = {}
        for split in SPLITS:
            final_rows[split] = selected[split] + identities[split]
            if len(final_rows[split]) != split_errorful[split] + split_identity[split]:
                raise RuntimeError(f"final split count mismatch: {split}")
            final_rows[split].sort(key=lambda row: (0 if row["is_errorful"] else 1, str(row["pair_id"])))

        # Build stage views from the exact final split allocation. Dataset 1
        # contains 80% of errorful rows; Dataset 2 contains the remainder plus
        # all identity rows, matching the Balarila two-stage interpretation.
        stage1_by_split = split_composition(stage["dataset1_errorful"], split_fractions)
        stage1_rows_by_split: dict[str, list[dict[str, Any]]] = {split: [] for split in SPLITS}
        stage2_rows_by_split: dict[str, list[dict[str, Any]]] = {split: [] for split in SPLITS}
        for split in SPLITS:
            errorful = sorted(selected[split], key=lambda row: str(row["pair_id"]))
            first = stage1_by_split[split]
            stage1_rows_by_split[split] = [{**row, "dataset_stage": "dataset1_stage2"} for row in errorful[:first]]
            stage2_rows_by_split[split] = [{**row, "dataset_stage": "dataset2_stage3"} for row in errorful[first:]]
            stage2_rows_by_split[split].extend([{**row, "dataset_stage": "dataset2_stage3"} for row in identities[split]])
        if sum(len(rows) for rows in stage1_rows_by_split.values()) != stage["dataset1_total"] or sum(len(rows) for rows in stage2_rows_by_split.values()) != stage["dataset2_total"]:
            raise RuntimeError("stage-view arithmetic mismatch")

        tag_counts = {
            split: {
                tag: sum(1 for row in selected[split] if str(parse_json_field(row["correction_tags"], "correction_tags")[0]) == tag)
                for tag in all_tag_ids()
            }
            for split in SPLITS
        }
        output_parent = output_dir.parent
        output_parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=".phase10-", dir=str(output_dir.parent)))
        try:
            outputs: dict[str, dict[str, str]] = {}
            for split in SPLITS:
                split_dir = tmp / split
                split_dir.mkdir()
                final_path = split_dir / "final.parquet"
                _write_table(final_path, final_rows[split])
                outputs[f"{split}/final.parquet"] = {"path": f"{split}/final.parquet", "sha256": sha256_file(final_path)}
                for name, rows in (("dataset1_stage2.parquet", stage1_rows_by_split[split]), ("dataset2_stage3.parquet", stage2_rows_by_split[split])):
                    if rows:
                        stage_path = split_dir / name
                        _write_table(stage_path, rows)
                        outputs[f"{split}/{name}"] = {"path": f"{split}/{name}", "sha256": sha256_file(stage_path)}
            manifest = {
                "status": "complete",
                "builder_version": DATASET_BUILDER_VERSION,
                "counting_mode": config.get("dataset", {}).get("counting_mode"),
                "target_total_pairs": comp["total"],
                "errorful_total": comp["errorful"],
                "identity_total": comp["identity"],
                "split_counts": {split: len(final_rows[split]) for split in SPLITS},
                "split_errorful_counts": split_errorful,
                "split_identity_counts": split_identity,
                "stage_counts": stage,
                "stage1_errorful_by_split": stage1_by_split,
                "candidate_rows_seen": candidate_rows_seen,
                "candidate_pair_collisions_rejected": candidate_collisions,
                "candidate_unique_pairs": len(first_seen_pairs),
                "not_applicable": 0,
                "candidate_selected": sum(len(selected[split]) for split in SPLITS),
                "candidate_rejected": sum(phase10_rejections.values()),
                "rejection_samples": rejection_samples[:REJECTION_SAMPLE_LIMIT],
                "rejection_telemetry": {
                    "not_applicable": 0,
                    "candidate_selected": sum(len(selected[split]) for split in SPLITS),
                    "candidate_rejected": sum(phase10_rejections.values()),
                    "rejections": dict(phase10_rejections),
                    "samples": rejection_samples[:REJECTION_SAMPLE_LIMIT],
                    "sample_limit": REJECTION_SAMPLE_LIMIT,
                },
                "tag_counts": tag_counts,
                "tag_status": shard_info["tag_status"],
                "identity_rows_are_clean": True,
                "one_error_per_errorful_pair": all(row["num_errors"] == 1 for split in SPLITS for row in selected[split]),
                "normalization_noise_injected": False,
                "primary_input_deduplicated": False,
                "input_split": str(split_input),
                "input_split_sha256": sha256_file(split_input),
                "candidate_dir": str(candidate_dir),
                "candidate_shard_hashes": {str(path): sha256_file(path) for path in candidate_paths},
                "candidate_shard_count": shard_info["shard_count"],
                "candidate_aggregate_manifest": str(candidate_aggregate_path) if candidate_aggregate_path else None,
                "candidate_aggregate_manifest_sha256": sha256_file(candidate_aggregate_path) if candidate_aggregate_path else None,
                "candidate_generator_sha256": shard_info["generator_sha256"],
                "quality_manifest_sha256": shard_info["quality_manifest_sha256"],
                "split_report_sha256": shard_info["split_report_sha256"],
                "input_sqlite_sha256": shard_info["input_sqlite_sha256"],
                "review_manifest": review.review_manifest,
                "review_manifest_sha256": review.manifest_hash,
                "pilot_report_sha256": review.current_hashes["pilot_report_sha256"],
                "pilot_output_sha256": review.current_hashes["pilot_output_sha256"],
                "review_sample_sha256": review.current_hashes["review_sample_sha256"],
                "config": str(config_path),
                "config_hash": current_config_hash,
                "candidate_builder_version": CANDIDATE_BUILDER_VERSION,
                "generator_version": GENERATOR_VERSION,
                "seed": seed,
                "effective_runtime": runtime_config.get("runtime") if runtime_config else {"seed": seed, "split_fractions": split_fractions},
                "outputs": outputs,
            }
            (tmp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmp.replace(output_dir)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return manifest
    except Exception as error:
        if failure_report_path is not None:
            failure_report_path.parent.mkdir(parents=True, exist_ok=True)
            failure_report_path.write_text(json.dumps({"status": "failed", "reason": str(error), "builder_version": DATASET_BUILDER_VERSION}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-dir", type=Path, default=Path("data/candidates"))
    parser.add_argument("--split-input", type=Path, default=Path("data/interim/split_clean.parquet"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/gec_1m"))
    parser.add_argument("--review-manifest", type=Path, default=Path("reports/pilot_review_manifest.json"))
    parser.add_argument("--pilot-report", type=Path, default=Path("reports/pilot_report.json"))
    parser.add_argument("--pilot-output", type=Path, default=Path("data/pilot/gec_pilot_100k.parquet"))
    parser.add_argument("--review-sample", type=Path, default=Path("reports/pilot_review_sample.jsonl"))
    parser.add_argument("--blocked-report", type=Path, default=Path("reports/phase10_blocked_attempt.json"))
    parser.add_argument("--failure-report", type=Path, default=Path("reports/phase10_failure.json"))
    parser.add_argument("--config", type=Path, default=Path("config/filly.yaml"))
    parser.add_argument("--candidate-aggregate", type=Path)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    try:
        report = build_final_dataset(
            args.candidate_dir, args.split_input, args.output_dir,
            review_manifest_path=args.review_manifest,
            pilot_report_path=args.pilot_report,
            pilot_output_path=args.pilot_output,
            review_sample_path=args.review_sample,
            blocked_report_path=args.blocked_report,
            failure_report_path=args.failure_report,
            seed=args.seed,
            config_path=args.config,
            candidate_aggregate_path=args.candidate_aggregate,
        )
    except ReviewGateError as error:
        print(json.dumps({"status": "blocked", "gate": error.result.status, "reason": error.result.reason}, ensure_ascii=True))
        raise SystemExit(2) from error
    print(json.dumps({key: report[key] for key in ("status", "target_total_pairs", "errorful_total", "identity_total")}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
