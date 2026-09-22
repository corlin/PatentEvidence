from __future__ import annotations

from datetime import date

from modules.assessment.package import AssessmentInput, assess_case
from modules.assessment.rules import (
    AuxiliaryFactor,
    CandidateDocument,
    DataSourceRun,
    EvidenceCitation,
    FeatureComparisonRow,
    MotivationChecklist,
    SubjectApplication,
)


def _subject() -> SubjectApplication:
    return SubjectApplication(filing_date=date(2025, 6, 1))


def _documents() -> list[CandidateDocument]:
    return [
        CandidateDocument(
            "D1", "CN1A", "doc one", source_verified=True,
            publication_date=date(2024, 1, 10), filing_date=date(2023, 5, 1),
        ),
        CandidateDocument(
            "D2", "CN2A", "doc two", source_verified=True,
            publication_date=date(2024, 3, 20), filing_date=date(2023, 8, 1),
        ),
    ]


def _rows() -> list[FeatureComparisonRow]:
    return [
        FeatureComparisonRow("F1", "D1", "identical"),
        FeatureComparisonRow("F2", "D1", "different"),
        FeatureComparisonRow("F1", "D2", "different"),
        FeatureComparisonRow("F2", "D2", "identical"),
    ]


def _citations() -> list[EvidenceCitation]:
    return [
        EvidenceCitation("D1", "F1", location="[0012]", quote="低位宽映射", verified=True),
        EvidenceCitation("D1", "F2", location="[0015]", quote="无此特征", verified=True),
        EvidenceCitation("D2", "F1", location="[0021]", quote="无此特征", verified=True),
        EvidenceCitation("D2", "F2", location="[0024]", quote="混合精度调度", verified=True),
    ]


def _checklist() -> MotivationChecklist:
    return MotivationChecklist(
        common_knowledge="no",
        explicit_teaching="no",
        prejudice_or_teaching_away="no",
        combination_obstacle="no",
        effect_predictability="unexpected",
    )


def test_assess_case_runs_every_gate_and_returns_a_package() -> None:
    package = assess_case(
        AssessmentInput(
            subject=_subject(),
            documents=_documents(),
            rows=_rows(),
            citations=_citations(),
            source_runs=[DataSourceRun("epo", "ok"), DataSourceRun("uspto", "ok")],
            legal_status_as_of={"D1": date(2026, 1, 5), "D2": date(2026, 1, 5)},
            motivation_checklist=_checklist(),
            auxiliary_factors=[AuxiliaryFactor("unexpected_effect", claimed=True, evidence_cited=True)],
            actual_technical_problem="如何在不增加硬件面积的前提下降低推理功耗",
            distinguishing_feature_statements=["在解码阶段采用低位宽映射"],
        )
    )

    assert package.rules_version == "assessment-rules-v2"
    assert package.reference_kinds == {"D1": "prior_art", "D2": "prior_art"}
    assert package.three_step is not None
    assert package.three_step.closest_prior_art in {"D1", "D2"}
    assert package.motivation is not None and package.motivation["complete"] is True
    assert package.hindsight is not None and package.hindsight["hindsight_risk"] is False
    assert package.blockers == []
    assert package.evidence.source_coverage == 1.0
    assert package.prompt_versions["assessment/inventive_step"] == "inventive-step-v2"
    assert any(f.risk_kind == "inventive_combination" for f in package.findings)


def test_assess_case_blocks_when_step3_checklist_missing() -> None:
    package = assess_case(
        AssessmentInput(
            subject=_subject(),
            documents=_documents(),
            rows=_rows(),
            citations=_citations(),
            legal_status_as_of={"D1": date(2026, 1, 5), "D2": date(2026, 1, 5)},
        )
    )

    assert any("第 3 步" in blocker for blocker in package.blockers)
    assert package.requires_human_confirmation is True


def test_assess_case_propagates_evidence_blocking_gaps() -> None:
    incomplete = [c for c in _citations() if c.feature_code != "F2"]
    package = assess_case(
        AssessmentInput(
            subject=_subject(),
            documents=_documents(),
            rows=_rows(),
            citations=incomplete,
            motivation_checklist=_checklist(),
        )
    )

    assert any("引证未定位" in blocker or "缺失比对单元格" in blocker for blocker in package.blockers)
    assert package.requires_human_confirmation is True


def test_assess_case_flags_hindsight_and_combination_confirmation() -> None:
    package = assess_case(
        AssessmentInput(
            subject=_subject(),
            documents=_documents(),
            rows=_rows(),
            citations=_citations(),
            motivation_checklist=_checklist(),
            actual_technical_problem="如何在解码阶段采用低位宽映射",
            distinguishing_feature_statements=["在解码阶段采用低位宽映射"],
        )
    )

    assert any("事后诸葛亮" in flag for flag in package.flags)
    assert any("人工确认" in flag for flag in package.flags)


def test_assess_case_blocks_when_no_usable_prior_art() -> None:
    late = [
        CandidateDocument(
            "D9", "CN9A", "late", publication_date=date(2025, 12, 1), filing_date=date(2025, 7, 1)
        )
    ]
    package = assess_case(
        AssessmentInput(
            subject=_subject(),
            documents=late,
            rows=[FeatureComparisonRow("F1", "D9", "identical")],
            motivation_checklist=_checklist(),
        )
    )

    assert package.three_step is None
    assert any("最接近的现有技术" in blocker for blocker in package.blockers)


def test_package_is_serialisable() -> None:
    package = assess_case(
        AssessmentInput(subject=_subject(), documents=_documents(), rows=_rows(), citations=_citations())
    )
    payload = package.to_dict()

    assert payload["rules_version"] == "assessment-rules-v2"
    assert isinstance(payload["findings"], list)
    assert isinstance(payload["evidence"], dict)
