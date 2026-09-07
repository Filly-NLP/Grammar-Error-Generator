# FILLY — Revised GEG, GEC Dataset, Morphology Resource, and System Evaluation Plan (Pre-Deduplicated Input)

**Project:** FILLY — Hybrid Filipino Text Normalization + Grammatical Error Correction  
**Architecture:** N-Gram + Damerau-Levenshtein text normalization → RoBERTa/GECToR grammatical error correction  
**Primary GEC source corpus:** 517,342 formal Filipino sentences stored in SQLite  
**GEC tag vocabulary:** Balarila Table 2  
**Verb morphology taxonomy:** Balarila Table 3  
**Target corpus size:** **1,000,000 total GEC pair rows across train, dev, and synthetic test**  
**Critical separation:** slang, abbreviations, shortcut spellings, phonetic spellings, and informal spelling variations are **not intentionally injected into the GEC training corpus**. They are handled by the normalization module and appear in the separate end-to-end evaluation dataset.

**Input-corpus assumption:** the 517,342-sentence SQLite corpus delivered by the Sentence-Pair-Scraper pipeline is treated as **already deduplicated**. The GEG pipeline must therefore **not perform a second destructive exact/near-deduplication pass** over this primary corpus. It may run cheap non-mutating integrity assertions to confirm the upstream contract, but duplicate removal belongs to the scraper/data-preparation pipeline.


---

# 1. Final conceptual separation

FILLY contains two different correction problems.

## 1.1 Normalization problem

Handled by the N-Gram + Damerau-Levenshtein module.

Examples:

```text
bka       -> baka
aq        -> ako
d2        -> dito
nkktawa   -> nakakatawa
grbe      -> grabe
```

Typical classes:

```text
slang
abbreviations
shortcut spelling
phonetic spelling
internet spelling variation
nonstandard contractions
```

These are **not Balarila GEC transformation tags**.

## 1.2 Grammar correction problem

Handled by RoBERTa/GECToR.

Examples:

```text
ng <-> nang
din <-> rin
incorrect verb aspect/focus
missing punctuation
incorrect casing
duplicate words
missing words
hyphen errors
space errors
siya/niya and sila/nila confusion
```

These are represented by the adopted Balarila Table 2 correction labels.

## 1.3 Why GEC training should remain free of normalization noise

The recommended design is:

```text
TRAINING
========

Normalization corpus               GEC corpus
--------------------               ----------
informal word/form                 formal clean sentence
       |                                  |
       v                                  v
standardized word/form             Balarila inverse corruption
       |                                  |
       v                                  v
N-Gram rule dictionary             erroneous -> correct pair


INFERENCE
=========

raw informal sentence
        |
        v
N-Gram + DLD normalizer
        |
        v
normalized sentence
        |
        v
RoBERTa/GECToR
        |
        v
final corrected sentence
```

Do **not** train GEC to directly learn mappings such as:

```text
bka -> baka
aq  -> ako
d2  -> dito
```

Doing so would let the GEC component perform work assigned to the normalization component and would make the thesis comparison between **normalized vs non-normalized GEC input** harder to interpret.

The GEC corpus may naturally contain borrowed English words that are legitimate in Filipino usage, but the GEG must not deliberately create netspeak or spelling-normalization errors.

---

# 2. Research alignment

## 2.1 Yu Flores & Radev (2022)

The normalization component is based on *Look Ma, Only 400 Samples!*.

Relevant design:

- nonstandard form → normalized form pairs;
- automatic character N-Gram rule extraction;
- recursive candidate generation;
- Damerau-Levenshtein ranking;
- 403 initial abbreviated/contracted forms;
- 398 retained after annotation filtering;
- 298 training examples and 100 held-out test examples;
- test examples deliberately used rules represented in training;
- cross-validation was additionally used to assess generalization.

FILLY should preserve a **frozen normalization test set** that is never added to the rule dictionary after evaluation starts.

## 2.2 Balarila (Espiritu et al., 2023)

FILLY adopts:

- Balarila Table 2 error types and transformation tags;
- Balarila Table 3 Tagalog verb-form taxonomy;
- synthetic erroneous → correct sentence pairs;
- token-level GECToR-style correction;
- two-stage fine-tuning:
  - error-filled data first;
  - mixed error-filled + error-free data afterward.

Balarila generated one artificial error per corrupted sentence. That should be FILLY's primary replication baseline.

## 2.3 GECToR

The final model predicts **correction operations**, not descriptions of the noise that was inserted.

Therefore:

```text
SOURCE = erroneous sentence
TARGET = correct sentence
TAG    = operation required to recover TARGET from SOURCE
```

Generation must work in the inverse direction of the correction tag.

---

# 3. Freeze the exact Balarila Table 2 vocabulary

The production label registry contains **39 correction tags**.

## Wrong use of `nang` vs `ng`

```text
$REPLACE_nang
$REPLACE_ng
```

## Wrong use of enclitics

