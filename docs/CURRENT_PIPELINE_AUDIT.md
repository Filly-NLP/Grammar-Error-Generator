# Current pipeline audit

## Scope

The repository was empty apart from `README.md`, `Implementation_Plan.md`, and
the supplied `corpus.db` when this cycle began. There was no existing GEG
implementation, tag registry, morphology resource, preprocessing code, test
suite, package manifest, or configuration file to preserve.

## Phase 0–4 implementation boundary

This cycle adds only the implementation needed for:

1. read-only SQLite schema/integrity inspection;
2. a frozen 39-label Balarila Table 2 registry;
3. a separate 10-state Balarila Table 3 registry with `IMPACT`/`IMPOBJ`
   explicitly source-only;
4. a local UniMorph-TSV importer that emits reviewable provisional mappings;
5. streaming SQLite extraction, target-quality validation, and immutable
   staging output.

Article-aware splitting, eligibility census, corruption generation, pilot
generation, and the 1M dataset build are intentionally not implemented here;
they are later phases in `Implementation_Plan.md`.

## Existing data contract observed

The supplied database contains 517,342 sentence rows. Sentence rows carry an
article ID, source ID, normalized text, language metadata, quality score,
content hash, and upstream duplicate markers. Article rows carry URL and
publication metadata, and source rows carry publisher/domain metadata. The
exporter preserves these relationships in staging metadata.

## Dependency decision

The environment does not currently provide PyYAML, pytest, pandas, or pyarrow.
The two resource files are therefore JSON documents with `.yaml` names (valid
YAML and readable by standard-library `json`), and tests use `unittest`.
Parquet remains the production staging format; the exporter reports a clear
dependency error when `pyarrow` is unavailable and offers JSONL only for small
local smoke checks.
