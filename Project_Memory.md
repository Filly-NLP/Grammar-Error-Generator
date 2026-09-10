# Project Memory

This file is the progress ledger for implementation cycles based on
`Implementation_Plan.md`. It is updated after each meaningful milestone and
material failure.

## 2026-09-08 - Post-Phase-8 review fixes integrated into main

- Ported the review fixes from `origin/bugfix/post-review-phase-8` without
  switching branches, cherry-picking, stashing, resetting, or cleaning the
  worktree. Added `docs/CODE_REVIEW_FIXES.md` and updated the Phase 8/quality
  policy documentation.
- Added `src/geg/artifacts.py` for fail-closed destination alias checks
  (including existing hard links/symlinks) and complete upstream manifest/hash
  verification. Phase 4–8 builders now reject report/artifact/input collisions
  before opening writers.
- Phase 5 requires the Phase 4 quality manifest; Phase 6 requires the Phase 5
  split report and records `candidates_by_split`, `quality_manifest_sha256`,
  and `split_report_sha256`; Phase 8 consumes exact split capacities,
  deterministically refills after structural rejection, and propagates the
  provenance hashes.
- Updated generator version to
  `filly-generators-v3-enclitic-context`; glide endings (`w`/`y`), accent-safe
  classification, and traditional enclitic exceptions are explicit in
  operation metadata. Formality markers now detect punctuation-adjacent
  informal forms without matching containing words. Source hashing is now
  repository-relative and relocation-stable.
- Phase 9 candidate manifests and Phase 10 final manifests now require and
  propagate the Phase 4 quality-manifest and Phase 5 split-report hashes.
  Phase 9/10/11/12 writers validate destination aliases before review gates,
  reads, or publication; Phase 11 freeze and Phase 12 prediction evaluation
  reject output/input collisions.
- Validation: full pytest `74 passed`; `python -m compileall -q scripts src
  tests`; `git diff --check` passed. No production regeneration was attempted
  in this integration step, and human pilot review remains pending.

## 2026-09-08 - Live Phase 4–8 regeneration after review integration

- Regenerated against read-only `corpus.db` in strict order: Phase 4 export,
  Phase 5 article-aware split, Phase 6 39-tag census, then Phase 8 pilot.
- Source invariant: `corpus.db` remains SHA-256
  `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`;
  `517342` rows checked, `517342` unique normalized-text hashes, `0`
  duplicates, no near-deduplication. Phase 4 produced `431840` validated and
  `85502` quarantined rows; the punctuation-safe marker policy contributed to
  the changed quarantine count.
- Phase 5 produced `302288` train, `64776` dev, and `64776` synthetic-test
  rows across `40634` document groups with no group crossover. Phase 6
  produced a complete 39-tag report with quality-manifest hash
  `19eefbee3f0848817c6e1a8a4b091dfd16b8b12631601e2e75efbaa49401c8de`, split
  report hash `6086b6c2d2c6269f974220f78dbbe0f54648b0ae223d0aaa7194921f39f0b021`,
  and generator hash `56a98f789ecbec0012b1949b898c2abc571bd1f04b0c819b38b126401e0e89fc`.
- Phase 8 completed exactly `100000` rows (`70000/15000/15000`), `26`
  supported tags represented, `39` tags present in the capacity census,
  `100000/100000` replay checks passed, `0` shortfall, and output SHA-256
  `8af53d557b0b7599457a5c214d31ef47ef10b15f1d2ff34a1469850b0514e4ad`.
  Pilot review remains pending; this is not linguistic approval.
- Phase 9 and Phase 10 preflights both exited `2` with the expected missing
  review-manifest blocker and created no candidate/final production output.
  Phase 11 freeze preflight exited `2` on the missing authentic annotation
  input; no frozen evaluation dataset was created.

## 2026-09-08 - Phase 11 evaluation contract milestone

- Added the separate `src/evaluation_noise/` package, versioned evaluation
  item schema, blank template generator, and dependency-gated freeze script.
- The validator enforces the 1,000 informal-item composition (300 slang,
  300 abbreviation, 300 spelling variation, 100 mixed noise), non-empty
  authentic and controlled subsets, 200-500 clean controls, `test_only`, two
  annotators plus adjudication, registered Table-2 tags, provenance/license
  fields, replayable normalization and grammar edits, no GEC train/dev text or
  clean-id leakage, and frozen normalizer-rule seen/unseen classification.
- No authentic examples were fabricated or scraped. A real freeze remains
  dependency-gated until annotated authentic/controlled JSONL, clean controls,
  a frozen rule inventory, and leakage inputs exist.

## 2026-09-08 - Phase 12 routing and metrics milestone

- Added separate `src/evaluation/` prediction artifacts and dependency-injected
  A/B/C routing: raw-to-GEC, raw-to-normalizer-to-GEC, and oracle-normalized-
  to-GEC. Added prediction artifact JSONL I/O and versioned JSON schema.
- Added normalization/GEC/end-to-end edit metrics, category/source breakdowns,
  sentence-level outputs, clean-control overcorrection, seeded paired bootstrap
  deltas, exact McNemar, and per-tag metrics that fail clearly when predicted
  tags are absent.
