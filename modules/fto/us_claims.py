"""Parse US claims from the USPTO grant full-text XML (PTGRXML) (ADR 0008).

Numbering and dependencies come from the office's markup (``<claim num>``,
``<claim-ref idref>``), not from parsing words. Initial features follow the
nested ``<claim-text>`` clauses; each feature records its character spans in
the claim's full text.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from modules.fto.model import Claim, ClaimFeature, ClaimSet

_LEADING_NUMBER = re.compile(r"^\s*\d+\s*\.\s*")
_CLAIM_ID = re.compile(r"CLM-0*(\d+)$")
# Review hint only, not a rule: a clause this long usually bundles several features.
LONG_FEATURE_CHARS = 400


class _Builder:
    """Walks one claim, building its full text and the own-text pieces of each clause."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.position = 0
        self.clauses: list[list[tuple[int, int]]] = []

    def add(self, text: str | None, clause: int | None) -> None:
        if not text:
            return
        start = self.position
        self.parts.append(text)
        self.position += len(text)
        if clause is not None:
            self.clauses[clause].append((start, self.position))

    def walk(self, node: ET.Element, clause: int | None) -> None:
        """Text of ``node`` belongs to ``clause``; nested claim-text opens a new clause."""
        self.add(node.text, clause)
        for child in node:
            if child.tag == "claim-text":
                self.clauses.append([])
                self.walk(child, len(self.clauses) - 1)
            else:  # inline markup (b, i, sub, sup, claim-ref, ...) stays in the same clause
                self.walk_inline(child, clause)
            self.add(child.tail, clause)

    def walk_inline(self, node: ET.Element, clause: int | None) -> None:
        self.add(node.text, clause)
        for child in node:
            self.walk_inline(child, clause)
            self.add(child.tail, clause)


def _number(claim: ET.Element) -> int:
    return int(claim.get("num", "0").lstrip("0") or "0")


def parse_us_claims(claims_xml: str, *, publication_number: str) -> ClaimSet:
    root = ET.fromstring(claims_xml)
    claims_node = root if root.tag == "claims" else root.find(".//claims")
    if claims_node is None:
        raise ValueError("no <claims> element")
    claims: list[Claim] = []
    for claim_node in claims_node.findall("claim"):
        number = _number(claim_node)
        builder = _Builder()
        for top in claim_node.findall("claim-text"):
            builder.clauses.append([])
            builder.walk(top, len(builder.clauses) - 1)
        text = "".join(builder.parts)
        refs = sorted(
            {
                int(m.group(1))
                for ref in claim_node.iter("claim-ref")
                if (m := _CLAIM_ID.search(ref.get("idref", "")))
            }
        )
        features: list[ClaimFeature] = []
        warnings: list[str] = []
        for index, spans in enumerate(builder.clauses):
            # Trim whitespace at the span edges and drop empty pieces.
            trimmed = []
            for start, end in spans:
                piece = text[start:end]
                left = len(piece) - len(piece.lstrip())
                right = len(piece.rstrip())
                if right > left:
                    trimmed.append((start + left, start + right))
            if not trimmed:
                continue
            if index == 0:
                # Drop the leading claim number ("1." or "<b>1</b>.") even when it spans pieces.
                match = _LEADING_NUMBER.match(text, trimmed[0][0])
                if match:
                    cut = match.end()
                    trimmed = [(max(s_, cut), e_) for s_, e_ in trimmed if e_ > cut]
            feature_text = " ".join(text[s:e] for s, e in trimmed)
            if not feature_text.strip():
                continue
            features.append(
                ClaimFeature(
                    feature_id=f"{number}.{len(features)}",
                    claim_number=number,
                    text=feature_text,
                    spans=tuple(trimmed),
                )
            )
        for feature in features:
            if len(feature.text) > LONG_FEATURE_CHARS:
                warnings.append(
                    f"feature {feature.feature_id} is {len(feature.text)} characters: "
                    "may contain several features; split during review"
                )
        if number in refs:
            refs.remove(number)
            warnings.append("claim references itself; reference ignored")
        claims.append(
            Claim(
                number=number,
                text=text,
                depends_on=tuple(refs),
                structure_source="uspto_grant_xml",
                features=tuple(features),
                language="en",
                parse_warnings=tuple(warnings),
            )
        )
    return ClaimSet(publication_number=publication_number, claims=tuple(claims), language="en")