```text
$REPLACE_daw
$REPLACE_din
$REPLACE_dito
$REPLACE_diyan
$REPLACE_doon
$REPLACE_raw
$REPLACE_rin
$REPLACE_roon
$REPLACE_rito
$REPLACE_riyan
```

## Wrong use of hyphens

```text
$MERGE_HYPHEN
$TRANSFORM_INSERT_HYPHEN
$TRANSFORM_SPLIT_HYPHEN
```

## Wrong use of spaces

```text
$MERGE_SPACE
$TRANSFORM_SPLIT_SPACE
```

## Duplicate words

```text
$DELETE
```

## Morphological errors

```text
$TRANSFORM_VERB_BASE
$TRANSFORM_VERB_COMPACT
$TRANSFORM_VERB_COMPOBJ
$TRANSFORM_VERB_CONTACT
$TRANSFORM_VERB_CONTOBJ
$TRANSFORM_VERB_INCACT
$TRANSFORM_VERB_INCOBJ
$TRANSFORM_VERB_RECCOMP
```

## Wrong use of punctuation

```text
$ADD_PUNC_EMARK
$ADD_PUNC_PERIOD
$ADD_PUNC_QMARK
$CHANGE_PUNC_EMARK
$CHANGE_PUNC_PERIOD
$CHANGE_PUNC_QMARK
```

## Improper casing

```text
$TRANSFORM_CASE_CAPITAL
$TRANSFORM_CASE_LOWER
```

## Missing words

```text
$APPEND_t1
```

## Wrong use of ang/ng pronouns

```text
$REPLACE_nila
$REPLACE_niya
$REPLACE_sila
$REPLACE_siya
```

Codex must create a single source of truth:

```text
resources/balarila_tags.yaml
```

No unregistered tag may enter training.

---

# 4. Balarila Table 3 verb states

The verb-form resource must represent:

```text
BASE      Base
COMPACT   Completed Aspect + Actor Focus
INCACT    Incompleted Aspect + Actor Focus
CONTACT   Contemplated Aspect + Actor Focus
IMPACT    Imperative Aspect + Actor Focus
COMPOBJ   Completed Aspect + Object Focus
INCOBJ    Incompleted Aspect + Object Focus
CONTOBJ   Contemplated Aspect + Object Focus
IMPOBJ    Imperative Aspect + Object Focus
RECCOMP   Recently Completed Aspect
```

## 4.1 Important Table 2 / Table 3 mismatch

Table 3 includes:

```text
IMPACT
IMPOBJ
```

but Table 2 does not define:

```text
$TRANSFORM_VERB_IMPACT
$TRANSFORM_VERB_IMPOBJ
```

Therefore:

- `IMPACT` and `IMPOBJ` may exist as **source/corruption states**;
- they may be used to corrupt a target whose recovery tag is one of the registered Table 2 tags;
- they must **not** be used as target correction states unless the thesis explicitly extends Table 2.

Example:

```text
TARGET:
Nagsulat siya kahapon.

target state:
COMPACT

SOURCE:
Magsulat siya kahapon.

source state:
IMPACT

correction tag:
$TRANSFORM_VERB_COMPACT
```

This is valid because the model can recover the target with a registered correction tag.

If the clean target itself requires an imperative transformation that has no registered Table 2 correction tag, skip that morphological candidate.

---

# 5. Recommended interpretation of the 1M requirement

The **1,000,000 requirement is the total GEC dataset across train + dev + synthetic test**, not 1M training pairs alone.

Recommended Balarila-compatible split:

```text
train            700,000
dev              150,000
synthetic test   150,000
------------------------
total          1,000,000
```

This follows Balarila's 70:15:15 split.

## 5.1 Recommended corpus composition

Because Balarila's complete corpus was approximately 83% error-filled and 17% error-free, the most literature-faithful interpretation of a 1M **total pair corpus** is:

```text
errorful -> correct     ~830,000
clean -> same clean     ~170,000
-------------------------------
total                  1,000,000
```

Then roughly:

```text
Dataset 1 / Stage-2 style:
~664,000 errorful rows

Dataset 2 / Stage-3 style:
~166,000 errorful rows
~170,000 clean identity rows
------------------------------
~336,000 rows
```

This approximates Balarila's design where about 80% of error-filled examples were assigned to Dataset 1 and about 20% to Dataset 2, while Dataset 2 was roughly balanced between error-filled and error-free rows.

### Configurable alternative

If your adviser defines the 1M requirement specifically as **one million corrupted/errorful pairs**, set:

```yaml
dataset:
  counting_mode: errorful_only
  target_total_pairs: 1000000
```

and construct identity rows only as derived Stage-3 training rows outside the 1M count.

**Default recommendation for the thesis:** `balarila_total` because you clarified that 1M means the whole model-development dataset.

---

# 6. Keep system-proper testing separate from the 1M GEC corpus

There are two different meanings of "test data":

## 6.1 Synthetic GEC test split

This is part of the 1M corpus.

Purpose:

```text
Does the GEC model learn the adopted Balarila transformations?
```

It contains formal Filipino + Balarila grammar errors.

