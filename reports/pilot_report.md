# Phase 8 pilot report

The pilot uses one conservative inverse corruption per errorful pair.
Generated output pairs are deduplicated by exact `(source_text,
target_text)` collision only; the validated primary input is never
deduplicated or reclustered here.

- Status: **complete**
- Requested rows: **100000**
- Produced rows: **100000**
- Shortfall: **0**
- Collision rejections: **8**
- Automated structural review: **complete**
- Human linguistic review: **pending**

## Split counts

| Split | Requested | Produced |
|---|---:|---:|
| train | 70000 | 70000 |
| dev | 15000 | 15000 |
| synthetic_test | 15000 | 15000 |

## Review state

`reports/pilot_review_sample.jsonl` is a stratified sample by split,
error family, and registered tag. Structural checks are complete, but
the sample still requires human linguistic review. This report does not
claim the pilot is linguistically reviewed or production-ready.
