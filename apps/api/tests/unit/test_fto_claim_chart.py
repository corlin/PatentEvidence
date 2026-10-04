"""FTO claim tree, features and all-elements conclusions (ADR 0008), on real claims."""

from __future__ import annotations

import json
import random
from dataclasses import replace
from pathlib import Path

import pytest

from modules.fto.chart import claim_conclusion, conclude_claim, conclude_features
from modules.fto.ep_claims import parse_ep_claims
from modules.fto.model import ClaimChart, ClaimSet, FeatureAssessment
from modules.fto.us_claims import parse_us_claims

FIX = Path(__file__).resolve().parents[4] / "fixtures" / "fto"


def _us(number: str) -> ClaimSet:
    return parse_us_claims((FIX / "us" / f"US-{number}-claims.xml").read_text(), publication_number=f"US-{number}-B2")


def _ep(publication: str) -> ClaimSet:
    return parse_ep_claims(json.loads((FIX / "ep" / f"{publication}-claims.json").read_text()), publication_number=publication)


def _confirmed(claim_set: ClaimSet) -> ClaimSet:
    return replace(
        claim_set,
        claims=tuple(replace(c, features=tuple(replace(f, status="confirmed") for f in c.features)) for c in claim_set.claims),
    )


# ------------------------------------------------------------------ US parsing


def test_us_structure_comes_from_office_markup() -> None:
    claims = _us("8623541")
    assert len(claims.claims) == 14
    assert [c.number for c in claims.claims if c.independent] == [1, 12, 13, 14]
    assert claims.claim(2).depends_on == (1,)
    assert {c.structure_source for c in claims.claims} == {"uspto_grant_xml"}


def test_us_dependency_chain_and_paths() -> None:
    claims = _us("10505211")
    assert claims.claim(3).depends_on == (2,)
    assert claims.dependency_paths(3) == (((1, 2, 3),), False)


def test_us_preamble_and_clauses_with_exact_spans() -> None:
    claims = _us("12630442")
    claim = claims.claim(1)
    # The claim number sits in <b>1</b>; the preamble is in its tail.
    assert claim.features[0].text == "A method for preparing a lithium-rich carbonate precursor comprising:"
    assert claim.features[1].text.startswith("(1) mixing a soluble nickel salt")
    assert len(claim.features) == 9  # preamble + steps (1)-(7) + wherein clause
    for feature in claim.features:
        assert " ".join(claim.text[s:e] for s, e in feature.spans) == feature.text


def test_us_long_clauses_are_flagged_for_splitting() -> None:
    claim = _us("8623541").claim(1)
    assert len(claim.features[0].text) > 400
    assert any("feature 1.0" in w and "split during review" in w for w in claim.parse_warnings)


# ------------------------------------------------------------------ EP parsing


def test_ep_claims_and_dependencies_match_the_wording() -> None:
    """Hand-checked against the EN text of EP-1819002-B1 ('of claim 1 or 2', 'of any of the preceding claims')."""
    claims = _ep("EP-1819002-B1")
    assert len(claims.claims) == 15  # 18 paragraphs include continuation paragraphs
    deps = {c.number: c.depends_on for c in claims.claims}
    assert deps[2] == (1,)
    assert deps[3] == (1, 2) and deps[4] == (1, 2)
    assert deps[5] == (1, 2, 3, 4)
    assert deps[6] == (5,) and deps[8] == (7,) and deps[9] == (7,)
    assert {c.structure_source for c in claims.claims} == {"ops_text_parsed"}
    assert any("preceding claims" in w for w in claims.claim(5).parse_warnings)


def test_ep_range_reference() -> None:
    assert _ep("EP-3467934-B1").claim(6).depends_on == (1, 2, 3, 4, 5)  # "one of claims 1 to 5"


def test_ep_authentic_language_is_not_inferred() -> None:
    claims = _ep("EP-2277223-B1")
    assert claims.proceedings_language is None
    assert claims.is_translation is None
    assert any("may be a translation" in w for w in claims.warnings)


