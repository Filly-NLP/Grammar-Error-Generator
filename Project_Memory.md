# Project Memory

This file is the progress ledger for implementation cycles based on
`Implementation_Plan.md`. It is updated after each meaningful milestone and
material failure.

## 2026-09-07 - Phase 0 schema audit complete

- Changed files: `scripts/inspect_sqlite.py`, `docs/SQLITE_SCHEMA_AUDIT.md`,
  `docs/CURRENT_PIPELINE_AUDIT.md`.
- Commands: `python scripts/inspect_sqlite.py corpus.db --output
  reports/sqlite_schema.json`; read-only SQLite connection with URI
  `mode=ro`; `PRAGMA query_only = ON`; `Get-FileHash -Algorithm SHA256
  corpus.db`.
- Counts: `sentences=517342`, `articles=40648`, `sources=5`, `urls=40738`,
  `crawl_runs=19`, `crawl_events=533001`.
- Input hash before implementation: `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.
- Result: schema and provenance fields are sufficient for traceable Phase 4
  staging. The primary corpus is treated as already deduplicated; only a
  fail-fast non-mutating uniqueness assertion will be used.
- Live integrity result: `normalized_text` distinct count `517342`, duplicate
  groups `0`, and `is_duplicate` marker rows `0`. The source hash after the
  audit remained `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.
- Assumptions/unresolved: no pre-existing pipeline code or tests were found;
  `source_doc_id` maps to `sentences.article_id`; primary publisher is joined
  through `sources`.

## 2026-09-07 - Phase 1/2 resource registries implemented

- Changed files: `resources/balarila_tags.yaml`,
  `resources/table3_states.yaml`, `src/geg/resources.py`, `src/geg/tags.py`,
  `src/geg/states.py`.
- Result: exactly 39 Table 2 correction labels and exactly 10 Table 3 states
  are loaded from single-source resource files. `IMPACT` and `IMPOBJ` have no
  correction tag and cannot be target states. Unknown labels fail closed.
- Dependency note: resource files use JSON syntax in `.yaml` files so the
  implementation remains dependency-free while remaining valid YAML.
- Tests: registry and morphology tests pass as part of the 10-test unittest
  run recorded below.

## 2026-09-07 - Phase 3/4 implementation and unit validation

- Changed files: `src/geg/morphology.py`, `scripts/import_unimorph_tgl.py`,
  `src/geg/ingest.py`, `scripts/export_sqlite.py`, and
  `tests/test_phase0_4.py`.
- Commands: `python -m unittest discover -s tests -v`.
- Tests/counts: 10 tests passed. Coverage includes exact registry counts,
  unknown-tag rejection, Table-3 source-only imperatives, provisional
  UniMorph mapping, malformed/unmapped safety, read-only SQLite enforcement,
  duplicate-contract detection, JSONL provenance export, source hash
  preservation, and importer review status.
- Result: Phase 3 accepts only an explicitly supplied local UniMorph TSV and
  emits reviewable JSONL plus a report; no remote resource was downloaded and
  no morphology row is marked frozen. Phase 4 streams joined sentence,
  article, and source metadata, normalizes targets, quarantines reason-coded
  failures, and fails before export if normalized-text uniqueness is violated.
- Dependency blocker: `pyarrow` is not installed, so production Parquet
  export is implemented but cannot run in this environment. `--format jsonl`
  is retained for bounded smoke checks; no full staging artifact was produced
  in this cycle.
- Unresolved: exact upstream UniMorph feature conventions and a reviewed
  Balarila morphology lookup remain human-review inputs; Phase 5 split and
  all later generation phases are intentionally untouched.

## 2026-09-07 - Live source checks and Parquet blocker recorded

- Command: `python scripts/inspect_sqlite.py corpus.db --output
  reports/sqlite_schema.json`; the command completed with read-only SQLite
  access and a streaming SHA-256 calculation.
- Result: the live uniqueness assertion passed for all 517,342 rows. A
  bounded JSONL fixture export passed in unit tests. A production Parquet run
  is intentionally not attempted past dependency validation because
  `pyarrow` is absent; the exporter fails closed with an actionable message.
- No data was written to `corpus.db`, and no primary-corpus deduplication or
  near-deduplication was performed.

## 2026-09-07 - Production export attempt failed closed

- Command: `python -u scripts/export_sqlite.py corpus.db --output
  data/interim/base_sentences.parquet --quarantine
  data/interim/quarantined_clean.parquet --report
  reports/upstream_integrity_report.json --format parquet`.
