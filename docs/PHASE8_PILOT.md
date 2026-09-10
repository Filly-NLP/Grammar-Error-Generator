# Phase 8 pilot

The pilot artifact is `data/pilot/gec_pilot_100k.parquet`. Its total is
authoritative in `config/filly.yaml` under `phase8.pilot_total`; split targets
are derived from the configured train/dev/synthetic-test fractions with
deterministic largest-remainder allocation. The default is 100,000 rows split
70,000 / 15,000 / 15,000. Every row inherits the clean
target's Phase 5 split; generated rows are never re-split independently.

The pilot builder only uses supported capacities from the Phase 6 census. It
deduplicates generated output collisions by exact `(source_text, target_text)`
pair, which is distinct from primary-corpus deduplication. It rejects source
or target surfaces that would require whitespace/NFC normalization, so no
normalization noise is injected into the GEC pilot.

`reports/pilot_review_sample.jsonl` contains five deterministic examples per
available tag and split. `reports/pilot_report.md` and
`reports/pilot_report.json` record the quotas, counts, rejection reasons, and
review state. Every row contains replay-derived `source_spans` and
`target_spans`; `alignment_success` is set only after replaying its structured
operation from source to target. `$APPEND_t1` records either an explicit
`$START`/`prepend` anchor or a previous-token anchor.

For `$APPEND_t1`, `source_token_index` is serialized as the previous target
token index (`target_token_index - 1`) when the operation uses
`anchor=previous_token`. A prepend operation uses `anchor=$START`,
`position=prepend`, and a JSON/Parquet null `source_token_index`; `$START` is
the documented sentinel rather than a fabricated source token index.

The report records `pilot_total`, `pilot_targets`, and hashes for the split
input, capacity report, generator/resource dependency, configuration, and
pilot output. The Phase 8 review manifest is schema v2 and binds pilot hashes
at both root and target, plus the current generator/config/capacity identities;
schema-v1 or missing production identities are incompatible with Phase 9/10.
Automated structural review is
complete; human linguistic review is pending. The pilot is not claimed as
reviewed or production-ready.

## Review fixes and regeneration (2026-09-08)

All builder outputs, reports, and review-sample destinations must be distinct
from each other and from their inputs/configuration. Existing hard-link and
symlink aliases are rejected before writing.

Phase 5 requires the Phase 4 run manifest (`--quality-manifest`, default
`reports/run_manifest.json`) with matching configuration and validated-data
hashes. Phase 6 requires the Phase 5 report (`--split-report`, default
`reports/base_split_report.json`) and propagates both `quality_manifest_sha256`
and `split_report_sha256` into the census and pilot reports.

The census records `candidates_by_split` for each tag. Pilot quotas use these
counts directly. A deterministic second scan fills remaining slots without tag
quotas when the bounded overflow reserve is exhausted; `refill_performed`
records whether this was needed.

Generator hashes now use repository-relative filenames and contents. The new
hash format, enclitic rules, and formality configuration invalidate earlier
artifacts. Regenerate phases 4, 5, 6, and 8 in that order before using a new
pilot. Human linguistic review remains required before Phase 9.
