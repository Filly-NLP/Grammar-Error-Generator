# Third-pass code-review fixes

Date: 2026-09-10

This pass preserves the existing fail-closed production/resource gates. It
does not create reviewed Filipino linguistic data or regenerate production
artifacts.

| Finding | Status | Fix |
|---|---|---|
| P0 global Phase 9 shard quota duplication | Fixed | `scripts/build_candidate_plan.py` measures shard-local eligible capacity before shard execution, allocates one global split/tag request with proportional largest-remainder allocation, and binds the immutable plan hash into each shard and the aggregate. |
| P0/P1 candidate row controls | Fixed | `target_rows` is the desired pre-buffer count; `max_output_rows` (with legacy `max_rows` as an alias) is an absolute output ceiling, even when the configured buffer ratio is greater than one. |
| P1 `errorful_only` contradiction | Fixed | Config validation requires 100% errorful and 0% identity fractions in that mode. |
| P1 morphology policy authority | Fixed | Freeze CLI resolves the minimum validated-state policy from effective config unless an explicit override is supplied, and records the effective config identity. |
| P1 identity provenance | Fixed | Identity rows carry the active final-build configuration hash. |
| P1 construction resource structure | Fixed | Freeze and load validate lexical preservation and exact directional delimiter relations for all five hyphen/space tags, including `pa rin -> parin` and `pinakamalaki -> pinaka malaki`. |
| P1 noise substring matching | Fixed | Noise rules declare `token`, `phrase`, or explicitly reviewed `substring`; token/phrase modes enforce boundaries. |
| P1 JSON Schema/runtime drift | Fixed | Canonical/legacy family aliases, `real_or_controlled` derivation, normalization rule/pattern ID lists, and clean-control empty-edit conditions are represented in the published schema and runtime contract. |
| P1 Phase 8 row-order bias | Fixed | Every eligible row/tag is scanned into bounded stable-ranked reservoirs; pilot output is independent of source row order and no first-seen fallback cutoff is used. |
| P2 publisher Markdown omission | Fixed | Synthetic-test Markdown now renders publisher counts and deterministic shares. |

## Validation

```text
.venv\Scripts\python.exe -m pytest -q -> 172 passed, 1 skipped
.venv\Scripts\python.exe -m compileall -q src scripts tests -> passed
git diff --check -> passed
```

The correction pass also makes the pre-shard plan a production prerequisite;
an empty local shard is still published as a schema-stable artifact so the
aggregate can verify the complete shard set. The third-pass changes stale earlier Phase 8/9/10 artifacts where selection,
configuration, schema, or resource-validation semantics changed. Production
remains blocked until genuine reviewed morphology, construction, and
punctuation resources are supplied and a fresh human linguistic review is
approved. `corpus.db` was not modified.

## Final correction addendum

Production-ready Phase 9 aggregation now requires exactly one shared,
content-hash-valid candidate plan whose `input_sha256` matches the canonical
shard input hash. Planless legacy fixtures are available only in explicit
development mode with `production_ready=false`. Shard execution also rejects
explicit CLI `target_rows` or `max_output_rows` values that disagree with the
measured plan; a plan cannot silently expand a caller's hard ceiling.

The evaluation template and published JSON Schema now include required string
`notes` metadata, with runtime/freeze validation covered by the same fixture
contract. These corrections invalidate prior Phase 9 aggregate/candidate
artifacts where the plan or schema contract differs; no production data was
regenerated.