- Added `docs/PHASE11_EVALUATION.md`, `docs/PHASE12_EVALUATION.md`, and CLI
  entry points for blank template creation, freeze validation, and prediction
  evaluation. Deterministic fixture/stub tests are planned; no real model
  evaluation is claimed.

## 2026-09-08 - Phase 11 real-freeze blocker recorded

- Real preflight command: `python scripts/freeze_evaluation.py --informal
  evaluation/annotations/informal.jsonl --controls
  evaluation/annotations/clean_controls.jsonl --rule-inventory
  normalization/rules/frozen_inventory.json --output
  data/evaluation/frozen_evaluation.json --blocked-report
  reports/phase11_freeze_blocked.json`.
- Result: expected exit `2`; blocker is missing
  `evaluation/annotations/informal.jsonl`. The blocker report is
  `reports/phase11_freeze_blocked.json`; no frozen evaluation file was
  created. Authentic examples were neither fabricated nor scraped.

## 2026-09-08 - Phase 11/12 validation milestone

- Added the frozen normalizer-rule inventory schema and tightened the runtime
  gate to require `status=frozen`; paired bootstrap and condition-level metrics
  exclude clean controls from the primary A/B comparison while retaining
  separate overcorrection reporting.
- Deterministic Phase 11/12 tests: `9 passed`; full suite: `45 passed`;
  compileall and `git diff --check` passed. No model or remote data was used.
- `corpus.db` was not modified; no Phase 11 frozen dataset or Phase 12 real
  prediction report exists.

## 2026-09-08 - Phase 12 metric completeness check

- The A/B bootstrap report now includes seeded 95% confidence intervals and
  delta(B-A) for all three requested measures: precision, recall, and F0.5;
  the primary comparison excludes clean controls, which remain in the explicit
  overcorrection section.
- JSON schemas load successfully; the full suite remains `45 passed`,
  compileall passes, and `git diff --check` passes.

## 2026-09-08 - Phase 11 freeze fail-closed hardening

- Unknown tags, malformed rule-inventory objects, and other validation
  failures now normalize to `EvaluationValidationError`, so the freeze CLI
  records a blocker instead of leaking an uncaught exception.
- Repeated real preflight still exits `2`, reports the missing authentic input,
  and leaves `data/evaluation/frozen_evaluation.json` absent.
- Prediction per-tag evaluation also rejects unregistered predicted labels;
  the final full suite remains `45 passed`.

## 2026-09-08 - Phase 11 reviewer finding hardening

- Controlled evaluation rows now require `base_clean_id`; annotator identities
  must be distinct. Production freeze requires existing GEC train/dev
  manifests/views and a separate normalizer-example training dependency.
  GEC dependencies must expose clean IDs, and normalizer dependencies must
  expose examples; exact raw/normalized example reuse is rejected.
- The freeze CLI now accepts `--normalizer-train` and records its dependency
  in the frozen manifest. The real freeze remains blocked before these checks
  because the authentic annotation input is absent.

## 2026-09-08 - Phase 12 reviewer finding hardening

- Added exact prediction-bundle validation: one and only one A/B/C route per
  frozen sample, no missing/extra/duplicate routes, raw/intermediate input
  equality against frozen item fields, and artifact binding to the expected
  frozen-evaluation SHA plus normalizer/GEC versions before metrics run.
- Prediction artifacts now carry tagged predicted spans/edits. Per-tag scoring
  matches `(tag, start, end, source, target)` with Counters, so wrong spans,
  repeated edits, false positives, and missed edits are counted explicitly.
- Added ERR, Levenshtein and Damerau distance-to-gold, error-family and
  seen/unseen normalization breakdowns, and denominator-safe empty/clean tests.
- Adversarial Phase 11/12 coverage now includes wrong route inputs, omitted
  IDs, extras, wrong bindings, same annotators, missing dependencies, wrong
  spans, repeated edits, and absent predicted edits. Full suite: `55 passed`.

## 2026-09-08 - Phase 11/12 final hardening validation

- Real freeze preflight was rerun with intended GEC train/dev and normalizer
  training paths. It exited `2` on the missing authentic input,
  `reports/phase11_freeze_blocked.json` remained the only freeze artifact, and
  `data/evaluation/frozen_evaluation.json` was not created.
- Final checks: full pytest `55 passed`, compileall passed, `git diff --check`
  passed, and `corpus.db` remains SHA-256
  `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.

## 2026-09-08 - Phase 11/12 reviewer findings 1-4, 6-8

- Primary informal rows now require nonempty replayable normalization edits,
  tagged grammar edits, and both boundaries `R != N* != G`; identity/empty
  edits remain limited to clean controls. Freeze manifests now record SHA-256
  hashes for GEC train/dev and normalizer-example leakage dependencies in
  addition to input/rule hashes.
- Prediction runtime/schema alignment requires non-null binding fields,
  canonical route constraints, and an edit coordinate-space declaration.
  Predicted tag/edit arrays are optional for text-only metrics, but when
  supplied validation checks source spans, overlap, replay to `gec_output`,
  and tag/edit consistency before metrics; per-tag mode requires them.
- Primary A-vs-B bootstrap uses the common raw-informal-to-final baseline;
  GEC-input bootstrap diagnostics are retained separately. A/B per-tag scores
  are explicitly unavailable unless gold-normalized spans are supplied; C
  reports all 39 tags, including support-zero rows.
- Freeze publication now uses an exclusive lock, unique temporary file,
  fsync, and no-overwrite hard-link publication with cleanup. Added adversarial
  tests for wrong spans, replay/tag mismatch, route bindings, hashes, repeated
  edits, and publication races.

## 2026-09-08 - Phase 11/12 final reviewer validation

- Real freeze preflight with all intended dependency flags exits `2` on the
  missing authentic annotation input; no frozen dataset is created and the
  blocker report remains `reports/phase11_freeze_blocked.json`.
- Final validation: full pytest `58 passed`, compileall passed, all JSON
  schemas parse, `git diff --check` passed, and `corpus.db` remains SHA-256
  `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.

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

