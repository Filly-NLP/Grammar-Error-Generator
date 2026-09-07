"""Stream the primary SQLite corpus into immutable Phase 4 artifacts.

The production contract is three Parquet files: ``base_sentences``,
``validated_clean``, and ``quarantined_clean``. The source database is opened
read-only, uniqueness is asserted before any staging writer opens, and all
quality decisions are recorded in a report and run manifest. JSONL remains a
small, dependency-free smoke-test format only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Support both ``python -m scripts.export_sqlite`` and direct invocation.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.geg.config import config_hash, load_config
from src.geg.ingest import (
    RejectedSentence,
    SentenceRecord,
    assert_unique_normalized_text,
    connect_read_only,
    iter_sentence_rows,
    row_to_candidate,
    validate_row,
)


EXPORTER_VERSION = "filly-phase4-export-v2"


def _record_dict(record: SentenceRecord) -> dict[str, object]:
    return {
        "clean_id": record.clean_id,
        "text": record.text,
        "source_corpus": record.source_corpus,
        "publisher": record.publisher,
        "source_doc_id": record.source_doc_id,
        "published_at": record.published_at,
        "url_hash": record.url_hash,
        "sqlite_table": record.sqlite_table,
        "sqlite_rowid": record.sqlite_rowid,
        "metadata_json": record.metadata_json,
    }


def _reject_dict(record: RejectedSentence) -> dict[str, object]:
    return {
        "clean_id": record.clean_id,
        "text": record.text,
        "reason_codes": list(record.reason_codes),
        "sqlite_table": "sentences",
        "sqlite_rowid": record.sqlite_rowid,
        "metadata_json": record.metadata_json,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _clean_paths(
    base_output: Path | None,
    validated_output: Path | None,
    quarantine: Path | None,
) -> dict[str, Path]:
    values = {
        name: path.resolve()
        for name, path in {
            "base_sentences": base_output,
            "validated_clean": validated_output,
            "quarantined_clean": quarantine,
        }.items()
        if path is not None
    }
    if len(values) != len(set(values.values())):
        raise ValueError("Phase 4 artifact paths must be distinct")
    return values


def _write_jsonl(
    database: Path,
    paths: dict[str, Path],
    fetch_size: int,
    max_rows: int | None,
    quality_rules: dict[str, Any],
) -> dict[str, object]:
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    input_rows = validated_rows = quarantined_rows = 0
    connection = connect_read_only(database)
    try:
        with ExitStack() as stack:
            streams = {
                name: stack.enter_context(path.open("w", encoding="utf-8", newline="\n"))
                for name, path in paths.items()
            }
            for index, row in enumerate(iter_sentence_rows(connection, fetch_size)):
                if max_rows is not None and index >= max_rows:
                    break
                input_rows += 1
                base_record = _record_dict(row_to_candidate(row))
                if "base_sentences" in streams:
                    streams["base_sentences"].write(json.dumps(base_record, ensure_ascii=False) + "\n")
                result = validate_row(row, quality_rules=quality_rules)
                if isinstance(result, SentenceRecord):
                    validated_rows += 1
                    if "validated_clean" in streams:
                        streams["validated_clean"].write(json.dumps(_record_dict(result), ensure_ascii=False) + "\n")
                else:
                    quarantined_rows += 1
                    counts.update(result.reason_codes)
                    if "quarantined_clean" in streams:
                        streams["quarantined_clean"].write(json.dumps(_reject_dict(result), ensure_ascii=False) + "\n")
    finally:
        connection.close()
    return {
        "input_rows": input_rows,
        "validated_rows": validated_rows,
        "quarantined_rows": quarantined_rows,
        "quarantine_reasons": dict(sorted(counts.items())),
    }


def _parquet_schemas(pa: Any) -> tuple[Any, Any]:
    clean_schema = pa.schema([
        ("clean_id", pa.string()), ("text", pa.string()), ("source_corpus", pa.string()),
        ("publisher", pa.string()), ("source_doc_id", pa.string()), ("published_at", pa.string()),
        ("url_hash", pa.string()), ("sqlite_table", pa.string()), ("sqlite_rowid", pa.int64()),
        ("metadata_json", pa.string()),
    ])
    reject_schema = pa.schema([
        ("clean_id", pa.string()), ("text", pa.string()), ("reason_codes", pa.list_(pa.string())),
        ("sqlite_table", pa.string()), ("sqlite_rowid", pa.int64()), ("metadata_json", pa.string()),
    ])
    return clean_schema, reject_schema


def _write_parquet(
    database: Path,
    paths: dict[str, Path],
    fetch_size: int,
    max_rows: int | None,
    quality_rules: dict[str, Any],
) -> dict[str, object]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as error:
        raise RuntimeError(
            "Parquet export requires pyarrow; install the locked data-preparation dependencies "
            "or use --format jsonl for a bounded smoke check"
        ) from error

    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    clean_schema, reject_schema = _parquet_schemas(pa)
    schemas = {"base_sentences": clean_schema, "validated_clean": clean_schema, "quarantined_clean": reject_schema}
    writers: dict[str, Any] = {}
    counts: Counter[str] = Counter()
    input_rows = validated_rows = quarantined_rows = 0
    connection = connect_read_only(database)
    try:
        writers = {name: pq.ParquetWriter(path, schemas[name]) for name, path in paths.items()}
        batches: dict[str, list[dict[str, object]]] = {name: [] for name in paths}

        def flush() -> None:
            for name, rows in batches.items():
                if rows:
                    writers[name].write_table(pa.Table.from_pylist(rows, schema=schemas[name]))
                    rows.clear()

        for index, row in enumerate(iter_sentence_rows(connection, fetch_size)):
            if max_rows is not None and index >= max_rows:
                break
            input_rows += 1
            batches.setdefault("base_sentences", []).append(_record_dict(row_to_candidate(row)))
            result = validate_row(row, quality_rules=quality_rules)
            if isinstance(result, SentenceRecord):
                validated_rows += 1
                batches.setdefault("validated_clean", []).append(_record_dict(result))
            else:
                quarantined_rows += 1
                counts.update(result.reason_codes)
                batches.setdefault("quarantined_clean", []).append(_reject_dict(result))
            if sum(len(rows) for rows in batches.values()) >= fetch_size:
                flush()
        flush()
    finally:
        for writer in writers.values():
            writer.close()
        connection.close()
    return {
        "input_rows": input_rows,
        "validated_rows": validated_rows,
        "quarantined_rows": quarantined_rows,
        "quarantine_reasons": dict(sorted(counts.items())),
    }


def _blocked_reports(
    quality_report: Path,
    run_manifest: Path,
    integrity_report: Path | None,
    database: Path,
    database_hash: str,
    config_path: Path,
    config_digest: str,
    uniqueness: dict[str, object],
    error: str,
) -> None:
    payload: dict[str, object] = {
        "status": "blocked",
        "input_sqlite_sha256": database_hash,
        "input_row_count": uniqueness.get("rows_checked", 0),
        "uniqueness": uniqueness,
        "uniqueness_assertion_result": uniqueness,
        "near_deduplication_performed": False,
        "source_read_only": True,
        "error": error,
        "config_path": str(config_path.resolve()),
        "config_hash": config_digest,
    }
    _write_json(quality_report, payload)
    _write_json(run_manifest, {
        "status": "blocked",
        "upstream_repository": "Filly-NLP/Sentence-Pair-Scraper",
        "upstream_branch_or_commit": None,
        "database": str(database),
        **payload,
    })
    if integrity_report is not None:
        _write_json(integrity_report, {
            "status": "blocked",
            "database": str(database),
            **payload,
        })


def export(
    database: Path,
    output: Path | None = None,
    quarantine: Path | None = None,
    report: Path | None = None,
    output_format: str = "parquet",
    fetch_size: int = 50_000,
    max_rows: int | None = None,
    *,
    base_output: Path | None = None,
    validated_output: Path | None = None,
    quality_report: Path | None = None,
    run_manifest: Path | None = None,
    integrity_report: Path | None = None,
    config_path: Path = Path("config/filly.yaml"),
) -> dict[str, object]:
    """Export Phase 4 artifacts.

    ``output``/``report`` are retained as compatibility aliases for the old
    two-file smoke-test API. Production callers should use the named artifact
    arguments and receive all three outputs plus both reports.
    """
    database = database.resolve()
    config_path = config_path.resolve()
    config = load_config(config_path)
    config_digest = config_hash(config)
    quality_rules = dict(config.get("quality", {}))

    legacy_mode = base_output is None and validated_output is None
    if legacy_mode:
        validated_output = output
    elif validated_output is None:
        validated_output = output
    if quarantine is None and not legacy_mode:
        quarantine = Path("data/interim/quarantined_clean.parquet")
    if quality_report is None:
        quality_report = report or Path("reports/quality_report.json")
    if run_manifest is None:
        run_manifest = Path("reports/run_manifest.json")
    artifact_paths = _clean_paths(base_output, validated_output, quarantine)
    report_paths = {quality_report.resolve(), run_manifest.resolve()}
    if integrity_report is not None:
        report_paths.add(integrity_report.resolve())
    if database in set(artifact_paths.values()) | report_paths:
        raise ValueError("source SQLite database cannot be an output path")

    database_hash = _sha256_file(database)
    connection = connect_read_only(database)
    try:
        uniqueness = assert_unique_normalized_text(connection, fetch_size, max_rows)
    finally:
        connection.close()
    if not uniqueness["passed"]:
        _blocked_reports(
            quality_report, run_manifest, integrity_report, database, database_hash, config_path, config_digest,
            uniqueness, "upstream uniqueness contract violated; no staging export was performed",
        )
        raise RuntimeError("upstream uniqueness contract violated; no staging export was performed")

    try:
        if output_format == "jsonl":
            summary = _write_jsonl(database, artifact_paths, fetch_size, max_rows, quality_rules)
        else:
            summary = _write_parquet(database, artifact_paths, fetch_size, max_rows, quality_rules)
    except Exception as error:
        _blocked_reports(
            quality_report, run_manifest, integrity_report, database, database_hash, config_path, config_digest,
            uniqueness, str(error),
        )
        raise

    quality_payload: dict[str, object] = {
        "status": "complete",
        "rows_exported": summary["validated_rows"],
        "rows_quarantined": summary["quarantined_rows"],
        "input_rows": summary["input_rows"],
        "validated_rows": summary["validated_rows"],
        "quarantined_rows": summary["quarantined_rows"],
        "quarantine_reasons": summary["quarantine_reasons"],
        "quality_rules": quality_rules,
        "uniqueness_assertion_result": uniqueness,
        "near_deduplication_performed": False,
        "source_read_only": True,
    }
    _write_json(quality_report, quality_payload)
    manifest: dict[str, object] = {
        "status": "complete",
        "exporter_version": EXPORTER_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "upstream_repository": "Filly-NLP/Sentence-Pair-Scraper",
        "upstream_branch_or_commit": None,
        "database": str(database),
        "input_sqlite_sha256": database_hash,
        "input_row_count": uniqueness["rows_checked"],
        "uniqueness_assertion_result": uniqueness,
        "source_read_only": True,
        "near_deduplication_performed": False,
        "config_path": str(config_path),
        "config_hash": config_digest,
        "fetch_size": fetch_size,
        "format": output_format,
        "artifacts": {name: str(path) for name, path in artifact_paths.items()},
        "quality_report": str(quality_report.resolve()),
    }
    _write_json(run_manifest, manifest)
    if integrity_report is not None:
        _write_json(integrity_report, {
            "status": "complete",
            "database": str(database),
            "input_sqlite_sha256": database_hash,
            "input_row_count": uniqueness["rows_checked"],
            "uniqueness_assertion_result": uniqueness,
            "source_read_only": True,
            "near_deduplication_performed": False,
            "config_path": str(config_path),
            "config_hash": config_digest,
            "artifacts": manifest["artifacts"],
            "quality_report": str(quality_report.resolve()),
            "run_manifest": str(run_manifest.resolve()),
        })
    return {
        "quality_report": quality_payload,
        "run_manifest": manifest,
        # Compatibility fields for the original two-file smoke-test API.
        "rows_exported": summary["validated_rows"],
        "rows_quarantined": summary["quarantined_rows"],
        "quarantine_reasons": summary["quarantine_reasons"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--base-output", type=Path, default=Path("data/interim/base_sentences.parquet"))
    parser.add_argument("--validated-output", type=Path, default=Path("data/interim/validated_clean.parquet"))
    parser.add_argument("--output", type=Path, help="legacy alias for validated output; omits base output")
    parser.add_argument("--quarantine", type=Path, default=Path("data/interim/quarantined_clean.parquet"))
    parser.add_argument("--quality-report", type=Path, default=Path("reports/quality_report.json"))
    parser.add_argument("--run-manifest", type=Path, default=Path("reports/run_manifest.json"))
    parser.add_argument("--integrity-report", type=Path, default=Path("reports/upstream_integrity_report.json"))
    parser.add_argument("--report", type=Path, help="legacy alias for --quality-report")
    parser.add_argument("--config", type=Path, default=Path("config/filly.yaml"))
    parser.add_argument("--format", choices=("parquet", "jsonl"), default="parquet")
    parser.add_argument("--fetch-size", type=int, default=50_000)
    parser.add_argument("--max-rows", type=int)
    args = parser.parse_args()
    if args.output is not None:
        result = export(
            args.database, output=args.output, quarantine=args.quarantine,
            report=args.report or args.quality_report, output_format=args.format,
            fetch_size=args.fetch_size, max_rows=args.max_rows,
            run_manifest=args.run_manifest, integrity_report=args.integrity_report,
            config_path=args.config,
        )
    else:
        result = export(
            args.database, quarantine=args.quarantine, output_format=args.format,
            fetch_size=args.fetch_size, max_rows=args.max_rows,
            base_output=args.base_output, validated_output=args.validated_output,
            quality_report=args.report or args.quality_report, run_manifest=args.run_manifest,
            integrity_report=args.integrity_report,
            config_path=args.config,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
