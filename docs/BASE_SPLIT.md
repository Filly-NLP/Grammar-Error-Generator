# Phase 5 base split

`split_base.py` assigns validated clean targets to `train`, `dev`, and
`synthetic_test` before any grammar corruption is generated. When available,
`source_doc_id` (the upstream article ID) is the grouping key; a stable
`clean_id` fallback is used only when a document ID is absent.

Groups are processed largest-first and assigned to the currently least-filled
target ratio. Seeded SHA-256 tie breaks make the result reproducible without
using process-dependent random ordering. A group is assigned as a whole, so
no article can cross a split. This is an article-leakage control, not a second
deduplication pass.

The live artifact is `data/interim/split_clean.parquet`, with `group_key` and
`split` columns. The exact row/group counts and input configuration are in
`reports/base_split_report.json`.
