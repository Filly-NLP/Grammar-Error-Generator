"""Conservative, auditable inverse generators for the Table 2 tags.

Each candidate starts from a clean target and constructs one erroneous source.
Generators deliberately fail closed when the repository has no reviewed
resource for a family. The emitted operation records the target-side token and
the generated wrong surface so source/target tag direction remains auditable.
"""

from __future__ import annotations

import re
import string
import unicodedata
from dataclasses import dataclass, replace
from functools import lru_cache
from types import MappingProxyType
from typing import Any, Mapping

from .alignment import diff_spans
from .morphology import load_frozen_morphology
from .resources import load_frozen_constructions, load_frozen_punctuation
from .states import state_by_id, states
from .tags import BalarilaTag, registry


TOKEN_RE = re.compile(r"\S+")
VOWELS = frozenset("aeiouáéíóúàèìòùâêîôûäëïöü")
PUNCTUATION = frozenset(string.punctuation + "…“”‘’—–")
GENERATOR_VERSION = "filly-generators-v3-enclitic-context"
GENERATOR_POLICY_STATUS = "provisional_pending_linguistic_review"
PUNCTUATION_RESOURCE_VERSION = "filipino-punctuation-context-v1"

# These are only conservative grammatical/function-word contexts. They are
# intentionally not used for arbitrary content-word deletion/duplication.
FUNCTION_WORDS = frozenset({
    "ang", "ng", "mga", "sa", "at", "na", "ay", "si", "ni", "kay",
    "para", "kung", "dahil", "nang", "upang", "ito", "iyon", "isang",
    "ako", "ikaw", "siya", "sila", "nila", "niya", "din", "rin", "daw",
    "raw",
})
# These are the only contexts currently allowed for automatic deletion or
# duplication. They remain provisional until a Filipino linguist reviews the
# pilot; the generator never falls back to arbitrary content-word edits.
REVIEWED_FUNCTION_CONTEXTS = frozenset({
    "ang", "ng", "mga", "sa", "at", "na", "ay", "si", "ni", "kay",
    "para", "kung", "dahil", "nang", "upang",
})

ENCLITIC_PAIRS = {
    "daw": "raw",
    "raw": "daw",
    "din": "rin",
    "rin": "din",
    "dito": "rito",
    "rito": "dito",
    "diyan": "riyan",
    "riyan": "diyan",
    "doon": "roon",
    "roon": "doon",
}
PRONOUN_PAIRS = {"nila": "sila", "niya": "siya", "sila": "nila", "siya": "niya"}
UNAVAILABLE_FAMILIES = {
    "hyphen": "no reviewed Filipino construction resource is frozen",
    "space": "no reviewed Filipino construction resource is frozen",
    "morphology": "no frozen reviewed verb paradigm resource is available",
}
UNAVAILABLE_TAGS = {
    "$CHANGE_PUNC_EMARK": "no reviewed punctuation context resource is frozen",
    "$CHANGE_PUNC_PERIOD": "no reviewed punctuation context resource is frozen",
    "$CHANGE_PUNC_QMARK": "no reviewed punctuation context resource is frozen",
}


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int

    @property
    def core(self) -> str:
        left = 0
        right = len(self.text)
        while left < right and self.text[left] in PUNCTUATION:
            left += 1
        while right > left and self.text[right - 1] in PUNCTUATION:
            right -= 1
        return self.text[left:right]

    @property
    def prefix(self) -> str:
        return self.text[: len(self.text) - len(self.text.lstrip(string.punctuation + "…“”‘’—–"))]

    @property
    def suffix(self) -> str:
        core = self.core
        return self.text[len(self.prefix) + len(core):]


@dataclass(frozen=True)
class Candidate:
    source_text: str
    target_text: str
    correction_tag: str
    family: str
    generation_operation: dict[str, Any]
    target_token_index: int | None
    source_token_index: int | None
    confidence: str
    source_spans: tuple[dict[str, Any], ...]
    target_spans: tuple[dict[str, Any], ...]
    morphology_source_state: str | None = None
    morphology_target_state: str | None = None
    morphology_lemma: str | None = None
    morphology_resource_version: str | None = None
    rejection_reason: str | None = None


