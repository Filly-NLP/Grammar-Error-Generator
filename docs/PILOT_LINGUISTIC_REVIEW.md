# Phase 8 pilot linguistic-review manifest

The Phase 8 pilot report only certifies automated structural checks. A human
reviewer must inspect `reports/pilot_review_sample.jsonl` before Phase 9 or
Phase 10 can run.

The expected manifest is `reports/pilot_review_manifest.json` and has schema
version `1`, formally described by
`resources/pilot_review_manifest.schema.json`:

```json
{
  "schema_version": 1,
  "status": "complete",
  "decision": "approve",
  "reviewer": "name-or-id",
  "adjudicator": "distinct-name-or-id",
  "reviewed_at": "2026-09-08T00:00:00+00:00",
  "target": {
    "pilot_report": "reports/pilot_report.json",
    "pilot_output": "data/pilot/gec_pilot_100k.parquet",
    "review_sample": "reports/pilot_review_sample.jsonl",
    "pilot_report_sha256": "...",
    "pilot_output_sha256": "...",
    "review_sample_sha256": "..."
  },
  "pilot_report_sha256": "...",
  "pilot_output_sha256": "...",
  "review_sample_sha256": "...",
  "expected_review_rows": 390,
  "reviewed_rows": 390,
  "accepted_rows": 390,
  "revised_rows": 0,
  "rejected_rows": 0,
  "row_decisions": [
    {
      "pair_id": "pilot-pair-id",
      "sample_row_sha256": "hash-of-canonical-sample-row",
      "decision": "approve",
      "notes": "specific linguistic decision"
    }
  ],
  "notes": "..."
}
```

The validator reports one of these states:

- `incomplete`: the manifest is missing/malformed, a dependency is missing, or
  not every sampled row is accounted for;
- `stale`: any pilot/report/sample hash differs from the manifest;
- `revise`: the reviewer requested corrections;
- `reject`: the reviewer rejected the pilot;
- `complete`: all sampled rows were reviewed and the decision approves them.

Only `complete` permits Phase 9 and Phase 10. The manifest is deliberately
hash-bound: if the pilot is regenerated, the prior approval becomes stale and
must be recreated.

Every sample `pair_id` must occur exactly once in `row_decisions`, with the
canonical sample-row hash, a resolved decision, and non-empty notes. An
approval requires a reviewer identity, a distinct adjudicator identity, and a
timezone-aware `reviewed_at` timestamp.

Validate it before dispatching builders:

```powershell
.venv\Scripts\python.exe scripts\validate_pilot_review.py `
  --manifest reports\pilot_review_manifest.json `
  --report reports\pilot_review_gate.json
```

The command exits `0` only for `complete`; all other states exit `2` and are
safe to use as a preflight failure.

The review should assess source/target direction, natural Filipino usage,
phonological enclitic context, acceptable punctuation/casing alternatives,
pronoun ambiguity, and whether the generated source contains only the intended
grammar error. Reviewer notes should identify any tag family that requires
revision rather than silently accepting it.
