# FILLY remediation report

Date: 2026-09-10  
Specification: `Implementation_Plan.md` and `FILLY_GEG_CODE_REVIEW_CODEX_REMEDIATION.md`

## Outcome

The remediation is code-complete for configuration, provenance, schemas,
reviewed-resource ingestion, candidate selection, controlled-noise tooling,
diagnostics, and evaluation contracts. It is **not production-ready**: genuine
reviewed Filipino morphology/construction/punctuation resources, a frozen
normalizer inventory, a fresh 39-tag census, a fresh Phase 8 pilot, human
linguistic approval, and reviewed evaluation inputs
are still required. No linguistic rows, approvals, authentic informal examples,
or final 1M dataset were fabricated.

## Finding-by-finding work log

| Finding | Status | Before | After | Main files | Schema/artifact impact | Remaining dependency |
|---|---|---|---|---|---|---|
| P0-01 resource-backed morphology, hyphen, spacing, and punctuation generation | partially fixed / blocked | 13 morphology/hyphen/spacing tags were unavailable and no complete freeze/load workflow existed | Freeze/load tools now require explicitly approved rows, provenance, reviewer/date, and hash-bound manifests. Exact same-lemma morphology, reviewed construction, and reviewed punctuation-context generators are implemented; punctuation contexts are separate lexical patterns and only one tag-consistent terminal mark may change; absent resources fail closed. | `src/geg/morphology.py`, `src/geg/resources.py`, `src/geg/resource_freeze.py`, `src/geg/generators.py`, `scripts/freeze_morphology_resource.py`, `scripts/freeze_construction_resource.py`, `scripts/freeze_punctuation_resource.py` | Dependency hash includes morphology, construction, and punctuation resources; morphology fields are stable in every GEC artifact; resource pairs publish without overwrite and roll back on a second-file race | Operator-supplied reviewed resources and human linguistic review |
| P0-02 39-tag production coverage gate | fixed | aggregate supported capacity could make a partial implementation look complete | Coverage is reported separately from observed capacity; Phase 8/9/10 reject non-production-ready reports. Zero-capacity implemented tags remain shortages, not missing implementations. | `src/geg/generators.py`, `scripts/build_eligibility.py`, `scripts/build_pilot.py`, `scripts/build_candidates.py`, `scripts/build_dataset.py` | Capacity manifests include registry, implementation, resource, and production-readiness fields | Resources still block production readiness |
| P0-03 common A/B end-to-end baseline | fixed | category breakdowns used each condition's `gec_input`, making A/B baselines incomparable | Primary end-to-end breakdowns always score raw input to final gold; separate GEC-input diagnostics are explicitly named. Bootstrap uses the raw baseline. | `src/evaluation/metrics.py`, `tests/test_remediation_eval.py` | Evaluation report keys now distinguish `end_to_end_breakdown_*` and `gec_input_breakdown_*` | Real frozen evaluation rows and predictions |
| P1-04 authoritative config | fixed | split ratios, stage shares, and seed were partly hard-coded/descriptive | Decimal validation, effective runtime resolution, configurable grouping, aggregate-manifest requirement, and manifest recording are centralized. Invalid sums fail before output. CLI seed overrides are explicit; otherwise `project.seed` is used. | `src/geg/config.py`, `src/geg/dataset.py`, `src/geg/split.py`, `scripts/split_base.py`, `scripts/build_pilot.py`, `scripts/build_candidates.py`, `scripts/build_dataset.py`, `scripts/evaluate_predictions.py`, `config/filly.yaml` | Manifests record effective seed, fractions, grouping, buffer ratio, and aggregate requirement | None for code; evaluation inputs remain external |
| P1-05 Phase 9 truncation/buffer bias | fixed | first-valid rows filled `max_rows`, starving late/rare groups | Complete shard scans retain stable SHA-256-ranked capacity-aware reservoirs, reserve rare groups, record buffer requests, and aggregate split/tag shortfalls before Phase 10. Aggregate publication validates complete unique shard sets, file/manifest hashes, common dependencies, production readiness, canonical aggregate hash, and exact per-split capacity. Phase 10 validates the aggregate before reading rows. | `scripts/build_candidates.py`, `scripts/aggregate_candidates.py`, `scripts/build_dataset.py`, `tests/test_phase9_reporting.py` | Shard and aggregate manifests include buffer, group quotas, produced counts, shortfalls, dependency hashes, rejection telemetry, and immutable aggregate publication | Fresh post-review capacity is required |
| P1-06 CWD-dependent hashing | fixed | some callers resolved relative source paths from the process CWD | `generator_dependency_manifest/hash` anchors all paths at the repository root and binds code plus morphology, construction, punctuation, tag/state, and schema resources. | `src/geg/hashing.py`, Phase 6/8/9/10 scripts, `tests/test_remediation_core.py` | Existing artifacts lacking the new dependency key are legacy/stale and cannot unlock production | Fresh artifacts after resources/review |
| P1-07 morphology provenance schema | fixed | candidate/final records did not expose the four required morphology fields | Nullable fields are present in Candidate, pilot, candidate, final, identity, Arrow schema, validation, and manifests. | `src/geg/schema.py`, `src/geg/generators.py`, `scripts/build_pilot.py`, `scripts/build_candidates.py`, `scripts/build_dataset.py`, `src/geg/reporting.py` | Non-morphology and identity rows carry nulls; morphology rows require state, lemma, and resource version | Frozen reviewed morphology resource |
| P1-08 synthetic-test diagnostics | fixed | final builder lacked the complete dedicated diagnostics artifact | Reporter validates final-manifest/hash provenance and emits all 39 tags, all 10 families, errorful/identity, lengths, publishers, and morphology transitions. Reports use alias/hardlink/symlink-safe destinations, exclusive create-new publication, paired rollback, and lock/temp cleanup. | `src/geg/reporting.py`, `scripts/report_synthetic_test.py`, `docs/SYNTHETIC_TEST_DIAGNOSTICS.md`, `tests/test_phase9_reporting.py` | JSON/Markdown reports are downstream of a frozen Phase 10 manifest and cannot retune it; external publication winners are preserved | Final exact dataset |
| P1-09 controlled informal injector | partially fixed / blocked | `src/evaluation_noise` had schemas/templates but no controlled transformation pipeline | Deterministic, resource-driven injector preserves `G`, `N*`, `R`, replayable edits, protected grammar spans, and seen/unseen rule checks. It now requires a genuinely frozen normalizer-rule inventory with metadata and approved entries; generated rows remain pending annotation; authentic data is not synthesized. | `src/evaluation_noise/injector.py`, `scripts/freeze_noise_resource.py`, `scripts/build_controlled_evaluation.py`, `tests/test_remediation_eval.py`, `tests/test_phase11_12.py` | Canonical evaluation schema and freeze gate are enforced; per-edit rule/pattern/status evidence is hash-bound | Reviewed noise rules, frozen normalizer inventory, annotators, adjudication, and authentic sourced data |
| P1-10 evaluation field drift | fixed | `error_families` and `grammar_families` could drift; canonical fields were not enforced | `grammar_families` and `real_or_controlled` are canonical; deprecated aliases are normalized and conflicting values fail. Tag/family correspondence is validated. | `src/evaluation_noise/schema.py`, `src/evaluation_noise/template.py`, `src/evaluation_noise/__init__.py`, `src/evaluation/metrics.py` | Frozen JSONL exposes one canonical schema | Reviewed evaluation rows |
| P1-11 rejection telemetry | fixed | generators returned only supported/unavailable and hid policy rejection causes | Structured not-applicable, selected, rejected counters, reason codes, and bounded samples flow through Phase 6/8/9/10. | `src/geg/generators.py`, `src/geg/telemetry.py`, Phase 6/8/9/10 scripts, `tests/test_phase9_reporting.py` | Manifests are auditable without unbounded row-level logs | Human review of provisional linguistic policy |
| P2-12 conservative linguistic heuristics | partially fixed / provisional | broad function-word deletion/duplication and punctuation substitutions could create ambiguous pairs | Reviewed function-word subset, boundary guards, explicit unsafe rejection, provisional confidence, exact reviewed punctuation-context matching, and resource-backed punctuation substitutions are enforced. Without approved punctuation contexts, substitution capacity remains zero. | `src/geg/generators.py`, `src/geg/resource_freeze.py`, `scripts/freeze_punctuation_resource.py`, `tests/test_remediation_core.py`, `docs/REMEDIATION_CORE.md` | Generator policy is marked `provisional_pending_linguistic_review`; pilot must be re-reviewed | Filipino linguist approval and reviewed function/punctuation context resources |
| Second-pass review bypass/span/resource follow-up | fixed / blocked | Production callers could consult review before binding the current config/capacity identity; morphology operations used the clean token end for longer erroneous forms; resource paths were code-selected | Production callers now preflight current config/capacity and call `require_review_gate(production=True, expected_...)`; morphology source spans cover the generated surface including punctuation; validated config selects versioned payload/manifest paths and dependency hashing binds them; freeze CLIs accept v2 resource versions | `src/geg/review.py`, `scripts/build_candidates.py`, `scripts/build_dataset.py`, `src/geg/generators.py`, `src/geg/config.py`, `src/geg/hashing.py`, `src/geg/resource_freeze.py`, `tests/test_second_pass_slice.py` | Existing Phase 6/8/9/10 artifacts remain stale; no production output regenerated | Genuine reviewed morphology/construction/punctuation resources and fresh human pilot approval |