@dataclass(frozen=True)
class GenerationResult:
    candidates: tuple[Candidate, ...]
    status: str
    reason: str | None = None
    not_applicable: int = 0
    rejected: dict[str, int] | None = None

    @property
    def telemetry(self) -> dict[str, Any]:
        """Compact audit counters for one generator invocation.

        ``supported`` means that an implementation exists; it does not mean
        that the current sentence contained an eligible construction.  The
        distinction is intentionally represented in the counters so Phase 6
        can report capacity shortages without treating them as implementation
        failures.
        """
        rejected = dict(self.rejected or {})
        return {
            "status": self.status,
            "candidate_selected": len(self.candidates),
            "not_applicable": int(self.not_applicable),
            "candidate_rejected": int(sum(rejected.values())),
            "rejections": rejected,
        }


def _freeze_rows(rows: tuple[dict[str, Any], ...]) -> tuple[Mapping[str, Any], ...]:
    return tuple(MappingProxyType(dict(row)) for row in rows)


def _terminal_mark(context: str, value: Any) -> str | None:
    """Normalize a reviewed punctuation mark or full context pattern."""
    surface = str(value)
    if len(surface) == 1 and surface in ".?!":
        return surface
    if surface.startswith(context) and len(surface) == len(context) + 1 and surface[-1] in ".?!":
        return surface[-1]
    return None


