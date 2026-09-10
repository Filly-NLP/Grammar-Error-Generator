"""Create deterministic article-aware Phase 5 base splits."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.geg.config import config_hash, load_config, resolve_runtime_config
from src.geg.hashing import sha256_file
from src.geg.artifacts import validate_destinations, verify_manifest
from src.geg.split import SPLIT_NAMES, assign_group_splits, group_key


SPLIT_ALGORITHM_VERSION = "filly-phase5-split-v1"


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def split_parquet(
    input_path: Path,
    output_path: Path,
    report_path: Path,
    config_path: Path = Path("config/filly.yaml"),
    seed: int | None = None,
    quality_manifest: Path = Path("reports/run_manifest.json"),
) -> dict[str, object]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as error:
        raise RuntimeError("Phase 5 requires pyarrow") from error
    input_path = input_path.resolve()
    output_path = output_path.resolve()
    report_path = report_path.resolve()
    validate_destinations(
        {"input": input_path, "config": config_path, "quality_manifest": quality_manifest},
        {"output": output_path, "report": report_path},
    )
    config = load_config(config_path.resolve())
    runtime = resolve_runtime_config(config)
    config_digest = config_hash(config)
    quality_provenance = verify_manifest(quality_manifest, input_path, config_digest, "validated_clean")
    if not quality_provenance.get("input_sqlite_sha256"):
        raise RuntimeError("quality manifest lacks input_sqlite_sha256; regenerate Phase 4")
    fractions = {name: float(runtime["splits"][name]) for name in SPLIT_NAMES}
    effective_seed = int(runtime["runtime"]["seed"] if seed is None else seed)
    group_by_document = bool(runtime["runtime"]["group_by_document"])

    parquet = pq.ParquetFile(input_path)
    group_counts: Counter[str] = Counter()
    rows_seen = 0
    for batch in parquet.iter_batches(columns=["clean_id", "source_doc_id"]):
        clean_ids = batch.column("clean_id").to_pylist()
        doc_ids = batch.column("source_doc_id").to_pylist()
        for clean_id, doc_id in zip(clean_ids, doc_ids):
            group_counts[group_key(str(clean_id), doc_id, group_by_document=group_by_document)] += 1
            rows_seen += 1
    assignments = assign_group_splits(group_counts, fractions, effective_seed)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = None
    split_counts: Counter[str] = Counter()
    split_group_counts: Counter[str] = Counter()
    try:
        for batch in parquet.iter_batches():
            clean_ids = batch.column("clean_id").to_pylist()
            doc_ids = batch.column("source_doc_id").to_pylist()
            keys = [group_key(str(clean_id), doc_id, group_by_document=group_by_document) for clean_id, doc_id in zip(clean_ids, doc_ids)]
            split_values = [assignments[key].split for key in keys]
            enriched = batch.append_column("group_key", pa.array(keys, type=pa.string()))
            enriched = enriched.append_column("split", pa.array(split_values, type=pa.string()))
            if writer is None:
                writer = pq.ParquetWriter(output_path, enriched.schema)
            writer.write_batch(enriched)
            split_counts.update(split_values)
            split_group_counts.update(f"{split_name}:{key}" for key, split_name in zip(keys, split_values))
    finally:
        if writer is not None:
            writer.close()

    group_split_counts = Counter(assignment.split for assignment in assignments.values())
    report: dict[str, object] = {
        "status": "complete",
        "input": str(input_path),
        "output": str(output_path),
        "rows": rows_seen,
        "groups": len(assignments),
        "grouping": "source_doc_id when present, clean_id fallback" if group_by_document else "clean_id",
        "group_by_document": group_by_document,
        "seed": effective_seed,
        "algorithm_version": SPLIT_ALGORITHM_VERSION,
        "config_hash": config_digest,
        "quality_manifest_sha256": sha256_file(quality_manifest),
        "quality_manifest": str(quality_manifest.resolve()),
        "input_sqlite_sha256": quality_provenance["input_sqlite_sha256"],
        "input_sha256": sha256_file(input_path),
        "output_sha256": sha256_file(output_path),
        "fractions": fractions,
        "row_counts": dict(sorted(split_counts.items())),
        "group_counts": dict(sorted(group_split_counts.items())),
        "all_groups_single_split": True,
        "primary_deduplication_performed": False,
    }
    _write_json(report_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/interim/validated_clean.parquet"))
    parser.add_argument("--output", type=Path, default=Path("data/interim/split_clean.parquet"))
    parser.add_argument("--report", type=Path, default=Path("reports/base_split_report.json"))
    parser.add_argument("--config", type=Path, default=Path("config/filly.yaml"))
    parser.add_argument("--seed", type=int)
    parser.add_argument("--quality-manifest", type=Path, default=Path("reports/run_manifest.json"))
    args = parser.parse_args()
    print(json.dumps(split_parquet(args.input, args.output, args.report, args.config, args.seed, args.quality_manifest), indent=2))


if __name__ == "__main__":
    main()
