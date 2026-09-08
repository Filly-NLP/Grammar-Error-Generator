"""Read-only SQLite iteration and clean-target validation."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping


WHITESPACE = re.compile(r"\s+")

DEFAULT_QUALITY_RULES: dict[str, Any] = {
    "unicode_normalization": "NFC",
    "collapse_whitespace": True,
    "reject_empty": True,
    "reject_nul": True,
    "require_letter": True,
    "max_characters": 2_000,
    "min_alphabetic_ratio": 0.20,
    "max_repeated_punctuation": 4,
    "boilerplate_patterns": ["^(read more|advertisement)$"],
    "reject_upstream_duplicate_marker": True,
    "required_language": None,
    "min_language_confidence": None,
    "check_language_code_switch_ratio": True,
    "language_code_switch_min_tokens": 8,
    "language_code_switch_min_markers": 4,
    "language_code_switch_borderline_ratio": 0.50,
    "language_code_switch_max_marker_ratio": 0.75,
    "language_code_switch_clause_min_tokens": 4,
    "language_code_switch_clause_min_markers": 2,
    "language_code_switch_clause_min_content": 2,
    "language_code_switch_boundary_tokens": [
        "ang", "ng", "mga", "sa", "para", "kay", "ni", "si", "at",
        "na", "ay", "dahil", "kung", "nang", "upang", "ito", "iyon",
    ],
    "language_code_switch_content_words": [
        "act", "announced", "change", "changes", "city", "climate",
        "country", "government", "hold", "local", "new", "people",
        "plan", "policy", "responsible", "team", "teams", "them",
    ],
    "language_code_switch_marker_words": [
        "the", "and", "of", "to", "in", "for", "with", "on", "from",
        "is", "are", "was", "were", "this", "that", "it", "as", "at",
        "by", "be", "have", "has", "had", "will", "can", "you", "we",
        "they", "he", "she", "a", "an",
    ],
    "check_balanced_delimiters": True,
    "check_sentence_integrity": True,
    "sentence_integrity_min_tokens": 1,
    "reject_suspicious_encoding": True,
    # U+FFFD is the Unicode replacement marker. Other markers are only
    # validated multi-character mojibake sequences; single characters such
    # as Ã, Â, and â are not enough to quarantine a target by themselves.
    "suspicious_encoding_patterns": [
        "\uFFFD", "\u00EF\u00BF\u00BD", "\u00C3\u00A9", "\u00C3\u00A1",
        "\u00C3\u00AD", "\u00C3\u00B3", "\u00C3\u00BA", "\u00C3\u00B1",
        "\u00C3\u00BC", "\u00E2\u20AC\u2122", "\u00E2\u20AC\u0153",
        "\u00E2\u20AC\u009D", "\u00E2\u20AC\u2013", "\u00E2\u20AC\u2014",
        "\u00E2\u20AC\u00A6",
    ],
    "check_formality": True,
    "formality_patterns": [],
    "reject_urls_and_email": True,
}

CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
URL_OR_EMAIL = re.compile(r"(?:https?://|www\.|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})", re.IGNORECASE)
ASCII_WORD = re.compile(r"[A-Za-z]+")
OPEN_BRACKETS = "([{"
CLOSE_BRACKETS = ")]}"


def _balanced_delimiters(text: str) -> tuple[str, ...]:
    """Check paired quotes/brackets without treating apostrophes as quotes."""

    reasons: list[str] = []
    bracket_stack: list[str] = []
    for character in text:
        if character in OPEN_BRACKETS:
            bracket_stack.append(character)
        elif character in CLOSE_BRACKETS:
            if not bracket_stack or OPEN_BRACKETS[CLOSE_BRACKETS.index(character)] != bracket_stack[-1]:
                reasons.append("unbalanced_bracket")
                bracket_stack.clear()
                break
            bracket_stack.pop()
    if bracket_stack:
        reasons.append("unbalanced_bracket")
    if text.count('"') % 2:
        reasons.append("unbalanced_quote")
    # U+2018/U+2019 are commonly apostrophes in Filipino contractions; only
    # paired double quotation marks participate in this conservative gate.
    curly_open = text.count("“")
    curly_close = text.count("”")
    if curly_open != curly_close:
        reasons.append("unbalanced_quote")
    return tuple(dict.fromkeys(reasons))


def _language_code_switch_reasons(
    text: str,
    rules: Mapping[str, Any],
) -> tuple[str, ...]:
    """Apply the model-free, conservative English-marker ratio gate.

    This does not identify language. It counts configured English function-word
    markers among ASCII word tokens, so a few borrowed terms or proper names
    remain acceptable. Only a sufficiently long sentence dominated by those
    markers is quarantined; borderline cases are not rewritten.
    """

    if not rules.get("check_language_code_switch_ratio", False):
        return ()
    words = [word.lower() for word in ASCII_WORD.findall(text)]
    if len(words) < int(rules.get("language_code_switch_min_tokens", 8)):
        return ()
    marker_words = {str(word).lower() for word in rules.get("language_code_switch_marker_words", ())}
    marker_count = sum(word in marker_words for word in words)
    ratio = marker_count / len(words)
    reasons: list[str] = []
    if marker_count >= int(rules.get("language_code_switch_min_markers", 4)):
        if ratio >= float(rules.get("language_code_switch_max_marker_ratio", 0.75)):
            reasons.append("language_code_switch_ratio")
        elif ratio >= float(rules.get("language_code_switch_borderline_ratio", 0.50)):
            reasons.append("language_code_switch_borderline")

    # A clause-level rule catches a substantial English lead-in or tail even
    # when Filipino content later in the sentence dilutes the whole-text
    # ratio. It requires both English function markers and configured content
    # signals around a strong Filipino boundary token; a single borrowed word
    # or name cannot satisfy it.
    boundaries = {str(word).lower() for word in rules.get("language_code_switch_boundary_tokens", ())}
    content_words = {str(word).lower() for word in rules.get("language_code_switch_content_words", ())}
    minimum_clause_tokens = int(rules.get("language_code_switch_clause_min_tokens", 4))
    minimum_clause_markers = int(rules.get("language_code_switch_clause_min_markers", 2))
    minimum_clause_content = int(rules.get("language_code_switch_clause_min_content", 2))
    if boundaries and content_words:
        boundary_indices = [index for index, word in enumerate(words) if word in boundaries]
        segments: list[list[str]] = []
        if boundary_indices and boundary_indices[0] >= minimum_clause_tokens:
            segments.append(words[:boundary_indices[0]])
        if boundary_indices and len(words) - boundary_indices[-1] - 1 >= minimum_clause_tokens:
            segments.append(words[boundary_indices[-1] + 1:])
        for segment in segments:
            segment_markers = sum(word in marker_words for word in segment)
            segment_content = sum(word in content_words for word in segment)
            if segment_markers >= minimum_clause_markers and segment_content >= minimum_clause_content:
                reasons.append("language_code_switch_clause")
                break
    return tuple(dict.fromkeys(reasons))


@dataclass(frozen=True)
class SentenceRecord:
    clean_id: str
    text: str
    source_corpus: str
    publisher: str | None
    source_doc_id: str | None
    published_at: str | None
    url_hash: str | None
    sqlite_table: str
    sqlite_rowid: int
    metadata_json: str


@dataclass(frozen=True)
class RejectedSentence:
    clean_id: str | None
    text: str
    reason_codes: tuple[str, ...]
    sqlite_rowid: int | None
    metadata_json: str


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    return WHITESPACE.sub(" ", value).strip()


def stable_text_hash(value: str) -> str:
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def connect_read_only(database: Path) -> sqlite3.Connection:
    resolved = database.resolve()
    connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
        connection.close()
        raise RuntimeError("SQLite query_only pragma was not enabled")
    return connection


def iter_sentence_rows(connection: sqlite3.Connection, fetch_size: int = 50_000) -> Iterator[sqlite3.Row]:
    query = """
        SELECT
            s.rowid AS sqlite_rowid,
            s.sentence_id,
            s.article_id,
            s.source_id,
            s.sentence_text,
            s.normalized_text,
            s.language,
            s.language_confidence,
            s.token_count,
            s.quality_score,
            s.is_quote,
            s.is_headline,
            s.content_hash,
            s.is_duplicate,
            s.duplicate_group_id,
            a.url AS article_url,
            a.canonical_url,
            a.publication_date,
            a.headline,
            src.name AS source_name,
            src.domain AS source_domain
        FROM sentences AS s
        LEFT JOIN articles AS a ON a.article_id = s.article_id
        LEFT JOIN sources AS src ON src.source_id = s.source_id
        ORDER BY s.rowid
    """
    cursor = connection.execute(query)
    while True:
        rows = cursor.fetchmany(fetch_size)
        if not rows:
            return
        yield from rows


def _metadata(row: sqlite3.Row) -> str:
    keys = (
        "sentence_id", "article_id", "source_id", "sentence_text", "language",
        "language_confidence", "token_count", "quality_score", "is_quote",
        "is_headline", "content_hash", "is_duplicate", "duplicate_group_id",
        "article_url", "canonical_url", "publication_date", "headline",
        "source_name", "source_domain",
    )
    return json.dumps({key: row[key] for key in keys}, ensure_ascii=False, sort_keys=True)


def row_to_candidate(row: sqlite3.Row) -> SentenceRecord:
    # Preserve the source sentence surface (including casing) for the gold
    # target.  ``normalized_text`` is reserved for the upstream uniqueness
    # assertion and integrity hash; it must not replace the target payload.
    text = normalize_text(row["sentence_text"])
    publisher = row["source_name"] or row["source_domain"]
    url = row["canonical_url"] or row["article_url"]
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest() if url else None
    return SentenceRecord(
        clean_id=row["sentence_id"],
        text=text,
        source_corpus="sentence-pair-scraper",
        publisher=publisher,
        source_doc_id=row["article_id"],
        published_at=row["publication_date"],
        url_hash=url_hash,
        sqlite_table="sentences",
        sqlite_rowid=row["sqlite_rowid"],
        metadata_json=_metadata(row),
    )


def validate_row(
    row: sqlite3.Row,
    max_characters: int | None = None,
    quality_rules: Mapping[str, Any] | None = None,
) -> SentenceRecord | RejectedSentence:
    rules = dict(DEFAULT_QUALITY_RULES)
    if quality_rules:
        rules.update(quality_rules)
    if max_characters is not None:
        rules["max_characters"] = max_characters
    text = normalize_text(row["sentence_text"] or "")
    reasons: list[str] = []
    if rules.get("reject_empty", True) and not text:
        reasons.append("empty_text")
    if rules.get("reject_nul", True) and "\x00" in text:
        reasons.append("nul_character")
    if rules.get("require_letter", True) and text and not any(character.isalpha() for character in text):
        reasons.append("no_letter")
    if len(text) > int(rules.get("max_characters", 2_000)):
        reasons.append("too_long")
    alpha_ratio = sum(character.isalpha() for character in text) / max(len(text.replace(" ", "")), 1)
    if text and alpha_ratio < float(rules.get("min_alphabetic_ratio", 0.0)):
        reasons.append("low_alphabetic_ratio")
    repeated_punctuation = int(rules.get("max_repeated_punctuation", 0))
    if repeated_punctuation > 0 and re.search(r"[!?.,;:]{%d,}" % (repeated_punctuation + 1), text):
        reasons.append("repeated_punctuation")
    for pattern in rules.get("boilerplate_patterns", []):
        if re.fullmatch(str(pattern), text, flags=re.IGNORECASE):
            reasons.append("boilerplate")
            break
    if rules.get("reject_upstream_duplicate_marker", True) and row["is_duplicate"]:
        reasons.append("upstream_duplicate_marker")
    required_language = rules.get("required_language")
    if required_language and (row["language"] or "").upper() != str(required_language).upper():
        reasons.append("language_mismatch")
    minimum_confidence = rules.get("min_language_confidence")
    if minimum_confidence is not None:
        confidence = row["language_confidence"]
        if confidence is None or float(confidence) < float(minimum_confidence):
            reasons.append("low_language_confidence")
    reasons.extend(_language_code_switch_reasons(text, rules))
    if rules.get("check_balanced_delimiters", True):
        reasons.extend(_balanced_delimiters(text))
    if rules.get("check_sentence_integrity", True):
        if CONTROL_CHARACTERS.search(text):
            reasons.append("control_character")
        minimum_tokens = int(rules.get("sentence_integrity_min_tokens", 1))
        if len(text.split()) < minimum_tokens:
            reasons.append("sentence_integrity_too_short")
        if text and text[0] in ".,;:!?)]}":
            reasons.append("sentence_integrity_leading_closer")
        if text and text[-1] in "([{":
            reasons.append("sentence_integrity_trailing_opener")
    if rules.get("reject_suspicious_encoding", True):
        if any(str(pattern) in text for pattern in rules.get("suspicious_encoding_patterns", [])):
            reasons.append("suspicious_encoding")
    if rules.get("check_formality", True):
        for pattern in rules.get("formality_patterns", []):
            if re.search(str(pattern), text):
                reasons.append("informal_marker")
                break
        if rules.get("reject_urls_and_email", True) and URL_OR_EMAIL.search(text):
            reasons.append("url_or_email")
    if reasons:
        return RejectedSentence(row["sentence_id"], text, tuple(reasons), row["sqlite_rowid"], _metadata(row))
    return row_to_candidate(row)


def assert_unique_normalized_text(
    connection: sqlite3.Connection,
    fetch_size: int = 50_000,
    max_rows: int | None = None,
) -> dict[str, int | bool]:
    seen: set[str] = set()
    duplicates = 0
    rows = 0
    for row in iter_sentence_rows(connection, fetch_size):
        if max_rows is not None and rows >= max_rows:
            break
        rows += 1
        digest = stable_text_hash(row["normalized_text"] or "")
        if digest in seen:
            duplicates += 1
        else:
            seen.add(digest)
    return {
        "rows_checked": rows,
        "unique_text_hashes": len(seen),
        "duplicate_rows": duplicates,
        "passed": duplicates == 0,
        "bounded": max_rows is not None,
    }