It does **not** contain deliberately injected slang, abbreviations, or informal spelling variants.

## 6.2 End-to-end FILLY evaluation dataset

This is **separate** from the 1M GEC corpus.

Purpose:

```text
Does the hybrid normalization -> GEC pipeline work on informal Filipino?
Does normalization improve downstream GEC?
```

This dataset contains:

```text
slang
abbreviations
spelling variations
grammar errors
mixed informal noise
```

Do not use it in:

```text
normalizer training
GEC training
GEC development tuning
threshold tuning
```

This separation prevents test leakage and preserves the thesis experiment.

---

# 7. SQLite ingestion architecture

The 517,342 scraped sentences currently live in SQLite.

Do not rewrite the source database.

## 7.1 Phase 0 database audit

Codex must first run read-only inspection:

```sql
SELECT name, type
FROM sqlite_master
WHERE type IN ('table', 'view')
ORDER BY name;

PRAGMA table_info(<table>);
PRAGMA index_list(<table>);
```

Then record:

```text
text column
sentence/article table
article/document ID
publisher/source
publication date
URL or URL hash
language metadata
existing split metadata
```

in:

```text
docs/SQLITE_SCHEMA_AUDIT.md
```

## 7.2 Open SQLite read-only

Python example:

```python
sqlite3.connect(
    f"file:{db_path}?mode=ro",
    uri=True
)
```

Also run:

```sql
PRAGMA query_only = ON;
```

Never:

```text
UPDATE
DELETE
DROP
VACUUM
ALTER
```

against the original corpus DB.

## 7.3 Stream rather than loading 517k rows as Python objects

Recommended process:

```text
SQLite
  |
  | fetchmany(25k–50k)
  v
clean/normalize batch
  |
  v
PyArrow/Parquet staging
```

After the immutable SQLite extraction, use Parquet for GEG processing because it is better suited to:

```text
columnar scans
parallel filtering
sharded generation
large metadata fields
repeatable intermediate artifacts
```

Do **not** insert a second corpus-deduplication stage here. Treat uniqueness as an upstream invariant supplied by Sentence-Pair-Scraper.

Suggested output:

```text
data/interim/base_sentences.parquet
```

## 7.4 Normalized staging schema

```text
clean_id
text
source_corpus
publisher
source_doc_id
published_at
url_hash
sqlite_table
sqlite_rowid
metadata_json
```

Every clean sentence must remain traceable to its SQLite origin.

---

# 8. Clean-target quality gate

The target is the gold correction, so target quality is more important than raw volume.

Apply:

```text
Unicode normalization
whitespace normalization
sentence integrity checks
language-ratio filtering
boilerplate filtering
suspicious-target quarantine
upstream-uniqueness integrity assertion
```

The uniqueness assertion is **fail-fast and non-destructive**:

```text
compute stable normalized-text hash
count repeated hashes
if repeated hashes > 0:
    stop and report upstream contract violation
else:
    continue without removing/reclustering rows
```

Do not run MinHash/LSH, semantic deduplication, or any other second near-deduplication pass on the primary 517,342-sentence corpus unless the upstream scraper contract is later changed.

Do **not** silently grammar-correct uncertain targets.

Output:

```text
validated_clean.parquet
quarantined_clean.parquet
quality_report.json
```

Every quarantine needs a reason code.

---

# 9. Split clean base sentences BEFORE GEG

Because the SQLite corpus is already deduplicated upstream, the GEG pipeline does **not** need duplicate clustering before splitting.

Correct order:

```text
validated unique base corpus
      |
      v
article/document grouping when source_doc_id is available
      |
      v
70/15/15 base split
      |
      +-- train clean groups
      +-- dev clean groups
      +-- synthetic-test clean groups
```

Only afterward generate corruptions.

All variants of the same clean target must remain in the same split.

Preferred grouping key:

```text
source_doc_id
```

If `source_doc_id` is unavailable, split by stable `clean_id`.

The purpose of document grouping is **not duplicate removal**. It prevents sentences from the same news article from being distributed across train/dev/test, reducing article-context leakage even when every sentence is unique.

Required checks:

```text
[ ] every clean_id occurs once in the primary base corpus
[ ] no source_doc_id crosses train/dev/test when document IDs exist
[ ] every generated variant inherits its base sentence split
[ ] no generated pair is re-split independently
```

# 10. Eligibility census before generation

Count opportunities for **every one of the 39 correction tags**.

Output:

```text
tag
family
eligible_clean_sentences
eligible_positions
estimated_unique_candidates
split
```

Required artifact:

```text
reports/TAG_CAPACITY_REPORT.md
```

Do not allocate tag quotas before the capacity report exists.

Balarila experienced severe shortages for rare forms such as `$REPLACE_riyan`; FILLY must report shortages instead of fabricating weak examples.

---

# 11. GEG direction

Generation is the inverse of correction.

Example:

```text
TARGET:
Umalis siya kahapon.

desired model tag:
$REPLACE_siya

SOURCE created by GEG:
Umalis niya kahapon.
```