## Commands and evidence

The final integration run used:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q src scripts tests
$paths = Get-ChildItem resources -Filter *.json -Recurse; .\.venv\Scripts\python.exe -c "import json; from pathlib import Path; paths=list(Path('resources').rglob('*.json')); [json.loads(p.read_text(encoding='utf-8')) for p in paths]; print('parsed_json_schemas=', len(paths))"
$ErrorActionPreference='Stop'; $fail=@(); Get-ChildItem scripts -Filter *.py | Where-Object Name -ne '__init__.py' | ForEach-Object { $o=& .\.venv\Scripts\python.exe $_.FullName --help 2>&1; if($LASTEXITCODE -ne 0){$fail += "${($_.Name)}:$LASTEXITCODE"} }; if($fail.Count){$fail -join "`n"; exit 1}else{'cli_help=all_passed'}
git diff --check
if(Test-Path corpus.db){(Get-FileHash corpus.db -Algorithm SHA256).Hash.ToLower()}
```

Current test result: **160 passed**. The test suite covers the registry/state
contracts, config ratios and seed, split behavior, freeze/load rejection,
resource-backed generation, morphology provenance, review gates, hash stability
outside the repository CWD, candidate order independence, synthetic diagnostics,
evaluation schema/baselines, noise replay, and leakage protections.

Safe blocked preflights invoked `build_candidate_shard` and
`build_final_dataset` with temporary output paths. The final-output probe
returned `ReviewGateError(incomplete: review manifest does not exist)` and
confirmed `final_created=False`; the candidate probe failed closed on its
missing capacity input and confirmed `candidate_created=False`.

The read-only source database remains unchanged at SHA-256
`aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.

