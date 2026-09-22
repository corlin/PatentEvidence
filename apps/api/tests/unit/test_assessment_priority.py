from __future__ import annotations

from datetime import date

from modules.assessment.rules import (
    CandidateDocument,
    FeatureComparisonRow,
    PriorityClaim,
    ReferenceKind,
    SubjectApplication,
    classify_all_references,
    classify_reference,
    classify_reference_for_features,
    priority_verification_findings,
    verify_priority,
)

FEATURES = ("F1", "F2", "F3")


def _subject(**kwargs: object) -> SubjectApplication:
    base: dict[str, object] = {"filing_date": date(2025, 6, 1)}
    base.update(kwargs)
    return SubjectApplication(**base)  # type: ignore[arg-type]


def test_single_priority_within_term_sets_earlier_reference_date() -> None:
    verification = verify_priority(
        _subject(priority_claims=(PriorityClaim("P1", date(2024, 12, 1), proof_verified=True),)),
        FEATURES,
    )

    assert verification.valid_claims == ("P1",)
    assert verification.default_reference_date == date(2024, 12, 1)
    assert verification.reference_date_for("F1") == date(2024, 12, 1)


def test_priority_beyond_twelve_months_is_invalid_and_falls_back_to_filing_date() -> None:
    verification = verify_priority(
        _subject(priority_claims=(PriorityClaim("P1", date(2024, 5, 1), proof_verified=True),)),
        FEATURES,
    )

    assert verification.valid_claims == ()
    assert verification.default_reference_date == date(2025, 6, 1)
    assert verification.invalid_claims[0]["reason"].startswith("超出 12 个月优先权期限")


def test_design_priority_term_is_six_months() -> None:
    within = verify_priority(
        _subject(
            application_type="design",
            priority_claims=(PriorityClaim("P1", date(2025, 1, 20), proof_verified=True),),
        ),
        FEATURES,
    )
    assert within.valid_claims == ("P1",)

    beyond = verify_priority(
        _subject(
            application_type="design",
            priority_claims=(PriorityClaim("P1", date(2024, 11, 20), proof_verified=True),),
        ),
        FEATURES,
    )
    assert beyond.valid_claims == ()


def test_non_first_application_is_invalid() -> None:
    verification = verify_priority(
        _subject(
            priority_claims=(
                PriorityClaim("P1", date(2024, 12, 1), first_application=False, proof_verified=True),
            )
        ),
        FEATURES,
    )

    assert verification.valid_claims == ()
    assert "第一次申请" in verification.invalid_claims[0]["reason"]


def test_unverified_proof_is_valid_but_flagged() -> None:
    verification = verify_priority(
        _subject(priority_claims=(PriorityClaim("P1", date(2024, 12, 1), proof_verified=False),)),
        FEATURES,
    )

    assert verification.valid_claims == ("P1",)
    assert any("证明文件" in flag for flag in verification.flags)
    assert verification.requires_human_confirmation is True


def test_multiple_priorities_take_the_earliest_valid_one() -> None:
    verification = verify_priority(
        _subject(
            priority_claims=(
                PriorityClaim("P1", date(2024, 12, 1), proof_verified=True),
                PriorityClaim("P2", date(2024, 8, 15), proof_verified=True),
            )
        ),
        FEATURES,
    )

    assert verification.default_reference_date == date(2024, 8, 15)


def test_partial_priority_gives_different_reference_dates_per_feature() -> None:
    verification = verify_priority(
        _subject(
            priority_claims=(
                PriorityClaim("P1", date(2024, 8, 15), proof_verified=True, covers=frozenset({"F1", "F2"})),
            )
        ),
        FEATURES,
    )

    assert verification.reference_date_for("F1") == date(2024, 8, 15)
    assert verification.reference_date_for("F2") == date(2024, 8, 15)
    assert verification.reference_date_for("F3") == date(2025, 6, 1)
    assert any("部分优先权" in flag for flag in verification.flags)


def test_partial_priority_splits_reference_classification_per_feature() -> None:
    subject = _subject(
        priority_claims=(
            PriorityClaim("P1", date(2024, 8, 15), proof_verified=True, covers=frozenset({"F1"})),
        )
    )
    verification = verify_priority(subject, FEATURES)
    doc = CandidateDocument(
        "D1", "CN1A", "doc", publication_date=date(2024, 12, 1), filing_date=date(2024, 6, 1)
    )

    per_feature = classify_reference_for_features(doc, subject, verification, list(FEATURES))

    # 公开于 2024-12-01：晚于 F2/F3 的基准日 2025-06-01？否 -> 早于，属现有技术
    assert per_feature["F2"] == ReferenceKind.PRIOR_ART
    # 对 F1（基准日 2024-08-15）公开在后、申请在先 -> 抵触申请
    assert per_feature["F1"] == ReferenceKind.CONFLICTING_APPLICATION

    aggregated = classify_all_references([doc], subject, verification, [])
    assert aggregated == {"D1": classify_reference(doc, subject, verification)}


def test_document_level_kind_takes_the_most_conservative_per_feature_result() -> None:
    subject = _subject(
        priority_claims=(
            PriorityClaim("P1", date(2024, 8, 15), proof_verified=True, covers=frozenset({"F1"})),
        )
    )
    verification = verify_priority(subject, FEATURES)
    doc = CandidateDocument(
        "D1", "CN1A", "doc", publication_date=date(2024, 12, 1), filing_date=date(2024, 6, 1)
    )
    rows = [
        FeatureComparisonRow("F1", "D1", "identical"),
        FeatureComparisonRow("F2", "D1", "identical"),
    ]

    kinds = classify_all_references([doc], subject, verification, rows)

    assert kinds == {"D1": ReferenceKind.CONFLICTING_APPLICATION}


def test_priority_findings_are_emitted_only_when_something_is_wrong() -> None:
    clean = priority_verification_findings(
        _subject(priority_claims=(PriorityClaim("P1", date(2024, 12, 1), proof_verified=True),)),
        FEATURES,
    )
    assert clean == []

    broken = priority_verification_findings(
        _subject(priority_claims=(PriorityClaim("P1", date(2024, 2, 1), proof_verified=True),)),
        FEATURES,
    )
    assert len(broken) == 1
    assert broken[0].risk_kind == "priority_verification"
    assert broken[0].requires_human_confirmation is True


def test_invalid_priority_changes_reference_classification() -> None:
    subject = _subject(
        priority_claims=(PriorityClaim("P1", date(2024, 2, 1), proof_verified=True),)
    )
    verification = verify_priority(subject, FEATURES)
    doc = CandidateDocument(
        "D1", "CN1A", "doc", publication_date=date(2024, 12, 1), filing_date=date(2024, 6, 1)
    )

    # 优先权不成立 -> 基准日回落到申请日 2025-06-01 -> 公开在先，属现有技术
    assert classify_reference(doc, subject, verification, "F1") == ReferenceKind.PRIOR_ART
