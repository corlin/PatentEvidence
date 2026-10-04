"""FTO claim tree, technical features and per-feature comparison (ADR 0008).

Pure data structures. A claim's features start as ``proposed`` (taken from the
drafter's clause structure) and must be confirmed by a person before they are
compared: clause structure is not the same as legal claim elements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

StructureSource = Literal["uspto_grant_xml", "ops_text_parsed"]
FeatureStatus = Literal["proposed", "confirmed"]
Finding = Literal["literally_present", "present_by_equivalent", "absent", "undetermined"]
ClaimConclusion = Literal["reads_literally", "reads_by_equivalents_only", "does_not_read", "undetermined"]

# Multiple-dependent claims multiply paths; beyond this the result is undetermined, never truncated silently.
MAX_DEPENDENCY_PATHS = 256


@dataclass(frozen=True)
class ClaimFeature:
    """One technical feature, located in the claim's full text by character spans."""

    feature_id: str  # e.g. "1.0" (preamble) / "1.3"
    claim_number: int
    text: str
    spans: tuple[tuple[int, int], ...]  # [start, end) offsets into Claim.text; may be non-contiguous
    status: FeatureStatus = "proposed"


@dataclass(frozen=True)
class Claim:
    number: int
    text: str
    depends_on: tuple[int, ...]
    structure_source: StructureSource
    features: tuple[ClaimFeature, ...] = ()
    language: str | None = None
    parse_warnings: tuple[str, ...] = ()

    @property
    def independent(self) -> bool:
        return not self.depends_on


@dataclass(frozen=True)
class ClaimSet:
    publication_number: str
    claims: tuple[Claim, ...]
    language: str | None = None
    # EP: language of the proceedings (authentic text, EPC Art. 70(1)); None if not established.
    proceedings_language: str | None = None
    warnings: tuple[str, ...] = ()

    def claim(self, number: int) -> Claim:
        for claim in self.claims:
            if claim.number == number:
                return claim
        raise KeyError(number)

    @property
    def is_translation(self) -> bool | None:
        if self.language is None or self.proceedings_language is None:
            return None  # unknown: not inferred
        return self.language.upper() != self.proceedings_language.upper()

    def dependency_paths(self, number: int, *, limit: int = MAX_DEPENDENCY_PATHS) -> tuple[tuple[int, ...], bool]:
        """Every chain from an independent claim down to ``number``.

        Several references in one claim ("of claim 1 or 2", "any preceding claim")
        are alternatives, not cumulative (37 CFR 1.75(c); EPC Rule 43(4)): each
        alternative is a separate path. Returns (paths, truncated); paths are
        root-first. ``truncated`` is True when ``limit`` was reached.
        """
        paths: list[tuple[int, ...]] = []
        truncated = False

        def walk(n: int, suffix: tuple[int, ...]) -> None:
            nonlocal truncated
            if truncated:
                return
            if n in suffix:  # malformed cycle: stop this branch
                return
            claim = self.claim(n)
            if not claim.depends_on:
                if len(paths) >= limit:
                    truncated = True
                    return
                paths.append((n,) + suffix)
                return
            for parent in claim.depends_on:
                walk(parent, (n,) + suffix)

        walk(number, ())
        return tuple(paths), truncated

    def path_features(self, path: tuple[int, ...]) -> tuple[ClaimFeature, ...]:
        """Features along one dependency path (root claim first)."""
        return tuple(f for n in path for f in self.claim(n).features)


@dataclass(frozen=True)
class FeatureAssessment:
    feature_id: str
    finding: Finding
    rationale: str = ""
    product_evidence: tuple[str, ...] = ()
    assessed_by: str = ""


@dataclass
class ClaimChart:
    """Per-feature findings for one claim set against one product description."""

    claim_set: ClaimSet
    assessments: dict[str, FeatureAssessment] = field(default_factory=dict)

    def assess(self, assessment: FeatureAssessment) -> None:
        known = {f.feature_id for c in self.claim_set.claims for f in c.features}
        if assessment.feature_id not in known:
            raise KeyError(f"unknown feature {assessment.feature_id}")
        self.assessments[assessment.feature_id] = assessment