## 2026-09-07 - Remaining reviewer findings fixed and phases 4-8 regenerated

- Added a documented conservative model-free `language_code_switch_ratio`
  gate based only on configured English function-word markers. Borderline or
  over-threshold rows are quarantined and never rewritten. Single-character
  mojibake markers were replaced with validated multi-character sequences;
  legitimate accented names such as `José` are preserved. Tests cover
  heavily English mixed text, borrowed terms, accented names, and mojibake.
- Removed the mutable global alignment switch. Candidate generation now takes
  an explicit per-call `compute_alignment` flag. APPEND operations serialize
  `source_token_index = target_token_index - 1` for previous-token anchors and
  a null index plus `$START` sentinel for prepends; pilot validation rejects
  inconsistent anchors.
- Pilot generation now requires the capacity report `config_hash` to match
  the current configuration. The legacy Parquet writer accepts
  `quarantine=None` even when a row is rejected; production and legacy paths
  have regression coverage.
- Changed files: `src/geg/ingest.py`, `src/geg/generators.py`,
  `scripts/build_eligibility.py`, `scripts/build_pilot.py`,
  `scripts/export_sqlite.py`, `config/filly.yaml`,
  `docs/TARGET_QUALITY_POLICY.md`, `docs/PHASE8_PILOT.md`,
  `tests/test_phase0_4.py`, `tests/test_phase5_8.py`, and this memory file.
- Validation: `.venv\\Scripts\\python.exe -m pytest -q` -> **30 passed**;
  `.venv\\Scripts\\python.exe -m compileall -q src scripts tests` passed.
- Phase 4 regenerated with read-only `corpus.db`: input `517342`, validated
  `432197`, quarantined `85145`; uniqueness passed with `517342` unique
  hashes and zero duplicates, and no near-deduplication. Reasons were
  `unbalanced_quote=80386`, `low_language_confidence=6309`,
  `unbalanced_bracket=442`, `informal_marker=168`,
  `repeated_punctuation=115`, `sentence_integrity_leading_closer=12`, and
  `low_alphabetic_ratio=1`. The new code-switch gate added no live rows;
  removing former single-character markers retained the two prior rows.
- Phase 5 regenerated `40634` article groups into train `302537`, dev
  `64830`, and synthetic-test `64830` rows. Phase 6 rescanned all `39` tags
  with current split/config/generator hashes; unsupported hyphen, space, and
  morphology families remain zero/unavailable.
- Phase 8 regenerated a complete `100000`-row pilot (`70000/15000/15000`),
  with `26` supported tags, `8` output-pair collisions rejected, and no
  shortfall. Replay verification passed for all rows. All `9078` APPEND rows
  had valid indices/anchors (`256` `$START` null-index prepends and `8822`
  previous-token anchors). Pilot SHA-256:
  `cf12336d2246a38ed8491e157d478e1d7ff3b8be7522d062796f5bd83ffa91f5`.
- Dependency hashes: config
  `87140306ab5762b70d56ade4fd446655d2b00f41f76fe81b94318c6ece071790`, split
  output `4cb135c4e205efb59e2ad95536004deee2795796b4a7c9596e0712eb96c2acba`,
  capacity `2d7e102d21d7d4d41ffb677d0cae9cee92e332c7affcb5f273f59e24f8746032`,
  generator `be1377d75e492c9e90823d2fcd74cfa3bc092c8f4c15a2657f68bcae4475d6cf`.
  `corpus.db` remains unchanged at
  `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.
- Automated structural review is complete; human linguistic review remains
  pending. Phase 9 and the 1M build were not started.
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

## 2026-09-07 - Corrective Phase 4 target-surface milestone

- Changed files: `src/geg/ingest.py`, `tests/test_phase0_4.py`, and
  `docs/SQLITE_SCHEMA_AUDIT.md`.
- Corrective change: staged `text` now derives from `sentence_text` with NFC
  and whitespace normalization while preserving source casing. The upstream
  `normalized_text` field remains restricted to the non-mutating uniqueness
  assertion and stable integrity hash.
- Tests: the phase 0-4 suite will be rerun after the production export;
  added a regression test asserting `Kumusta sa mundo!` remains cased.
- Assumption: existing quality thresholds and quarantine policy are unchanged;
  this milestone changes only the target surface used downstream.

## 2026-09-07 - Corrective Phase 4 production rerun complete

- Command: `.venv\\Scripts\\python.exe scripts/export_sqlite.py corpus.db
  --base-output data/interim/base_sentences.parquet
  --validated-output data/interim/validated_clean.parquet --quarantine
  data/interim/quarantined_clean.parquet --quality-report
  reports/quality_report.json --integrity-report
  reports/upstream_integrity_report.json --run-manifest
  reports/run_manifest.json --format parquet --fetch-size 50000`.
- Counts: `input=517342`, `validated=517226`, `quarantined=116`;
  `repeated_punctuation=115`, `low_alphabetic_ratio=1`; uniqueness
  `duplicate_rows=0`.
- Verification: staged text retains source casing (for example `INANUNSYO`
  and `Lionel Messi`); database SHA-256 remains
  `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.
