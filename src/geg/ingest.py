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
}


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
    text = normalize_text(row["normalized_text"])
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
    text = normalize_text(row["normalized_text"] or "")
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
