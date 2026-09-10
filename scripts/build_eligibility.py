"""Run the Phase 6 39-tag eligibility census before any quotas."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.geg.generators import GENERATOR_VERSION, all_tag_ids, generate_candidates
from src.geg.config import config_hash, load_config
from src.geg.hashing import sha256_file, sha256_files
from src.geg.tags import registry
from src.geg.artifacts import validate_destinations, verify_manifest


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _markdown(report: dict[str, object]) -> str:
    lines = [
        "# Tag capacity report",
        "",
        "This census was run before quota assignment. Counts are generated from",
        "validated clean targets after the deterministic base split. Unsupported",
        "families are recorded as zero capacity; no weak fallback is used.",
        "",
        f"- Input rows: **{report['input_rows']}**",
        f"- Input: `{report['input']}`",
        f"- Generator status: **{report['status']}**",
        "",
        "| Tag | Family | Status | Train sentences | Dev sentences | Synthetic-test sentences | Eligible positions | Estimated unique candidates | Reason |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in report["tags"]:
        lines.append(
            "| {tag} | {family} | {status} | {train} | {dev} | {synthetic_test} | "
            "{positions} | {candidates} | {reason} |".format(**row)
        )
    lines.extend([
        "",
        "`estimated_unique_candidates` is the number of valid inverse operations",
        "observed before generated-output collision deduplication. Phase 8 performs",
        "that separate output-pair deduplication while building the pilot.",
        "",
    ])
    return "\n".join(lines)


def build_report(
    input_path: Path,
    report_json: Path,
    report_markdown: Path,
    config_path: Path = Path("config/filly.yaml"),
    split_report: Path = Path("reports/base_split_report.json"),
) -> dict[str, object]:
    try:
        import pyarrow.parquet as pq
    except ImportError as error:
        raise RuntimeError("Phase 6 requires pyarrow") from error
    input_path = input_path.resolve()
    validate_destinations(
        {"input": input_path, "config": config_path, "split_report": split_report},
        {"json_report": report_json, "markdown_report": report_markdown},
    )
    config_digest = config_hash(load_config(config_path.resolve()))
    provenance = verify_manifest(split_report, input_path, config_digest)
    if not provenance.get("quality_manifest_sha256") or not provenance.get("input_sqlite_sha256"):
        raise RuntimeError("split report lacks quality provenance; rerun Phase 5")
    parquet = pq.ParquetFile(input_path)
    rows_by_tag = {
        tag_id: {
            "sentences": defaultdict(int),
            "positions": 0,
            "candidates": 0,
            "candidates_by_split": defaultdict(int),
            "status": None,
            "reason": None,
        }
        for tag_id in all_tag_ids()
    }
    input_rows = 0
    for batch in parquet.iter_batches(columns=["clean_id", "text", "split"]):
        clean_ids = batch.column("clean_id").to_pylist()
        texts = batch.column("text").to_pylist()
        splits = batch.column("split").to_pylist()
        for clean_id, text, split in zip(clean_ids, texts, splits):
            input_rows += 1
            for tag_id in all_tag_ids():
                result = generate_candidates(str(text), tag_id, compute_alignment=False)
                bucket = rows_by_tag[tag_id]
                bucket["status"] = result.status
                bucket["reason"] = result.reason or ""
                if result.candidates:
                    bucket["sentences"][str(split)] += 1
                    bucket["positions"] += len(result.candidates)
                    bucket["candidates"] += len(result.candidates)
                    bucket["candidates_by_split"][str(split)] += len(result.candidates)

    tags = []
    metadata = {item.id: item for item in registry()}
    for tag_id in all_tag_ids():
        bucket = rows_by_tag[tag_id]
        tags.append({
            "tag": tag_id,
            "family": metadata[tag_id].family,
            "status": bucket["status"] or "supported",
            "train": bucket["sentences"].get("train", 0),
            "dev": bucket["sentences"].get("dev", 0),
            "synthetic_test": bucket["sentences"].get("synthetic_test", 0),
            "eligible_clean_sentences": sum(bucket["sentences"].values()),
            "positions": bucket["positions"],
            "candidates": bucket["candidates"],
            "candidates_by_split": dict(bucket["candidates_by_split"]),
            "reason": bucket["reason"] or "",
        })
    report: dict[str, object] = {
        "status": "complete",
        "input": str(input_path),
        "input_sha256": sha256_file(input_path),
        "config_path": str(config_path.resolve()),
        "config_hash": config_digest,
        "split_report_sha256": sha256_file(split_report),
        "quality_manifest_sha256": provenance["quality_manifest_sha256"],
        "input_sqlite_sha256": provenance["input_sqlite_sha256"],
        "generator_version": GENERATOR_VERSION,
        "generator_sha256": sha256_files((Path("src/geg/generators.py").resolve(), Path("src/geg/alignment.py").resolve())),
        "input_rows": input_rows,
        "tag_count": len(tags),
        "tags": tags,
        "quota_assignment_performed": False,
        "primary_deduplication_performed": False,
    }
    _write_json(report_json, report)
    report_markdown.parent.mkdir(parents=True, exist_ok=True)
    report_markdown.write_text(_markdown(report), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/interim/split_clean.parquet"))
    parser.add_argument("--json", type=Path, default=Path("reports/tag_capacity_report.json"))
    parser.add_argument("--markdown", type=Path, default=Path("reports/TAG_CAPACITY_REPORT.md"))
    parser.add_argument("--config", type=Path, default=Path("config/filly.yaml"))
    parser.add_argument("--split-report", type=Path, default=Path("reports/base_split_report.json"))
    args = parser.parse_args()
    report = build_report(args.input, args.json, args.markdown, args.config, args.split_report)
    print(json.dumps({"status": report["status"], "input_rows": report["input_rows"], "tag_count": report["tag_count"]}, indent=2))


if __name__ == "__main__":
    main()
