# Phase 9 candidate shards

`scripts/build_candidates.py` creates deterministic Parquet shards from the
article-aware Phase 5 split. It enumerates only the supported entries in the
Phase 6 capacity report and records the inverse operation, source/target spans,
source metadata, hashes, and the review-manifest dependency.

The command is review-gated and refuses to create output while the Phase 8
pilot review is missing, incomplete, stale, marked for revision, or rejected.
It also refuses to overwrite an existing shard or manifest.

`--max-rows` is mandatory for production: every shard has an explicit finite
bound. The assigned shard is scanned completely; candidates are retained in
bounded per-split/per-tag reservoirs ranked by a stable SHA-256 digest. This
means reversing Parquet row order cannot change the selected set, while rare
tags receive capacity-aware slots before common tags consume the bound. Exact
output-pair collisions are checked after ranking and counted separately.

Production shards require a current `production_ready=true` Phase 6/8 chain
and schema-v2 review identity. Development-only legacy fixtures are not
eligible to unlock Phase 9. Existing shards from before the second-pass
dependency/review changes are stale.

Both minimal/malformed and non-production configurations are rejected by
default. Fixture callers must pass `--allow-development` (or the API
`allow_development=True`); such shards are explicitly non-production.

When `phase9.candidate_buffer_ratio` (or the legacy
`dataset.candidate_buffer_ratio`) is configured, the requested bound is
multiplied by that ratio and recorded as `buffer_rows`; the default root
configuration uses `1.25`. A shard manifest records per-group requests and
shortfalls, selected counts, and bounded rejection samples. Aggregate shards
with `scripts/aggregate_candidates.py` before Phase 10 to obtain the explicit
capacity-adequacy gate. The aggregate validates that every shard index in the
declared set exists exactly once, each shard file and sibling manifest hash
matches, all required Phase 4/5/review/config/resource dependencies agree,
and every shard is marked `production_ready=true`. Its canonical payload hash
is bound as `aggregate_sha256`; Phase 10 recomputes that hash and rejects
stale, incomplete, or mismatched aggregates before reading candidate rows.

The shard is published through a unique temporary file and atomic rename under
an exclusive lock; failed runs remove temporary files and locks.

Example after linguistic approval:

```powershell
for ($i = 0; $i -lt 16; $i++) {
  .venv\Scripts\python.exe scripts\build_candidates.py `
    --input data\interim\split_clean.parquet `
    --capacity-report reports\tag_capacity_report.json `
    --output ("data\candidates\candidates_{0:D5}-of-00016.parquet" -f $i) `
    --shard-index $i --shard-count 16 --max-rows 85000
}
```

The bounded `--max-rows` value is intentional. Candidate over-generation is a
buffer for Phase 10 rejection/collision/shortfall handling; it is not itself a
claim that 1M rows have been produced. Each shard has a sibling
`.manifest.json` containing the input, generator, configuration, review, and
output hashes, a complete 39-tag status/count map, and its exact shard index.
Every shard manifest and every candidate row also records the generation seed
and candidate-builder version; Phase 10 rejects mixed seeds/versions or rows
whose config hash disagrees with the final build.

No Phase 9 command writes to `corpus.db`, performs primary-corpus
deduplication, or injects normalization noise.

Each shard manifest must also carry the Phase 4 `quality_manifest_sha256`,
Phase 5 `split_report_sha256`, and original SQLite `input_sqlite_sha256`, all
propagated by the Phase 6 capacity report. Phase 9 refuses capacity reports
missing any of these fields. Phase 10 requires every shard to agree on the
SQLite hash, so a relocated/custom report chain cannot silently mix a different
source database. All input, dependency, output,
manifest, review, and blocked-report destinations are checked for path,
symlink, and hard-link aliases before the review gate or any writer runs.

Generation reports distinguish ordinary `not_applicable` sentence/tag misses
from constructed-candidate rejections such as alignment failures, resource
problems, collisions, and quota/buffer exclusions. Counters and a bounded
sample are propagated through Phases 6, 8, 9, and 10.
