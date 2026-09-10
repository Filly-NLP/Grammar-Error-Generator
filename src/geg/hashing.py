"""Stable file and source-manifest hashing helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_files(paths: tuple[Path, ...], *, root: Path | None = None) -> str:
    root = (root or Path(__file__).resolve().parents[2]).resolve()
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda value: value.resolve().relative_to(root).as_posix()):
        digest.update(path.resolve().relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()
