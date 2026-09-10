"""Run the Phase 6 39-tag eligibility census before any quotas."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.geg.generators import GENERATOR_VERSION, GENERATOR_POLICY_STATUS, all_tag_ids, generate_candidates, production_coverage
from src.geg.config import config_hash, load_config, resolve_runtime_config
from src.geg.hashing import sha256_file, generator_dependency_hash
from src.geg.generators import GeneratorContext
from src.geg.tags import registry
from src.geg.artifacts import validate_destinations, verify_manifest
from src.geg.telemetry import REJECTION_SAMPLE_LIMIT, telemetry_from_result


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
    loaded_config = load_config(config_path.resolve())
    runtime_config = resolve_runtime_config(loaded_config)
    resource_config = runtime_config["runtime"]["resource_paths"]
    generator_context = GeneratorContext.load(resource_config)
    config_digest = config_hash(loaded_config)
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
            "not_applicable": 0,
            "rejections": defaultdict(int),
            "rejection_samples": [],
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
                result = generate_candidates(str(text), tag_id, compute_alignment=False, context=generator_context)
                bucket = rows_by_tag[tag_id]
                bucket["status"] = result.status
                bucket["reason"] = result.reason or ""
                telemetry = telemetry_from_result(
                    result,
                    context={"clean_id": str(clean_id), "split": str(split), "tag": tag_id},
                )
                bucket["not_applicable"] += telemetry.not_applicable
                if telemetry.samples:
                    bucket["rejection_samples"].extend(
                        telemetry.samples[: max(0, REJECTION_SAMPLE_LIMIT - len(bucket["rejection_samples"]))]
                    )
                for rejection, count in (result.rejected or {}).items():
                    bucket["rejections"][str(rejection)] += int(count)
                if result.candidates:
                    bucket["sentences"][str(split)] += 1
                    bucket["positions"] += len(result.candidates)
                    bucket["candidates"] += len(result.candidates)
                    bucket["candidates_by_split"][str(split)] += len(result.candidates)
                elif result.status == "supported" and telemetry.not_applicable == 0:
                    # Older generator implementations did not populate the
                    # explicit counter; retain the distinction for those
                    # results without treating unavailable generators as N/A.
                    bucket["not_applicable"] += 1

    tags = []
    metadata = {item.id: item for item in registry()}
    coverage = production_coverage(resource_config)
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
            "not_applicable": bucket.get("not_applicable", 0),
            "candidate_selected": bucket["candidates"],
            "rejections": dict(bucket.get("rejections", {})),
            "rejection_samples": bucket.get("rejection_samples", [])[:REJECTION_SAMPLE_LIMIT],
            "rejection_telemetry": {
                "not_applicable": bucket.get("not_applicable", 0),
                "candidate_selected": bucket["candidates"],
                "candidate_rejected": sum(bucket.get("rejections", {}).values()),
                "rejections": dict(bucket.get("rejections", {})),
                "samples": bucket.get("rejection_samples", [])[:REJECTION_SAMPLE_LIMIT],
                "sample_limit": REJECTION_SAMPLE_LIMIT,
            },
            "implementation_status": coverage[tag_id]["implementation_status"],
            "implemented": coverage[tag_id]["implemented"],
            "resource_backed": coverage[tag_id]["resource_backed"],
            "resource_available": coverage[tag_id].get("resource_available", True),
            "resource_error": coverage[tag_id].get("resource_error", ""),
        })
    aggregate_rejections: Counter[str] = Counter()
    aggregate_not_applicable = 0
    aggregate_selected = 0
    aggregate_samples: list[dict[str, object]] = []
    for tag in tags:
        aggregate_not_applicable += int(tag["not_applicable"])
        aggregate_selected += int(tag["candidate_selected"])
        aggregate_rejections.update({str(key): int(value) for key, value in tag["rejections"].items()})
        if len(aggregate_samples) < REJECTION_SAMPLE_LIMIT:
            aggregate_samples.extend(tag.get("rejection_samples", [])[: REJECTION_SAMPLE_LIMIT - len(aggregate_samples)])
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
        "generator_policy_status": GENERATOR_POLICY_STATUS,
        "effective_runtime": runtime_config.get("runtime", {}),
        "generator_sha256": generator_dependency_hash(resource_paths=resource_config),
        "generator_dependency_hash": generator_dependency_hash(resource_paths=resource_config),
        "input_rows": input_rows,
        "tag_count": len(tags),
        "registered_tag_count": len(tags),
        "implemented_tag_count": sum(1 for tag in tags if tag["implemented"]),
        "unavailable_registered_tag_count": sum(1 for tag in tags if not tag["implemented"]),
        "tag_registry_complete": len(tags) == 39,
        "production_generator_coverage_complete": all(tag["implemented"] for tag in tags),
        "resource_ready": all(tag["status"] != "unavailable" and tag.get("resource_available", True) for tag in tags if tag["resource_backed"]),
        "production_ready": all(tag["implemented"] for tag in tags)
        and all(tag["status"] != "unavailable" and tag.get("resource_available", True) for tag in tags if tag["resource_backed"]),
        "zero_capacity_supported_tags": [tag["tag"] for tag in tags if tag["status"] == "supported" and int(tag["candidates"]) == 0],
        "not_applicable": aggregate_not_applicable,
        "candidate_selected": aggregate_selected,
        "candidate_rejected": sum(aggregate_rejections.values()),
        "rejection_samples": aggregate_samples,
        "rejection_telemetry": {
            "not_applicable": aggregate_not_applicable,
            "candidate_selected": aggregate_selected,
            "candidate_rejected": sum(aggregate_rejections.values()),
            "rejections": dict(aggregate_rejections),
            "samples": aggregate_samples,
            "sample_limit": REJECTION_SAMPLE_LIMIT,
        },
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
