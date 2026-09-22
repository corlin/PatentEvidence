"""Assessment version persistence.

Append-only by design: this service can create and read assessment versions,
never update or delete one. A revised assessment is a new version number, so a
version that has been reviewed (and later approved) always still points at the
exact package that was reviewed.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.assessment.approval import (
    AssessmentApprovalEngine,
    AssessmentDecisionRecord,
    AssessmentVersionStatus,
    derive_status,
)
from modules.assessment.diff import diff_packages
from modules.assessment.package import AssessmentInput, AssessmentPackage, assess_case
from modules.assessment.records import AssessmentVersionRecord, build_assessment_version_record


class AssessmentService:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    async def create_version(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        payload: AssessmentInput,
        actor_identity_id: UUID | None = None,
        extra_blockers: Iterable[str] = (),
    ) -> AssessmentVersionRecord:
        """Run every gate once and freeze the resulting package as a new version.

        `extra_blockers` 用于组装层报告的源数据缺口。它们与领域层阻塞项合并
        进记录的 blockers，但不进 payload，因此包摘要仍只覆盖领域层产物。
        """
        await self._assert_case(session, organization_id, case_id)

        package: AssessmentPackage = assess_case(payload)
        version_number = await self._next_version_number(session, organization_id, case_id)
        record = build_assessment_version_record(
            package,
            record_id=uuid4(),
            organization_id=organization_id,
            case_id=case_id,
            version_number=version_number,
            created_by_identity_id=actor_identity_id,
            created_at=self._clock(),
        )
        merged = list(record.blockers)
        for blocker in extra_blockers:
            if blocker not in merged:
                merged.append(blocker)
        if merged != list(record.blockers):
            record = replace(record, blockers=merged)

        await session.execute(
            text(
                """INSERT INTO assessment_versions
                (id, organization_id, case_id, version_number, rules_version,
                 prompt_versions, payload, payload_sha256, blockers, flags,
                 requires_human_confirmation, created_by_identity_id, created_at)
                VALUES
                (:id, :org_id, :case_id, :version_number, :rules_version,
                 :prompt_versions, :payload, :payload_sha256, :blockers, :flags,
                 :requires_human_confirmation, :created_by, :created_at)"""
            ),
            {
                "id": record.id,
                "org_id": organization_id,
                "case_id": case_id,
                "version_number": record.version_number,
                "rules_version": record.rules_version,
                "prompt_versions": json.dumps(record.prompt_versions, ensure_ascii=False),
                "payload": json.dumps(record.payload, ensure_ascii=False, sort_keys=True),
                "payload_sha256": record.payload_sha256,
                "blockers": json.dumps(record.blockers, ensure_ascii=False),
                "flags": json.dumps(record.flags, ensure_ascii=False),
                "requires_human_confirmation": record.requires_human_confirmation,
                "created_by": record.created_by_identity_id,
                "created_at": record.created_at,
            },
        )
        return record

    async def get_version(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        version_number: int,
    ) -> AssessmentVersionRecord:
        row = (
            await session.execute(
                text(
                    """SELECT id, organization_id, case_id, version_number, rules_version,
                    prompt_versions, payload, payload_sha256, blockers, flags,
                    requires_human_confirmation, created_by_identity_id, created_at
                    FROM assessment_versions
                    WHERE organization_id=:org_id AND case_id=:case_id
                    AND version_number=:version_number"""
                ),
                {
                    "org_id": organization_id,
                    "case_id": case_id,
                    "version_number": version_number,
                },
            )
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="assessment_version_not_found")
        return self._row_to_record(row)

    async def list_versions(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
    ) -> list[AssessmentVersionRecord]:
        rows = (
            await session.execute(
                text(
                    """SELECT id, organization_id, case_id, version_number, rules_version,
                    prompt_versions, payload, payload_sha256, blockers, flags,
                    requires_human_confirmation, created_by_identity_id, created_at
                    FROM assessment_versions
                    WHERE organization_id=:org_id AND case_id=:case_id
                    ORDER BY version_number DESC"""
                ),
                {"org_id": organization_id, "case_id": case_id},
            )
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    async def diff_versions(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        from_version: int,
        to_version: int,
    ) -> Any:
        """对比两个已冻结版本的 payload。

        只对比内容，不推断输入档案的变化：档案可变且未版本化，无法忠实重建
        生成各版本时的输入。方向由版本号决定，调用方不必关心先后。
        """
        older = await self.get_version(
            session,
            organization_id=organization_id,
            case_id=case_id,
            version_number=min(from_version, to_version),
        )
        newer = await self.get_version(
            session,
            organization_id=organization_id,
            case_id=case_id,
            version_number=max(from_version, to_version),
        )
        return diff_packages(
            older.payload,
            newer.payload,
            from_version=older.version_number,
            to_version=newer.version_number,
            from_payload_sha256=older.payload_sha256,
            to_payload_sha256=newer.payload_sha256,
        )

    @staticmethod
    def _row_to_record(row: Any) -> AssessmentVersionRecord:
        def load(value: Any) -> Any:
            if isinstance(value, (str, bytes, bytearray)):
                return json.loads(value)
            return value

        return AssessmentVersionRecord(
            id=row.id,
            organization_id=row.organization_id,
            case_id=row.case_id,
            version_number=row.version_number,
            rules_version=row.rules_version,
            prompt_versions=load(row.prompt_versions) or {},
            payload=load(row.payload) or {},
            payload_sha256=row.payload_sha256,
            blockers=load(row.blockers) or [],
            flags=load(row.flags) or [],
            requires_human_confirmation=bool(row.requires_human_confirmation),
            created_by_identity_id=row.created_by_identity_id,
            created_at=row.created_at,
        )

    async def submit_version(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        version_number: int,
        actor_identity_id: UUID | None = None,
    ) -> AssessmentDecisionRecord:
        """提交评估版本进入待复核。状态以追加事件记录，不改写版本行。"""
        version = await self.get_version(
            session,
            organization_id=organization_id,
            case_id=case_id,
            version_number=version_number,
        )
        decisions = await self._decision_sequence(
            session, organization_id=organization_id, version_id=version.id
        )
        AssessmentApprovalEngine.assert_transition(
            derive_status(decisions), AssessmentVersionStatus.SUBMITTED
        )
        record = AssessmentApprovalEngine.generate_submission_record(
            version_id=str(version.id),
            version_number=version.version_number,
            payload_sha256=version.payload_sha256,
            submitter_identity_id=str(actor_identity_id) if actor_identity_id else None,
            submitted_at=self._clock(),
        )
        await self._insert_decision(session, organization_id, case_id, record)
        return record

    async def decide_version(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        version_number: int,
        decision: str,
        reviewer_identity_id: UUID | None = None,
        comments: str = "",
        accepts_insufficient_evidence: bool = False,
    ) -> AssessmentDecisionRecord:
        """对评估版本作出复核决定。

        状态由既有决策流推导，任何决定都只是追加一条记录；已批准版本会被
        状态机直接拒绝。
        """
        version = await self.get_version(
            session,
            organization_id=organization_id,
            case_id=case_id,
            version_number=version_number,
        )
        decisions = await self._decision_sequence(
            session, organization_id=organization_id, version_id=version.id
        )
        current = derive_status(decisions)

        if decision == "approved":
            record = AssessmentApprovalEngine.approve(
                version_id=str(version.id),
                version_number=version.version_number,
                current_status=current,
                payload_sha256=version.payload_sha256,
                blockers=list(version.blockers),
                reviewer_identity_id=str(reviewer_identity_id) if reviewer_identity_id else None,
                comments=comments,
                accepts_insufficient_evidence=accepts_insufficient_evidence,
                decided_at=self._clock(),
            )
        elif decision == "rejected":
            record = AssessmentApprovalEngine.reject(
                version_id=str(version.id),
                version_number=version.version_number,
                current_status=current,
                payload_sha256=version.payload_sha256,
                reviewer_identity_id=str(reviewer_identity_id) if reviewer_identity_id else None,
                comments=comments,
                decided_at=self._clock(),
            )
        elif decision == "changes_requested":
            record = AssessmentApprovalEngine.request_changes(
                version_id=str(version.id),
                version_number=version.version_number,
                current_status=current,
                payload_sha256=version.payload_sha256,
                reviewer_identity_id=str(reviewer_identity_id) if reviewer_identity_id else None,
                comments=comments,
                decided_at=self._clock(),
            )
        else:
            raise HTTPException(status_code=422, detail="unsupported_decision")

        await self._insert_decision(session, organization_id, case_id, record)
        return record

    async def current_status(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        version_number: int,
    ) -> str:
        version = await self.get_version(
            session,
            organization_id=organization_id,
            case_id=case_id,
            version_number=version_number,
        )
        decisions = await self._decision_sequence(
            session, organization_id=organization_id, version_id=version.id
        )
        return derive_status(decisions)

    async def _insert_decision(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
        record: AssessmentDecisionRecord,
    ) -> None:
        await session.execute(
            text(
                """INSERT INTO assessment_version_reviews
                (id, organization_id, case_id, assessment_version_id, version_number,
                 payload_sha256, decision, reviewer_identity_id, comments, open_blockers,
                 accepts_insufficient_evidence, decision_signature, decided_at)
                VALUES
                (:id, :org_id, :case_id, :version_id, :version_number,
                 :payload_sha256, :decision, :reviewer, :comments, :open_blockers,
                 :accepts_insufficient, :signature, :decided_at)"""
            ),
            {
                "id": uuid4(),
                "org_id": organization_id,
                "case_id": case_id,
                "version_id": UUID(record.version_id),
                "version_number": record.version_number,
                "payload_sha256": record.payload_sha256,
                "decision": record.decision,
                "reviewer": UUID(record.reviewer_identity_id) if record.reviewer_identity_id else None,
                "comments": record.comments,
                "open_blockers": json.dumps(list(record.open_blockers), ensure_ascii=False),
                "accepts_insufficient": record.accepts_insufficient_evidence,
                "signature": record.decision_signature,
                "decided_at": record.decided_at,
            },
        )

    @staticmethod
    async def _decision_sequence(
        session: AsyncSession, organization_id: UUID, version_id: UUID
    ) -> list[str]:
        rows = (
            await session.execute(
                text(
                    """SELECT decision FROM assessment_version_reviews
                    WHERE organization_id=:org_id AND assessment_version_id=:version_id
                    ORDER BY decided_at, created_at"""
                ),
                {"org_id": organization_id, "version_id": version_id},
            )
        ).fetchall()
        return [row.decision for row in rows]

    @staticmethod
    async def _assert_case(session: AsyncSession, organization_id: UUID, case_id: UUID) -> None:
        exists = await session.scalar(
            text("SELECT 1 FROM cases WHERE id=:case_id AND organization_id=:org_id"),
            {"case_id": case_id, "org_id": organization_id},
        )
        if not exists:
            raise HTTPException(status_code=404, detail="case_not_found")

    @staticmethod
    async def _next_version_number(
        session: AsyncSession, organization_id: UUID, case_id: UUID
    ) -> int:
        current = await session.scalar(
            text(
                """SELECT MAX(version_number) FROM assessment_versions
                WHERE organization_id=:org_id AND case_id=:case_id"""
            ),
            {"org_id": organization_id, "case_id": case_id},
        )
        return (current or 0) + 1
