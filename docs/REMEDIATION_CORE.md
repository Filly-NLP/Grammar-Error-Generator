# Remediation core status

This document records the core remediation slice completed on 2026-09-10.

| Area | Status | Evidence |
|---|---|---|
| Decimal config validation | fixed | `src/geg/config.py`, `src/geg/dataset.py`, `scripts/split_base.py` |
| Config seed/split/group behavior | fixed | Phase 5/9/10 callers resolve effective values and record them |
| CWD-independent dependency hash | fixed | `src/geg/hashing.py` |
| Stable GEC morphology columns | fixed | `src/geg/schema.py`, pilot/candidate/final row builders |
| Morphology freeze/load | code complete, resource blocked | `src/geg/resource_freeze.py`, `scripts/freeze_morphology_resource.py` |
| Hyphen/spacing freeze/load | code complete, resource blocked | `scripts/freeze_construction_resource.py` |
| Punctuation-context freeze/load | code complete, resource blocked | `scripts/freeze_punctuation_resource.py`; context is stored separately and only the reviewed terminal mark may change |
| Resource-backed generators | code complete, resource blocked | exact approved entries only; absent resources fail closed |
| 39-tag implementation coverage | fixed | `production_coverage()` and Phase 6 coverage fields |
| Rejection telemetry | fixed | structured `not_applicable` and rejection counters |
| Conservative heuristic policy | fixed/provisional | reviewed function-word subset and provisional confidence |
| Resource publication safety | fixed | exclusive hard-link publication; no overwrite; pair rollback if manifest publication loses a race |
| Morphology lookup | fixed | tokenization plus exact `morphology_by_surface` lookup, then same-lemma sibling filtering; no target-state scan per sentence |

## Validation

The initial core slice passed `.venv\\Scripts\\python.exe -m pytest -q` with
**148 passed**; subsequent reviewer hardening brings the current full-suite
result to **160 passed**.

`compileall` and `git diff --check` passed. The source SQLite database was not
opened for writing. No new pilot, candidate shard, or final dataset was built.

## Remaining blockers

Production remains blocked until genuine reviewed morphology paradigms and
reviewed Filipino hyphen/spacing construction rows are supplied and frozen,
followed by a fresh 39-tag Phase 6 census and a new Phase 8 pilot with human
linguistic approval. Existing Phase 6/8/9/10 artifacts are stale under the new
dependency contract and must not be reused.