- Result: corrected Phase 4 artifacts are production-ready for Phase 5;
  no source database writes or primary-corpus deduplication occurred.

## 2026-09-07 - Phase 5 deterministic article-aware split complete

- Changed files: `src/geg/split.py`, `scripts/split_base.py`, and
  `docs/BASE_SPLIT.md`; artifact `data/interim/split_clean.parquet` and report
  `reports/base_split_report.json`.
- Command: `.venv\\Scripts\\python.exe scripts/split_base.py --input
  data/interim/validated_clean.parquet --output
  data/interim/split_clean.parquet --report reports/base_split_report.json`.
- Counts: `517226` validated rows across `40635` document groups; train
  `362058`, dev `77584`, synthetic test `77584`; group counts `28447`, `6094`,
  `6094` respectively.
- Result: every source document group is assigned to one split; no primary
  deduplication or generated-pair operation occurred. Seed `20260905` and
  config fractions are recorded in the report.

## 2026-09-07 - Phase 6 complete 39-tag eligibility census

- Changed files: `src/geg/generators.py`, `scripts/build_eligibility.py`,
  `reports/TAG_CAPACITY_REPORT.md`, and `reports/tag_capacity_report.json`.
- Command: `.venv\\Scripts\\python.exe scripts/build_eligibility.py --input
  data/interim/split_clean.parquet --json reports/tag_capacity_report.json
  --markdown reports/TAG_CAPACITY_REPORT.md`.
- Counts: all **39** registry tags were evaluated over `517226` split rows.
  Supported capacities include `$REPLACE_ng=424580`,
  `$ADD_PUNC_PERIOD=482021`, and `$DELETE=3280775` eligible positions.
- Explicit zero/unavailable capacity: all 5 hyphen/space labels (no reviewed
  construction resource) and all 8 morphology labels (no frozen reviewed verb
  paradigm resource). No quota assignment was performed.
- Assumption: conservative function-word, punctuation, casing, pronoun, and
  phonological enclitic rules are eligible for pilot review; their linguistic
  validity remains subject to human review.

## 2026-09-07 - Phase 7 single-error inverse generators complete

- Changed files: `src/geg/generators.py` and `tests/test_phase5_8.py`.
- Implemented auditable inverse operations for complete-token `ng`/`nang`,
  context-sensitive enclitics, reviewed function-word duplicate/deletion
  candidates, terminal punctuation add/change, conservative casing, and
  pronoun substitutions. Every candidate stores target-side correction tag,
  source/target surfaces, and a structured generation operation.
- Fail-closed behavior: all hyphen/space families and all morphology tags
  return `unavailable` with zero candidates until reviewed resources are
  frozen. No arbitrary string morphology or construction editing is present.
- Tests: `.venv\\Scripts\\python.exe -m pytest -q` -> **19 passed**.
- Automated structural review is complete for the implemented operations;
  human linguistic review remains pending.

## 2026-09-07 - Phase 7 test correction recorded

- Failure: the first enclitic golden test used a terminal `rin.` token, and
  the generator incorrectly rejected its punctuation suffix as non-complete.
- Fix: terminal punctuation is now preserved by the replacement operation and
  does not invalidate a complete enclitic token; the phonological context
  check remains required.
- Validation: the corrected suite passed **19 tests**; no live artifact or
  source database was changed by the failed test run.

## 2026-09-07 - Phase 8 deterministic 100k pilot complete

- Changed files: `scripts/build_pilot.py`, `tests/test_phase5_8.py`, and
  `docs/PHASE8_PILOT.md`; artifacts `data/pilot/gec_pilot_100k.parquet`,
  `reports/pilot_report.json`, `reports/pilot_report.md`, and
  `reports/pilot_review_sample.jsonl`.
- Command: `.venv\\Scripts\\python.exe scripts/build_pilot.py --input
  data/interim/split_clean.parquet --capacity-report
  reports/tag_capacity_report.json --output data/pilot/gec_pilot_100k.parquet
  --report-json reports/pilot_report.json --report-markdown
  reports/pilot_report.md --review-sample reports/pilot_review_sample.jsonl
  --seed 20260905 --config-hash d935d0a2a0a881a42337e6602337e33d7416f73b5d85d661f6caef95d3e00fb4`.
- Counts: exactly `100000` rows (`70000` train, `15000` dev,
  `15000` synthetic test), `26` supported tags represented, `8` generated
  output-pair collisions rejected, and `247` source surfaces rejected for
  introducing whitespace/NFC normalization.
- Structural checks: one error per errorful pair, no normalization noise
  injected, output-pair collision dedupe only, all variants inherit the base
  split. Stratified sample contains `390` rows (five per available tag/split).
