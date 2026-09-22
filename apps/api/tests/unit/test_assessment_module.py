from __future__ import annotations

from modules.assessment.rules import (
    CandidateDocument,
    FeatureComparisonRow,
    ThreeStepScaffold,
    combination_findings,
    evidence_completeness_finding,
    novelty_findings,
    three_step_scaffold,
)


def _rows_all_identical(doc: str, features: tuple[str, ...]) -> list[FeatureComparisonRow]:
    return [FeatureComparisonRow(feature_code=f, doc_id=doc, judgment="identical") for f in features]


def test_novelty_gate_fires_only_on_single_reference_all_elements() -> None:
    features = ("F1", "F2", "F3")
    rows = _rows_all_identical("D1", features)
    findings = novelty_findings(rows, total_features=len(features))

    assert len(findings) == 1
    assert findings[0].level == "high_novelty_risk"
    assert findings[0].risk_kind == "novelty"
    assert {b["feature_code"] for b in findings[0].basis} == set(features)


def test_equivalent_substitutes_do_not_trigger_the_novelty_gate() -> None:
    features = ("F1", "F2", "F3")
    rows = _rows_all_identical("D1", features)
    rows[-1] = FeatureComparisonRow(feature_code="F3", doc_id="D1", judgment="equivalent")

    findings = novelty_findings(rows, total_features=len(features))
    assert len(findings) == 1
    assert findings[0].level == "needs_confirmation"
    assert findings[0].requires_human_confirmation is True


def test_covering_pair_becomes_combination_candidate_never_a_conclusion() -> None:
    features = ("F1", "F2", "F3")
    rows = _rows_all_identical("D1", features[:2]) + _rows_all_identical("D2", features[2:])
    findings = combination_findings(rows, total_features=len(features))

    assert len(findings) == 1
    assert findings[0].risk_kind == "inventive_combination"
    assert findings[0].level == "needs_confirmation"
    assert findings[0].requires_human_confirmation is True
    assert "不给结论" in findings[0].reasoning


def test_non_covering_pair_produces_no_combination_finding() -> None:
    rows = _rows_all_identical("D1", ("F1", "F2")) + [
        FeatureComparisonRow("F2", "D2", "identical"),
        FeatureComparisonRow("F3", "D2", "different"),
    ]
    assert combination_findings(rows, total_features=3) == []


def test_evidence_completeness_reports_unverified_sources_and_uncovered_features() -> None:
    rows = [
        FeatureComparisonRow("F1", "D1", "identical"),
        FeatureComparisonRow("F1", "D2", "insufficient_evidence"),
        FeatureComparisonRow("F2", "D1", "equivalent"),
    ]
    documents = [
        CandidateDocument("D1", "CN1A", "doc one", source_verified=True),
        CandidateDocument("D2", "CN2A", "doc two"),
    ]
    finding = evidence_completeness_finding(rows, total_features=3, documents=documents)

    assert finding.level == "needs_confirmation"
    assert "未核验原文来源 D2" in finding.reasoning


def test_three_step_scaffold_selects_closest_prior_art_and_distinguishing_features() -> None:
    rows = [
        FeatureComparisonRow("F1", "D1", "identical"),
        FeatureComparisonRow("F2", "D1", "identical"),
        FeatureComparisonRow("F3", "D1", "insufficient_evidence"),
        FeatureComparisonRow("F1", "D2", "identical"),
        FeatureComparisonRow("F2", "D2", "different"),
        FeatureComparisonRow("F3", "D2", "different"),
    ]
    scaffold = three_step_scaffold(rows)

    assert isinstance(scaffold, ThreeStepScaffold)
    assert scaffold.closest_prior_art == "D1"
    assert scaffold.closest_prior_art_identical == 2
    assert scaffold.distinguishing_features == ["F3"]
    assert "占位" in scaffold.actual_technical_problem


def test_three_step_scaffold_returns_none_without_rows() -> None:
    assert three_step_scaffold([]) is None
