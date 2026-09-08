# Gold-target quality policy

Phase 4 treats the immutable `sentence_text` surface as a candidate gold
target. NFC normalization and whitespace collapsing are deterministic staging
normalizations; no grammar correction or suspicious-target rewriting is
performed. Rows that fail a gate are quarantined with one or more reason codes
and retain their original provenance in `quarantined_clean.parquet`.

The configured gates are intentionally model-free:

- `required_language` and `min_language_confidence` use the upstream
  `language` and `language_confidence` fields.
- The code-switch gate is a conservative text-level signal: it counts only
  configured English function-word markers among ASCII word tokens. A row is
  quarantined as `language_code_switch_ratio` when the high threshold is
  reached and as `language_code_switch_borderline` in the configured
  intermediate band. It is not a language model and does not reject an
  isolated borrowed word, proper name, or product/team label. Borderline rows
  are quarantined for review rather than rewritten.
- A clause-level code-switch gate catches substantial leading or trailing
  English segments that whole-sentence ratios can dilute. The segment must
  contain at least the configured number of tokens, at least two configured
  English function markers, and at least two configured English content
  signals immediately before or after a strong Filipino boundary token such
  as `sa`, `ang`, or `ng`. It emits `language_code_switch_clause`. This is an
  auditable lexical rule, not an exact-sentence exception: ordinary borrowed
  words, names, and Filipino clauses remain below the required segment
  thresholds.
- Balanced ASCII/curly quotes and `()[]{}` delimiters are checked. Apostrophes
  inside words are not treated as quotation marks.
- Sentence-integrity checks reject control characters, too-short text, leading
  closing punctuation, and trailing opening delimiters.
- Suspicious encoding checks quarantine replacement characters and configured
  mojibake markers (`U+FFFD`, `Ã`, `Â`, `â`). These are not repaired.
- Formality checks use only configured lexical markers and URL/email patterns;
  no language model or inferred grammar score is used.

Suspicious encoding checks quarantine the Unicode replacement marker and a
validated list of multi-character mojibake sequences (for example the
UTF-8-as-Windows-1252 forms of accented vowels and smart quotes). Single
characters such as `Ã`, `Â`, or `â` are not sufficient evidence and are
preserved, protecting legitimate accented names such as `José`. Sequences are
not repaired.

All thresholds and pattern lists live in `config/filly.yaml`. Disabling a gate
must be an explicit configuration change recorded in the run manifest. The
primary corpus remains read-only, and no second deduplication pass is implied
by these quality checks.
