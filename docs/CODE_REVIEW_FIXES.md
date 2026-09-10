# Phase 0–8 code review fixes

Date: 2026-09-08

The post-Phase-8 review identified seven integrity risks and the corresponding
fixes now integrated into `main`:

1. Shared destination validation rejects input/output collisions, existing
   hard-link aliases, and symlink aliases before any writer opens.
2. Phase 4–8 reports and artifacts are mutually protected from report/report,
   input/report, and artifact/report overwrites.
3. Phase 5–8 require complete, hash-matching upstream manifests. Configuration,
   validated-input, split-report, and quality-manifest hashes are propagated
   through each handoff.
4. Enclitic generation recognizes `w`/`y` glide endings, strips accents only
   for classification, and records the traditional `-ri/-ra/-raw/-ray`
   exceptions in operation metadata.
5. Phase 6 records exact `candidates_by_split` capacity. Phase 8 uses those
   counts and performs a deterministic quota-free refill after structural
   rejection or pair collisions.
6. Formality patterns quarantine punctuation-adjacent informal markers while
   preserving containing words such as `lola` and `Lolita`.
7. Source hashes use repository-relative filenames and file contents, making
   them stable across relocated checkouts and independent of caller ordering.

The same destination and provenance contracts are enforced by Phase 9–12
builders. Existing production artifacts must be regenerated in strict order
(Phase 4 → 5 → 6 → 8) after these changes; old reports must not be relabeled
with new hashes. Human linguistic approval of the pilot remains required
before Phase 9 or the full 1M build.

## Second-pass refresh

The shared dependency identity is now the only production source/resource hash
path; Phase 6/8/9/10 callers no longer pre-resolve CWD-relative source files.
Auxiliary mapping artifacts contribute content digests without embedding an
absolute operator path. Phase 8 derives its pilot split targets from
`phase8.pilot_total` and configured split fractions. Review approval uses
schema v2 with root/target pilot and production dependency identities, and
Phase 10 records `generator_dependency_hash` explicitly. Existing artifacts
are stale under these expanded contracts.
