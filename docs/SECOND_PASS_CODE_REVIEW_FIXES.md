# Second-pass code-review fixes

Date: 2026-09-10

This pass preserves the fail-closed pipeline and marks the existing Phase
6/8/9/10 chain stale. No production corpus was regenerated.

| Finding | Status | Implementation | Validation / impact |
|---|---|---|---|
| P0-A stale review approval | Fixed for schema v2 | Review manifests now require schema v2 and bind pilot hashes at both root and target. Production approvals additionally bind the current generator dependency, config, and capacity-report identities; explicit expected identities are accepted by the gate. Schema-v1 or missing identities are incompatible with production. | `src/geg/review.py`, `resources/pilot_review_manifest.schema.json`; old approvals are stale and require a fresh pilot/review. |
| P0-B/C partial tag readiness | Preserved fail-closed | Phase 8/9/10 production paths require an explicit `production_ready=true` capacity/shard state. Development fixtures without a project config retain only an isolated legacy compatibility path and cannot unlock production. | No production output was written. |
| P1-A authoritative pilot configuration | Fixed | `phase8.pilot_total` is validated and pilot split targets are derived from the resolved configured fractions using largest-remainder allocation. Reports record `pilot_total` and `pilot_targets`; the old map remains only as an explicit test seam. | `src/geg/config.py`, `scripts/build_pilot.py`, `config/filly.yaml`; prior pilot is stale. |
| P1-B CWD-independent identity | Fixed | Runtime callers no longer pre-resolve CWD-relative generator files. Auxiliary mapping artifacts contribute content digests without absolute local paths. A root-anchored legacy digest is isolated to non-production fixtures. | `src/geg/hashing.py`, Phase 8/9/10 callers; dependency hash changes, invalidating downstream artifacts. |
| P1-C order-independent candidate selection | Preserved and covered | Phase 9 scans the complete assigned shard and uses stable rank/reservoir selection by split/tag. | Reversed logical Parquet order produces the same selected set. |
| P1-D/E morphology resource path | Strengthened / blocked | Frozen-resource loading now validates provenance metadata, review timestamp, approval flag, resource hash, and row count. Freeze output stores stable auxiliary-resource identities. Morphology remains blocked until genuine reviewed paradigms are supplied. | `src/geg/resource_freeze.py`; no synthetic approvals or rows were created. |
| P1-F synthetic diagnostics | Fixed | Diagnostics now compare the observed synthetic-test row count with the final manifest split count before publication. | `src/geg/reporting.py`; stale/mismatched artifacts are rejected. |
| P2 provisional linguistic contexts | Clarified | The deletion/duplication function-word set is named `PROVISIONAL_FUNCTION_CONTEXTS`; boundary guards and unsafe rejection remain active pending Filipino linguistic review. | `src/geg/generators.py`; no claim of linguistic approval is made. |
| Review bypass and source-span hardening | Fixed / blocked | Production Phase 9/10 now load the current validated config and capacity identity before calling an explicitly production-enabled review gate. Morphology replacement operations use the generated erroneous span length, including punctuation suffixes, so different-length forms replay exactly. | `src/geg/review.py`, `scripts/build_candidates.py`, `scripts/build_dataset.py`, `src/geg/generators.py`; crafted legacy approvals produce no output. |
| Config-selected frozen resources | Fixed / blocked | Morphology, construction, and punctuation payload/manifest paths are selected from validated repository-relative config, included in the dependency hash, and can point to a v2 freeze without code edits. Freeze CLIs accept explicit resource versions; no mutable “latest” pointer is used. | `src/geg/config.py`, `src/geg/hashing.py`, `src/geg/morphology.py`, `src/geg/resources.py`, `src/geg/resource_freeze.py`; genuine reviewed rows are still absent. |
| Explicit development override | Fixed | Phase 9/10 reject missing, minimal, or malformed configs by default. Fixture mode is explicit through `allow_development=True` / `--allow-development`; development manifests cannot claim production readiness. | `scripts/build_candidates.py`, `scripts/build_dataset.py`; regression coverage added. |
| Reversed-Parquet/no-output regressions | Fixed | A real Phase 9 build over forward and reversed logical Parquet inputs produces identical pair IDs and preserves a late rare tag. Crafted schema-v2 approvals missing production identities are rejected by both downstream builders without output. | `tests/test_second_pass_slice.py`; no production artifacts generated. |
| Documentation synchronization | In progress | This report, readiness notes, Phase 8/9/10 references, README, and Project Memory must retain the refined separation between grammar-only GEC data and separate informal evaluation. | Manuscript chapter synchronization remains an external thesis task. |

## Artifact invalidation

The review schema, pilot target resolution, resource loader, and dependency
identity changed. Existing capacity reports, pilots, review manifests,
candidate shards, aggregates, and final datasets must be treated as stale and
must not be reused for production. The next unlock sequence is a fresh Phase 6
census, a fresh Phase 8 pilot, new human review, then Phase 9/10.

## Remaining blockers

Genuine reviewed morphology paradigms, Filipino construction resources, and
human pilot approval remain required. Authentic informal evaluation data,
normalizer-rule inventory, annotations, and model predictions remain separate
external inputs.