Store both:

```text
generation_operation:
replace(correct="siya", generated_wrong="niya")

correction_tag:
$REPLACE_siya
```

This prevents source/target tag inversion.

---

# 12. Error automation policy

Start with one introduced GEC error per errorful pair.

```yaml
generation:
  errors_per_errorful_pair:
    1: 1.0
```

This gives the cleanest Balarila replication.

After a successful baseline experiment, optionally test:

```yaml
generation:
  errors_per_errorful_pair:
    1: 0.85
    2: 0.15
```

Do not make multi-error generation the primary thesis dataset without first comparing it to the single-error baseline.

---

# 13. Tag-family implementation notes

## 13.1 `ng` / `nang`

Only operate on complete tokens.

Never use substring replacement.

## 13.2 Enclitics

Use explicit confusion pairs and phonological context.

Store the previous token and its final phonological/orthographic class.

## 13.3 Hyphen and spacing

Use verified Filipino constructions.

Do not randomly merge/split arbitrary strings.

## 13.4 Duplicate words

Balarila identified unrestricted random word duplication as a weakness.

Prefer likely accidental duplicate targets such as grammatical/function words and reviewed patterns.

## 13.5 Missing words

Do not randomly delete arbitrary content words.

Prefer recoverable grammatical/function words where the correction can be represented as `$APPEND_t1`.

## 13.6 Punctuation

Separate:

```text
terminal punctuation removal
period/question changes
exclamation changes
```

Audit exclamation transformations especially carefully because multiple punctuation choices may remain acceptable.

## 13.7 Casing

Avoid modifying proper names unless certainty is high.

## 13.8 `siya/niya` and `sila/nila`

Treat as medium-confidence generation because replacing a pronoun can sometimes result in a different but still grammatical sentence.

## 13.9 Morphology

Do not generate morphology by arbitrary string editing.

Use a verb paradigm resource.

---

# 14. Filipino verb morphology resources found

No public Balarila code/resource repository containing its exact verb lookup table was found in the current search. Do not invent the resource that Balarila used.

The best practical route is to build FILLY's own versioned morphology resource from multiple documented sources.

## 14.1 Primary machine-readable seed: UniMorph Tagalog

Repository:

```text
unimorph/tgl
```

Current repository properties:

- contains Tagalog **verb paradigms**;
- approximately **344 lemmas / 2,912 inflected forms** in the current published Tagalog dataset;
- source is the Center for Southeast Asian Studies at Northern Illinois University;
- warns that some forms are archaic;
- licensed **CC BY-SA 3.0**.

Why use it:

```text
machine readable
explicit morphology features
open license
research-standard resource
usable for automated conversion
```

Why not use it blindly:

```text
small
some archaic entries
feature schema differs from Balarila Table 3
not every Balarila verb state is guaranteed for every root
```

### Implementation

Create:

```text
scripts/import_unimorph_tgl.py
```

Convert UniMorph triples into an intermediate table:

```text
lemma
surface
unimorph_features
focus
aspect
balarila_state_candidate
mapping_confidence
resource_source
```

Do not automatically accept a Balarila-state mapping unless the feature bundle and surface pattern support it.

## 14.2 NIU / Table of Tagalog Verbs

The UniMorph Tagalog data traces back to the NIU *Table of Tagalog Verbs*.

It contains actor-focus and object-focus forms across completed, incompleted, and contemplated aspects.

Use it as:

```text
linguistic validation/reference
additional manually reviewed paradigms
```

Prefer redistributing the licensed UniMorph representation rather than copying an uncertainly licensed web table wholesale.

## 14.3 MAG-Tagalog — highly relevant methodology

Cheng et al., *MAG-Tagalog: A Rule-Based Tagalog Morphological Analyzer and Generator* is especially relevant because Charibeth Cheng is also an author of Balarila.

Reported resources in that work:

```text
369 affix entries
4,988 word-list entries
367 morphological rules
```

The system explicitly supports:

```text
affixation
reduplication
morphophonemic changes
verb aspect
verb focus
generation from a root
analysis back to a root
```

Reported results:

```text
generation accuracy: 68.42% on 13,937 words
analysis accuracy:   83.84% on 16,540 words
```

This is an excellent methodological reference, but a reusable public code/data repository was **not found in the current search**.

### Action item

Before reimplementing all morphology rules, contact the authors / DLSU group and ask whether the following can be shared for academic use:

```text
MAG-Tagalog rule list
root-word lexicon
affix list
generation module
Balarila morphology lookup/resource
```

Do not block implementation waiting for a reply.

## 14.4 Roxas & Mula (2008)

*A Morphological Analyzer for Filipino Verbs* is another direct Filipino verb morphology reference.

The paper describes analysis of:

```text
affixes
infinitive/base forms
verb aspect
```

and evaluated a prototype on approximately 1,050 conjugated Filipino verbs.

Use it to cross-check morphology logic and edge cases.

No clearly reusable modern code/resource package was found in the current search.

