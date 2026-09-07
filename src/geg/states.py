"""Balarila Table 3 verb states, kept separate from correction tags."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .resources import load_resource
from .tags import require_registered


@dataclass(frozen=True)
class VerbState:
    id: str
    label: str
    aspect: str
    focus: str | None
    correction_tag: str | None
    can_be_target: bool


@lru_cache(maxsize=1)
def states() -> tuple[VerbState, ...]:
    payload = load_resource("table3_states.yaml")
    values = tuple(VerbState(**item) for item in payload["states"])
    if len(values) != 10:
        raise ValueError(f"Table 3 must contain 10 states, got {len(values)}")
    ids = [item.id for item in values]
    if len(ids) != len(set(ids)):
        raise ValueError("Table 3 contains duplicate state ids")
    for item in values:
        if item.can_be_target:
            if item.correction_tag is None:
                raise ValueError(f"target-capable state has no correction tag: {item.id}")
            require_registered(item.correction_tag)
        elif item.correction_tag is not None:
            raise ValueError(f"Table-3-only state has a correction tag: {item.id}")
    mismatch = set(payload.get("table2_target_mismatch", []))
    actual = {item.id for item in values if not item.can_be_target}
    if mismatch != actual:
        raise ValueError(f"Table 2/3 mismatch declaration {mismatch} != {actual}")
    return values


def state_by_id(state_id: str) -> VerbState:
    for state in states():
        if state.id == state_id:
            return state
    raise ValueError(f"unknown Table 3 state: {state_id}")
