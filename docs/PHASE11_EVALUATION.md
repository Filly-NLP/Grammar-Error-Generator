# Phase 11: separate end-to-end evaluation data

Phase 11 is the boundary between formal GEC training data and the FILLY
system evaluation.  The files under `src/evaluation_noise/` are not imported
by the formal GEG generators and must never be used to make GEC train/dev
rows.

## Required composition

The frozen informal set contains exactly 1,000 rows:

| category | rows |
| --- | ---: |
| slang | 300 |
| abbreviation | 300 |
| spelling variation | 300 |
| mixed noise | 100 |

Both `source_type=authentic` and `source_type=controlled` must be present.
The separate clean-control file contains 200--500 rows.  Every row is
`split=test_only`; the freeze validator rejects any other split.

## Required row evidence

Each row records `raw_informal`, `gold_normalized_errorful`, and
`gold_final_correct`.  Normalization and grammar edits are offset-based and
must replay exactly.  Grammar edits carry only tags registered in
`resources/balarila_tags.yaml`.  Each row also includes two annotator IDs,
adjudication status, source/license/attribution/timestamp provenance, and a
frozen normalizer `normalization_rule_id` with a validated
`seen_rule`/`unseen_pattern` classification.

Primary informal rows must contain at least one normalization edit and at
least one tagged grammar edit, with `raw_informal != gold_normalized_errorful`
and `gold_normalized_errorful != gold_final_correct`. Clean controls are the
only rows allowed to have identity text and empty edit lists.

The validator accepts no inferred or repaired labels.  It checks exact text
and clean-id leakage against GEC train/dev Parquet or JSONL inputs. Controlled
rows must carry `base_clean_id`; a production freeze requires both GEC
train/dev views/manifests and verifies those IDs. It also requires a separate
normalizer-example training dependency and rejects exact raw/normalized-example
reuse, beyond the frozen rule inventory check. Annotator identities must be
distinct. All leakage dependencies and input manifests are SHA-256 recorded
in the freeze manifest.

## Safe workflow

1. Run `scripts/build_evaluation_template.py` to create a blank manifest
   template.  It contains no examples.
2. Populate authentic rows from a documented, licensed source and controlled
   rows from a separately reviewed process.  Do not scrape or fabricate rows
   as part of this repository automation.
3. Freeze with `scripts/freeze_evaluation.py`, supplying the JSONL files,
   frozen normalizer-rule inventory, GEC train/dev views/manifests, and the
   normalizer-example training file.
4. Treat a `status=blocked` report as a real blocker.  The script creates no
   frozen output on missing or invalid dependencies. Successful publication
   uses an exclusive lock, unique temporary file, and no-overwrite atomic
   link; a concurrent publisher cannot replace an existing freeze.

The current repository intentionally has no authentic annotations or frozen
normalizer inventory, so the real freeze preflight is expected to fail.

Freeze validates the output and blocker-report destinations against every input
and optional leakage dependency, including existing hard-link/symlink aliases,
before parsing or writing. This keeps a blocked freeze from overwriting an
annotation or leakage source.