@dataclass(frozen=True)
class GeneratorContext:
    """Immutable, pre-indexed reviewed resources for one generator run.

    Resource files are loaded once at context construction.  Generation calls
    only read these tuples/mapping proxies; they never perform per-sentence
    filesystem I/O or rebuild indexes.
    """

    morphology_rows: tuple[Mapping[str, Any], ...]
    morphology_manifest: Mapping[str, Any]
    morphology_by_lemma: Mapping[str, tuple[Mapping[str, Any], ...]]
    morphology_by_state: Mapping[str, tuple[Mapping[str, Any], ...]]
    morphology_by_surface: Mapping[str, tuple[Mapping[str, Any], ...]]
    construction_rows: tuple[Mapping[str, Any], ...]
    construction_manifest: Mapping[str, Any]
    constructions_by_tag: Mapping[str, tuple[Mapping[str, Any], ...]]
    punctuation_rows: tuple[Mapping[str, Any], ...]
    punctuation_manifest: Mapping[str, Any]
    punctuation_by_tag: Mapping[str, tuple[Mapping[str, Any], ...]]

    @classmethod
    def load(cls) -> "GeneratorContext":
        morphology, morphology_manifest = load_frozen_morphology()
        constructions, construction_manifest = load_frozen_constructions()
        punctuation, punctuation_manifest = load_frozen_punctuation()
        morphology_rows = _freeze_rows(tuple(morphology))
        construction_rows = _freeze_rows(tuple(constructions))
        punctuation_rows = _freeze_rows(tuple(punctuation))
        morphology_version = str(morphology_manifest.get("resource_version", ""))
        morphology_states: dict[str, set[str]] = {}
        morphology_surfaces: dict[str, str] = {}
        for row in morphology_rows:
            if row.get("review_status") != "approved":
                raise ValueError("generator context contains unapproved morphology row")
            lemma = str(row.get("lemma", "")).strip()
            surface = str(row.get("surface", "")).strip()
            state_id = str(row.get("balarila_state", "")).strip()
            if not lemma or not surface or not morphology_version:
                raise ValueError("generator context contains incomplete morphology row/manifest")
            state_by_id(state_id)
            if row.get("resource_version", morphology_version) != morphology_version:
                raise ValueError("morphology row resource version does not match manifest")
            if surface in morphology_surfaces and morphology_surfaces[surface] != lemma:
                raise ValueError(f"homographic morphology surface requires contextual review: {surface!r}")
            morphology_surfaces[surface] = lemma
            morphology_states.setdefault(lemma, set()).add(state_id)
        minimum_states = int(morphology_manifest.get("minimum_validated_states_per_lemma", 1) or 1)
        if any(len(values) < minimum_states for values in morphology_states.values()):
            raise ValueError("generator context contains a lemma below the frozen minimum state coverage")
        construction_version = str(construction_manifest.get("resource_version", ""))
        for row in construction_rows:
            if row.get("review_status") != "approved" or row.get("resource_version") != construction_version:
                raise ValueError("generator context contains an unapproved/version-mismatched construction row")
            require_tag = str(row.get("correction_tag", ""))
            matching = next((item for item in registry() if item.id == require_tag), None)
            if matching is None or matching.family != row.get("family"):
                raise ValueError("generator context contains an invalid construction tag/family")
        punctuation_version = str(punctuation_manifest.get("resource_version", ""))
        for row in punctuation_rows:
            if row.get("review_status") != "approved" or row.get("resource_version") != punctuation_version:
                raise ValueError("generator context contains an unapproved/version-mismatched punctuation row")
            punctuation_tag = str(row.get("correction_tag", row.get("tag", "")))
            if not punctuation_tag.startswith("$CHANGE_PUNC_"):
                raise ValueError("generator context contains a non-change punctuation row")
            context = str(row.get("context", "")).strip()
            correct = _terminal_mark(context, row.get("correct_surface", ""))
            wrong = _terminal_mark(context, row.get("generated_wrong_surface", ""))
            expected = {
                "$CHANGE_PUNC_PERIOD": ".",
                "$CHANGE_PUNC_QMARK": "?",
                "$CHANGE_PUNC_EMARK": "!",
            }.get(punctuation_tag)
            if (
                not context
                or context.endswith((".", "?", "!"))
                or correct is None
                or wrong is None
                or correct == wrong
                or correct != expected
            ):
                raise ValueError("generator context contains an invalid punctuation context row")
        by_lemma: dict[str, list[Mapping[str, Any]]] = {}
        by_state: dict[str, list[Mapping[str, Any]]] = {}
        by_surface: dict[str, list[Mapping[str, Any]]] = {}
        for row in morphology_rows:
            by_lemma.setdefault(str(row.get("lemma", "")), []).append(row)
            by_state.setdefault(str(row.get("balarila_state", "")), []).append(row)
            by_surface.setdefault(str(row.get("surface", "")), []).append(row)
        by_tag: dict[str, list[Mapping[str, Any]]] = {}
        for row in construction_rows:
            by_tag.setdefault(str(row.get("correction_tag", "")), []).append(row)
        punctuation_by_tag: dict[str, list[Mapping[str, Any]]] = {}
        for row in punctuation_rows:
            punctuation_by_tag.setdefault(str(row.get("correction_tag", row.get("tag", ""))), []).append(row)
        return cls(
            morphology_rows=morphology_rows,
            morphology_manifest=MappingProxyType(dict(morphology_manifest)),
            morphology_by_lemma=MappingProxyType({key: tuple(value) for key, value in by_lemma.items()}),
            morphology_by_state=MappingProxyType({key: tuple(value) for key, value in by_state.items()}),
            morphology_by_surface=MappingProxyType({key: tuple(value) for key, value in by_surface.items()}),
            construction_rows=construction_rows,
            construction_manifest=MappingProxyType(dict(construction_manifest)),
            constructions_by_tag=MappingProxyType({key: tuple(value) for key, value in by_tag.items()}),
            punctuation_rows=punctuation_rows,
            punctuation_manifest=MappingProxyType(dict(punctuation_manifest)),
            punctuation_by_tag=MappingProxyType({key: tuple(value) for key, value in punctuation_by_tag.items()}),
        )


@lru_cache(maxsize=1)
def get_generator_context() -> GeneratorContext:
    """Return the process-wide immutable resource context."""
    return GeneratorContext.load()


def clear_generator_context_cache() -> None:
    """Clear the cached context after an operator freezes new resources."""
    get_generator_context.cache_clear()


def tokens(text: str) -> tuple[Token, ...]:
    return tuple(Token(match.group(0), match.start(), match.end()) for match in TOKEN_RE.finditer(text))


def _replace_token(text: str, token: Token, replacement_core: str) -> str:
    return text[:token.start] + token.prefix + replacement_core + token.suffix + text[token.end:]


def _remove_token(text: str, token: Token) -> str:
    before = text[:token.start]
    after = text[token.end:]
    if before and after and before[-1].isspace() and after[:1].isspace():
        after = after[1:]
    elif before and after and not before[-1].isspace() and not after[:1].isspace():
        return ""
    elif before and before[-1].isspace():
        before = before[:-1]
    elif after and after[:1].isspace():
        after = after[1:]
    return before + after


