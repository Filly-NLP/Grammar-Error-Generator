# Phase 0–8 code review: issues and fixes

Date: 2026-09-08

This document records the seven findings from the comprehensive source review,
the changes made to address them, and the verification performed. The review
used [Implementation_Plan.md](../Implementation_Plan.md) and
[Project_Memory.md](../Project_Memory.md) as the project requirements and history.

The fixes are implemented and the combined suite passed **83 tests**. Production
data was unavailable in this checkout, so these results establish behavior on
test fixtures, not acceptance of a regenerated production corpus.

## 1. Input files could be overwritten by output arguments — P1

**Issue:** The schema inspector allowed its report destination to be the input
database. Although SQLite access was read-only, the later report write replaced
the database with JSON. The morphology importer similarly opened its output in
write mode without checking whether it was also the input TSV; this truncated
the source and reported zero imported rows.

**Fix:** A shared `validate_destinations()` helper resolves input and output
paths, rejects collisions, and checks existing hard-link aliases with
`samefile()`. Resolving paths also catches symlink aliases. The inspector and
importer invoke it before opening writers. Invalid destinations raise
`ValueError` rather than modifying the input.

**Files:** [artifacts.py](../src/geg/artifacts.py),
[inspect_sqlite.py](../scripts/inspect_sqlite.py), and
[import_unimorph_tgl.py](../scripts/import_unimorph_tgl.py).

**Verification:** Disposable-fixture tests assert that colliding arguments are
rejected and that original input bytes remain unchanged. Coverage includes
input/output, input/report, output/report, and existing hard-link collisions.

## 2. Reports could overwrite generated artifacts — P1

**Issue:** The exporter checked data destinations against each other and the
database, but did not check them against report destinations. An export could
return `complete` after replacing its sentence data with its own quality report.
Downstream commands also lacked complete destination checks.

**Fix:** The shared validator now checks every destination against protected
inputs and every other destination. The exporter includes quality, run, and
integrity reports. Split, census, and pilot builders include their reports,
configuration, upstream manifests, and the pilot review sample as applicable.
These checks occur before any output writer opens.

**Files:** [export_sqlite.py](../scripts/export_sqlite.py),
[split_base.py](../scripts/split_base.py),
[build_eligibility.py](../scripts/build_eligibility.py), and
[build_pilot.py](../scripts/build_pilot.py).

**Verification:** Regression tests cover artifact/report and report/report
collisions. An additional 24-case test matrix, implemented by a Luna xhigh
worker and reviewed by the root agent, covers downstream output collisions
and aliases to configuration or upstream manifests. Missing input paths help
prove that collision validation runs before data reads; no outputs are created.

## 3. Stale upstream quality decisions could acquire current hashes — P1

**Issue:** Splitting and the eligibility census recorded the currently loaded
configuration hash without checking which configuration produced their input.
After tightening quality rules, running only downstream stages could retain
previously accepted targets while labeling the resulting artifacts with the
new configuration hash. Matching pilot and census hashes did not catch this.

**Fix:** `verify_manifest()` requires a complete upstream manifest, a matching
configuration hash, and a matching input-artifact hash. The stages now enforce
the following handoffs:

| Consumer | Required provenance | Validation |
|---|---|---|
| Phase 5 split | Phase 4 run manifest | Configuration and `validated_clean` artifact hash |
| Phase 6 census | Phase 5 split report | Configuration, split artifact hash, and recorded quality-manifest provenance |
| Phase 8 pilot | Phase 6 capacity report | Existing configuration/input/generator checks plus required upstream provenance fields |

The split report records `quality_manifest_sha256`. The census records that
hash and `split_report_sha256`; both propagate into the pilot report. These
hashes record the accepted handoff; the pilot does not reopen the original
database or reapply all quality gates.

Custom locations can be supplied using `--quality-manifest` on the splitter
and `--split-report` on the census. Their defaults are
`reports/run_manifest.json` and `reports/base_split_report.json` respectively.
Missing, blocked, stale, or mismatched upstream manifests are rejected.

**Files:** [artifacts.py](../src/geg/artifacts.py),
[split_base.py](../scripts/split_base.py),
[build_eligibility.py](../scripts/build_eligibility.py), and
[build_pilot.py](../scripts/build_pilot.py).

**Verification:** A fixture exported under the original configuration is
rejected downstream after `max_characters` changes to `1`. Other tests cover
missing/blocked manifests, mismatched artifact hashes, and a successful
export-to-pilot handoff under a consistent configuration.

## 4. Enclitic context rules mishandled glide endings — P2

**Issue:** The generator classified only vowels as contexts for r-forms,
treating `w` and `y` as ordinary consonant endings. It rejected `Ikaw rin.` as
a target for `$REPLACE_rin`, yet generated it as the wrong source for target
`Ikaw din.` This affected both eligibility counts and corruption direction.

