"""预评估输入档案的读写。

`case_application_profiles` 与 `candidate_document_profiles` 存的是人工录入的
输入事实，不是审批记录，所以可以改写。这不削弱评估的可追溯性：版本在创建时
就冻结了自己的评估包与摘要，改输入只能影响下一个版本，改不到已写入或已批准
的版本。

写入用 upsert，并且必须先校验所属案件与候选文献确实属于当前租户——
租户隔离不能只靠 RLS，显式校验能在拼错 id 时给出明确错误而不是静默空操作。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

VALID_APPLICATION_TYPES = ("invention", "utility_model", "design")


class AssessmentInputService:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    async def get_application_profile(
        self, session: AsyncSession, *, organization_id: UUID, case_id: UUID
    ) -> dict[str, Any] | None:
        row = (
            await session.execute(
                text(
                    """SELECT id, filing_date, application_type, priority_claims,
                    recorded_by_identity_id, created_at, updated_at
                    FROM case_application_profiles
                    WHERE organization_id=:org_id AND case_id=:case_id"""
                ),
                {"org_id": organization_id, "case_id": case_id},
            )
        ).fetchone()
        return self._application_row(row) if row else None

    async def upsert_application_profile(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        filing_date: date,
        application_type: str = "invention",
        priority_claims: list[dict[str, Any]] | None = None,
        actor_identity_id: UUID | None = None,
    ) -> dict[str, Any]:
        if application_type not in VALID_APPLICATION_TYPES:
            raise HTTPException(status_code=422, detail="unsupported_application_type")
        await self._assert_case(session, organization_id, case_id)

        now = self._clock()
        row = (
            await session.execute(
                text(
                    """INSERT INTO case_application_profiles
                    (id, organization_id, case_id, filing_date, application_type,
                     priority_claims, recorded_by_identity_id, created_at, updated_at)
                    VALUES
                    (:id, :org_id, :case_id, :filing_date, :application_type,
                     :priority_claims, :recorded_by, :created_at, :updated_at)
                    ON CONFLICT (case_id) DO UPDATE SET
                      filing_date = EXCLUDED.filing_date,
                      application_type = EXCLUDED.application_type,
                      priority_claims = EXCLUDED.priority_claims,
                      recorded_by_identity_id = EXCLUDED.recorded_by_identity_id,
                      updated_at = EXCLUDED.updated_at
                    RETURNING id, filing_date, application_type, priority_claims,
                    recorded_by_identity_id, created_at, updated_at"""
                ),
                {
                    "id": uuid4(),
                    "org_id": organization_id,
                    "case_id": case_id,
                    "filing_date": filing_date,
                    "application_type": application_type,
                    "priority_claims": _json(priority_claims or []),
                    "recorded_by": actor_identity_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        ).fetchone()
        return self._application_row(row)

    async def list_candidate_profiles(
        self, session: AsyncSession, *, organization_id: UUID, case_id: UUID
    ) -> list[dict[str, Any]]:
        rows = (
            await session.execute(
                text(
                    """SELECT p.id, p.candidate_id, c.publication_number, c.title,
                    p.filing_date, p.priority_date, p.filed_in_china, p.source_verified,
                    p.verified_by_identity_id, p.created_at, p.updated_at
                    FROM candidate_document_profiles p
                    JOIN search_candidates c
                      ON c.id = p.candidate_id AND c.organization_id = p.organization_id
                    WHERE p.organization_id=:org_id AND p.case_id=:case_id
                    ORDER BY c.created_at"""
                ),
                {"org_id": organization_id, "case_id": case_id},
            )
        ).fetchall()
        return [self._candidate_row(row) for row in rows]

    async def upsert_candidate_profile(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        candidate_id: UUID,
        filing_date: date | None = None,
        priority_date: date | None = None,
        filed_in_china: bool = True,
        source_verified: bool = False,
        actor_identity_id: UUID | None = None,
    ) -> dict[str, Any]:
        exists = await session.scalar(
            text(
                """SELECT 1 FROM search_candidates
                WHERE id=:candidate_id AND case_id=:case_id AND organization_id=:org_id"""
            ),
            {"candidate_id": candidate_id, "case_id": case_id, "org_id": organization_id},
        )
        if not exists:
            raise HTTPException(status_code=404, detail="candidate_not_found")

        now = self._clock()
        row = (
            await session.execute(
                text(
                    """INSERT INTO candidate_document_profiles
                    (id, organization_id, case_id, candidate_id, filing_date, priority_date,
                     filed_in_china, source_verified, verified_by_identity_id,
                     created_at, updated_at)
                    VALUES
                    (:id, :org_id, :case_id, :candidate_id, :filing_date, :priority_date,
                     :filed_in_china, :source_verified, :verified_by, :created_at, :updated_at)
                    ON CONFLICT (case_id, candidate_id) DO UPDATE SET
                      filing_date = EXCLUDED.filing_date,
                      priority_date = EXCLUDED.priority_date,
                      filed_in_china = EXCLUDED.filed_in_china,
                      source_verified = EXCLUDED.source_verified,
                      verified_by_identity_id = EXCLUDED.verified_by_identity_id,
                      updated_at = EXCLUDED.updated_at
                    RETURNING id, candidate_id, filing_date, priority_date,
                    filed_in_china, source_verified, verified_by_identity_id,
                    created_at, updated_at"""
                ),
                {
                    "id": uuid4(),
                    "org_id": organization_id,
                    "case_id": case_id,
                    "candidate_id": candidate_id,
                    "filing_date": filing_date,
                    "priority_date": priority_date,
                    "filed_in_china": filed_in_china,
                    "source_verified": source_verified,
                    "verified_by": actor_identity_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        ).fetchone()
        return self._candidate_row(row)

    @staticmethod
    async def _assert_case(session: AsyncSession, organization_id: UUID, case_id: UUID) -> None:
        exists = await session.scalar(
            text("SELECT 1 FROM cases WHERE id=:case_id AND organization_id=:org_id"),
            {"case_id": case_id, "org_id": organization_id},
        )
        if not exists:
            raise HTTPException(status_code=404, detail="case_not_found")

    @staticmethod
    def _application_row(row: Any) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "filing_date": row.filing_date.isoformat() if row.filing_date else None,
            "application_type": row.application_type,
            "priority_claims": _load(row.priority_claims) or [],
            "recorded_by_identity_id": (
                str(row.recorded_by_identity_id) if row.recorded_by_identity_id else None
            ),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    @staticmethod
    def _candidate_row(row: Any) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "candidate_id": str(row.candidate_id),
            "publication_number": getattr(row, "publication_number", None),
            "title": getattr(row, "title", None),
            "filing_date": row.filing_date.isoformat() if row.filing_date else None,
            "priority_date": row.priority_date.isoformat() if row.priority_date else None,
            "filed_in_china": bool(row.filed_in_china),
            "source_verified": bool(row.source_verified),
            "verified_by_identity_id": (
                str(row.verified_by_identity_id) if row.verified_by_identity_id else None
            ),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load(value: Any) -> Any:
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value