def _candidate(
    text: str,
    token: Token | None,
    source: str,
    tag: BalarilaTag,
    operation: dict[str, Any],
    confidence: str = "high",
    compute_alignment: bool = True,
    morphology_source_state: str | None = None,
    morphology_target_state: str | None = None,
    morphology_lemma: str | None = None,
    morphology_resource_version: str | None = None,
) -> Candidate:
    index = tokens(text).index(token) if token is not None else None
    if compute_alignment:
        source_spans, target_spans = diff_spans(source, text)
    else:
        source_spans, target_spans = (), ()
    return Candidate(
        source_text=source,
        target_text=text,
        correction_tag=tag.id,
        family=tag.family,
        generation_operation=operation,
        target_token_index=index,
        source_token_index=index,
        confidence=confidence,
        source_spans=source_spans,
        target_spans=target_spans,
        morphology_source_state=morphology_source_state,
        morphology_target_state=morphology_target_state,
        morphology_lemma=morphology_lemma,
        morphology_resource_version=morphology_resource_version,
    )


def _unavailable(tag: BalarilaTag, reason: str | None = None) -> GenerationResult:
    return GenerationResult(
        (), "unavailable", reason or UNAVAILABLE_TAGS.get(tag.id) or UNAVAILABLE_FAMILIES.get(tag.family, "generator unavailable"),
        rejected={"unreviewed_resource": 1},
    )


def _ng_nang(text: str, tag: BalarilaTag, compute_alignment: bool) -> GenerationResult:
    desired = "nang" if tag.id == "$REPLACE_nang" else "ng"
    wrong = "ng" if desired == "nang" else "nang"
    result = []
    for token in tokens(text):
        if token.core.lower() == desired and token.core == desired and token.prefix == token.suffix == "":
            source_surface = token.prefix + wrong + token.suffix
            result.append(_candidate(text, token, _replace_token(text, token, wrong), tag, {
                "type": "replace", "correct": desired, "generated_wrong": wrong,
                "target_start": token.start, "target_end": token.end,
                "target_surface": token.text, "source_start": token.start,
                "source_end": token.start + len(source_surface), "source_surface": source_surface,
            }, compute_alignment=compute_alignment))
    return GenerationResult(tuple(result), "supported")


def _enclitic(text: str, tag: BalarilaTag, compute_alignment: bool) -> GenerationResult:
    desired = tag.id.removeprefix("$REPLACE_")
    result = []
    word_tokens = tokens(text)
    for index, token in enumerate(word_tokens):
        # Terminal punctuation is retained by ``_replace_token`` and does not
        # prevent a complete-token enclitic replacement.
        if token.core != desired or index == 0 or token.prefix:
            continue
        previous = word_tokens[index - 1].core.lower()
        if not previous or not previous[-1].isalpha():
            continue
        phonological = "".join(c for c in unicodedata.normalize("NFD", previous)
                               if not unicodedata.combining(c))
        previous_is_vowel = phonological[-1] in "aeiou"
        previous_is_glide = phonological[-1] in "wy"
        # Traditional din/rin and daw/raw exceptions (KWF manual, section 8.1).
        exception = desired in {"din", "rin", "daw", "raw"} and phonological.endswith(("ri", "ra", "raw", "ray"))
        expects_r_form = (previous_is_vowel or previous_is_glide) and not exception
        target_is_d_form = desired.startswith("d")
        if target_is_d_form == expects_r_form:
            continue
        wrong = ENCLITIC_PAIRS[desired]
        source_surface = token.prefix + wrong + token.suffix
        result.append(_candidate(text, token, _replace_token(text, token, wrong), tag, {
            "type": "replace", "correct": desired, "generated_wrong": wrong,
            "previous_token": previous,
            "previous_final_class": "glide" if previous_is_glide else "vowel" if previous_is_vowel else "consonant",
            "enclitic_exception": exception,
            "target_start": token.start, "target_end": token.end,
            "target_surface": token.text, "source_start": token.start,
            "source_end": token.start + len(source_surface), "source_surface": source_surface,
        }, compute_alignment=compute_alignment))
    return GenerationResult(tuple(result), "supported")