## 14.5 University of Hawai‘i Filipino grammar resources

The UH Mānoa Filipino program provides detailed descriptions of:

```text
-um- verbs
mag- verbs
ma- verbs
mang- verbs
-in object-focus verbs
i- object-focus verbs
-an forms
reduplication
completed aspect
incompleted aspect
contemplated aspect
```

Use these pages as **rule documentation and unit-test references**, not as the main data lexicon.

## 14.6 Optional experimental validator: `ablaut`

A recent morphology package exposes a work-in-progress Tagalog aspect × voice generator and reports strong agreement on a small intersection of independent lexicons.

Do **not** make it a primary thesis dependency yet.

It can be used only as:

```text
secondary automatic cross-check
candidate-generation experiment
disagreement detector
```

Any output entering the gold morphology resource still requires validation.

---

# 15. Recommended morphology-resource construction pipeline

Build:

```text
resources/tagalog_verb_paradigms.parquet
```

## Step 1 — import UniMorph

Create candidate paradigms.

## Step 2 — map features to Balarila states

Target schema:

```text
lemma
surface
balarila_state
aspect
focus
source_resource
source_features
confidence
review_status
```

## Step 3 — corpus frequency filter

Scan the 517,342-sentence corpus.

For every morphology form:

```text
count occurrences
record sentence contexts
```

Prioritize forms that genuinely occur in your own formal-news corpus.

This avoids spending effort on archaic UniMorph forms that never occur in FILLY data.

## Step 4 — build complete local paradigms

For a root to be enabled for production morphology corruption, require enough validated sibling forms.

Recommended minimum:

```text
at least 3 validated states for the same lemma
```

Prefer paradigms with:

```text
actor completed
actor incompleted
actor contemplated
object completed
object incompleted
object contemplated
```

where available.

## Step 5 — manual linguistic audit

Create a stratified review sheet.

Do not accept generated morphology merely because a string-morphology rule produced it.

## Step 6 — freeze a version

```text
tagalog_verb_paradigms_v1.parquet
morphology_manifest_v1.json
```

Store:

```text
resource versions
licenses
mapping rules
manual reviewer
date frozen
```

The final 1M generation must reference a frozen morphology-resource version.

---

# 16. Morphology generation strategy

Given a clean sentence:

```text
Tinapos niya ang gawain.
```

1. detect an exact verb surface present in the frozen paradigm resource;
2. obtain its correct Balarila target state;
3. choose a different validated sibling state;
4. replace only that verb in the source;
5. assign the correction tag corresponding to the **target state**;
6. validate the resulting pair.

Example structure:

```text
clean target form:      nagsulat
target state:           COMPACT
generated wrong form:   magsusulat
wrong/source state:     CONTACT
correction tag:         $TRANSFORM_VERB_COMPACT
```

Reject if:

```text
target state has no Table-2 tag
source == target
source form is not validated
alignment fails
the replacement alters more than the intended verb
```

---

# 17. Candidate count for the 1M corpus

Do not generate exactly 1M candidates.

Recommended:

```text
candidate buffer: 1.20M–1.30M pair candidates
final selected:    1.00M pair rows
```

Why:

```text
invalid corruptions
ambiguous morphology
generation collisions
rare-tag shortages
target-quality failures
alignment failures
quota balancing
```

Here, `generation collisions` means two corruption paths accidentally create the same erroneous→correct pair. This is **GEG-output deduplication**, not re-deduplication of the already-clean input corpus.

For a Balarila-total corpus containing ~170k identity rows, only the errorful portion needs GEG candidate over-generation.

Example:

```text
target errorful rows: ~830k
generate:             ~1.05M errorful candidates
select:               ~830k
add:                   170k clean identity rows
final:                   1M
```

---

# 18. BalitaNLP supplementation

The primary 517,342-sentence corpus is assumed deduplicated and must not be deduplicated again.

BalitaNLP is different because it is an **external supplementary corpus** entering after the upstream scraper pipeline.

Before importing BalitaNLP:

```text
exclude Bandera/Inquirer-derived rows
```

because Bandera/Inquirer overlaps your scraped sources.

Then perform **cross-corpus** duplicate checks only between:

```text
existing validated FILLY primary corpus
vs
candidate BalitaNLP additions
```

Recommended cross-corpus checks:

```text
exact normalized-text hash
article/title/URL identity when metadata exists
optional conservative near-duplicate check for syndicated/reposted stories
```

Do not re-run the primary corpus through the deduper. Only reject supplementary BalitaNLP rows that collide with material already present in FILLY or with one another.

Use BalitaNLP only after the eligibility census proves that the 517,342-sentence corpus does not have enough high-quality capacity for:

```text
overall target size
or
specific underrepresented transformation tags
```

Do not supplement only to increase the raw sentence count.

Store provenance:

```text
source_corpus = balitanlp
publisher
article_id
date
url_hash
```

# 19. Synthetic GEC test inside the 1M corpus

The synthetic test split is for **controlled GEC diagnostics**.

Recommended total:

