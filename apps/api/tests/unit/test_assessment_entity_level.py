from __future__ import annotations

from datetime import date

from modules.assessment.package import AssessmentInput, assess_case
from modules.assessment.rules import (
    CandidateDocument,
    ConceptRelation,
    EntityObservationEffect,
    FeatureComparisonRow,
    KnownSubstitute,
    NumericRange,
    SubjectApplication,
    entity_level_observations,
    novelty_findings,
    observe_concept_relations,
    observe_known_substitutes,
    observe_numeric_ranges,
)


def test_overlapping_numeric_range_is_only_a_candidate() -> None:
    observations = observe_numeric_ranges(
        [
            NumericRange(
                "F1", "D1", claimed_lower=8.0, claimed_upper=16.0,
                disclosed_lower=4.0, disclosed_upper=12.0,
            )
        ]
    )

    assert observations[0].effect == EntityObservationEffect.MAY_DEFEAT
    assert observations[0].requires_human_confirmation is True
    assert "不作认定" in observations[0].reasoning


def test_disjoint_numeric_range_does_not_defeat() -> None:
    observations = observe_numeric_ranges(
        [
            NumericRange(
                "F1", "D1", claimed_lower=8.0, claimed_upper=16.0,
                disclosed_lower=20.0, disclosed_upper=30.0,
            )
        ]
    )

    assert observations[0].effect == EntityObservationEffect.DOES_NOT_DEFEAT
    assert "选择发明" in observations[0].reasoning


def test_example_point_value_is_noted_as_possible_exception() -> None:
    observations = observe_numeric_ranges(
        [
            NumericRange(
                "F1", "D1", claimed_lower=8.0, claimed_upper=16.0,
                disclosed_lower=10.0, disclosed_upper=10.0, disclosed_is_example=True,
            )
        ]
    )

    assert observations[0].effect == EntityObservationEffect.MAY_DEFEAT
    assert "实施例点值" in observations[0].reasoning


def test_incomplete_numeric_range_is_undetermined() -> None:
    observations = observe_numeric_ranges(
        [NumericRange("F1", "D1", claimed_lower=8.0, disclosed_upper=12.0)]
    )

    assert observations[0].effect == EntityObservationEffect.UNDETERMINED


def test_generic_disclosure_does_not_defeat_specific_claim() -> None:
    observations = observe_concept_relations(
        [ConceptRelation("F1", "D1", claimed_concept="铜", disclosed_concept="金属", relation="generic_disclosed")]
    )

    assert observations[0].effect == EntityObservationEffect.DOES_NOT_DEFEAT


def test_specific_disclosure_may_defeat_generic_claim() -> None:
    observations = observe_concept_relations(
        [ConceptRelation("F1", "D1", claimed_concept="金属", disclosed_concept="铜", relation="specific_disclosed")]
    )

    assert observations[0].effect == EntityObservationEffect.MAY_DEFEAT


def test_unknown_concept_relation_is_undetermined() -> None:
    observations = observe_concept_relations(
        [ConceptRelation("F1", "D1", claimed_concept="导热件", disclosed_concept="散热片", relation="synonym")]
    )

    assert observations[0].effect == EntityObservationEffect.UNDETERMINED


def test_documented_known_substitute_may_defeat() -> None:
    observations = observe_known_substitutes(
        [
            KnownSubstitute(
                "F1", "D1", claimed_means="螺栓连接", disclosed_means="螺钉连接",
                substitutability_documented=True,
            )
        ]
    )

    assert observations[0].effect == EntityObservationEffect.MAY_DEFEAT


def test_undocumented_substitute_is_never_presumed() -> None:
    observations = observe_known_substitutes(
        [KnownSubstitute("F1", "D1", claimed_means="螺栓连接", disclosed_means="焊接")]
    )

    assert observations[0].effect == EntityObservationEffect.UNDETERMINED
    assert "不得推定" in observations[0].reasoning


def _subject() -> SubjectApplication:
    return SubjectApplication(filing_date=date(2025, 6, 1))


def _documents() -> list[CandidateDocument]:
    return [
        CandidateDocument(
            "D1", "CN1A", "doc one", source_verified=True,
            publication_date=date(2024, 1, 10), filing_date=date(2023, 5, 1),
        )
    ]


def test_observations_never_upgrade_a_novelty_gate() -> None:
    """回归铁律：实体级观察项只能出候选，绝不能让单篇全覆盖门禁改判。"""
    rows = [
        FeatureComparisonRow("F1", "D1", "different"),
        FeatureComparisonRow("F2", "D1", "different"),
    ]

    before = novelty_findings(rows, total_features=2)
    entity_level_observations(
        ranges=[NumericRange("F1", "D1", claimed_lower=1.0, claimed_upper=5.0, disclosed_lower=2.0, disclosed_upper=4.0)],
        relations=[ConceptRelation("F2", "D1", claimed_concept="金属", disclosed_concept="铜", relation="specific_disclosed")],
    )
    after = novelty_findings(rows, total_features=2)

    assert before == []
    assert after == []


def test_package_carries_observations_without_changing_gate() -> None:
    rows = [
        FeatureComparisonRow("F1", "D1", "different"),
        FeatureComparisonRow("F2", "D1", "different"),
    ]
    package = assess_case(
        AssessmentInput(
            subject=_subject(),
            documents=_documents(),
            rows=rows,
            numeric_ranges=[
                NumericRange("F1", "D1", claimed_lower=8.0, claimed_upper=16.0, disclosed_lower=4.0, disclosed_upper=12.0)
            ],
            concept_relations=[
                ConceptRelation("F2", "D1", claimed_concept="铜", disclosed_concept="金属", relation="generic_disclosed")
            ],
            known_substitutes=[KnownSubstitute("F2", "D1", claimed_means="螺栓", disclosed_means="螺钉")],
        )
    )

    assert len(package.entity_observations) == 3
    assert package.entity_observations[0].effect == EntityObservationEffect.MAY_DEFEAT
    assert package.entity_observations[1].effect == EntityObservationEffect.DOES_NOT_DEFEAT
    assert package.entity_observations[2].effect == EntityObservationEffect.UNDETERMINED
    assert all(item.requires_human_confirmation for item in package.entity_observations)
    # 门禁未因此触发：无新颖性高风险结论
    assert not any(f.risk_kind == "novelty" for f in package.findings)
    assert any("实体级候选观察项" in flag for flag in package.flags)
    assert any("证据不足" in flag for flag in package.flags)
    assert isinstance(package.to_dict()["entity_observations"], list)
