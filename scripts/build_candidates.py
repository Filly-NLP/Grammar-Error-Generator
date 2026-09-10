"""Phase 9 bounded/sharded candidate builder.

This command is intentionally blocked until a hash-bound linguistic review
manifest approves the Phase 8 pilot.  It writes one deterministic Parquet
shard per invocation and never mutates the primary SQLite corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.geg.config import config_hash as compute_config_hash, load_config
from src.geg.dataset import SPLITS
from src.geg.generators import GENERATOR_VERSION, all_tag_ids, generate_candidates
from src.geg.hashing import sha256_file, sha256_files
from src.geg.review import ReviewGateError, require_review_gate
from src.geg.artifacts import validate_destinations


CANDIDATE_BUILDER_VERSION = "filly-phase9-sharded-v1"


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
    }


def _shard_for(clean_id: str, shard_count: int) -> int:
    return int(hashlib.sha256(clean_id.encode("utf-8")).hexdigest(), 16) % shard_count


def _supported_tags(capacity: dict[str, Any]) -> list[str]:
    supported = {str(item["tag"]) for item in capacity.get("tags", []) if item.get("status") == "supported" and int(item.get("candidates", 0)) > 0}
    return [tag for tag in all_tag_ids() if tag in supported]


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
    seed: int = 20260905,
    config_path: Path = Path("config/filly.yaml"),
    shard_index: int = 0,
    shard_count: int = 1,
    max_rows: int | None = None,
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
    # This is deliberately the first operation that can fail for a production
    # run.  A pending review therefore cannot create an output directory/file.
    review = require_review_gate(
        review_manifest_path,
        pilot_report_path=pilot_report_path,
        pilot_output_path=pilot_output_path,
        review_sample_path=review_sample_path,
        blocked_report=blocked_report_path,
        attempted_output=output_path,
    )
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
    input_path = input_path.resolve()
    capacity_report_path = capacity_report_path.resolve()
    config_path = config_path.resolve()
    capacity = json.loads(capacity_report_path.read_text(encoding="utf-8"))
    input_sha256 = sha256_file(input_path)
    if capacity.get("input_sha256") != input_sha256:
        raise RuntimeError("stale capacity report: split input hash does not match")
    generator_sha256 = sha256_files((Path("src/geg/generators.py").resolve(), Path("src/geg/alignment.py").resolve()))
    if capacity.get("generator_version") != GENERATOR_VERSION or capacity.get("generator_sha256") != generator_sha256:
        raise RuntimeError("stale capacity report: generator source/version does not match")
    config = load_config(config_path)
    current_config_hash = compute_config_hash(config)
    if capacity.get("config_hash") != current_config_hash:
        raise RuntimeError("stale capacity report: configuration hash does not match")
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
    collision_db = temp_dir / "collisions.sqlite3"
    writer = None
    connection = None
    parquet = None
    published_output = False
    selected_count = 0
    batch_rows: list[dict[str, Any]] = []
    split_counts: Counter[str] = Counter()
    writer_schema = None
    try:
        if output_path.exists() or manifest_path.exists():
            raise FileExistsError(f"refusing to overwrite candidate shard or manifest: {output_path}")
        connection = sqlite3.connect(collision_db)
        connection.execute("CREATE TABLE output_pairs (source_text TEXT NOT NULL, target_text TEXT NOT NULL, PRIMARY KEY(source_text, target_text))")
        parquet = pq.ParquetFile(input_path)
        for batch in parquet.iter_batches(columns=columns):
            values = {name: batch.column(name).to_pylist() for name in columns}
            for index in range(len(values["clean_id"])):
                if selected_count >= max_rows:
                    break
                clean_id = str(values["clean_id"][index])
                if _shard_for(clean_id, shard_count) != shard_index:
                    continue
                source_rows += 1
                split = str(values["split"][index])
                if split not in SPLITS:
                    rejected["unknown_split"] += 1
                    continue
                clean = {name: values[name][index] for name in columns}
                for tag in tags:
                    if selected_count >= max_rows:
                        break
                    result = generate_candidates(str(clean["text"]), tag, compute_alignment=True)
                    for candidate in result.candidates:
                        if selected_count >= max_rows:
                            break
                        cursor = connection.execute(
                            "INSERT OR IGNORE INTO output_pairs(source_text, target_text) VALUES (?, ?)",
                            (candidate.source_text, candidate.target_text),
                        )
                        if cursor.rowcount != 1:
                            rejected["output_pair_collision"] += 1
                            continue
                        if any(not isinstance(item, dict) for spans in (candidate.source_spans, candidate.target_spans) for item in spans):
                            rejected["invalid_alignment"] += 1
                            continue
                        record = _candidate_record(clean, candidate, seed, current_config_hash)
                        batch_rows.append(record)
                        selected_count += 1
                        split_counts[split] += 1
                        tag_counts[candidate.correction_tag] += 1
                        if len(batch_rows) >= 4096:
                            table = pa.Table.from_pylist(batch_rows)
                            if writer is None:
                                writer_schema = table.schema
                                writer = pq.ParquetWriter(temp_output, writer_schema, compression="zstd")
                            else:
                                table = table.cast(writer_schema, safe=False)
                            writer.write_table(table)
                            batch_rows.clear()
            if selected_count >= max_rows:
                break
        if batch_rows:
            table = pa.Table.from_pylist(batch_rows)
            if writer is None:
                writer_schema = table.schema
                writer = pq.ParquetWriter(temp_output, writer_schema, compression="zstd")
            else:
                table = table.cast(writer_schema, safe=False)
            writer.write_table(table)
            batch_rows.clear()
        if writer is not None:
            writer.close()
            writer = None
        connection.commit()
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
            "generator_sha256": generator_sha256,
            "shard_index": shard_index,
            "shard_count": shard_count,
            "source_rows": source_rows,
            "candidate_rows": selected_count,
            "split_counts": dict(split_counts),
            "tag_counts": dict(tag_counts),
            "tag_status": tag_status,
            "collision_store": "sqlite3 temporary bounded store",
            "collision_rejections": rejected.get("output_pair_collision", 0),
            "rejections": dict(rejected),
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
    parser.add_argument("--seed", type=int, default=20260905)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--max-rows", type=int, default=None)
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
        )
    except ReviewGateError as error:
        print(json.dumps({"status": "blocked", "gate": error.result.status, "reason": error.result.reason}, ensure_ascii=True))
        raise SystemExit(2) from error
    print(json.dumps({key: report[key] for key in ("status", "shard_index", "candidate_rows", "output")}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