- Review state: automated structural review **complete**; human linguistic
  review **pending**. The pilot is not claimed linguistically reviewed or
  production-ready. Phase 9/full 1M generation was not started.

## 2026-09-07 - Final clause-level gate regeneration and acceptance validation

- Added the configurable clause-level code-switch rule requested by review.
  It examines only substantial leading/trailing segments around strong
  Filipino boundary tokens and requires both English marker and configured
  English content signals. It emits language_code_switch_clause; it is not an
  exact-string exception and preserves ordinary borrowed words.
- Regression coverage includes the exact SENT_00003260d19295aa sentence,
  which is quarantined, plus legitimate borrowed-word and Filipino controls.
- Final Phase 4: input 517342, validated 432078, quarantined 85264.
  Quarantine reasons include language_code_switch_borderline=109 and
  language_code_switch_clause=161; upstream uniqueness remains 517342 unique
  hashes with zero duplicates.
- Final Phase 5: 40634 groups; train 302454, dev 64812, synthetic test 64812.
  Final Phase 6 rescanned all 39 tags with the current config and sources.
- Final Phase 8: complete 100000 rows (70000/15000/15000), 26 tags,
  zero shortfall, 9079 APPEND rows, and 0 replay/span or APPEND-index errors.
  Pilot SHA-256 is
  ede27d2476bb7796cfad5bf510359e01c0f1cc510657d0e4b6a190f1d130b8a6.
- Full pytest passed 30 tests; compileall passed. Quality, split, capacity,
  and pilot config hashes match f927575f4bfee486e881bea2e8c007b35197ba9536c1d34e4e26ba323ccc69a8;
  all dependency/input/generator/output hashes match current artifacts.
  The reviewer sentence is absent from validated targets. corpus.db remains
  unchanged at aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50.
  Human linguistic review remains pending; Phase 9 was not started.

## 2026-09-07 - Final borderline-gate regeneration and acceptance validation

- The code-switch gate now quarantines both high-ratio
  language_code_switch_ratio rows and the configured intermediate
  language_code_switch_borderline band. The policy remains model-free,
  reason-coded, conservative, and non-rewriting. Test fixtures now construct
  José and JosÃ© explicitly with code points, avoiding source-encoding
  ambiguity.
- Final Phase 4: input 517342, validated 432159, quarantined 85183;
  uniqueness passed with 517342 unique hashes and zero duplicates. The new
  borderline reason contributed 109 rows. Final Phase 5: 40634 groups,
  train 302511, dev 64824, synthetic test 64824.
- Final Phase 6 scanned all 39 tags against the current split, generator,
  and config. Unsupported hyphen/space and morphology tags remain zero with
  explicit unavailable reasons.
- Final Phase 8: 100000 rows exactly (70000/15000/15000), 26 tags,
  8 output collisions, zero shortfall, 9078 APPEND rows. Replay and span
  checks had 0 errors; APPEND anchor/index checks had 0 errors.
- Dependency validation: quality/split/capacity/pilot config hashes all match
  63668dc43657b2880e881a9268c4d8ab0298f384e0178710411d10ef52c4f029;
  capacity input and generator hashes match split/generator sources; pilot
  input, capacity, generator, and output hashes all match current artifacts.
  Pilot SHA-256:
  d0f9aa4040cf0f0b2646d21c348083531c97f16696eb2065d6bf808cc7dc0004.
- Final checks: focused tests and full pytest each passed 30 tests; compileall
  passed; all 100000 pilot rows replayed successfully. corpus.db remains
  unchanged at SHA-256
  aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50.
  Human linguistic review remains pending; Phase 9 and the 1M build were not
  started.

## 2026-09-07 - Final Phase 6 consistency rerun

- Command: `.venv\\Scripts\\python.exe scripts/build_eligibility.py --input
  data/interim/split_clean.parquet --json reports/tag_capacity_report.json
  --markdown reports/TAG_CAPACITY_REPORT.md`.
- Result: the final generator implementation was rescanned over all `517226`
  rows and all `39` tags. Terminal-punctuation enclitic opportunities are now
  included; unsupported hyphen/space and morphology families remain zero with
  explicit unavailable reasons.
- The existing 100k pilot remains valid: it uses only supported candidates,
  has exact requested counts and no normalization noise. The refreshed census
  is more permissive than the pilot's conservative capacity estimate and does
  not change pilot rows.
