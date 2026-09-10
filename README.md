# Grammar-Error-Generator

## Current remediation status (2026-09-10)

The implementation is hardened through the Phase 9–12 remediation pass, but
production generation remains intentionally blocked pending genuine reviewed
Filipino morphology/hyphen/spacing/punctuation resources, a frozen normalizer
inventory, and human pilot approval.
The repository does not fabricate linguistic rows, approvals, authentic informal
examples, or the final 1M dataset.

- Automated validation: **160 tests passed**.
- The source SQLite corpus is read-only and remains unchanged.
- Existing Phase 6/8 artifacts are historical/stale under the new dependency
  and schema contracts; regenerate them only after the reviewed resources are
  frozen.
- See [REMEDIATION_REPORT.md](REMEDIATION_REPORT.md) for the finding-by-finding
  work log and [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) for the
  fail-closed unlock checklist.
- See [docs/SYNTHETIC_TEST_DIAGNOSTICS.md](docs/SYNTHETIC_TEST_DIAGNOSTICS.md)
  for the post-Phase-10 diagnostic report.
- See [docs/SECOND_PASS_CODE_REVIEW_FIXES.md](docs/SECOND_PASS_CODE_REVIEW_FIXES.md)
  for the second-pass dependency-bound review, configured Phase 8 pilot
  targets, and artifact invalidation log.
