# Synthetic-test diagnostics

After a final Phase 10 dataset is created, run:

```powershell
.venv\Scripts\python.exe scripts/report_synthetic_test.py `
  --input data\gec_1m\synthetic_test\final.parquet `
  --manifest data\gec_1m\manifest.json `
  --json reports\synthetic_test_diagnostics.json `
  --markdown reports\SYNTHETIC_TEST_DIAGNOSTICS.md
```

The reporter refuses a missing or stale final manifest and validates the
synthetic-test Parquet SHA-256 against the manifest before writing reports. It
emits all 39 registered Table 2 tags and all 10 error families, including
zero-count categories, plus errorful/identity totals, sentence-length
buckets, publisher counts, and unambiguous `SOURCE_STATE -> TARGET_STATE`
morphology transitions. The report records the final dataset configuration,
generator dependency, and builder versions for auditability.

This is a diagnostic artifact only. It must not be used to retune the frozen
synthetic-test split or quotas after final freeze.

Both report files are immutable publications: existing, aliased, hard-linked,
symlinked, or locked destinations are rejected. Each is written to a unique
temporary sibling and published under exclusive lock with cleanup on failure,
so a failed run cannot leave a partial JSON/Markdown pair.