- Full pre-export check passed: `rows_checked=517342`,
  `unique_text_hashes=517342`, `duplicate_rows=0`.
- Result: export stopped before writing staging files because `pyarrow` is not
  installed. `reports/upstream_integrity_report.json` records status
  `blocked`, the unchanged input SHA-256, and the dependency error. The
  optional dependency is documented in `requirements-data.txt`; install it
  before the first real Parquet staging run.
- Script fix during this milestone: direct invocation now bootstraps the
  repository import path, and dependency failures are recorded in the report
  instead of appearing as an untracked partial export.

## 2026-09-07 - Final phase 0-4 validation

- Commands: `python -m compileall -q src scripts tests`; direct `--help`
  checks for both import/export entry points; `python -m unittest discover -s
  tests -v`; final `Get-FileHash -Algorithm SHA256 corpus.db`.
- Result: all 11 unit tests passed, all Python sources compiled, both command
  line entry points load directly, and the final corpus hash is unchanged at
  `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.
- Phase boundary: phases 0, 1, 2, 3, and 4 are implemented and documented;
  phase 5 (base splitting) and later GEG generation work were not started.

## 2026-09-07 - Phase 4 artifact contract and project bootstrap

- Changed files: `pyproject.toml`, `config/filly.yaml`, `.gitignore`,
  `requirements-data.txt`, `src/geg/config.py`, `src/geg/ingest.py`, and
  `scripts/export_sqlite.py`.
- The configuration now contains the exact plan configuration plus explicit,
  deterministic target-quality rules for NFC normalization, whitespace,
  empty/NUL/letter checks, length, alphabetic ratio, repeated punctuation,
  boilerplate, and upstream duplicate markers.
- The exporter now performs one read-only streaming pass after the full
  uniqueness assertion and writes production `base_sentences.parquet`,
  `validated_clean.parquet`, `quarantined_clean.parquet`,
  `quality_report.json`, and `run_manifest.json`. JSONL remains a compatibility
  smoke format only.
- The old two-file Python API remains compatible for small tests while the CLI
  defaults to the three production artifacts.

## 2026-09-07 - Isolated dependency installation

- Command: `python -m venv .venv`, followed by `.venv\\Scripts\\python.exe -m
  pip install -e \".[dev]\"`.
- First install attempt was blocked by the sandbox network policy while
  fetching setuptools build dependencies. The required escalation was
  approved; the retry installed editable `filly-geg` plus `pyarrow 25.0.1`,
  `PyYAML 6.0.3`, and `pytest 9.1.1` successfully.
- The `.venv` directory is ignored and is not part of corpus or source data.

## 2026-09-07 - Report-isolation regression fixed and live artifacts refreshed

- Bug found: exporter tests used the default `reports/run_manifest.json`, so a
  one-row fixture could overwrite the repository's live manifest; the prior
  `reports/upstream_integrity_report.json` also remained a stale blocked report.
- Changed files: `scripts/export_sqlite.py` and `tests/test_phase0_4.py`.
- Fix: added explicit `--integrity-report` support, wrote complete/blocked
  integrity reports alongside quality and run manifests, routed every test
  report to a temporary directory, and added a regression guard that fails if
  any repository report changes during tests.
- Tests: `.venv\\Scripts\\python.exe -m pytest -q` passed all 11 tests.
- Full live command: `.venv\\Scripts\\python.exe scripts/export_sqlite.py
  corpus.db --base-output data/interim/base_sentences.parquet
  --validated-output data/interim/validated_clean.parquet --quarantine
  data/interim/quarantined_clean.parquet --quality-report
  reports/quality_report.json --integrity-report
  reports/upstream_integrity_report.json --run-manifest
  reports/run_manifest.json --format parquet --fetch-size 50000`.
- Final live counts: base/input `517342`; validated `517226`; quarantined
  `116`; reasons `repeated_punctuation=115`, `low_alphabetic_ratio=1`.
  Full uniqueness passed with `517342` checked, `0` duplicate rows.
- Final report status: `quality_report.json=complete`,
  `upstream_integrity_report.json=complete`, `run_manifest.json=complete`.
- Final manifest hash and post-run database hash:
  `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.

## 2026-09-07 - Final hygiene

- Added `*.egg-info/` to `.gitignore` and normalized progress-ledger heading
  punctuation. No corpus, Parquet artifact, or production report was changed.
