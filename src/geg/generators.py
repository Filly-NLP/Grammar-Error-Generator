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
from typing import Any

from .alignment import diff_spans
from .tags import BalarilaTag, registry


TOKEN_RE = re.compile(r"\S+")
VOWELS = frozenset("aeiouáéíóúàèìòùâêîôûäëïöü")
PUNCTUATION = frozenset(string.punctuation + "…“”‘’—–")
GENERATOR_VERSION = "filly-generators-v3-enclitic-context"

# These are only conservative grammatical/function-word contexts. They are
# intentionally not used for arbitrary content-word deletion/duplication.
FUNCTION_WORDS = frozenset({
    "ang", "ng", "mga", "sa", "at", "na", "ay", "si", "ni", "kay",
    "para", "kung", "dahil", "nang", "upang", "ito", "iyon", "isang",
    "ako", "ikaw", "siya", "sila", "nila", "niya", "din", "rin", "daw",
    "raw",
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


@dataclass(frozen=True)
class GenerationResult:
    candidates: tuple[Candidate, ...]
    status: str
    reason: str | None = None


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
    )


def _unavailable(tag: BalarilaTag) -> GenerationResult:
    return GenerationResult((), "unavailable", UNAVAILABLE_FAMILIES.get(tag.family, "generator unavailable"))


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
    for token in tokens(text):
        if token.core.lower() not in FUNCTION_WORDS or token.prefix or token.suffix:
            continue
        source = text[:token.end] + " " + token.text + text[token.end:]
        result.append(_candidate(text, token, source, tag, {
            "type": "duplicate", "correct": token.core, "generated_wrong": token.core,
            "target_start": token.start, "target_end": token.end,
            "target_surface": token.text, "source_remove_start": token.end,
            "source_remove_end": token.end + 1 + len(token.text),
            "source_duplicate_surface": " " + token.text,
        }, compute_alignment=compute_alignment))
    return GenerationResult(tuple(result), "supported")


def _missing_word(text: str, tag: BalarilaTag, compute_alignment: bool) -> GenerationResult:
    result = []
    word_tokens = tokens(text)
    for index, token in enumerate(word_tokens):
        if token.core.lower() not in FUNCTION_WORDS or token.prefix or token.suffix:
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
            candidate = _candidate(text, token, source, tag, operation, compute_alignment=compute_alignment)
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
    return GenerationResult(tuple(result), "supported")


def _punctuation(text: str, tag: BalarilaTag, compute_alignment: bool) -> GenerationResult:
    target_punc = {"EMARK": "!", "PERIOD": ".", "QMARK": "?"}
    kind = tag.id.rsplit("_", 1)[-1]
    desired = target_punc[kind]
    result = []
    if text.endswith(desired) and tag.id.startswith("$ADD_"):
        result.append(_candidate(text, None, text[:-1], tag, {
            "type": "add_punctuation", "correct": desired, "generated_wrong": "",
            "target_start": len(text) - 1, "target_end": len(text),
            "target_surface": desired, "source_surface": "",
        }, compute_alignment=compute_alignment))
    elif text.endswith(desired) and tag.id.startswith("$CHANGE_"):
        wrong = {"!": ".", ".": "?", "?": "!"}[desired]
        result.append(_candidate(text, None, text[:-1] + wrong, tag, {
            "type": "change_punctuation", "correct": desired, "generated_wrong": wrong,
            "target_start": len(text) - 1, "target_end": len(text),
            "target_surface": desired, "source_start": len(text) - 1,
            "source_end": len(text), "source_surface": wrong,
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


def generate_candidates(text: str, tag_id: str, *, compute_alignment: bool = True) -> GenerationResult:
    """Generate all conservative one-error candidates for one registered tag."""

    tag = next((item for item in registry() if item.id == tag_id), None)
    if tag is None:
        raise ValueError(f"unregistered Balarila correction tag: {tag_id}")
    if tag.family in UNAVAILABLE_FAMILIES:
        return _unavailable(tag)
    if tag.family == "ng_nang":
        return _ng_nang(text, tag, compute_alignment)
    if tag.family == "enclitic":
        return _enclitic(text, tag, compute_alignment)
    if tag.family == "duplicate_word":
        return _duplicate(text, tag, compute_alignment)
    if tag.family == "missing_word":
        return _missing_word(text, tag, compute_alignment)
    if tag.family == "punctuation":
        return _punctuation(text, tag, compute_alignment)
    if tag.family == "casing":
        return _case(text, tag, compute_alignment)
    if tag.family == "pronoun":
        return _pronoun(text, tag, compute_alignment)
    raise ValueError(f"no generator registered for family {tag.family}")


def all_tag_ids() -> tuple[str, ...]:
    return tuple(item.id for item in registry())
