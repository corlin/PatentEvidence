import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.reports.generator import MarkdownReportGenerator
from modules.reports.sealer import EvidenceSealer
from modules.review.workflow import ReviewWorkflowEngine


class ReviewService:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._sealer = EvidenceSealer()
        self._generator = MarkdownReportGenerator()

    async def submit_case_for_review(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        actor_identity_id: UUID,
        submitter_notes: str = "",
    ) -> dict[str, Any]:
        """Submit a case for review, automatically capturing the current snapshot and report."""
        # 1. Verify case exists
        case = await session.execute(
            text(
                """SELECT id, case_number, title, status FROM cases
                WHERE id=:case_id AND organization_id=:org_id"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        case_row = case.fetchone()
        if not case_row:
            raise HTTPException(status_code=404, detail="case_not_found")

        # 2. Get or create latest snapshot and report
        snapshot = await session.execute(
            text(
                """SELECT id, root_sha256 FROM evidence_snapshots
                WHERE case_id=:case_id AND organization_id=:org_id
                ORDER BY created_at DESC LIMIT 1"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        snapshot_row = snapshot.fetchone()
        snapshot_id = snapshot_row.id if snapshot_row else None

        report = await session.execute(
            text(
                """SELECT id FROM analysis_reports
                WHERE case_id=:case_id AND organization_id=:org_id
                ORDER BY created_at DESC LIMIT 1"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        report_row = report.fetchone()
        report_id = report_row.id if report_row else None

        # 3. Determine next round number
        prev_round = await session.scalar(
            text(
                """SELECT MAX(round_number) FROM review_submissions
                WHERE case_id=:case_id AND organization_id=:org_id"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        round_number = (prev_round or 0) + 1

        # 4. Insert submission
        submission_id = uuid4()
        now = self._clock()
        await session.execute(
            text(
                """INSERT INTO review_submissions
                (id, organization_id, case_id, round_number, evidence_snapshot_id, report_id,
                 submitter_identity_id, submitter_notes, status, created_at, updated_at)
                VALUES
                (:id, :org_id, :case_id, :round_number, :snapshot_id, :report_id,
                 :submitter_id, :notes, 'pending', :now, :now)"""
            ),
            {
                "id": submission_id,
                "org_id": organization_id,
                "case_id": case_id,
                "round_number": round_number,
                "snapshot_id": snapshot_id,
                "report_id": report_id,
                "submitter_id": actor_identity_id,
                "notes": submitter_notes,
                "now": now,
            },
        )

        # 5. Update case status to in_review
        await session.execute(
            text(
                """UPDATE cases SET status='in_review', updated_at=:now
                WHERE id=:case_id AND organization_id=:org_id"""
            ),
            {"case_id": case_id, "org_id": organization_id, "now": now},
        )

        return {
            "id": str(submission_id),
            "case_id": str(case_id),
            "round_number": round_number,
            "evidence_snapshot_id": str(snapshot_id) if snapshot_id else None,
            "report_id": str(report_id) if report_id else None,
            "submitter_identity_id": str(actor_identity_id),
            "submitter_notes": submitter_notes,
            "status": "pending",
            "created_at": now.isoformat(),
        }

    async def get_current_review(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
    ) -> dict[str, Any] | None:
        """Get the active or latest review submission with decision and submitter info."""
        res = await session.execute(
            text(
                """SELECT s.id, s.round_number, s.evidence_snapshot_id, s.report_id,
                          s.submitter_identity_id, s.submitter_notes, s.status, s.created_at, s.updated_at,
                          d.id as decision_id, d.decision, d.overall_comments, d.itemized_feedback,
                          d.is_self_audit, d.decision_signature, d.created_at as decided_at,
                          es.root_sha256
                   FROM review_submissions s
                   LEFT JOIN review_decisions d ON d.review_submission_id = s.id
                   LEFT JOIN evidence_snapshots es ON es.id = s.evidence_snapshot_id
                   WHERE s.case_id = :case_id AND s.organization_id = :org_id
                   ORDER BY s.round_number DESC LIMIT 1"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        row = res.fetchone()
        if not row:
            return None

        return {
            "id": str(row.id),
            "case_id": str(case_id),
            "round_number": row.round_number,
            "evidence_snapshot_id": str(row.evidence_snapshot_id) if row.evidence_snapshot_id else None,
            "root_sha256": row.root_sha256,
            "report_id": str(row.report_id) if row.report_id else None,
            "submitter_identity_id": str(row.submitter_identity_id) if row.submitter_identity_id else None,
            "submitter_notes": row.submitter_notes,
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "decision": {
                "id": str(row.decision_id),
                "decision": row.decision,
                "overall_comments": row.overall_comments,
                "itemized_feedback": row.itemized_feedback if isinstance(row.itemized_feedback, list) else json.loads(row.itemized_feedback or "[]"),
                "is_self_audit": row.is_self_audit,
                "decision_signature": row.decision_signature,
                "decided_at": row.decided_at.isoformat() if row.decided_at else None,
            } if row.decision_id else None,
        }

    async def list_review_history(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
    ) -> list[dict[str, Any]]:
        """List all review submissions and decisions across all rounds."""
        res = await session.execute(
            text(
                """SELECT s.id, s.round_number, s.evidence_snapshot_id, s.report_id,
                          s.submitter_identity_id, s.submitter_notes, s.status, s.created_at,
                          d.id as decision_id, d.reviewer_identity_id, d.decision, d.overall_comments,
                          d.itemized_feedback, d.is_self_audit, d.decision_signature, d.created_at as decided_at
                   FROM review_submissions s
                   LEFT JOIN review_decisions d ON d.review_submission_id = s.id
                   WHERE s.case_id = :case_id AND s.organization_id = :org_id
                   ORDER BY s.round_number ASC"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        rows = res.fetchall()
        items: list[dict[str, Any]] = []
        for r in rows:
            items.append({
                "id": str(r.id),
                "round_number": r.round_number,
                "evidence_snapshot_id": str(r.evidence_snapshot_id) if r.evidence_snapshot_id else None,
                "report_id": str(r.report_id) if r.report_id else None,
                "submitter_identity_id": str(r.submitter_identity_id) if r.submitter_identity_id else None,
                "submitter_notes": r.submitter_notes,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "decision": {
                    "id": str(r.decision_id),
                    "reviewer_identity_id": str(r.reviewer_identity_id) if r.reviewer_identity_id else None,
                    "decision": r.decision,
                    "overall_comments": r.overall_comments,
                    "itemized_feedback": r.itemized_feedback if isinstance(r.itemized_feedback, list) else json.loads(r.itemized_feedback or "[]"),
                    "is_self_audit": r.is_self_audit,
                    "decision_signature": r.decision_signature,
                    "decided_at": r.decided_at.isoformat() if r.decided_at else None,
                } if r.decision_id else None,
            })
        return items

    async def record_review_decision(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        submission_id: UUID,
        actor_identity_id: UUID,
        decision: str,
        overall_comments: str = "",
        itemized_feedback: list[dict[str, Any]] | None = None,
        is_self_audit: bool = False,
    ) -> dict[str, Any]:
        """Record a review decision ('approved' | 'changes_requested' | 'rejected')."""
        if decision not in ("approved", "changes_requested", "rejected"):
            raise HTTPException(status_code=422, detail="invalid_decision_type")

        # 1. Fetch submission
        sub_res = await session.execute(
            text(
                """SELECT s.id, s.round_number, s.submitter_identity_id, s.evidence_snapshot_id, es.root_sha256
                FROM review_submissions s
                LEFT JOIN evidence_snapshots es ON es.id = s.evidence_snapshot_id
                WHERE s.id=:sub_id AND s.case_id=:case_id AND s.organization_id=:org_id"""
            ),
            {"sub_id": submission_id, "case_id": case_id, "org_id": organization_id},
        )
        sub = sub_res.fetchone()
        if not sub:
            raise HTTPException(status_code=404, detail="review_submission_not_found")

        # 2. Check self-audit
        actual_self_audit = is_self_audit or (sub.submitter_identity_id == actor_identity_id)

        now = self._clock()
        root_sha256 = sub.root_sha256 or "0000000000000000000000000000000000000000000000000000000000000000"
        signature = ReviewWorkflowEngine.generate_decision_signature(
            submission_id=str(submission_id),
            case_id=str(case_id),
            reviewer_identity_id=str(actor_identity_id),
            decision=decision,
            root_sha256=root_sha256,
            decided_at=now.isoformat(),
        )

        itemized = itemized_feedback or []

        # 3. Insert decision
        decision_id = uuid4()
        await session.execute(
            text(
                """INSERT INTO review_decisions
                (id, organization_id, review_submission_id, case_id, reviewer_identity_id,
                 decision, overall_comments, itemized_feedback, is_self_audit, decision_signature, created_at)
                VALUES
                (:id, :org_id, :sub_id, :case_id, :reviewer_id,
                 :decision, :comments, :feedback, :self_audit, :signature, :now)"""
            ),
            {
                "id": decision_id,
                "org_id": organization_id,
                "sub_id": submission_id,
                "case_id": case_id,
                "reviewer_id": actor_identity_id,
                "decision": decision,
                "comments": overall_comments,
                "feedback": json.dumps(itemized),
                "self_audit": actual_self_audit,
                "signature": signature,
                "now": now,
            },
        )

        # 4. Update submission status
        await session.execute(
            text(
                """UPDATE review_submissions
                SET status=:status, updated_at=:now
                WHERE id=:sub_id AND organization_id=:org_id"""
            ),
            {"status": decision, "now": now, "sub_id": submission_id, "org_id": organization_id},
        )

        # 5. Update case status
        new_case_status = "approved" if decision == "approved" else ("changes_requested" if decision == "changes_requested" else "draft")
        await session.execute(
            text(
                """UPDATE cases
                SET status=:status, updated_at=:now
                WHERE id=:case_id AND organization_id=:org_id"""
            ),
            {"status": new_case_status, "now": now, "case_id": case_id, "org_id": organization_id},
        )

        return {
            "decision_id": str(decision_id),
            "submission_id": str(submission_id),
            "case_id": str(case_id),
            "decision": decision,
            "case_status": new_case_status,
            "overall_comments": overall_comments,
            "itemized_feedback": itemized,
            "is_self_audit": actual_self_audit,
            "decision_signature": signature,
            "decided_at": now.isoformat(),
        }

    async def deliver_case(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        actor_identity_id: UUID,
        client_recipient: str = "",
    ) -> dict[str, Any]:
        """Perform formal delivery to client, seal delivery record and mark case as delivered."""
        # 1. Verify case
        case_res = await session.execute(
            text(
                """SELECT id, status FROM cases
                WHERE id=:case_id AND organization_id=:org_id"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        case = case_res.fetchone()
        if not case:
            raise HTTPException(status_code=404, detail="case_not_found")

        # 2. Get latest approved or pending submission
        sub_res = await session.execute(
            text(
                """SELECT id, evidence_snapshot_id, report_id FROM review_submissions
                WHERE case_id=:case_id AND organization_id=:org_id
                ORDER BY round_number DESC LIMIT 1"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        sub = sub_res.fetchone()

        snapshot_id = sub.evidence_snapshot_id if sub else None
        report_id = sub.report_id if sub else None
        sub_id = sub.id if sub else None

        # 3. Create delivery record
        delivery_id = uuid4()
        now = self._clock()
        token = ReviewWorkflowEngine.generate_download_token(str(case_id), str(organization_id))

        await session.execute(
            text(
                """INSERT INTO delivery_records
                (id, organization_id, case_id, review_submission_id, final_snapshot_id,
                 final_report_id, delivered_by_identity_id, client_recipient, download_token,
                 delivered_at, created_at)
                VALUES
                (:id, :org_id, :case_id, :sub_id, :snap_id, :rep_id, :deliv_id,
                 :client, :token, :now, :now)"""
            ),
            {
                "id": delivery_id,
                "org_id": organization_id,
                "case_id": case_id,
                "sub_id": sub_id,
                "snap_id": snapshot_id,
                "rep_id": report_id,
                "deliv_id": actor_identity_id,
                "client": client_recipient,
                "token": token,
                "now": now,
            },
        )

        # 4. Update case status to delivered
        await session.execute(
            text(
                """UPDATE cases SET status='delivered', updated_at=:now
                WHERE id=:case_id AND organization_id=:org_id"""
            ),
            {"case_id": case_id, "org_id": organization_id, "now": now},
        )

        return {
            "id": str(delivery_id),
            "case_id": str(case_id),
            "status": "delivered",
            "client_recipient": client_recipient,
            "download_token": token,
            "delivered_at": now.isoformat(),
        }

    async def get_delivery_record(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
    ) -> dict[str, Any] | None:
        """Get the latest delivery record for a case."""
        res = await session.execute(
            text(
                """SELECT d.id, d.case_id, d.client_recipient, d.download_token,
                          d.delivered_at, d.created_at, es.root_sha256, ar.title as report_title
                   FROM delivery_records d
                   LEFT JOIN evidence_snapshots es ON es.id = d.final_snapshot_id
                   LEFT JOIN analysis_reports ar ON ar.id = d.final_report_id
                   WHERE d.case_id = :case_id AND d.organization_id = :org_id
                   ORDER BY d.created_at DESC LIMIT 1"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        row = res.fetchone()
        if not row:
            return None

        return {
            "id": str(row.id),
            "case_id": str(row.case_id),
            "client_recipient": row.client_recipient,
            "download_token": row.download_token,
            "root_sha256": row.root_sha256,
            "report_title": row.report_title,
            "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
        }