- Final validation: `.venv\\Scripts\\python.exe -m pytest -q` -> **19 passed**;
  `compileall` passed; `corpus.db` SHA-256 remains
  `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.

## 2026-09-07 - Reviewer fixes: alignment, quality gates, and manifests

- Changed files: `src/geg/alignment.py`, `src/geg/generators.py`,
  `scripts/build_pilot.py`, `src/geg/ingest.py`, `config/filly.yaml`,
  `scripts/export_sqlite.py`, `src/geg/hashing.py`, `scripts/split_base.py`,
  `scripts/build_eligibility.py`, and focused tests/docs.
- Alignment: candidates now carry replayable structured operations and
  diff-derived source/target spans. Pilot `alignment_success` is computed only
  after source-to-target replay. `$APPEND_t1` uses explicit `$START`/`prepend`
  at sentence start or a previous-token anchor elsewhere. Casing metadata
  records exact target/source surfaces and direction.
- Quality policy: configurable language/language-confidence, delimiter,
  sentence-integrity, suspicious-encoding, and model-free formality gates now
  quarantine reason-coded targets without rewriting them. The policy is
  documented in `docs/TARGET_QUALITY_POLICY.md`.
- Reproducibility: Phase 4, split, census, and pilot reports now record config,
  artifact/input/output, generator, and capacity-report hashes. Pilot aborts on
  stale split/capacity/generator/config dependencies. A count-only census mode
  avoids expensive span construction; selected pilot rows still receive full
  replay validation.
- Parquet: fixed the legacy two-output path's `base_sentences` writer
  `KeyError`; production and legacy Parquet tests cover casing and artifact
  shape.

## 2026-09-07 - Reviewer-fix regeneration and final validation

- First quality-gate rerun exposed a false-positive bug: curly apostrophes
  were counted as closing quotes, quarantining `119990` rows. The gate now
  treats only paired curly double quotes as quote delimiters; apostrophes are
  allowed. The Windows CLI also initially failed printing U+FFFD through
  cp1252; JSON CLI output now uses ASCII escapes while artifacts remain UTF-8.
- Final Phase 4 command regenerated `517342` input rows into `432195`
  validated and `85147` quarantined. Reasons: `unbalanced_quote=80386`,
  `low_language_confidence=6309`, `unbalanced_bracket=442`,
  `informal_marker=168`, `sentence_integrity_leading_closer=12`,
  `repeated_punctuation=115`, `suspicious_encoding=2`,
  `low_alphabetic_ratio=1`.
- Final Phase 5 split: `40634` document groups; train `302536`, dev `64829`,
  synthetic test `64830`. Input/output SHA-256 hashes are recorded in
  `reports/base_split_report.json`.
- Final Phase 6 census: all `39` tags; hyphen/space and morphology families
  remain explicitly unavailable/zero. Capacity report includes config,
  split-input, generator-version, and generator-source hashes.
- Final Phase 8 pilot: exactly `100000` rows (`70000/15000/15000`), `26`
  tags, `8` output-pair collisions rejected, and `292` source candidates
  rejected for normalization contamination. Pilot output includes replayed
  source/target spans and records all dependency hashes. Human linguistic
  review remains pending; Phase 9/full 1M generation was not started.
- Validation: `.venv\\Scripts\\python.exe -m pytest -q` -> **26 passed**;
  `compileall` passed; full pilot replay/span verification passed for all
  `100000` rows; `corpus.db` SHA-256 remains
  `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.

## 2026-09-08 - Phase 9/10 preflight reconciliation

- Authoritative on-disk artifacts before implementation: validated staging has
  `432078` rows and SHA-256
  `b0f8fd95f79b4cc8013f3a9705d3c1a663a68daaffd9f6680eb6912e7bd979a8`; the
  article-aware split has SHA-256
  `c0262c173459a4d6e643bf683397f32f8ab0d081e3358ee6502af100ac9a25db`; the
  Phase 8 pilot has exactly `100000` rows and SHA-256
  `ede27d2476bb7796cfad5bf510359e01c0f1cc510657d0e4b6a190f1d130b8a6`.
- Current reports confirm split counts `70000/15000/15000`, 26 supported tags,
  zero pilot shortfall, and `human_linguistic_review=pending` with
  `pilot_review_complete=false`. Older ledger counts/hashes are historical and
  must not be used as Phase 9/10 dependencies.
- Phase 9/10 implementation is review-gated. No candidate shard or final 1M
  output may be created until a hash-bound, complete, approving linguistic
  review manifest is validated.

## 2026-09-08 - Phase 9/10 review gate implementation and blocked preflight

- Added `src/geg/review.py` with a versioned review-manifest schema and
  explicit `complete`, `incomplete`, `stale`, `revise`, and `reject` outcomes.
  The gate binds the pilot report, pilot Parquet, and review-sample hashes and
  requires every sampled row to be reviewed with an approving decision.
- Added `src/geg/dataset.py` for exact largest-remainder split arithmetic,
  bounded tag quotas, candidate replay invariants, and identity-row checks.
- Added Phase 9 `scripts/build_candidates.py` for deterministic sharded
  candidate Parquet output and Phase 10 `scripts/build_dataset.py` for exact
  1M final/stage-view construction. Both refuse existing outputs and invoke the
  review gate before creating output directories.
- Expected blocked commands were run for both phases. Reports are
  `reports/phase9_blocked_attempt.json` and
  `reports/phase10_blocked_attempt.json`; both classify the current missing
  review manifest as `incomplete`, exit with code `2`, and created no candidate
  or final dataset output.
- Current gate evidence: pilot report SHA-256
  `f19e24b6afe43c0536375de268fa4b44d640a97182d6f3138b3388714316e752`, pilot
  output SHA-256
  `ede27d2476bb7796cfad5bf510359e01c0f1cc510657d0e4b6a190f1d130b8a6`, and
  review sample SHA-256
  `057e7114fae304d4cc0cde31b2f3cb4a3fd4bbac48d7beb496de42919c3d9a78`.
