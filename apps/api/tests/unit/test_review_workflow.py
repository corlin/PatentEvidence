import pytest
from modules.review.workflow import ReviewWorkflowEngine


def test_review_workflow_engine_signature():
    sig1 = ReviewWorkflowEngine.generate_decision_signature(
        submission_id="sub-123",
        case_id="case-456",
        reviewer_identity_id="user-789",
        decision="approved",
        root_sha256="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        decided_at="2026-09-02T12:00:00Z",
    )
    assert len(sig1) == 64
    assert isinstance(sig1, str)

    # Different decision yields different signature
    sig2 = ReviewWorkflowEngine.generate_decision_signature(
        submission_id="sub-123",
        case_id="case-456",
        reviewer_identity_id="user-789",
        decision="changes_requested",
        root_sha256="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        decided_at="2026-09-02T12:00:00Z",
    )
    assert sig1 != sig2


def test_review_workflow_engine_download_token():
    token = ReviewWorkflowEngine.generate_download_token("case-1", "org-1")
    assert token.startswith("dlv_")
    assert len(token) > 20


def test_review_workflow_engine_revision_diff():
    prev = [
        {
            "claim_feature_id": "feat-1",
            "candidate_id": "cand-1",
            "judgment": "identical",
            "citation_text": "Paragraph [0012]",
        }
    ]
    cur = [
        {
            "claim_feature_id": "feat-1",
            "candidate_id": "cand-1",
            "judgment": "equivalent",
            "citation_text": "Paragraph [0012] and [0015]",
        },
        {
            "claim_feature_id": "feat-2",
            "candidate_id": "cand-1",
            "judgment": "none",
            "citation_text": "",
        },
    ]

    diffs = ReviewWorkflowEngine.compute_revision_diff(prev, cur)
    assert len(diffs) == 3
    # Check judgment modified
    judgment_diff = next(d for d in diffs if d["field"] == "judgment")
    assert judgment_diff["previous"] == "identical"
    assert judgment_diff["current"] == "equivalent"

    # Check added feature
    added_diff = next(d for d in diffs if d["change_type"] == "added")
    assert added_diff["feature_id"] == "feat-2"
