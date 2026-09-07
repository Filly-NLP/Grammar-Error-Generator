"""The frozen Balarila Table 2 correction-label registry."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .resources import load_resource


@dataclass(frozen=True)
class BalarilaTag:
    id: str
    family: str
    description: str


@lru_cache(maxsize=1)
def registry() -> tuple[BalarilaTag, ...]:
    payload = load_resource("balarila_tags.yaml")
    tags = tuple(BalarilaTag(**item) for item in payload["tags"])
    declared_count = payload.get("tag_count")
    if declared_count != len(tags):
        raise ValueError(f"tag_count={declared_count} but resource contains {len(tags)} tags")
    ids = [tag.id for tag in tags]
    if len(ids) != len(set(ids)):
        raise ValueError("Balarila registry contains duplicate tag ids")
    return tags


def tag_ids() -> frozenset[str]:
    return frozenset(tag.id for tag in registry())


def require_registered(tag: str) -> str:
    if tag not in tag_ids():
        raise ValueError(f"unregistered Balarila correction tag: {tag}")
    return tag


def validate_tags(tags: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(require_registered(tag) for tag in tags)