- Compile/help checks passed. Full candidate/final generation remains blocked
  until human linguistic review is completed and the approving manifest is
  created.

## 2026-09-08 - Phase 9/10 fixture validation

- Review gate tightened to require `accepted_rows + revised_rows +
  rejected_rows == reviewed_rows` and, for approval, every reviewed row to be
  accepted with zero revised/rejected rows.
- Added `docs/PILOT_LINGUISTIC_REVIEW.md`, `docs/PHASE9_CANDIDATES.md`,
  `docs/PHASE10_DATASET.md`, and `tests/test_phase9_10.py` covering exact
  Balarila arithmetic, replay/collision invariants, review state/hash gates,
  exact fixture finalization, identity rows, overwrite refusal, and blocked
  output creation.
- Validation: `.venv\\Scripts\\python.exe -m pytest -q` -> **36 passed**;
  `.venv\\Scripts\\python.exe -m compileall -q src scripts tests` passed;
  repeated live preflight attempts exited `2` for both builders with
  `incomplete/review manifest does not exist`, and both candidate/final output
  paths remain absent.
- Added `scripts/validate_pilot_review.py` as the standalone review preflight
  CLI; it exits `0` only for an approving complete review and `2` for every
  blocking state.
- Review preflight was run against the current missing manifest and recorded
  in `reports/pilot_review_gate.json` as `incomplete`; it exited `2`. Final
  validation after this addition remains **36 passed**, compileall passed, and
  the source database hash is unchanged.
- Added the explicit JSON Schema resource
  `resources/pilot_review_manifest.schema.json`; the standalone validator and
  builders continue to enforce the same schema fields without adding a runtime
  dependency.

## 2026-09-08 - Phase 9/10 reviewer safeguards

- Linguistic approval now requires reviewer and distinct adjudicator identities,
  a timezone-aware `reviewed_at`, and unique hash-bound row decisions covering
  every review-sample `pair_id` with non-empty notes. Unresolved or stale row
  decisions remain blocked.
- Phase 10 now requires a complete shard set `0..n-1`, consistent input/config/
  generator/review/capacity dependencies, all-39-tag status manifests, and a
  streamed clean-id provenance lookup. Every candidate is checked against its
  current target text, split, source document, publisher, corpus, table, and
  row ID before selection.
- Phase 10 stage outputs are split-specific under `train/`, `dev/`, and
  `synthetic_test/`; no mixed dev/test training-facing file is emitted.
- Phase 9 now requires an explicit `--max-rows` bound, writes incrementally
  with `ParquetWriter`, tracks output collisions in a temporary SQLite store,
  and publishes through a unique temporary file plus exclusive lock/atomic
  rename with cleanup on failure.
- Added adversarial coverage for review identity/row hashes, incomplete shard
  sets, provenance tampering, split-specific stage files, bounded Phase 9
  output, and complete 39-tag manifests.
- Validation: `.venv\\Scripts\\python.exe -m pytest -q` -> **48 passed**;
  compileall and `git diff --check` passed. Review/Phase 9/Phase 10 live
  preflights each exited `2` with `incomplete/review manifest does not exist`;
  candidate and final output paths remain absent. `corpus.db` remains
  SHA-256 `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.

## 2026-09-08 - Phase 9/10 seed and builder-version binding

- Every Phase 9 shard manifest now records `seed` and both explicit/current
  candidate-builder version fields. Every candidate row already carries the
  same seed/version/config metadata; Phase 10 now validates those fields while
  streaming and rejects any mismatch.
- Phase 10 requires all shard manifests to agree on seed, builder version,
  input/config/generator/review/capacity dependencies, and the complete shard
  index set. The final requested seed and current Phase 9 builder version are
  recorded in the final manifest, preventing mixed candidates or a falsely
  claimed final seed.
- Added adversarial tests for mixed shard seeds and final-build seed mismatch.
- Validation: `.venv\\Scripts\\python.exe -m pytest -q` -> **58 passed**;
  compileall and `git diff --check` passed. Review, Phase 9, and Phase 10 live
  preflights remain fail-closed with exit `2`; no production outputs were
  created. `corpus.db` SHA-256 remains
  `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.

## 2026-09-08 - Phase 11/12 final replay, optional-artifact, and TOCTOU hardening

- `replay_edits` now rejects every negative or out-of-range start/end span,
  including zero-width insertions beyond the source length. Repeated edits at
  the same valid boundary remain supported and are scored with multiplicity.
- Prediction artifacts now permit both `predicted_tags` and `predicted_edits`
  to be absent/null for text-only reports. If either is supplied, both are
  validated, registered, non-overlapping, source-bounded, replayable, and
  tag-consistent; per-tag mode still requires them. The JSON Schema and Phase
  12 documentation now describe this contract.
- Freeze parsing uses byte snapshots for the small JSON/JSONL inputs, hashes
  dependencies before validation, re-hashes after validation and immediately
  before hard-link publication, and blocks on either mutation. Added tests for
  both mutation windows, out-of-bounds/impossible insertions, overlapping
  predicted spans, and valid repeated same-boundary edits.
- Focused validation: `.venv\\Scripts\\python.exe -m pytest -q
  tests/test_phase11_12.py` -> **24 passed**. Full-suite and blocked real-data
  preflight evidence will be appended after the final repository checks.

