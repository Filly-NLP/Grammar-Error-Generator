# Tag capacity report

This census was run before quota assignment. Counts are generated from
validated clean targets after the deterministic base split. Unsupported
families are recorded as zero capacity; no weak fallback is used.

- Input rows: **431840**
- Input: `D:\files\Online Classes\College\4th Year\random\Grammar-Error-Generator\data\interim\split_clean.parquet`
- Generator status: **complete**

| Tag | Family | Status | Train sentences | Dev sentences | Synthetic-test sentences | Eligible positions | Estimated unique candidates | Reason |
|---|---|---|---:|---:|---:|---:|---:|---|
| $REPLACE_nang | ng_nang | supported | 21918 | 4665 | 4685 | 32834 | 32834 |  |
| $REPLACE_ng | ng_nang | supported | 168320 | 35995 | 35996 | 378705 | 378705 |  |
| $REPLACE_daw | enclitic | supported | 10360 | 2165 | 2231 | 15415 | 15415 |  |
| $REPLACE_din | enclitic | supported | 14622 | 3227 | 3130 | 21583 | 21583 |  |
| $REPLACE_dito | enclitic | supported | 4179 | 904 | 898 | 6015 | 6015 |  |
| $REPLACE_diyan | enclitic | supported | 1072 | 226 | 218 | 1525 | 1525 |  |
| $REPLACE_doon | enclitic | supported | 967 | 193 | 218 | 1387 | 1387 |  |
| $REPLACE_raw | enclitic | supported | 10981 | 2366 | 2381 | 16384 | 16384 |  |
| $REPLACE_rin | enclitic | supported | 30129 | 6410 | 6398 | 45288 | 45288 |  |
| $REPLACE_roon | enclitic | supported | 464 | 81 | 89 | 641 | 641 |  |
| $REPLACE_rito | enclitic | supported | 2509 | 554 | 550 | 3622 | 3622 |  |
| $REPLACE_riyan | enclitic | supported | 1352 | 294 | 285 | 1933 | 1933 |  |
| $MERGE_HYPHEN | hyphen | unavailable | 0 | 0 | 0 | 0 | 0 | no reviewed Filipino construction resource is frozen |
| $TRANSFORM_INSERT_HYPHEN | hyphen | unavailable | 0 | 0 | 0 | 0 | 0 | no reviewed Filipino construction resource is frozen |
| $TRANSFORM_SPLIT_HYPHEN | hyphen | unavailable | 0 | 0 | 0 | 0 | 0 | no reviewed Filipino construction resource is frozen |
| $MERGE_SPACE | space | unavailable | 0 | 0 | 0 | 0 | 0 | no reviewed Filipino construction resource is frozen |
| $TRANSFORM_SPLIT_SPACE | space | unavailable | 0 | 0 | 0 | 0 | 0 | no reviewed Filipino construction resource is frozen |
| $DELETE | duplicate_word | supported | 290220 | 62150 | 62226 | 2952383 | 2952383 |  |
| $TRANSFORM_VERB_BASE | morphology | unavailable | 0 | 0 | 0 | 0 | 0 | no frozen reviewed verb paradigm resource is available |
| $TRANSFORM_VERB_COMPACT | morphology | unavailable | 0 | 0 | 0 | 0 | 0 | no frozen reviewed verb paradigm resource is available |
| $TRANSFORM_VERB_COMPOBJ | morphology | unavailable | 0 | 0 | 0 | 0 | 0 | no frozen reviewed verb paradigm resource is available |
| $TRANSFORM_VERB_CONTACT | morphology | unavailable | 0 | 0 | 0 | 0 | 0 | no frozen reviewed verb paradigm resource is available |
| $TRANSFORM_VERB_CONTOBJ | morphology | unavailable | 0 | 0 | 0 | 0 | 0 | no frozen reviewed verb paradigm resource is available |
| $TRANSFORM_VERB_INCACT | morphology | unavailable | 0 | 0 | 0 | 0 | 0 | no frozen reviewed verb paradigm resource is available |
| $TRANSFORM_VERB_INCOBJ | morphology | unavailable | 0 | 0 | 0 | 0 | 0 | no frozen reviewed verb paradigm resource is available |
| $TRANSFORM_VERB_RECCOMP | morphology | unavailable | 0 | 0 | 0 | 0 | 0 | no frozen reviewed verb paradigm resource is available |
| $ADD_PUNC_EMARK | punctuation | supported | 8741 | 1940 | 1798 | 12479 | 12479 |  |
| $ADD_PUNC_PERIOD | punctuation | supported | 282620 | 60502 | 60807 | 403929 | 403929 |  |
| $ADD_PUNC_QMARK | punctuation | supported | 10888 | 2326 | 2162 | 15376 | 15376 |  |
| $CHANGE_PUNC_EMARK | punctuation | supported | 8741 | 1940 | 1798 | 12479 | 12479 |  |
| $CHANGE_PUNC_PERIOD | punctuation | supported | 282620 | 60502 | 60807 | 403929 | 403929 |  |
| $CHANGE_PUNC_QMARK | punctuation | supported | 10888 | 2326 | 2162 | 15376 | 15376 |  |
| $TRANSFORM_CASE_CAPITAL | casing | supported | 268005 | 57367 | 57373 | 382745 | 382745 |  |
| $TRANSFORM_CASE_LOWER | casing | supported | 288576 | 61727 | 61866 | 2863475 | 2863475 |  |
| $APPEND_t1 | missing_word | supported | 290220 | 62150 | 62226 | 2952383 | 2952383 |  |
| $REPLACE_nila | pronoun | supported | 17151 | 3784 | 3639 | 26297 | 26297 |  |
| $REPLACE_niya | pronoun | supported | 37658 | 7946 | 8122 | 62235 | 62235 |  |
| $REPLACE_sila | pronoun | supported | 12605 | 2652 | 2722 | 19162 | 19162 |  |
| $REPLACE_siya | pronoun | supported | 30154 | 6349 | 6366 | 48098 | 48098 |  |

`estimated_unique_candidates` is the number of valid inverse operations
observed before generated-output collision deduplication. Phase 8 performs
that separate output-pair deduplication while building the pilot.