def _duplicate(text: str, tag: BalarilaTag, compute_alignment: bool) -> GenerationResult:
    result = []
    word_tokens = tokens(text)
    rejected: dict[str, int] = {}
    for index, token in enumerate(word_tokens):
        if token.core.lower() not in REVIEWED_FUNCTION_CONTEXTS or token.prefix or token.suffix:
            continue
        # Sentence-boundary duplication is too ambiguous to create without a
        # reviewed construction pattern.  Interior function-word contexts
        # remain conservative and auditable.
        if index == 0 or index == len(word_tokens) - 1:
            rejected["unsafe_or_ambiguous_construction"] = rejected.get("unsafe_or_ambiguous_construction", 0) + 1
            continue
        source = text[:token.end] + " " + token.text + text[token.end:]
        result.append(_candidate(text, token, source, tag, {
            "type": "duplicate", "correct": token.core, "generated_wrong": token.core,
            "target_start": token.start, "target_end": token.end,
            "target_surface": token.text, "source_remove_start": token.end,
            "source_remove_end": token.end + 1 + len(token.text),
            "source_duplicate_surface": " " + token.text,
        }, confidence="provisional", compute_alignment=compute_alignment))
    return GenerationResult(tuple(result), "supported", rejected=rejected or None)


def _missing_word(text: str, tag: BalarilaTag, compute_alignment: bool) -> GenerationResult:
    result = []
    word_tokens = tokens(text)
    rejected: dict[str, int] = {}
    for index, token in enumerate(word_tokens):
        if token.core.lower() not in REVIEWED_FUNCTION_CONTEXTS or token.prefix or token.suffix:
            continue
        # A terminal function word is often grammatical in its own right;
        # deleting it would create an arbitrary/irrecoverable target.  The
        # reviewed start-of-sentence ``Ang ...`` pattern is retained for the
        # existing Balarila-style append baseline.
        if index == len(word_tokens) - 1 and index != 0:
            rejected["unsafe_or_ambiguous_construction"] = rejected.get("unsafe_or_ambiguous_construction", 0) + 1
            continue
        source = _remove_token(text, token)
        if source and source != text:
            operation: dict[str, Any] = {
                "type": "append", "correct": token.core, "generated_wrong": "",
                "target_start": token.start, "target_end": token.end,
                "target_surface": token.text,
            }
            if index == 0:
                operation.update({"anchor": "$START", "position": "prepend"})
            else:
                anchor = word_tokens[index - 1]
                operation.update({
                    "anchor": "previous_token", "position": "after_anchor",
                    "source_anchor_start": anchor.start, "source_anchor_end": anchor.end,
                    "source_anchor_surface": anchor.text,
                })
            candidate = _candidate(text, token, source, tag, operation, confidence="provisional", compute_alignment=compute_alignment)
            # The source has lost the target token. Its insertion anchor is
            # therefore the previous target token; at document start there is
            # no source token and the explicit $START sentinel is serialized
            # as a null index.
            candidate = replace(
                candidate,
                source_token_index=None if index == 0 else index - 1,
            )
            operation["source_token_index_sentinel"] = "$START" if index == 0 else None
            if index > 0:
                operation["source_token_index_anchor"] = index - 1
            result.append(candidate)
    return GenerationResult(tuple(result), "supported", rejected=rejected or None)


