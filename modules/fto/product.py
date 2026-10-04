"""Product description → candidate technical features (ADR 0010).

Deterministic rules only: product descriptions are customer-confidential and
no sensitivity-routed model exists yet, so nothing here calls an LLM. The
output is a set of *candidates* with exact spans in the original text; a person
confirms, edits, splits or merges them before any comparison.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

SPLITTER_VERSION = "product-splitter/1"
LONG_FEATURE_CHARS = 120  # review hint only: long candidates usually bundle several features

FeatureOrigin = Literal["split", "manual", "edited"]

# No "^": pattern.match(text, pos) already anchors at pos, while "^" would only match at index 0.
# "-" and "*" count as bullets only before whitespace, so "-5 °C" keeps its sign.
_LIST_MARKER = re.compile(
    r"[ \t]*(?:-(?=\s)|\*(?=\s)|[•·▪]|\(?\d{1,3}[.)、](?!\d)|（\d{1,3}）|\(\d{1,3}\)|[一二三四五六七八九十]+、|[a-zA-Z][.)](?=\s))[ \t]*"
)
# Clause/sentence ends: Chinese and ASCII semicolons, Chinese full stop, ! and ?.
_HARD_END = re.compile(r"[。；;！？!?]")
# English sentence end: '.' then whitespace then an uppercase letter or CJK character.
_EN_SENTENCE_END = re.compile(r"\.(?=\s+[A-Z一-鿿])")
_ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "fig.", "no.", "approx.", "vs.", "mr.", "dr.")


@dataclass(frozen=True)
class ProductFeature:
    feature_id: str
    text: str
    spans: tuple[tuple[int, int], ...]  # into the description text; empty for manual features
    origin: FeatureOrigin = "split"


@dataclass(frozen=True)
class SplitResult:
    features: tuple[ProductFeature, ...]
    warnings: tuple[str, ...]
    splitter_version: str = SPLITTER_VERSION


def _is_abbreviation(text: str, dot_index: int) -> bool:
    window = text[max(0, dot_index - 7) : dot_index + 1].lower()
    return any(window.endswith(a) for a in _ABBREVIATIONS)


def _cut_points(text: str, start: int, end: int) -> list[int]:
    cuts = []
    for match in _HARD_END.finditer(text, start, end):
        cuts.append(match.end())
    for match in _EN_SENTENCE_END.finditer(text, start, end):
        if not _is_abbreviation(text, match.start()):
            cuts.append(match.end())
    return sorted(set(cuts))


def split_description(text: str) -> SplitResult:
    features: list[ProductFeature] = []
    warnings: list[str] = []
    position = 0
    for line in text.splitlines(keepends=True):
        line_start, line_end = position, position + len(line)
        position = line_end
        marker = _LIST_MARKER.match(text, line_start, line_end)
        content_start = marker.end() if marker else line_start
        bounds = [content_start, *_cut_points(text, content_start, line_end), line_end]
        for start, end in zip(bounds, bounds[1:]):
            piece = text[start:end]
            left = len(piece) - len(piece.lstrip())
            right = len(piece.rstrip())
            if right <= left:
                continue
            span = (start + left, start + right)
            body = text[span[0] : span[1]]
            if not re.search(r"\w", body):  # punctuation-only fragments carry no feature
                continue
            features.append(ProductFeature(feature_id=f"P{len(features) + 1}", text=body, spans=(span,)))
    for feature in features:
        if len(feature.text) > LONG_FEATURE_CHARS:
            warnings.append(
                f"{feature.feature_id} is {len(feature.text)} characters: may contain several features; split during review"
            )
    if not features:
        warnings.append("no candidate features found")
    return SplitResult(tuple(features), tuple(warnings))
