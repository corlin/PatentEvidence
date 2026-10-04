"""Parse EP claims from EPO OPS ``claims`` responses (ADR 0008).

OPS returns each language as flat paragraphs; claim numbers and dependencies
exist only in the wording, so the structure here is parsed from text
(``ops_text_parsed``) and anything ambiguous is reported, not guessed.
OPS does not state the language of the proceedings (the authentic text, EPC
Art. 70(1)), so it is left unknown and the claim set says so.
"""

from __future__ import annotations

import re
from typing import Any

from modules.fto.model import Claim, ClaimFeature, ClaimSet

# Recorded with every chart snapshot; bump when parsing output can change.
PARSER_ID = "fto-ep-claims/1"

_CLAIM_START = re.compile(r"^\s*(\d+)\s*\.\s+")
_REFERENCE = re.compile(
    r"\bclaims?\s+(\d+(?:\s*(?:,|or|and|to|-|–)\s*\d+)*)", re.IGNORECASE
)
_ALL_PRECEDING = re.compile(r"\b(?:any|one)\s+(?:one\s+)?of\s+the\s+preceding\s+claims\b|\bany\s+preceding\s+claim\b", re.IGNORECASE)
_TWO_PART = re.compile(r"\bcharacteri[sz]ed\s+in\s+that\b", re.IGNORECASE)
_FEATURE_BREAK = re.compile(r";|\n")
_BARE_CONJUNCTION = re.compile(r"(?:and|or)", re.IGNORECASE)


def _claim_texts(payload: dict[str, Any], language: str) -> list[str]:
    found: list[list[str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("@lang", "").upper() == language.upper() and "claim" in node:
                claim = node["claim"]
                items = claim.get("claim-text") if isinstance(claim, dict) else None
                items = items if isinstance(items, list) else [items] if items else []
                found.append([str(i.get("$", "")) if isinstance(i, dict) else str(i) for i in items])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return found[0] if found else []


def _references(text: str, own: int) -> tuple[list[int], list[str]]:
    refs: set[int] = set()
    warnings: list[str] = []
    for match in _REFERENCE.finditer(text):
        body = match.group(1)
        for a, b in re.findall(r"(\d+)\s*(?:to|-|–)\s*(\d+)", body):
            refs.update(range(int(a), int(b) + 1))
        refs.update(int(n) for n in re.findall(r"\d+", body))
    if _ALL_PRECEDING.search(text):
        refs.update(range(1, own))
        warnings.append("refers to 'preceding claims': depends on every earlier claim")
    if re.search(r"\bclaim", text, re.IGNORECASE) and not refs:
        warnings.append("mentions 'claim' but no reference could be parsed")
    refs.discard(own)
    bad = sorted(r for r in refs if r >= own)
    if bad:
        warnings.append(f"references later or own claims {bad}: kept, check the text")
    return sorted(refs), warnings


def _features(number: int, text: str, body_start: int) -> list[ClaimFeature]:
    """Split at ';', line breaks and the two-part 'characterised in that' boundary."""
    cuts = {body_start, len(text)}
    for match in _FEATURE_BREAK.finditer(text, body_start):
        cuts.add(match.end())
    for match in _TWO_PART.finditer(text, body_start):
        cuts.add(match.start())
    bounds = sorted(cuts)
    spans: list[tuple[int, int]] = []
    for start, end in zip(bounds, bounds[1:]):
        piece = text[start:end]
        left = len(piece) - len(piece.lstrip())
        right = len(piece.rstrip())
        if right <= left:
            continue
        span = (start + left, start + right)
        # A bare conjunction left by "...; and <last feature>" belongs to the next feature.
        if _BARE_CONJUNCTION.fullmatch(text[span[0] : span[1]]):
            pending = span
            spans.append(pending)
            continue
        if spans and _BARE_CONJUNCTION.fullmatch(text[spans[-1][0] : spans[-1][1]]):
            span = (spans.pop()[0], span[1])
        spans.append(span)
    return [
        ClaimFeature(feature_id=f"{number}.{i}", claim_number=number, text=text[s:e], spans=((s, e),))
        for i, (s, e) in enumerate(spans)
    ]


def parse_ep_claims(payload: dict[str, Any], *, publication_number: str, language: str = "EN") -> ClaimSet:
    paragraphs = _claim_texts(payload, language)
    if not paragraphs:
        raise ValueError(f"no {language} claims in OPS response")
    grouped: list[tuple[int, list[str]]] = []
    preamble_orphans = 0
    for paragraph in paragraphs:
        match = _CLAIM_START.match(paragraph)
        if match:
            grouped.append((int(match.group(1)), [paragraph]))
        elif grouped:
            grouped[-1][1].append(paragraph)
        else:
            preamble_orphans += 1
    set_warnings = [
        "language of the proceedings is not stated by OPS: this text may be a translation, "
        "not the authentic text (EPC Art. 70(1))"
    ]
    if preamble_orphans:
        set_warnings.append(f"{preamble_orphans} paragraph(s) before claim 1 were ignored")
    numbers = [n for n, _ in grouped]
    if numbers != list(range(1, len(numbers) + 1)):
        set_warnings.append(f"claim numbering is not consecutive: {numbers}")

    claims: list[Claim] = []
    for number, parts in grouped:
        text = "\n".join(parts)
        body_start = _CLAIM_START.match(text).end()  # type: ignore[union-attr]
        refs, warnings = _references(text[body_start:], number)
        claims.append(
            Claim(
                number=number,
                text=text,
                depends_on=tuple(refs),
                structure_source="ops_text_parsed",
                features=tuple(_features(number, text, body_start)),
                language=language.lower(),
                parse_warnings=tuple(warnings),
            )
        )
    return ClaimSet(
        publication_number=publication_number,
        claims=tuple(claims),
        language=language.lower(),
        proceedings_language=None,
        warnings=tuple(set_warnings),
    )
