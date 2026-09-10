# FILLY production-readiness checklist

As of 2026-09-10, the repository is **not production-ready**. The checklist is
intentionally fail-closed and distinguishes implementation coverage from actual
reviewed linguistic-resource readiness.

| Gate | Status | Evidence / blocker |
|---|---:|---|
| Exactly 39 Table 2 tags registered | PASS | `resources/balarila_tags.yaml`, registry tests |
| Exactly 10 Table 3 states registered | PASS | `resources/table3_states.yaml`, state tests |
| Unknown tags rejected | PASS | Registry and candidate-validation tests |
| All 39 tags have code paths | PASS | `production_coverage()` reports implementation coverage separately |
| All 39 tags have production-ready reviewed resources | BLOCKED | Morphology, hyphen, spacing, and punctuation context resources are absent; punctuation substitutions fail closed |
| `IMPACT`/`IMPOBJ` source-only constraint | PASS | Morphology freeze/generation validation |
| Primary SQLite read-only / no second dedupe | PASS | Phase 4 code and unchanged source hash |
| Config seed/fractions/grouping authoritative | PASS | `resolve_runtime_config()` and regression tests |
| CWD-independent dependency hash | PASS | Canonical repository-root manifest and regression test; active configured payload/manifest paths are hash-bound |
| Stable morphology columns end-to-end | PASS | Arrow schema and row validation |
| Reviewed morphology resource frozen | BLOCKED | No genuine reviewed paradigms, reviewer, date, or license metadata supplied |
| Reviewed hyphen/spacing construction resource frozen | BLOCKED | No genuine approved construction rows supplied |
| Reviewed punctuation-context resource frozen | BLOCKED | No genuine approved punctuation-context rows supplied |
| Fresh 39-tag Phase 6 census | BLOCKED | Existing census is stale after remediation dependency changes |
| Fresh 39-tag-aware Phase 8 pilot | BLOCKED | Existing pilot is historical/stale and lacks new resource/review dependencies |
| Human Filipino linguistic pilot approval | BLOCKED | No signed/hash-bound review manifest supplied |
| Phase 9 candidate buffer/capacity adequate | BLOCKED | Cannot run before the fresh approved Phase 8 gate and census |
| Phase 10 exact 1,000,000 rows permitted | BLOCKED | Upstream production gates and candidate capacity are not satisfied |
| Phase 9 aggregate manifest required and validated | PASS (gate) | Root config requires it; no production aggregate exists to validate yet |
| Synthetic-test diagnostics available | CODE READY | Reporter exists; requires a final Phase 10 artifact |
| Controlled informal-noise injector available | CODE READY | Resource-driven injector exists; output is pending annotation |
| Authentic informal evaluation set frozen | BLOCKED | Must be sourced and manually annotated; must not be fabricated |
| Normalizer training rule inventory frozen | BLOCKED | Required for seen/unseen-pattern evaluation |
| A/B/C prediction evaluation runnable | CODE READY | Requires frozen evaluation rows and real model predictions |
| Full automated test suite | PASS | `160 passed` |

## Latest hardening slice

- Production Phase 9/10 now validate the current full config and capacity
  identity before invoking the explicit production review gate. Schema-v2
  approvals with missing or stale identities cannot create candidate/final
  outputs.
- Morphology operations now record the generated erroneous span length, so
  same-lemma replacements with different lengths and token punctuation replay
  exactly.
- Frozen resource payloads and manifests are selected by validated config and
  may use a newly versioned freeze without changing generator code. The
  morphology, construction, punctuation, and human-review blockers remain
  genuine and no resource rows or pilot approvals were fabricated.
- Minimal or malformed configs are rejected by Phase 9/10 unless the caller
  explicitly supplies `allow_development=True` or `--allow-development`; dev
  outputs are never labeled production-ready.

## Second-pass dependency refresh

- Phase 8 targets are controlled by `phase8.pilot_total` and resolved split
  fractions; reports record the effective targets.
- The review manifest is schema v2. It must bind pilot hashes at root and
  target plus the current generator dependency, config, and capacity hashes.
  Schema-v1 and missing production identities cannot unlock Phase 9/10.
- The Phase 10 manifest records `generator_dependency_hash` explicitly.
- Existing Phase 6/8/9/10 artifacts are stale after these identity and schema
  changes. No production regeneration was performed.
- The thesis manuscript still needs wording synchronization with the refined
  grammar-only GEC versus separate informal-evaluation architecture.

## Unlock sequence

1. Supply and independently review the morphology, Filipino hyphen/spacing,
   and punctuation-context resources; freeze them with explicit provenance,
   reviewer, date, and hashes.
2. Regenerate Phase 6 from the current validated split and verify all 39 tag
   implementation/resource fields.
3. Build a new Phase 8 pilot, conduct human Filipino linguistic review, and
   create a hash-bound approval manifest.
4. Generate and aggregate Phase 9 shards. Confirm per-split/per-tag candidate
   capacity and buffer shortfalls are zero for the requested final quotas.
5. Build the exact 1M GEC dataset, then emit synthetic-test diagnostics.
6. Supply reviewed normalizer rules and real/controlled evaluation annotations;
   freeze the separate end-to-end dataset before evaluating model predictions.

No step should bypass a missing resource or human-review gate.