## 2026-09-08 - Phase 11/12 final checks complete

- Direct `per_tag_metrics` callers now receive the same replay/span/tag
  validation for supplied prediction edits as the full evaluator; text-only
  calls may still omit both optional arrays.
- Full validation: `.venv\\Scripts\\python.exe -m pytest -q` -> **63 passed**;
  compileall passed; all evaluation JSON schemas parse and confirm
  `predicted_tags`/`predicted_edits` are optional; `git diff --check` passed.
- Real freeze preflight exited `2` with blocker status `blocked` because
  `evaluation/annotations/informal.jsonl` is absent. No
  `data/evaluation/frozen_evaluation.json` was created. `corpus.db` remains
  unchanged at SHA-256
  `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.

## 2026-09-08 - Phase 11/12 post-check hardening

- Freeze publication now records a blocker if a dependency disappears while
  either post-validation or pre-publication hashing is in progress.
- Final rerun after this change: full pytest **63 passed**, compileall passed,
  JSON schema parsing passed, and `git diff --check` passed. The real freeze
  preflight again exited `2` for the missing authentic annotation file, with
  no frozen output; the source database hash is unchanged.
- Added a JSONL round-trip assertion proving text-only artifacts preserve
  omitted/null predicted tag and edit fields without weakening required
  model/version/frozen-evaluation bindings.

## 2026-09-08 - Phase 11/12 no-op edit rejection

- The shared edit validator now rejects every edit whose `source == target`,
  including empty zero-width insertions. This uniformly blocks no-op
  normalization edits, gold grammar edits, and predicted edits before replay
  or scoring; registered-tag validation remains enforced for fabricated tags.
- Added regression coverage for normalization/gold/predicted no-ops, valid
  repeated edits, and fabricated predicted tags. Full pytest: **64 passed**;
  compileall, JSON schema parsing, and `git diff --check` passed. `corpus.db`
  remains SHA-256
  `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.

## 2026-09-08 - Reviewer acceptance fixes: provenance, report safety, and atomic predictions

- Phase 5 through Phase 9 now propagate the original SQLite SHA-256 from the
  Phase 4 quality manifest. Phase 10 validates that every candidate shard
  agrees on `quality_manifest_sha256`, `split_report_sha256`, and
  `input_sqlite_sha256`; it no longer reads a hard-coded
  `reports/run_manifest.json`.
- Phase 10 rejects blocked/failure report paths inside the final output tree.
  Prediction JSONL publication now validates each row into a unique temporary
  file, fsyncs it, atomically links it without overwrite, and removes the
  temporary file after any partial-row failure.
- Restored/adapted destination collision matrices, punctuation-boundary tests,
  importer/exporter collision tests, deterministic pilot refill/shortfall
  tests, stale shard SQLite-chain coverage, and symlink alias coverage.
- Focused acceptance suite after these edits: **77 passed**. Live Phase 9/10
  production generation remains prohibited pending the human pilot review.

## 2026-09-08 - Provenance-chain regeneration and blocked production preflights

- Regenerated the approved live chain in strict order against read-only
  `corpus.db`: Phase 4 exported 517,342 rows, validated 431,840, quarantined
  85,502, and asserted 517,342 unique normalized-text hashes with zero
  duplicates. The source SQLite SHA-256 remains
  `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.
- Phase 5 regenerated 431,840 split rows across 40,634 article groups
  (`train=302,288`, `dev=64,776`, `synthetic_test=64,776`). The authoritative
  quality-manifest hash is
  `e70d52c4317424318c9c53941c6241c5c249f3072d080c28d88c020c551ad40e`.
- Phase 6 completed the 39-tag census. Phase 8 rebuilt the exact 100,000-row
  pilot (`70,000/15,000/15,000`), with zero shortfall and 100,000/100,000
  replay validation. Pilot Parquet SHA-256:
  `8af53d557b0b7599457a5c214d31ef47ef10b15f1d2ff34a1469850b0514e4ad`;
  split-report hash:
  `a08a02a52ddce7e8a820411d9764d13dd88e65fbc5435fb2aa851a3d165aa1e4`.
- Phase 9 and Phase 10 production preflights both exited **2** with the
  expected `incomplete/review manifest does not exist` blocker and created no
  candidate or final dataset output. Phase 11 freeze preflight exited **2** for
  the absent `evaluation/annotations/informal.jsonl`; no frozen evaluation
  manifest was created.
- Final validation: full pytest **118 passed**, compileall passed, all JSON
  schemas parsed, and `git diff --check` passed. No production Phase 9/10 or
  frozen evaluation data was generated.

## 2026-09-08 - Final Phase 12 leaf-symlink safeguard

- Prediction artifact publication now checks the originally requested leaf
  before resolving its parent, rejecting existing and dangling symlinks while
  still allowing a symlinked/relocated parent directory to resolve normally.
- Corrected the Phase 10 containment regression to exercise both
  `blocked_report_path` and `failure_report_path` descendants independently.
- Added the dangling-leaf symlink regression. Final validation: full pytest
  **119 passed**, focused Phase 9–12 tests **31 passed**, compileall passed,
  all JSON schemas parsed, and `git diff --check` passed. The source database
  remains unchanged at SHA-256
  `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.