def _punctuation(text: str, tag: BalarilaTag, compute_alignment: bool, context: GeneratorContext) -> GenerationResult:
    target_punc = {"EMARK": "!", "PERIOD": ".", "QMARK": "?"}
    kind = tag.id.rsplit("_", 1)[-1]
    desired = target_punc[kind]
    result = []
    # Generic punctuation substitution is semantically ambiguous (especially
    # ``!`` versus ``.``/``?``).  Until a reviewed construction/context
    # resource is supplied, keep the registered path implemented but produce
    # no production candidates.  Terminal punctuation *addition/removal* is
    # deterministic and remains available.
    if tag.id.startswith("$CHANGE_"):
        rows = context.punctuation_by_tag.get(tag.id, ())
        if not rows:
            return _unavailable(tag)
        for row in rows:
            reviewed_context = str(row.get("context", "")).strip()
            desired = _terminal_mark(reviewed_context, row.get("correct_surface", row.get("target_surface", "")))
            wrong = _terminal_mark(reviewed_context, row.get("generated_wrong_surface", row.get("source_surface", "")))
            # Context is an exact, reviewed lexical pattern.  Matching only a
            # terminal mark would turn semantically different sentences such as
            # ``Masaya.`` and ``Malungkot?`` into arbitrary punctuation errors.
            # Requiring the complete target pattern also proves that this
            # operation changes punctuation and nothing else.
            if (
                not reviewed_context
                or desired is None
                or wrong is None
                or desired == wrong
                or text != reviewed_context + desired
            ):
                continue
            start = len(reviewed_context)
            source = reviewed_context + wrong
            if source[:-1] != text[:-1]:
                continue
            result.append(_candidate(text, None, source, tag, {
                "type": "change_punctuation", "correct": desired, "generated_wrong": wrong,
                "context": reviewed_context,
                "target_start": start, "target_end": len(text), "target_surface": desired,
                "source_start": start, "source_end": start + len(wrong), "source_surface": wrong,
                "resource_version": context.punctuation_manifest.get("resource_version"),
            }, confidence="reviewed", compute_alignment=compute_alignment))
        return GenerationResult(tuple(result), "supported", not_applicable=0 if result else 1)
    if text.endswith(desired) and tag.id.startswith("$ADD_"):
        result.append(_candidate(text, None, text[:-1], tag, {
            "type": "add_punctuation", "correct": desired, "generated_wrong": "",
            "target_start": len(text) - 1, "target_end": len(text),
            "target_surface": desired, "source_surface": "",
        }, compute_alignment=compute_alignment))
    return GenerationResult(tuple(result), "supported")


def _case(text: str, tag: BalarilaTag, compute_alignment: bool) -> GenerationResult:
    result = []
    word_tokens = tokens(text)
    if tag.id == "$TRANSFORM_CASE_CAPITAL":
        if word_tokens:
            token = word_tokens[0]
            if token.core and token.core[0].isalpha() and token.core[0].isupper() and not token.core.isupper():
                wrong_core = token.core[0].lower() + token.core[1:]
                source = _replace_token(text, token, wrong_core)
                source_surface = token.prefix + wrong_core + token.suffix
                result.append(_candidate(text, token, source, tag, {
                    "type": "case", "correct": token.text, "generated_wrong": source_surface,
                    "direction": "capitalize", "target_start": token.start, "target_end": token.end,
                    "target_surface": token.text, "source_start": token.start,
                    "source_end": token.start + len(source_surface), "source_surface": source_surface,
                }, compute_alignment=compute_alignment))
    else:
        for token in word_tokens[1:]:
            if token.core in FUNCTION_WORDS and token.core.islower() and not token.prefix and not token.suffix:
                wrong = token.core[0].upper() + token.core[1:]
                result.append(_candidate(text, token, _replace_token(text, token, wrong), tag, {
                    "type": "case", "correct": token.text,
                    "generated_wrong": token.prefix + wrong + token.suffix,
                    "direction": "lower", "target_start": token.start, "target_end": token.end,
                    "target_surface": token.text, "source_start": token.start,
                    "source_end": token.start + len(token.prefix + wrong + token.suffix),
                    "source_surface": token.prefix + wrong + token.suffix,
                }, compute_alignment=compute_alignment))
    return GenerationResult(tuple(result), "supported")


def _pronoun(text: str, tag: BalarilaTag, compute_alignment: bool) -> GenerationResult:
    desired = tag.id.removeprefix("$REPLACE_")
    result = []
    for token in tokens(text):
        if token.core == desired and not token.prefix and not token.suffix:
            wrong = PRONOUN_PAIRS[desired]
            result.append(_candidate(text, token, _replace_token(text, token, wrong), tag, {
                "type": "replace", "correct": desired, "generated_wrong": wrong,
                "target_start": token.start, "target_end": token.end,
                "target_surface": token.text, "source_start": token.start,
                "source_end": token.start + len(wrong), "source_surface": wrong,
            }, confidence="medium", compute_alignment=compute_alignment))
    return GenerationResult(tuple(result), "supported")