```text
150,000 rows
```

It should preserve the same frozen source groups and tag registry.

Produce reports by:

```text
39 transformation tags
10 error families
errorful vs identity
sentence length
publisher
morphology state transition
```

Never use synthetic-test rows for:

```text
training
early stopping
tag quota tuning after final freeze
threshold optimization
```

---

# 20. Separate end-to-end FILLY evaluation dataset

This dataset tests the actual hybrid thesis.

Each example should have:

```text
raw_informal
gold_normalized_errorful
gold_final_correct
```

Example:

```text
RAW
"bka punta nya sa skul kahapon"

GOLD NORMALIZED-ERRORFUL
"baka punta niya sa school kahapon"

GOLD FINAL
"Baka pumunta siya sa school kahapon."
```

The middle representation is critical.

Normalization should fix:

```text
bka -> baka
skul -> school
```

but preserve grammar errors intended for GEC:

```text
punta
niya/siya usage
missing punctuation
```

---

# 21. End-to-end evaluation conditions

For the same test item define:

```text
R  = raw informal input
N* = manually validated normalized-but-grammar-errorful text
G  = fully corrected gold
```

Run three conditions.

## Condition A — GEC without normalization

```text
R -> GEC -> output_A
```

This is the baseline.

## Condition B — complete FILLY

```text
R -> Normalizer -> GEC -> output_B
```

This is the actual proposed system.

## Condition C — oracle-normalized diagnostic

```text
N* -> GEC -> output_C
```

This shows how well GEC could perform if normalization were perfect.

Condition C allows you to distinguish:

```text
normalizer failure
vs
GEC failure
```

and is strongly recommended even if the formal hypothesis compares only A and B.

---

# 22. End-to-end evaluation composition

Recommended manually validated primary set:

```text
1,000 informal sentences
```

Suggested stratification:

```text
300 slang-dominant
300 abbreviation-dominant
300 spelling-variation-dominant
100 mixed-noise
```

Also include a separate:

```text
200–500 clean/formal control sentences
```

to measure overcorrection / unnecessary edits.

Do not deliberately place these rows in the GEC training corpus.

---

# 23. Two types of informal test cases

## 23.1 Authentic real-world subset

Collect public informal Filipino text.

Annotate:

```text
raw
normalized-but-grammar-preserved
fully corrected
```

This measures external validity.

## 23.2 Controlled informal subset

Start from fully held-out correct Filipino.

Then:

```text
gold final
   |
   v
inverse Balarila grammar corruption
   |
   v
gold normalized-errorful
   |
   v
informal-noise injector
   |
   v
raw informal
```

The **informal-noise injector is not the GEG**.

Keep code separate:

```text
src/geg/
src/evaluation_noise/
```

This is essential to preserve module responsibilities.

---

# 24. Normalization test leakage

The Yu Flores paper's main test selected examples whose rules appeared in training, which is useful for testing rule application.

FILLY should report two normalization conditions:

```text
SEEN-RULE TEST
held-out word/context but normalization pattern represented in training

UNSEEN-PATTERN STRESS TEST
normalization pattern absent from training
```

Do not combine them into a single unexplained metric.

---

# 25. Evaluation metrics

## 25.1 Normalization module

Compare normalizer output against `N*`.

Report:

```text
Accuracy@1
Accuracy@3 / @5 if suggestions are exposed
Damerau-Levenshtein Distance
sentence exact match
normalization precision
normalization recall
normalization F0.5
normalization Error Reduction Rate
```

## 25.2 GEC module

Compare output from `N* -> GEC` against `G`.

Report:

```text
edit Precision
edit Recall
edit F0.5
per-Table-2-tag results
per-error-family results
clean-sentence false positive / overcorrection rate
```

## 25.3 End-to-end FILLY

Compare Condition A and Condition B against `G`.

Report:

```text
Precision
Recall
F0.5
Error Reduction Rate
exact corrected-sentence rate
edit-distance-to-gold
```

Break down by:

```text
slang
abbreviation
spelling variation
mixed
```

---

# 26. Statistical testing

The manuscript currently proposes ANOVA and a paired t-test.

Do not run a paired t-test directly on one aggregate F0.5 number from each condition.

Recommended:

## A vs B primary comparison

Use:

```text
paired bootstrap resampling over test sentences
```

for:

```text
Delta Precision
Delta Recall
Delta F0.5
95% confidence interval
```

Also consider:

```text
McNemar test
```

for a binary outcome such as:

```text
fully corrected vs not fully corrected
```

If a paired t-test must remain in the thesis, apply it only to a well-defined per-sentence continuous variable such as:

```text
remaining error count
edit-distance-to-gold
per-sentence error reduction
```

after checking assumptions.

If normality is poor, use:

```text
Wilcoxon signed-rank
```

For comparisons among:

```text
slang
abbreviation
spelling variation
```

use ANOVA only on a suitable sentence-level measure when assumptions are satisfied; otherwise use Kruskal-Wallis.

Category-level P/R/F0.5 can still be reported descriptively.

