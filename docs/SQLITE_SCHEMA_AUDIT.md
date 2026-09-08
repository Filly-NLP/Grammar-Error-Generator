# SQLite schema audit

This audit records the Phase 0 inspection of the supplied `corpus.db`. The
database was opened using SQLite URI `mode=ro` and `PRAGMA query_only = ON`.
No SQL write statement, migration, deduplication, or vacuum was run.

## Input identity

| Field | Value |
|---|---|
| Path | `corpus.db` |
| SHA-256 at audit start | `aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50` |
| Total rows in `sentences` | 517,342 |
| Distinct `normalized_text` values | 517,342 |
| Duplicate `normalized_text` groups | 0 |
| Rows marked `is_duplicate` | 0 |
| Database access | read-only URI plus `query_only` |

The complete machine-readable schema report is
[`reports/sqlite_schema.json`](../reports/sqlite_schema.json).

## Tables and provenance

| Table | Rows | Role | Relevant columns |
|---|---:|---|---|
| `sentences` | 517,342 | sentence corpus | `sentence_id`, `article_id`, `source_id`, `sentence_text`, `normalized_text`, `language`, `language_confidence`, `token_count`, `quality_score`, `content_hash`, `is_duplicate`, `duplicate_group_id` |
| `articles` | 40,648 | document metadata | `article_id`, `source_id`, `url`, `canonical_url`, `headline`, `publication_date`, `language`, `article_text`, `content_hash` |
| `sources` | 5 | publisher/source metadata | `source_id`, `name`, `domain`, `language`, `status` |
| `urls` | 40,738 | URL/discovery metadata | `url_id`, `url`, `canonical_url`, `source_id`, `publication_date_hint`, `content_hash` |
| `crawl_runs` | 19 | crawl provenance | `crawl_id`, `source_id`, `start_time`, `end_time`, `crawler_version`, `config_hash` |
| `crawl_events` | 533,001 | crawl events | `crawl_id`, `source_id`, `url`, `event_type`, `http_status`, `timestamp` |
| `discovery_observations` | 9 | discovery outcomes | `observation_id`, `crawl_id`, `source_id`, `discovery_method`, `outcome`, `http_status`, `metadata_json` |
| `discovery_observation_samples` | 10 | discovery samples | `sample_id`, `observation_id`, `candidate_url`, `normalized_url` |
| `url_discovery_edges` | 0 | discovery graph | `from_url_id`, `to_url_id`, `crawl_id`, `discovery_method`, `depth` |

## Phase 4 staging mapping

The immutable export maps each sentence to the following traceable record:

| Staging field | SQLite source |
|---|---|
| `clean_id` | `sentences.sentence_id` |
| `text` | `sentences.sentence_text` (NFC/whitespace-normalized at export; casing preserved) |
| `source_corpus` | constant `sentence-pair-scraper` |
| `publisher` | `sources.name` with `sources.domain` fallback |
| `source_doc_id` | `sentences.article_id` |
| `published_at` | `articles.publication_date` |
| `url_hash` | SHA-256 of `articles.canonical_url` or `articles.url` |
| `sqlite_table` | constant `sentences` |
| `sqlite_rowid` | SQLite `rowid` |
| `metadata_json` | selected sentence/article/source provenance fields |

The primary corpus is treated as an upstream-deduplicated contract. FILLY
performs only a non-mutating normalized-text uniqueness assertion and fails
before staging if that assertion finds duplicates. No near-deduplication pass
is present in the Phase 4 exporter.

The `normalized_text` column is used only for this integrity assertion and its
stable hash. It is not used as the gold target surface and is never rewritten.

The live Phase 0 assertion passed: all 517,342 normalized-text values were
distinct and no source row was marked as an upstream duplicate. The input
SHA-256 after inspection remained
`aadfbbaf0f9ee428e394395a4c73a13dcb0a798b75ca2356eece0f1df0fc7f50`.