def test_ep_feature_split_keeps_conjunction_with_next_feature() -> None:
    features = [f.text for f in _ep("EP-1819002-B1").claim(1).features]
    assert features[1] == "a negative electrode comprising zinc or a zinc compound;"
    assert "and" not in features  # no bare conjunction features
    assert any(f.startswith("and\nan electrolyte comprising:") for f in features)


# ------------------------------------------------------------------ conclusions


def _chart(claim_set: ClaimSet, finding: str = "literally_present") -> ClaimChart:
    chart = ClaimChart(claim_set)
    for claim in claim_set.claims:
        for feature in claim.features:
            chart.assess(FeatureAssessment(feature.feature_id, finding))  # type: ignore[arg-type]
    return chart


def test_all_elements_rule() -> None:
    claims = _confirmed(_us("12451529"))
    chart = _chart(claims)
    assert claim_conclusion(chart, 1) == "reads_literally"
    chart.assess(FeatureAssessment("1.2", "present_by_equivalent", rationale="judged equivalent by reviewer"))
    assert claim_conclusion(chart, 1) == "reads_by_equivalents_only"
    chart.assess(FeatureAssessment("1.3", "absent"))
    result = conclude_claim(chart, 1)
    assert result.conclusion == "does_not_read"
    assert result.paths[0].absent == ("1.3",)
    # A dependent claim inherits the missing feature.
    assert claim_conclusion(chart, 2) == "does_not_read"


def test_unconfirmed_features_never_read() -> None:
    claims = _us("12451529")  # features still "proposed"
    assert claim_conclusion(_chart(claims), 1) == "undetermined"


def test_missing_finding_is_undetermined_not_present() -> None:
    claims = _confirmed(_us("12451529"))
    chart = _chart(claims)
    del chart.assessments["1.1"]
    assert claim_conclusion(chart, 1) == "undetermined"


def test_multiple_dependent_claim_reads_through_any_alternative() -> None:
    """Claim 3 'of claim 1 or 2': a feature missing only in claim 2 must not block the claim-1 path."""
    claims = _confirmed(_ep("EP-1819002-B1"))
    chart = _chart(claims)
    chart.assess(FeatureAssessment(claims.claim(2).features[-1].feature_id, "absent"))
    assert claim_conclusion(chart, 2) == "does_not_read"
    assert claim_conclusion(chart, 3) == "reads_literally"
    assert claims.dependency_paths(3)[0] == ((1, 3), (1, 2, 3))


def test_assessing_unknown_feature_is_rejected() -> None:
    with pytest.raises(KeyError):
        _chart(_us("12451529")).assess(FeatureAssessment("99.9", "absent"))


def _brute_force(chart: ClaimChart, number: int) -> str:
    paths, _ = chart.claim_set.dependency_paths(number, limit=10**6)
    results = [conclude_features(chart, chart.claim_set.path_features(p), p).conclusion for p in paths]
    if "reads_literally" in results:
        return "reads_literally"
    if "reads_by_equivalents_only" in results:
        return "reads_by_equivalents_only"
    if all(r == "does_not_read" for r in results):
        return "does_not_read"
    return "undetermined"


def test_exact_conclusion_matches_full_path_enumeration() -> None:
    """Randomized findings on a real tree with up to 2,304 paths per claim."""
    claims = _confirmed(_ep("EP-1819002-B1"))
    feature_ids = [f.feature_id for c in claims.claims for f in c.features]
    rng = random.Random(20261004)
    weights = {"literally_present": 6, "present_by_equivalent": 2, "absent": 1, "undetermined": 1}
    for _ in range(150):
        chart = ClaimChart(claims)
        for fid in feature_ids:
            chart.assess(FeatureAssessment(fid, rng.choices(list(weights), list(weights.values()))[0]))  # type: ignore[arg-type]
        for claim in claims.claims:
            assert claim_conclusion(chart, claim.number) == _brute_force(chart, claim.number)