def _reviewed_construction(text: str, tag: BalarilaTag, compute_alignment: bool, context: GeneratorContext) -> GenerationResult:
    rows = context.constructions_by_tag.get(tag.id, ())
    manifest = context.construction_manifest
    if not rows:
        return _unavailable(tag)
    result: list[Candidate] = []
    rejected: dict[str, int] = {}
    for row in rows:
        if row.get("family") != tag.family or row.get("correction_tag") != tag.id or row.get("review_status") != "approved":
            continue
        if str(row.get("resource_version", "")) != str(manifest.get("resource_version", "")):
            rejected["resource_version_mismatch"] = rejected.get("resource_version_mismatch", 0) + 1
            continue
        target_surface = str(row["correct_surface"])
        source_surface = str(row["generated_wrong_surface"])
        # Construction resources may contain phrases, but must never trigger
        # a substring edit inside a larger word.  Emit every exact occurrence
        # so capacity is truthful and each operation identifies one span.
        matches = list(re.finditer(re.escape(target_surface), text))
        for match in matches:
            start, end = match.span()
            if (target_surface[:1].isalnum() and start > 0 and text[start - 1].isalnum()) or (
                target_surface[-1:].isalnum() and end < len(text) and text[end].isalnum()
            ):
                rejected["unsafe_or_ambiguous_construction"] = rejected.get("unsafe_or_ambiguous_construction", 0) + 1
                continue
            source = text[:start] + source_surface + text[end:]
            if source == text:
                rejected["same_source_and_target"] = rejected.get("same_source_and_target", 0) + 1
                continue
            operation = {
            "type": "replace", "correct": target_surface, "generated_wrong": source_surface,
            "target_surface": target_surface, "source_surface": source_surface,
            "source_start": start, "source_end": start + len(source_surface),
            "resource_version": manifest.get("resource_version"),
            "resource_note": row.get("notes"),
        }
            result.append(_candidate(text, None, source, tag, operation, confidence="reviewed", compute_alignment=compute_alignment))
    return GenerationResult(tuple(result), "supported", rejected=rejected or None)


def _morphology(text: str, tag: BalarilaTag, compute_alignment: bool, context: GeneratorContext) -> GenerationResult:
    rows = context.morphology_rows
    manifest = context.morphology_manifest
    if not rows:
        return _unavailable(tag)
    target_state = next((state for state in states() if state.correction_tag == tag.id), None)
    if target_state is None:
        return GenerationResult((), "supported", "registered tag has no Table-3 target mapping")
    resource_version = str(manifest.get("resource_version", "")).strip()
    if not resource_version:
        return GenerationResult((), "unavailable", "frozen morphology manifest has no resource_version", rejected={"unreviewed_resource": 1})
    by_lemma = context.morphology_by_lemma
    result: list[Candidate] = []
    sentence_tokens = tokens(text)
    for token in sentence_tokens:
        # Index by the exact token surface first.  This keeps generation
        # proportional to sentence tokens rather than scanning every resource
        # row in the requested target state for every sentence.
        surface_rows = context.morphology_by_surface.get(token.core, ())
        for row in surface_rows:
            if str(row.get("balarila_state", "")) != target_state.id:
                continue
            surface = str(row.get("surface", ""))
            lemma = str(row.get("lemma", ""))
            siblings = [
                sibling for sibling in by_lemma.get(lemma, ())
                if str(sibling.get("surface")) != surface
                and str(sibling.get("balarila_state")) != target_state.id
            ]
            for sibling in siblings:
                source_surface = str(sibling["surface"])
                source = _replace_token(text, token, source_surface)
                if source == text:
                    continue
                source_state = str(sibling.get("balarila_state"))
                operation = {
                    "type": "replace", "correct": surface, "generated_wrong": source_surface,
                    "target_surface": token.text, "source_surface": token.prefix + source_surface + token.suffix,
                    "source_start": token.start, "source_end": token.end,
                    "target_start": token.start, "target_end": token.end,
                    "morphology_lemma": lemma,
                    "morphology_source_state": source_state,
                    "morphology_target_state": target_state.id,
                    "morphology_resource_version": manifest.get("resource_version"),
                }
                result.append(_candidate(
                    text, token, source, tag, operation, confidence="reviewed", compute_alignment=compute_alignment,
                    morphology_source_state=source_state,
                    morphology_target_state=target_state.id,
                    morphology_lemma=lemma,
                    morphology_resource_version=resource_version,
                ))
    return GenerationResult(tuple(result), "supported")