---

# 27. Annotation schema for end-to-end evaluation

```text
sample_id

raw_informal
gold_normalized_errorful
gold_final_correct

normalization_types
normalization_edits

grammar_tags
grammar_families

real_or_controlled
source_type

normalization_rule_seen_status

annotator_1
annotator_2
adjudication_status
notes

split = test_only
```

Annotators should verify:

```text
raw form is plausible
normalization preserves meaning
normalization does not accidentally fix designated grammar errors
final gold is grammatical
grammar edits map to adopted Balarila tags
ambiguous alternatives are documented
```

---

# 28. Repository structure

```text
filly-data/
├─ normalization/
│  ├─ train/
│  ├─ dev/
│  ├─ test_seen_rule/
│  └─ test_unseen_pattern/
│
├─ gec/
│  ├─ raw_sqlite/
│  ├─ staging/
│  │  └─ upstream_integrity_report.json
│  ├─ resources/
│  │  ├─ balarila_tags.yaml
│  │  ├─ table3_states.yaml
│  │  └─ tagalog_verb_paradigms.parquet
│  ├─ candidates/
│  ├─ train/
│  ├─ dev/
│  └─ synthetic_test/
│
├─ evaluation/
│  ├─ real_informal/
│  ├─ controlled_informal/
│  ├─ clean_control/
│  ├─ annotations/
│  └─ frozen_test/
│
└─ reports/
```

Code:

```text
src/
├─ sqlite_ingest/
├─ normalization/
├─ geg/
│  ├─ tags.py
│  ├─ eligibility.py
│  ├─ morphology.py
│  ├─ generate.py
│  ├─ validate.py
│  └─ align.py
├─ evaluation_noise/
└─ evaluation/
```

---

# 29. GEC pair schema

```text
pair_id
clean_id

source_text
target_text

is_errorful

correction_tags
error_families
num_errors

source_spans
target_spans

morphology_source_state
morphology_target_state
morphology_lemma
morphology_resource_version

split
dataset_stage

source_corpus
publisher
source_doc_id
sqlite_table
sqlite_rowid

seed
generator_version
config_hash

alignment_success
quality_flags
```

---

# 30. Codex implementation order

## Phase 0 — repository + SQLite audit

Do not generate data.

Inspect:

```text
SQLite schema
current pipeline
existing tag code
existing GEC preprocessing
normalization files
existing tests
```

Write:

```text
docs/SQLITE_SCHEMA_AUDIT.md
docs/CURRENT_PIPELINE_AUDIT.md
```

## Phase 1 — tag registry

Implement exactly 39 Table 2 tags.

Write tests that reject unknown labels.

## Phase 2 — Table 3 morphology layer

Implement the 10 Table 3 states separately from the correction-label registry.

Encode the IMPACT/IMPOBJ mismatch explicitly.

## Phase 3 — morphology resource importer

Start with UniMorph Tagalog.

Produce a mapping-review report rather than silently assuming mappings.

## Phase 4 — SQLite export + target validation

Read source DB only.

Export immutable Parquet staging.

Run a cheap, non-mutating uniqueness assertion. If the upstream corpus violates the stated uniqueness contract, stop and report it rather than silently deduplicating.

## Phase 5 — article-aware base split

Perform the 70/15/15 split before GEG.

Group by `source_doc_id` when available; otherwise use `clean_id`.

Do not run another primary-corpus deduplication pass.

## Phase 6 — 39-tag eligibility census

Do not generate the full corpus until capacity is known.

## Phase 7 — single-error GEG

Implement one tag family at a time with golden tests.

## Phase 8 — 100k pilot

Generate a pilot, manually inspect difficult tags, and fix rule problems.

## Phase 9 — full candidate build

Generate enough valid candidates for the final 1M composition.

## Phase 10 — exact 1M dataset builder

Create the configured:

```text
train
dev
synthetic test
Dataset-1/Stage-2
Dataset-2/Stage-3
```

views.

## Phase 11 — end-to-end test builder

Create a completely separate frozen informal evaluation dataset.

## Phase 12 — evaluation framework

Run Conditions A/B/C and produce module-level + end-to-end reports.

---

# 31. Codex hard constraints

Codex must follow these instructions.

1. Never write to the original SQLite corpus.
2. Never put slang/abbreviation/informal spelling injections into GEC training.
3. Never use end-to-end evaluation examples for normalizer or GEC training.
4. Never invent Balarila transformation tags.
5. Keep Table 2 labels and Table 3 verb states as separate registries.
6. Explicitly handle the IMPACT/IMPOBJ Table-3-only states.
7. Treat primary-corpus deduplication as an upstream Sentence-Pair-Scraper responsibility.
8. Do not run a second destructive exact/near-deduplication pass on the 517,342-sentence SQLite corpus.
9. Run only a non-mutating uniqueness assertion and fail/report if the upstream invariant is violated.
10. Split base sentences before GEG.
11. Keep all variants of a base target in the same split.
12. Run a 39-tag eligibility census before quota assignment.
13. Do not force a rare-tag quota beyond valid corpus capacity.
14. Every errorful pair must have an auditable inverse correction operation.
15. Every morphology pair must identify its lemma, source state, target state, and resource version.
16. Do not trust automatically generated morphology without validation.
17. Do not run the 1M build before a reviewed 100k pilot.
18. BalitaNLP supplementation must exclude Bandera/Inquirer first and undergo **cross-corpus** duplicate checking only.
19. Keep `src/geg/` separate from `src/evaluation_noise/`.
20. Freeze final dev/test data before final training/tuning.
21. Report all rejected candidates and reasons.
22. Same config + same seed + same input must reproduce the same corpus.
23. At the end of each phase, report changed files, commands, tests, counts, and unresolved assumptions.

