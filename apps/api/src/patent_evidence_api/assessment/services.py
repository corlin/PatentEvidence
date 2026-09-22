"""Assessment version persistence.

Append-only by design: this service can create and read assessment versions,
never update or delete one. A revised assessment is a new version number, so a
version that has been reviewed (and later approved) always still points at the
exact package that was reviewed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
    ) -> AssessmentVersionRecord:
        """Run every gate once and freeze the resulting package as a new version."""
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