The final Phase 9 hardening slice also verifies that a supplied capacity
report is the exact SHA-256 artifact bound by both the pilot report and the
approved review dependency. Adversarial external-winner races for aggregate
and paired synthetic-diagnostics publication preserve the external winner
and roll back only the builder's partial publication.

## Artifact compatibility and stale status

Changing generator behavior, schemas, config resolution, aggregate requirements,
and dependency hashing
invalidates the existing Phase 6 capacity report, Phase 8 pilot/review sample,
and any downstream Phase 9/10 artifacts. The prior pilot is retained as a
historical artifact only; it cannot unlock production. Phase 9 and Phase 10
preflights create only blocked reports and no candidate/final dataset output.

## Final state

```text
CODE COMPLETE FOR RESOURCE INGESTION/FREEZING AND PIPELINE HARDENING
PRODUCTION GENERATION BLOCKED PENDING GENUINE REVIEWED RESOURCES AND HUMAN REVIEW

## Second-pass refresh (2026-09-10)

The Phase 8 pilot total is now authoritative in `phase8.pilot_total`, with
configured split-derived targets recorded in the pilot report. Review approval
uses schema v2 and binds root/target pilot hashes, generator dependency,
configuration, and capacity identities. Runtime hashing no longer includes
external absolute mapping paths, and the Phase 10 manifest records the
canonical generator dependency hash. Frozen-resource loading validates review
metadata, resource hashes, and row counts; synthetic diagnostics validate the
observed row count against the final manifest. Existing Phase 6/8/9/10
artifacts are stale and were not regenerated.

The older manuscript's broad wording that GEG may inject informal noise must
be synchronized with the refined `Implementation_Plan.md`: grammar-only GEC
training and synthetic-test data remain separate from the controlled/authentic
informal end-to-end evaluation pipeline. This is a thesis-document task, not a
reason to mix the datasets in code.
```