---

# 32. Initial configuration

```yaml
project:
  name: filly
  seed: 20260905

sqlite:
  read_only: true
  fetch_size: 50000

dataset:
  target_total_pairs: 1000000
  counting_mode: balarila_total
  errorful_fraction: 0.83
  identity_fraction: 0.17

input_contract:
  primary_corpus_already_deduplicated: true
  verify_unique_text_hashes: true
  fail_on_duplicate_contract_violation: true
  perform_primary_near_dedupe: false

splits:
  train: 0.70
  dev: 0.15
  synthetic_test: 0.15
  group_by_document: true

balarila:
  enforce_table2_registry: true
  table2_tag_count: 39
  allow_unregistered_tags: false
  one_error_baseline: true

stage_views:
  dataset1_errorful_share: 0.80
  dataset2_errorful_share: 0.20

morphology:
  primary_seed: unimorph_tgl
  require_frozen_resource_version: true
  minimum_validated_states_per_lemma: 3
  allow_table3_source_states:
    - BASE
    - COMPACT
    - INCACT
    - CONTACT
    - IMPACT
    - COMPOBJ
    - INCOBJ
    - CONTOBJ
    - IMPOBJ
    - RECCOMP
  allowed_target_correction_states:
    - BASE
    - COMPACT
    - INCACT
    - CONTACT
    - COMPOBJ
    - INCOBJ
    - CONTOBJ
    - RECCOMP

balitanlp:
  enabled: false
  use_only_on_shortfall: true
  excluded_publishers:
    - bandera
    - bandera.inquirer
  cross_corpus_exact_duplicate_check: true
  cross_corpus_near_duplicate_check: optional_conservative
  rerun_primary_corpus_dedupe: false

evaluation:
  end_to_end_test_is_separate_from_1m: true
  conditions:
    - raw_to_gec
    - raw_to_normalizer_to_gec
    - oracle_normalized_to_gec
```

---

# 33. Upstream deduplication contract

The GEG implementation should explicitly document the division of responsibility:

```text
Sentence-Pair-Scraper
    -> scraping
    -> cleaning performed there
    -> duplicate removal performed there
    -> SQLite corpus contract: unique sentence rows

FILLY GEG
    -> read-only ingest
    -> target-quality validation
    -> uniqueness assertion only
    -> article-aware split
    -> eligibility census
    -> grammar error generation
```

This avoids:

```text
duplicated preprocessing work
unnecessary MinHash/LSH cost
unexpected loss of valid sentences
different deduplication thresholds between repositories
difficulty reproducing the reported 517,342 input count
```

The GEG run manifest must record:

```text
upstream_repository = Filly-NLP/Sentence-Pair-Scraper
upstream_branch_or_commit
input_sqlite_sha256
input_row_count
uniqueness_assertion_result
```

If the exact upstream commit SHA is available at production time, freeze it in the manifest.

The GEG may still deduplicate **its own generated output pairs**, because two different generation attempts can converge on an identical erroneous→correct pair. That is a separate problem from input-corpus deduplication.

---

# 34. Morphology resource recommendation

Use this priority:

```text
1. UniMorph Tagalog
   -> machine-readable seed and open licensed data

2. Corpus occurrence counts from your 517,342 news sentences
   -> determine which forms actually matter to FILLY

3. UH Mānoa Filipino grammar documentation
   -> validate aspect/focus rules and build unit tests

4. MAG-Tagalog paper
   -> methodology for bidirectional analysis/generation and morphophonemic handling

5. Roxas & Mula morphological analyzer
   -> secondary linguistic/algorithmic reference

6. Human review
   -> freeze a FILLY-specific morphology lexicon

7. Contact Balarila/MAG-Tagalog authors
   -> attempt to obtain the exact original resources
```

Do not make a newly generated morphology model the sole source of gold verb forms.

---

# 35. Most important experimental principle

> **The GEC model should learn Balarila grammar transformations from formal Filipino; the normalization model should learn informal lexical variation; only the frozen end-to-end test set should deliberately combine the two.**

This gives FILLY a clean and defensible experiment:

```text
Does GEC work on normalized Filipino?
Does GEC degrade on raw informal Filipino?
Does normalization recover that lost performance?
Where do normalization errors propagate into GEC?
```