def generate_candidates(
    text: str,
    tag_id: str,
    *,
    compute_alignment: bool = True,
    context: GeneratorContext | None = None,
) -> GenerationResult:
    """Generate all conservative one-error candidates for one registered tag."""

    tag = next((item for item in registry() if item.id == tag_id), None)
    if tag is None:
        raise ValueError(f"unregistered Balarila correction tag: {tag_id}")
    context = context or get_generator_context()
    if tag.family == "morphology":
        result = _morphology(text, tag, compute_alignment, context)
    elif tag.family in {"hyphen", "space"}:
        result = _reviewed_construction(text, tag, compute_alignment, context)
    elif tag.family in UNAVAILABLE_FAMILIES:
        result = _unavailable(tag)
    elif tag.family == "ng_nang":
        result = _ng_nang(text, tag, compute_alignment)
    elif tag.family == "enclitic":
        result = _enclitic(text, tag, compute_alignment)
    elif tag.family == "duplicate_word":
        result = _duplicate(text, tag, compute_alignment)
    elif tag.family == "missing_word":
        result = _missing_word(text, tag, compute_alignment)
    elif tag.family == "punctuation":
        result = _punctuation(text, tag, compute_alignment, context)
    elif tag.family == "casing":
        result = _case(text, tag, compute_alignment)
    elif tag.family == "pronoun":
        result = _pronoun(text, tag, compute_alignment)
    else:
        raise ValueError(f"no generator registered for family {tag.family}")
    # A supported generator with no eligible operation is an ordinary capacity
    # miss, not an implementation failure.  Keep this counter on the result
    # so callers can aggregate it without manufacturing row-level rejections.
    if result.status == "supported" and not result.candidates and result.not_applicable == 0:
        result = replace(result, not_applicable=1)
    return result


def all_tag_ids() -> tuple[str, ...]:
    return tuple(item.id for item in registry())


def production_coverage() -> dict[str, dict[str, str | bool]]:
    """Report implementation coverage independently of observed capacity."""
    implemented_families = {
        "ng_nang", "enclitic", "hyphen", "space", "duplicate_word", "missing_word",
        "morphology", "punctuation", "casing", "pronoun",
    }
    resource_available: dict[str, bool] = {"hyphen": False, "space": False, "morphology": False}
    resource_error: dict[str, str] = {}
    context: GeneratorContext | None = None
    try:
        context = get_generator_context()
        resource_available["hyphen"] = any(row.get("family") == "hyphen" and row.get("review_status") == "approved" for row in context.construction_rows)
        resource_available["space"] = any(row.get("family") == "space" and row.get("review_status") == "approved" for row in context.construction_rows)
        resource_available["morphology"] = bool(context.morphology_rows)
    except (OSError, ValueError, RuntimeError) as error:
        resource_error["hyphen"] = str(error)
        resource_error["space"] = str(error)
        resource_error["morphology"] = str(error)
    if context is None:
        return {
            tag.id: {
                "implemented": True,
                "implementation_status": "implemented",
                "resource_backed": tag.family in {"hyphen", "space", "morphology"} or tag.id in UNAVAILABLE_TAGS,
                "resource_available": False if tag.family in {"hyphen", "space", "morphology"} or tag.id in UNAVAILABLE_TAGS else True,
                "resource_error": resource_error.get(tag.family, "resource context unavailable"),
            }
            for tag in registry()
        }
    # Resource readiness is per registered tag.  In particular, punctuation
    # substitution tags do not inherit readiness from the punctuation family:
    # they require their own reviewed context rows.
    resource_backed_families = {"hyphen", "space", "morphology"}
    return {
        tag.id: {
            "implemented": tag.family in implemented_families,
            "implementation_status": "implemented" if tag.family in implemented_families else "unimplemented",
            "resource_backed": tag.family in resource_backed_families or tag.id in UNAVAILABLE_TAGS,
            "resource_available": (
                any(row.get("correction_tag") == tag.id for row in context.constructions_by_tag.get(tag.id, ()))
                if tag.family in {"hyphen", "space"} else
                any(state.correction_tag == tag.id and any(str(row.get("balarila_state")) == state.id for row in context.morphology_rows) for state in states())
                if tag.family == "morphology" else
                bool(context.punctuation_by_tag.get(tag.id)) if tag.id in UNAVAILABLE_TAGS else True
            ),
            "resource_error": resource_error.get(tag.family, ""),
        }
        for tag in registry()
    }
