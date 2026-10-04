"""Claim-level conclusions from per-feature findings (ADR 0008).

All-elements rule: a claim reads on the product only if every feature is present
(literally or by an equivalent). Each dependency path of a multiple-dependent
claim is a separate alternative; the claim reads if any path reads.

These are risk indications, not legal opinions. Whether something is an
equivalent is a professional judgment supplied as a finding; nothing here
computes it.
"""

from __future__ import annotations

from dataclasses import dataclass

from modules.fto.model import ClaimChart, ClaimConclusion, ClaimFeature


@dataclass(frozen=True)
class PathConclusion:
    path: tuple[int, ...]
    conclusion: ClaimConclusion
    absent: tuple[str, ...]  # features found absent (the "broken elements")
    undetermined: tuple[str, ...]  # features without a finding, or found undetermined
    unconfirmed: tuple[str, ...]  # features still "proposed", not confirmed by a person


@dataclass(frozen=True)
class ClaimResult:
    claim_number: int
    conclusion: ClaimConclusion
    paths: tuple[PathConclusion, ...]  # per-path detail for display; may be capped
    truncated: bool  # True if the path list was capped (the conclusion itself is still exact)


def conclude_features(chart: ClaimChart, features: tuple[ClaimFeature, ...], path: tuple[int, ...]) -> PathConclusion:
    absent, undetermined, unconfirmed, equivalent = [], [], [], False
    for feature in features:
        if feature.status != "confirmed":
            unconfirmed.append(feature.feature_id)
        assessment = chart.assessments.get(feature.feature_id)
        finding = assessment.finding if assessment else "undetermined"
        if finding == "absent":
            absent.append(feature.feature_id)
        elif finding == "undetermined":
            undetermined.append(feature.feature_id)
        elif finding == "present_by_equivalent":
            equivalent = True
    if absent:
        conclusion: ClaimConclusion = "does_not_read"
    elif undetermined or unconfirmed:
        # Unreviewed feature boundaries could hide a missing feature: never conclude "reads".
        conclusion = "undetermined"
    else:
        conclusion = "reads_by_equivalents_only" if equivalent else "reads_literally"
    return PathConclusion(path, conclusion, tuple(absent), tuple(undetermined), tuple(unconfirmed))


_RANK = {"reads_literally": 3, "reads_by_equivalents_only": 2, "undetermined": 1, "does_not_read": 0}


def _own_conclusion(chart: ClaimChart, number: int) -> ClaimConclusion:
    claim = chart.claim_set.claim(number)
    return conclude_features(chart, claim.features, (number,)).conclusion


def claim_conclusion(chart: ClaimChart, number: int, _memo: dict[int, ClaimConclusion] | None = None) -> ClaimConclusion:
    """Exact all-elements conclusion over every dependency path, without enumerating them.

    A claim does not read if one of its own features is absent, or if no parent
    path can read. It reads if its own features are present and at least one
    parent reads (alternatives). Otherwise it is undetermined.
    """
    memo = {} if _memo is None else _memo
    if number in memo:
        return memo[number]
    memo[number] = "undetermined"  # cycle guard: a malformed cycle never yields "reads"
    claim = chart.claim_set.claim(number)
    own = _own_conclusion(chart, number)
    if own == "does_not_read" or not claim.depends_on:
        memo[number] = own
        return own
    parents = [claim_conclusion(chart, p, memo) for p in claim.depends_on]
    if all(c == "does_not_read" for c in parents):
        result: ClaimConclusion = "does_not_read"
    elif own == "undetermined":
        result = "undetermined"
    else:
        best = max(parents, key=_RANK.__getitem__)
        if best == "reads_literally" and own == "reads_literally":
            result = "reads_literally"
        elif best in ("reads_literally", "reads_by_equivalents_only"):
            result = "reads_by_equivalents_only"
        else:
            result = "undetermined"
    memo[number] = result
    return result


def conclude_claim(chart: ClaimChart, number: int) -> ClaimResult:
    """Exact conclusion, plus per-path detail (paths are examples, capped for display)."""
    paths, truncated = chart.claim_set.dependency_paths(number)
    results = tuple(conclude_features(chart, chart.claim_set.path_features(p), p) for p in paths)
    return ClaimResult(number, claim_conclusion(chart, number), results, truncated)
