# Phase 12: A/B/C prediction evaluation

Phase 12 consumes a frozen Phase 11 manifest and dependency-injected
prediction artifacts.  It does not instantiate or claim a trained normalizer
or GEC model.

## Conditions

| condition | route |
| --- | --- |
| A | raw informal -> GEC |
| B | raw informal -> normalizer -> GEC |
| C | oracle normalized-errorful -> GEC |

`src/evaluation/routing.py` accepts callables or objects with `normalize` and
`correct` methods.  Test doubles can therefore exercise the complete route
without downloading a model.  Prediction rows are written as JSONL by
`src/evaluation/artifacts.py` and contain the GEC input/output, optional
predicted tagged spans, the frozen-evaluation SHA-256, and normalizer/GEC
versions.  Before any metric is computed, the validator requires exactly one
A, B, and C row per frozen sample, rejects extras, and checks that each route's
raw/intermediate/GEC inputs match the frozen item fields.  The evaluation API
requires the expected frozen SHA and component versions explicitly.

Tagged spans are normally in `gec_input` coordinates. A/B per-tag scoring is
reported as unavailable unless an artifact explicitly uses
`predicted_edits_coordinate_space=gold_normalized`; C can be scored directly
because its GEC input is the frozen normalized-errorful text.

Text-only evaluation is supported: when `include_per_tag=false`,
`predicted_tags` and `predicted_edits` may both be omitted or null. If either
field is supplied, both must be supplied and the validator always checks that
the edits are non-overlapping, within the declared source bounds, tagged with
registered labels, and replay exactly to `gec_output`; a mismatched pair is
rejected. When `include_per_tag=true`, tagged edits are required for every
route that is scored. The C per-tag report contains all 39 registered Balarila
tags, including zero-support tags. A/B reports expose an explicit unavailable
status unless gold-normalized alignment is supplied.

## Reports

`src/evaluation/metrics.py` produces:

- token-edit precision, recall, F0.5 and exact sentence rate for normalization,
  GEC, and raw-to-final end-to-end output;
- category/source breakdowns and sentence-level output records;
- clean-control overcorrection rate;
- per-Table-2-tag metrics when predicted tags are supplied (otherwise it
  fails with an explicit missing-`predicted_tags` error);
- seeded paired bootstrap delta(B-A) with a 95% interval for P/R/F0.5; and
- exact two-sided McNemar counts and p-value on sentence-level exact success.

The evaluation report is descriptive infrastructure only.  A report made
from deterministic fixtures is not a real model result and must not be cited
as one.

Prediction artifacts are published through a unique temporary file, flushed and
validated row-by-row, then atomically linked into place without overwrite. A
partial-row validation failure removes the temporary file and leaves no final
artifact. The prediction evaluator rejects an output path that aliases the
frozen evaluation manifest or prediction artifact (including existing
hard-link and symlink aliases) before loading either input.
