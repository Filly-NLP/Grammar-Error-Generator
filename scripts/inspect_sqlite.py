"""Read-only SQLite schema and integrity inspection for the FILLY input corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_database(db_path: Path) -> dict[str, Any]:
    resolved = db_path.resolve()
    connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        objects = connection.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE type IN ('table', 'view') ORDER BY name"
        ).fetchall()
        tables: list[dict[str, Any]] = []
        for name, object_type in objects:
            identifier = quote_identifier(name)
            columns = [
                dict(zip(("cid", "name", "type", "notnull", "default", "pk"), row))
                for row in connection.execute(f"PRAGMA table_info({identifier})")
            ]
            indexes = [
                dict(zip(("seq", "name", "unique", "origin", "partial"), row))
                for row in connection.execute(f"PRAGMA index_list({identifier})")
            ]
            count = None
            if object_type == "table":
                count = connection.execute(f"SELECT COUNT(*) FROM {identifier}").fetchone()[0]
            tables.append(
                {
                    "name": name,
                    "type": object_type,
                    "row_count": count,
                    "columns": columns,
                    "indexes": indexes,
                }
            )

        integrity: dict[str, Any] = {}
        if any(name == "sentences" and object_type == "table" for name, object_type in objects):
            total, distinct_text, marked_duplicate = connection.execute(
                "SELECT COUNT(*), COUNT(DISTINCT normalized_text), "
                "COALESCE(SUM(CASE WHEN is_duplicate THEN 1 ELSE 0 END), 0) "
                "FROM sentences"
            ).fetchone()
            duplicate_groups = connection.execute(
                "SELECT COUNT(*) FROM ("
                "SELECT normalized_text FROM sentences "
                "GROUP BY normalized_text HAVING COUNT(*) > 1"
                ")"
            ).fetchone()[0]
            integrity = {
                "sentences_total": total,
                "normalized_text_distinct": distinct_text,
                "normalized_text_duplicate_groups": duplicate_groups,
                "upstream_is_duplicate_marked_rows": marked_duplicate,
                "normalized_text_unique": duplicate_groups == 0,
            }

        return {
            "database": str(resolved),
            "sha256": sha256_file(resolved),
            "tables": tables,
            "integrity": integrity,
            "read_only": True,
            "query_only": True,
        }
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = inspect_database(args.database)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
