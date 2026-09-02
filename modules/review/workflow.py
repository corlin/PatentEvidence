from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


@dataclass
class ItemizedFeedback:
    feature_id: str
    feature_code: str
    comment: str
    suggested_judgment: str | None = None


@dataclass
class ReviewSubmissionInfo:
    id: str
    organization_id: str
    case_id: str
    round_number: int
    evidence_snapshot_id: str | None
    report_id: str | None
    submitter_identity_id: str | None
    submitter_notes: str
    status: str
    created_at: str
    updated_at: str


@dataclass
class ReviewDecisionInfo:
    id: str
    organization_id: str
    review_submission_id: str
    case_id: str
    reviewer_identity_id: str | None
    decision: str  # 'approved' | 'changes_requested' | 'rejected'
    overall_comments: str
    itemized_feedback: list[dict[str, Any]]
    is_self_audit: bool
    decision_signature: str
    created_at: str


@dataclass
class DeliveryRecordInfo:
    id: str
    organization_id: str
    case_id: str
    review_submission_id: str | None
    final_snapshot_id: str | None
    final_report_id: str | None
    delivered_by_identity_id: str | None
    client_recipient: str
    download_token: str
    delivered_at: str
    created_at: str


class ReviewWorkflowEngine:
    """Core domain logic for patent case review, multi-round iteration diff, and delivery sealing."""

    @staticmethod
    def generate_decision_signature(
        *,
        submission_id: str,
        case_id: str,
        reviewer_identity_id: str | None,
        decision: str,
        root_sha256: str,
        decided_at: str,
    ) -> str:
        """Create a cryptographic SHA-256 signature binding the reviewer, decision, and evidence Merkle root."""
        payload = f"submission:{submission_id}|case:{case_id}|reviewer:{reviewer_identity_id}|decision:{decision}|merkle_root:{root_sha256}|timestamp:{decided_at}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def generate_download_token(case_id: str, organization_id: str) -> str:
        """Generate a cryptographically secure opaque token for verified client report downloads."""
        random_part = secrets.token_urlsafe(32)
        return f"dlv_{hashlib.sha256(f'{case_id}:{organization_id}:{random_part}'.encode()).hexdigest()[:48]}"

    @staticmethod
    def compute_revision_diff(
        previous_comparisons: list[dict[str, Any]],
        current_comparisons: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Compute the visual diff between two rounds of Claim Chart comparison items."""
        diffs: list[dict[str, Any]] = []
        prev_map = {
            f"{c.get('claim_feature_id')}_{c.get('candidate_id')}": c
            for c in previous_comparisons
        }

        for cur in current_comparisons:
            key = f"{cur.get('claim_feature_id')}_{cur.get('candidate_id')}"
            prev = prev_map.get(key)
            if not prev:
                diffs.append({
                    "feature_id": cur.get("claim_feature_id"),
                    "candidate_id": cur.get("candidate_id"),
                    "field": "item",
                    "change_type": "added",
                    "previous": None,
                    "current": cur.get("judgment"),
                    "summary": f"新增对比项，判定为 {cur.get('judgment')}",
                })
                continue

            # Check judgment change
            if prev.get("judgment") != cur.get("judgment"):
                diffs.append({
                    "feature_id": cur.get("claim_feature_id"),
                    "candidate_id": cur.get("candidate_id"),
                    "field": "judgment",
                    "change_type": "modified",
                    "previous": prev.get("judgment"),
                    "current": cur.get("judgment"),
                    "summary": f"三态判定由 [{prev.get('judgment')}] 调整为 [{cur.get('judgment')}]",
                })

            # Check citation changes
            if prev.get("citation_text") != cur.get("citation_text"):
                diffs.append({
                    "feature_id": cur.get("claim_feature_id"),
                    "candidate_id": cur.get("candidate_id"),
                    "field": "citation_text",
                    "change_type": "modified",
                    "previous": prev.get("citation_text"),
                    "current": cur.get("citation_text"),
                    "summary": "引文佐证段落已更新",
                })

        return diffs
