"""Conservative UniMorph-to-Balarila state mapping.

The mapping is deliberately review-oriented. UniMorph features are not treated
as an exact copy of Balarila Table 3; every emitted row remains provisional
until human review freezes a local morphology resource.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StateMapping:
    state: str | None
    aspect: str | None
    focus: str | None
    confidence: str
    reason: str


def _tokens(features: str) -> set[str]:
    return {token.strip().upper() for token in features.replace("|", ";").split(";") if token.strip()}


def map_unimorph_features(features: str) -> StateMapping:
    tokens = _tokens(features)
    if not tokens:
        return StateMapping(None, None, None, "none", "empty_feature_bundle")

    explicit = next((token for token in tokens if token.startswith("BALARILA=")), None)
    if explicit:
        state = explicit.split("=", 1)[1]
        if state in {
            "BASE", "COMPACT", "INCACT", "CONTACT", "IMPACT",
            "COMPOBJ", "INCOBJ", "CONTOBJ", "IMPOBJ", "RECCOMP",
        }:
            return StateMapping(state, None, None, "provisional", "explicit_balarila_hint")

    if "BASE" in tokens or "INFINITIVE" in tokens:
        return StateMapping("BASE", "base", None, "provisional", "base_feature")

    if tokens & {"PFV", "PERF", "PST", "COMPLETED"}:
        aspect = "completed"
    elif tokens & {"IPFV", "IMPF", "PRS", "INCOMPLETED"}:
        aspect = "incompleted"
    elif tokens & {"PROSP", "FUT", "CONTEMPLATED"}:
        aspect = "contemplated"
    elif tokens & {"IMP", "IMPERATIVE"}:
        aspect = "imperative"
    elif tokens & {"REC", "RECENT", "RECENTLY_COMPLETED"}:
        aspect = "recently_completed"
    else:
        return StateMapping(None, None, None, "none", "aspect_not_supported")

    if tokens & {"AF", "AV", "ACTOR", "ACTORFOCUS"}:
        focus = "actor"
    elif tokens & {"OF", "OV", "OBJECT", "OBJECTFOCUS"}:
        focus = "object"
    else:
        focus = None

    if aspect == "recently_completed" and focus is None:
        state = "RECCOMP"
    elif aspect == "imperative" and focus == "actor":
        state = "IMPACT"
    elif aspect == "imperative" and focus == "object":
        state = "IMPOBJ"
    elif aspect == "completed" and focus == "actor":
        state = "COMPACT"
    elif aspect == "completed" and focus == "object":
        state = "COMPOBJ"
    elif aspect == "incompleted" and focus == "actor":
        state = "INCACT"
    elif aspect == "incompleted" and focus == "object":
        state = "INCOBJ"
    elif aspect == "contemplated" and focus == "actor":
        state = "CONTACT"
    elif aspect == "contemplated" and focus == "object":
        state = "CONTOBJ"
    else:
        return StateMapping(None, aspect, focus, "none", "focus_not_supported")
    return StateMapping(state, aspect, focus, "provisional", "feature_bundle_rule")
