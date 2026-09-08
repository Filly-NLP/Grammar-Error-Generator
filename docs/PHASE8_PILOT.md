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
