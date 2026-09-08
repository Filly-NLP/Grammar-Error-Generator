# Tag capacity report

This census was run before quota assignment. Counts are generated from
validated clean targets after the deterministic base split. Unsupported
families are recorded as zero capacity; no weak fallback is used.

- Input rows: **432078**
- Input: `D:\files\Online Classes\College\4th Year\random\Grammar-Error-Generator\data\interim\split_clean.parquet`
- Generator status: **complete**

| Tag | Family | Status | Train sentences | Dev sentences | Synthetic-test sentences | Eligible positions | Estimated unique candidates | Reason |
|---|---|---|---:|---:|---:|---:|---:|---|
| $REPLACE_nang | ng_nang | supported | 21665 | 4918 | 4701 | 32850 | 32850 |  |
| $REPLACE_ng | ng_nang | supported | 168364 | 35941 | 36094 | 378838 | 378838 |  |
| $REPLACE_daw | enclitic | supported | 10663 | 2292 | 2360 | 16027 | 16027 |  |
| $REPLACE_din | enclitic | supported | 15696 | 3302 | 3394 | 23077 | 23077 |  |
| $REPLACE_dito | enclitic | supported | 4332 | 947 | 931 | 6245 | 6245 |  |
| $REPLACE_diyan | enclitic | supported | 1122 | 251 | 240 | 1623 | 1623 |  |
| $REPLACE_doon | enclitic | supported | 1072 | 229 | 224 | 1541 | 1541 |  |
| $REPLACE_raw | enclitic | supported | 11062 | 2478 | 2358 | 16569 | 16569 |  |
| $REPLACE_rin | enclitic | supported | 29995 | 6329 | 6423 | 45070 | 45070 |  |
| $REPLACE_roon | enclitic | supported | 422 | 99 | 107 | 635 | 635 |  |
| $REPLACE_rito | enclitic | supported | 2505 | 539 | 520 | 3573 | 3573 |  |
| $REPLACE_riyan | enclitic | supported | 1342 | 265 | 293 | 1902 | 1902 |  |
| $MERGE_HYPHEN | hyphen | unavailable | 0 | 0 | 0 | 0 | 0 | no reviewed Filipino construction resource is frozen |
| $TRANSFORM_INSERT_HYPHEN | hyphen | unavailable | 0 | 0 | 0 | 0 | 0 | no reviewed Filipino construction resource is frozen |
| $TRANSFORM_SPLIT_HYPHEN | hyphen | unavailable | 0 | 0 | 0 | 0 | 0 | no reviewed Filipino construction resource is frozen |
| $MERGE_SPACE | space | unavailable | 0 | 0 | 0 | 0 | 0 | no reviewed Filipino construction resource is frozen |
| $TRANSFORM_SPLIT_SPACE | space | unavailable | 0 | 0 | 0 | 0 | 0 | no reviewed Filipino construction resource is frozen |
| $DELETE | duplicate_word | supported | 290284 | 62243 | 62278 | 2953343 | 2953343 |  |
| $TRANSFORM_VERB_BASE | morphology | unavailable | 0 | 0 | 0 | 0 | 0 | no frozen reviewed verb paradigm resource is available |
| $TRANSFORM_VERB_COMPACT | morphology | unavailable | 0 | 0 | 0 | 0 | 0 | no frozen reviewed verb paradigm resource is available |
| $TRANSFORM_VERB_COMPOBJ | morphology | unavailable | 0 | 0 | 0 | 0 | 0 | no frozen reviewed verb paradigm resource is available |
| $TRANSFORM_VERB_CONTACT | morphology | unavailable | 0 | 0 | 0 | 0 | 0 | no frozen reviewed verb paradigm resource is available |
| $TRANSFORM_VERB_CONTOBJ | morphology | unavailable | 0 | 0 | 0 | 0 | 0 | no frozen reviewed verb paradigm resource is available |
| $TRANSFORM_VERB_INCACT | morphology | unavailable | 0 | 0 | 0 | 0 | 0 | no frozen reviewed verb paradigm resource is available |
| $TRANSFORM_VERB_INCOBJ | morphology | unavailable | 0 | 0 | 0 | 0 | 0 | no frozen reviewed verb paradigm resource is available |
| $TRANSFORM_VERB_RECCOMP | morphology | unavailable | 0 | 0 | 0 | 0 | 0 | no frozen reviewed verb paradigm resource is available |
| $ADD_PUNC_EMARK | punctuation | supported | 8925 | 1808 | 1841 | 12574 | 12574 |  |
| $ADD_PUNC_PERIOD | punctuation | supported | 282662 | 60631 | 60762 | 404055 | 404055 |  |
| $ADD_PUNC_QMARK | punctuation | supported | 10825 | 2363 | 2203 | 15391 | 15391 |  |
| $CHANGE_PUNC_EMARK | punctuation | supported | 8925 | 1808 | 1841 | 12574 | 12574 |  |
| $CHANGE_PUNC_PERIOD | punctuation | supported | 282662 | 60631 | 60762 | 404055 | 404055 |  |
| $CHANGE_PUNC_QMARK | punctuation | supported | 10825 | 2363 | 2203 | 15391 | 15391 |  |
| $TRANSFORM_CASE_CAPITAL | casing | supported | 268042 | 57438 | 57468 | 382948 | 382948 |  |
| $TRANSFORM_CASE_LOWER | casing | supported | 288540 | 61888 | 61944 | 2864399 | 2864399 |  |
| $APPEND_t1 | missing_word | supported | 290284 | 62243 | 62278 | 2953343 | 2953343 |  |
| $REPLACE_nila | pronoun | supported | 17120 | 3783 | 3683 | 26309 | 26309 |  |
| $REPLACE_niya | pronoun | supported | 37575 | 8096 | 8067 | 62248 | 62248 |  |
| $REPLACE_sila | pronoun | supported | 12535 | 2747 | 2702 | 19167 | 19167 |  |
| $REPLACE_siya | pronoun | supported | 30026 | 6490 | 6363 | 48108 | 48108 |  |

`estimated_unique_candidates` is the number of valid inverse operations
observed before generated-output collision deduplication. Phase 8 performs
that separate output-pair deduplication while building the pilot.
