from __future__ import annotations

from datetime import date

from modules.assessment.rules import (
    AuxiliaryFactor,
    CandidateDocument,
    FeatureComparisonRow,
    MotivationChecklist,
    ReferenceKind,
    SubjectApplication,
    ThreeStepScaffold,
    classify_reference,
    combination_findings,
    evaluate_auxiliary_factors,
    evidence_completeness_finding,
    hindsight_risk,
    motivation_checklist_state,
    novelty_findings,
    reference_eligibility_findings,
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


def _subject() -> SubjectApplication:
    return SubjectApplication(filing_date=date(2025, 6, 1), priority_date=date(2024, 12, 1))


def test_classify_reference_prior_art_when_published_before_reference_date() -> None:
    doc = CandidateDocument(
        "D1", "CN1A", "doc", publication_date=date(2024, 1, 10), filing_date=date(2023, 5, 1)
    )
    assert classify_reference(doc, _subject()) == ReferenceKind.PRIOR_ART


def test_classify_reference_conflicting_application_when_filed_earlier_published_later() -> None:
    doc = CandidateDocument(
        "D2", "CN2A", "doc", publication_date=date(2025, 9, 1), filing_date=date(2024, 3, 1)
    )
    assert classify_reference(doc, _subject()) == ReferenceKind.CONFLICTING_APPLICATION


def test_classify_reference_foreign_later_filing_is_not_conflicting() -> None:
    doc = CandidateDocument(
        "D3", "EP3A", "doc", publication_date=date(2025, 9, 1),
        filing_date=date(2024, 3, 1), filed_in_china=False,
    )
    assert classify_reference(doc, _subject()) == ReferenceKind.NOT_USABLE


def test_classify_reference_unknown_when_dates_missing() -> None:
    doc = CandidateDocument("D4", "CN4A", "doc")
    assert classify_reference(doc, _subject()) == ReferenceKind.UNKNOWN


def test_conflicting_application_counts_for_novelty_only() -> None:
    kinds = {"D2": ReferenceKind.CONFLICTING_APPLICATION}
    rows = _rows_all_identical("D2", ("F1", "F2"))

    novelty = novelty_findings(rows, total_features=2, reference_kinds=kinds)
    assert len(novelty) == 1
    assert "仅可用于评价新颖性" in novelty[0].reasoning

    assert combination_findings(rows, total_features=2, reference_kinds=kinds) == []


def test_unusable_reference_is_excluded_from_novelty_and_flagged() -> None:
    doc = CandidateDocument(
        "D5", "CN5A", "doc", publication_date=date(2025, 12, 1), filing_date=date(2025, 7, 1)
    )
    findings = reference_eligibility_findings([doc], _subject())
    assert len(findings) == 1
    assert findings[0].risk_kind == "reference_eligibility"
    assert "不能用于评价新颖性或创造性" in findings[0].reasoning

    assert novelty_findings(
        _rows_all_identical("D5", ("F1", "F2")),
        total_features=2,
        reference_kinds={"D5": ReferenceKind.NOT_USABLE},
    ) == []


def test_closest_prior_art_skips_conflicting_application() -> None:
    rows = _rows_all_identical("D9", ("F1", "F2", "F3")) + _rows_all_identical("D1", ("F1",))
    scaffold = three_step_scaffold(
        rows, reference_kinds={"D9": ReferenceKind.CONFLICTING_APPLICATION}
    )

    assert scaffold is not None
    assert scaffold.closest_prior_art == "D1"


def test_motivation_checklist_blocks_conclusion_when_incomplete() -> None:
    state = motivation_checklist_state(MotivationChecklist(common_knowledge="no"))
    assert state["complete"] is False
    assert state["blocks_conclusion"] is True
    assert len(state["unanswered"]) == 4


def test_motivation_checklist_flags_items_favouring_inventiveness() -> None:
    filled = MotivationChecklist(
        common_knowledge="no",
        explicit_teaching="no",
        prejudice_or_teaching_away="yes",
        combination_obstacle="no",
        effect_predictability="unexpected",
    )
    state = motivation_checklist_state(filled)
    assert state["complete"] is True
    assert state["blocks_conclusion"] is False
    assert state["favouring_inventiveness"] == ["prejudice_or_teaching_away"]


def test_commercial_success_without_causal_link_is_unsubstantiated() -> None:
    result = evaluate_auxiliary_factors([
        AuxiliaryFactor("commercial_success", claimed=True, evidence_cited=True),
        AuxiliaryFactor("unexpected_effect", claimed=True, evidence_cited=True),
    ])
    statuses = {entry["kind"]: entry["status"] for entry in result["counted"]}
    assert statuses["commercial_success"] == "unsubstantiated"
    assert statuses["unexpected_effect"] == "counted"
    assert "不得单独作为具备创造性的依据" in result["note"]


def test_hindsight_risk_when_problem_restates_distinguishing_feature() -> None:
    risk = hindsight_risk("如何在解码阶段采用低位宽映射", ["在解码阶段采用低位宽映射"])
    assert risk["hindsight_risk"] is True

    clean = hindsight_risk("如何在不增加硬件面积的前提下降低推理功耗", ["在解码阶段采用低位宽映射"])
    assert clean["hindsight_risk"] is False