**Fix:** Context classification now recognizes vowel and `w`/`y` glide
endings. For din/rin and daw/raw, it also implements the traditional d-form
exceptions after `-ri`, `-ra`, `-raw`, and `-ray`. Accent marks are removed only
for classification; original source/target spelling is preserved. Operation
metadata records the final class and whether an exception applied.

**File:** [generators.py](../src/geg/generators.py).

**Verification:** Tests cover `Ikaw rin.`, `Okey raw.`, `Maaari din.`,
`Kapara daw.`, `Araw daw.`, and `Biray din.`, plus rejected opposite forms
under this policy. An old test incorrectly used a y-ending as a consonant
control; it now uses `Aalis rin.`.

This is the traditional convention adopted for pilot generation, as described
in the [KWF writing manual, section 8.1](https://kwf.gov.ph/wp-content/uploads/MMP_Full.pdf).
It does not establish that every alternative usage is universally
ungrammatical. Human linguistic review remains required.

## 5. The pilot could report a false capacity shortfall — P2

**Issue:** Quotas estimated split capacity using corpus-wide candidate-position
averages. Uneven distributions could overestimate a tag in one split. Once a
tag reached its quota and the overflow reserve contained 1,000 candidates,
later candidates could be skipped. The reserve could then be insufficient to
fill a deficit, even when additional valid candidates existed in the input.

**Fix:** The census now records actual `candidates_by_split` counts, and quota
allocation uses those counts directly. Counts still precede pilot structural
validation and output-pair deduplication, so rejection can reduce usable
capacity. If the bounded reserve cannot fill the requested rows, a second
deterministic scan ignores tag quotas and admits additional valid, unique pairs
until the split is full or its candidates are exhausted. Counters increase
only after structural acceptance. The report records `refill_performed`.

**Files:** [build_eligibility.py](../scripts/build_eligibility.py) and
[build_pilot.py](../scripts/build_pilot.py).

**Verification:** A fixture supplies 3,000 valid casing pairs alongside
punctuation candidates that fail structural checks. The refill reaches 3,000
requested rows without duplicate pairs. Requesting 3,500 from the same fixture
correctly reports a genuine 500-row shortfall.

## 6. Punctuation hid informal markers from the quality gate — P2

**Issue:** The configured patterns required whitespace around markers.
`Masaya ang bata lol` was quarantined, while `Masaya ang bata lol.` and
`Masaya ang bata (lol)!` were accepted as candidate gold targets.

**Fix:** Patterns now use `(?<!\w)` and `(?!\w)` boundaries. Punctuation can
surround a marker, while matches embedded inside larger words are excluded.

**File:** [filly.yaml](../config/filly.yaml).

**Verification:** Tests reject `lol`, `lol.`, `(LOL)!`, and `omg!`, while
preserving containing words such as `lola` and `Lolita`.

## 7. Source hashes depended on checkout location — P2

**Issue:** Generator hashing included absolute file paths. Moving unchanged
code to another directory or machine changed the hash and invalidated the
capacity report.

**Fix:** Multi-file hashing now sorts repository-relative filenames and hashes
those names with file contents and explicit separators. An optional root
supports equivalent hashing of relocated trees. Location and caller ordering
no longer affect the digest; content changes still do.

**File:** [hashing.py](../src/geg/hashing.py).

**Verification:** Identical files in two temporary checkout roots hash equally,
including when passed in reverse order. Changing a file changes the digest.

## Verification and remaining work

The combined test suite passed **83 tests** after integration. Python
compilation and `git diff --check` also passed, and CLI help confirmed the
new manifest arguments. Tests ran in an isolated temporary environment with
PyArrow, pytest, and PyYAML installed.

Regression coverage is in
[test_review_fixes.py](../tests/test_review_fixes.py) and
[test_destination_matrix.py](../tests/test_destination_matrix.py), alongside
the existing phase tests. Destructive-case probes used disposable fixtures.

The fixes change configuration, generator behavior, provenance requirements,
and source-hash format. Earlier production reports are not evidence that the
revised pipeline has run successfully. Once the source database is available:

1. Regenerate Phase 4 validated/quarantined data and its run manifest.
2. Regenerate Phase 5 splits using that manifest.
3. Regenerate Phase 6 capacities using the new split report.
4. Regenerate Phase 8 pilot data and its review sample using the updated generators.
5. Perform human linguistic review before Phase 9 or the full 1M build.

Do not update old report hashes to make stale artifacts appear current.
Neither production regeneration nor human linguistic acceptance was completed
as part of these fixes. See [PHASE8_PILOT.md](PHASE8_PILOT.md) for the current
pilot contract and regeneration requirements.
