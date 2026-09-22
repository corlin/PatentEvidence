from __future__ import annotations

from datetime import UTC, datetime

import pytest

from modules.assessment.approval import (
    AssessmentApprovalEngine,
    AssessmentApprovalError,
    AssessmentVersionStatus,
    derive_status,
)

VERSION_ID = "11111111-1111-1111-1111-111111111111"
DIGEST = "a" * 64
FIXED = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def test_derive_status_from_empty_event_stream_is_draft() -> None:
    assert derive_status([]) == AssessmentVersionStatus.DRAFT


def test_derive_status_maps_each_decision() -> None:
    assert derive_status(["submitted"]) == AssessmentVersionStatus.SUBMITTED
    assert derive_status(["submitted", "approved"]) == AssessmentVersionStatus.APPROVED
    assert derive_status(["submitted", "rejected"]) == AssessmentVersionStatus.REJECTED
    # 打回修改后回到草稿，等待再次提交
    assert derive_status(["submitted", "changes_requested"]) == AssessmentVersionStatus.DRAFT
    assert derive_status(["submitted", "changes_requested", "submitted"]) == (
        AssessmentVersionStatus.SUBMITTED
    )


def test_submit_from_draft_is_allowed() -> None:
    record = AssessmentApprovalEngine.generate_submission_record(
        version_id=VERSION_ID,
        version_number=1,
        payload_sha256=DIGEST,
        submitter_identity_id="agent-1",
        submitted_at=FIXED,
    )
    assert record.decision == "submitted"
    assert len(record.decision_signature) == 64


def test_approve_without_blockers_succeeds() -> None:
    record = AssessmentApprovalEngine.approve(
        version_id=VERSION_ID,
        version_number=1,
        current_status=AssessmentVersionStatus.SUBMITTED,
        payload_sha256=DIGEST,
        blockers=[],
        reviewer_identity_id="reviewer-1",
        decided_at=FIXED,
    )
    assert record.decision == "approved"
    assert record.open_blockers == ()
    assert record.accepts_insufficient_evidence is False


def test_approve_with_open_blockers_is_refused() -> None:
    with pytest.raises(AssessmentApprovalError) as exc:
        AssessmentApprovalEngine.approve(
            version_id=VERSION_ID,
            version_number=1,
            current_status=AssessmentVersionStatus.SUBMITTED,
            payload_sha256=DIGEST,
            blockers=["引证未定位：D1/F2"],
            reviewer_identity_id="reviewer-1",
            decided_at=FIXED,
        )
    assert exc.value.code == "blockers_open"
    assert "引证未定位" in exc.value.message


def test_approving_insufficient_evidence_requires_a_reason() -> None:
    with pytest.raises(AssessmentApprovalError) as exc:
        AssessmentApprovalEngine.approve(
            version_id=VERSION_ID,
            version_number=1,
            current_status=AssessmentVersionStatus.SUBMITTED,
            payload_sha256=DIGEST,
            blockers=["引证未核验"],
            reviewer_identity_id="reviewer-1",
            comments="",
            accepts_insufficient_evidence=True,
            decided_at=FIXED,
        )
    assert exc.value.code == "acceptance_reason_required"


def test_approving_insufficient_evidence_with_reason_is_recorded() -> None:
    record = AssessmentApprovalEngine.approve(
        version_id=VERSION_ID,
        version_number=1,
        current_status=AssessmentVersionStatus.SUBMITTED,
        payload_sha256=DIGEST,
        blockers=["引证未核验"],
        reviewer_identity_id="reviewer-1",
        comments="客户确认不再补充检索，结论按证据不足交付",
        accepts_insufficient_evidence=True,
        decided_at=FIXED,
    )
    assert record.decision == "approved"
    assert record.accepts_insufficient_evidence is True
    assert record.open_blockers == ("引证未核验",)


def test_draft_cannot_be_approved_without_submission() -> None:
    with pytest.raises(AssessmentApprovalError) as exc:
        AssessmentApprovalEngine.approve(
            version_id=VERSION_ID,
            version_number=1,
            current_status=AssessmentVersionStatus.DRAFT,
            payload_sha256=DIGEST,
            blockers=[],
            reviewer_identity_id="reviewer-1",
            decided_at=FIXED,
        )
    assert exc.value.code == "invalid_transition"


def test_approved_version_is_frozen() -> None:
    with pytest.raises(AssessmentApprovalError) as exc:
        AssessmentApprovalEngine.reject(
            version_id=VERSION_ID,
            version_number=1,
            current_status=AssessmentVersionStatus.APPROVED,
            payload_sha256=DIGEST,
            reviewer_identity_id="reviewer-1",
            decided_at=FIXED,
        )
    assert exc.value.code == "version_frozen"


def test_rejected_version_is_also_frozen() -> None:
    with pytest.raises(AssessmentApprovalError) as exc:
        AssessmentApprovalEngine.approve(
            version_id=VERSION_ID,
            version_number=1,
            current_status=AssessmentVersionStatus.REJECTED,
            payload_sha256=DIGEST,
            blockers=[],
            reviewer_identity_id="reviewer-1",
            decided_at=FIXED,
        )
    assert exc.value.code == "version_frozen"


def test_request_changes_returns_version_to_draft() -> None:
    record = AssessmentApprovalEngine.request_changes(
        version_id=VERSION_ID,
        version_number=1,
        current_status=AssessmentVersionStatus.SUBMITTED,
        payload_sha256=DIGEST,
        reviewer_identity_id="reviewer-1",
        comments="补充 F3 的引证位置",
        decided_at=FIXED,
    )
    assert record.decision == "changes_requested"
    assert derive_status(["submitted", "changes_requested"]) == AssessmentVersionStatus.DRAFT


def test_signature_binds_payload_digest_and_reviewer() -> None:
    base = AssessmentApprovalEngine.approve(
        version_id=VERSION_ID,
        version_number=1,
        current_status=AssessmentVersionStatus.SUBMITTED,
        payload_sha256=DIGEST,
        blockers=[],
        reviewer_identity_id="reviewer-1",
        decided_at=FIXED,
    )
    other_reviewer = AssessmentApprovalEngine.approve(
        version_id=VERSION_ID,
        version_number=1,
        current_status=AssessmentVersionStatus.SUBMITTED,
        payload_sha256=DIGEST,
        blockers=[],
        reviewer_identity_id="reviewer-2",
        decided_at=FIXED,
    )
    other_digest = AssessmentApprovalEngine.approve(
        version_id=VERSION_ID,
        version_number=1,
        current_status=AssessmentVersionStatus.SUBMITTED,
        payload_sha256="b" * 64,
        blockers=[],
        reviewer_identity_id="reviewer-1",
        decided_at=FIXED,
    )

    assert base.decision_signature != other_reviewer.decision_signature
    assert base.decision_signature != other_digest.decision_signature


def test_decision_record_is_serialisable() -> None:
    record = AssessmentApprovalEngine.reject(
        version_id=VERSION_ID,
        version_number=2,
        current_status=AssessmentVersionStatus.SUBMITTED,
        payload_sha256=DIGEST,
        reviewer_identity_id="reviewer-1",
        comments="结论与证据不符",
        decided_at=FIXED,
    )
    payload = record.to_dict()
    assert payload["version_number"] == 2
    assert isinstance(payload["open_blockers"], list)
    assert payload["decision_signature"] == record.decision_signature
