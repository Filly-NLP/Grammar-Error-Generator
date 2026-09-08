# Phase 8 pilot

The pilot artifact is `data/pilot/gec_pilot_100k.parquet`. It contains exactly
100,000 errorful pairs with one inverse operation per row, split 70,000 / 15,000
/ 15,000 across train, dev, and synthetic test. Every row inherits the clean
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

The report records hashes for the split input, capacity report, generator
sources, configuration, and pilot output. Automated structural review is
complete; human linguistic review is pending. The pilot is not claimed as
reviewed or production-ready.

## Review fixes and regeneration (2026-09-08)

All builder outputs, reports, and review-sample destinations must be distinct
from each other and from their inputs/configuration. Existing hard-link and
symlink aliases are rejected before writing.

Phase 5 now requires the Phase 4 run manifest (`--quality-manifest`, default
`reports/run_manifest.json`) with a matching configuration and validated-data
hash. Phase 6 requires the Phase 5 report (`--split-report`, default
`reports/base_split_report.json`) with a matching configuration, split-data
hash, and quality-manifest provenance. Their manifest hashes propagate into
the census and pilot reports. Supply these flags for custom artifact locations.

The census records `candidates_by_split` for each tag. Pilot quotas use these
counts directly. If structural rejection or pair collisions exhaust the
bounded overflow reserve, a deterministic second scan fills the remaining
slots without tag quotas. A genuine shortage still produces `status=shortfall`;
`refill_performed` records whether the second scan was needed.

Generator hashes now use repository-relative filenames and contents. Moving
a checkout does not change this hash. The new hash format, changed enclitic
rules, and changed formality configuration invalidate earlier artifacts.
Regenerate phases 4, 5, 6, and 8 in that order using the source database before
using the new pilot. Old reports must not be relabeled with new hashes.

The source database and production Parquet artifacts were unavailable during
this implementation; validation used disposable fixtures. Human linguistic
review is still required before Phase 9.
