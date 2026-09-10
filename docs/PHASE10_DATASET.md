# Phase 10 exact dataset builder

`scripts/build_dataset.py` consumes complete Phase 9 candidate shards and the
already split clean targets. It implements the configured `balarila_total`
arithmetic exactly:

```text
total       1,000,000
errorful      830,000
identity      170,000
train         700,000 (581,000 errorful + 119,000 identity)
dev           150,000 (124,500 errorful + 25,500 identity)
synthetic     150,000 (124,500 errorful + 25,500 identity)
```

The output directory contains `train/final.parquet`,
`dev/final.parquet`, and `synthetic_test/final.parquet`. Stage views are also
separate by split (`<split>/dataset1_stage2.parquet` and
`<split>/dataset2_stage3.parquet`), so no training-facing file mixes dev/test
rows. A hash manifest records all output paths and counts. The builder first
requires a complete shard set `0..n-1` with consistent input/config/generator/
review dependencies. It then streams the split input into a clean-id lookup
and validates every candidate's target text, split, source document, and
provenance fields against that current input before selection. Every selected
candidate is replay-validated, exact generated `(source_text, target_text)`
collisions are rejected, and registered tags are counted across all 39 labels.
The final seed and current Phase 9 builder version are checked against both
every shard manifest and every candidate row, preventing mixed-generation
inputs from being claimed as one reproducible corpus.

Output directories are never overwritten. The review gate runs before output
directory creation. If capacities are insufficient, the builder writes only a
failure report (when requested) and leaves the final output absent.

Phase 10 rejects candidate shards that lack or disagree on
`quality_manifest_sha256`, `split_report_sha256`, or `input_sqlite_sha256`; all
three provenance values are retained in the final manifest. The SQLite hash is
propagated from the Phase 4 quality manifest through the Phase 5 split, Phase 6
census, and Phase 9 shard manifests. Phase 10 verifies that chain from shard
metadata and never reads a hard-coded `reports/run_manifest.json`. Candidate,
split, review, config, output, blocked-report, and failure-report paths are
checked for path/symlink/hard-link aliases before reads, review-gate writes, or
final publication. Blocked/failure reports are also rejected when they are
descendants of the final output directory, preventing a failed run from
wedging its own output tree.

The synthetic-test split is part of this 1M GEC corpus. It is not the separate
end-to-end informal evaluation dataset described in the implementation plan;
phases 11–12 remain separate work.
