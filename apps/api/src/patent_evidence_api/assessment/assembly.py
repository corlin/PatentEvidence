"""从案件既有数据组装预评估输入。

组装层最容易犯的错是「静默降级」：源数据里没有的东西被填成默认值，
于是跑出来的评估看起来完整，实际建立在一片空白上。这里的规则是反过来的：

- 缺了就无法评估的（本案申请日、比对单元格）→ 直接拒绝组建版本，
  不产出任何版本记录。没有基准日的日期门禁毫无意义，产出版本只会误导。
- 缺了仍能评估但会削弱结论的（对比文件申请日、来源核验、引文逐字核验）
  → 照实记入 gaps，并让领域层的既有门禁去阻塞结论，绝不替它补默认值。

特别地：数据库里没有「引文是否已逐字核验」的持久化字段，比对矩阵的
「已确认」也不等于逐字核验（前者是人工看过图表，后者要求引文能在原文块
中定位）。所以组装出的引文一律 verified=False，并记入 gaps —— 这会阻塞
结论，而阻塞正是正确的结果。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.assessment.package import AssessmentInput
from modules.assessment.rules import (
    CandidateDocument,
    DataSourceRun,
    EvidenceCitation,
    FeatureComparisonRow,
    PriorityClaim,
    SubjectApplication,
)


@dataclass(frozen=True)
class AssembledAssessment:
    payload: AssessmentInput
    gaps: tuple[str, ...]
    source: dict[str, Any]


def _parse_date(value: Any) -> date | None:
    """兼容 '2024-01-10'、'20240110' 与 date 对象；无法解析返回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        pass
    digits = raw.replace("-", "").replace("/", "").replace(".", "")
    if len(digits) == 8 and digits.isdigit():
        try:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        except ValueError:
            return None
    return None


def _priority_claims(raw: Any) -> tuple[PriorityClaim, ...]:
    if not raw:
        return ()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return ()
    if not isinstance(raw, list):
        return ()
    claims: list[PriorityClaim] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        priority_date = _parse_date(item.get("priority_date"))
        if priority_date is None:
            continue
        claims.append(
            PriorityClaim(
                claim_id=str(item.get("claim_id") or f"P{index + 1}"),
                priority_date=priority_date,
                country=str(item.get("country") or ""),
                first_application=bool(item.get("first_application", True)),
                same_subject=bool(item.get("same_subject", True)),
                proof_verified=bool(item.get("proof_verified", False)),
                covers=frozenset(str(c) for c in (item.get("covers") or [])),
            )
        )
    return tuple(claims)


class AssessmentAssemblyService:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    async def assemble(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
    ) -> AssembledAssessment:
        exists = await session.scalar(
            text("SELECT 1 FROM cases WHERE id=:case_id AND organization_id=:org_id"),
            {"case_id": case_id, "org_id": organization_id},
        )
        if not exists:
            raise HTTPException(status_code=404, detail="case_not_found")

        subject = await self._subject(session, organization_id, case_id)
        matrix_id = await self._matrix_id(session, organization_id, case_id)
        cells = await self._cells(session, organization_id, case_id, matrix_id)
        if not cells:
            raise HTTPException(status_code=422, detail="no_comparison_cells")

        documents = await self._documents(
            session, organization_id, case_id, {row["candidate_id"] for row in cells}
        )
        source_runs = await self._source_runs(session, organization_id, case_id)

        rows: list[FeatureComparisonRow] = []
        citations: list[EvidenceCitation] = []
        for cell in cells:
            doc_id = documents.cell_doc_ids.get(cell["candidate_id"])
            if doc_id is None:
                continue
            rows.append(
                FeatureComparisonRow(
                    feature_code=cell["feature_code"],
                    doc_id=doc_id,
                    judgment=cell["judgment"],
                )
            )
            # 无逐字核验记录：一律按未核验（见模块 docstring）
            citations.append(
                EvidenceCitation(
                    doc_id=doc_id,
                    feature_code=cell["feature_code"],
                    location=cell["citation_location"] or "",
                    quote=cell["citation_quote"] or "",
                    verified=False,
                )
            )

        gaps = list(documents.gaps)
        if not source_runs:
            gaps.append("无检索数据源运行记录，来源覆盖率无法计算")
        if citations:
            gaps.append(
                "组装来源无引文逐字核验记录，全部引文按未核验处理；"
                "未核验引文会阻塞结论，须人工完成逐字核对"
            )
        gaps.append("三步法第 3 步结合启示清单需人工填写，组装不代为推断")

        payload = AssessmentInput(
            subject=subject,
            documents=documents.documents,
            rows=rows,
            citations=citations,
            source_runs=source_runs,
            legal_status_as_of={},
            total_features=len({row.feature_code for row in rows}),
        )
        return AssembledAssessment(
            payload=payload,
            gaps=tuple(gaps),
            source={
                "matrix_id": str(matrix_id),
                "candidate_count": len(documents.documents),
                "cell_count": len(rows),
                "source_run_count": len(source_runs),
                "assembled_at": self._clock().isoformat(),
            },
        )

    @staticmethod
    async def _subject(
        session: AsyncSession, organization_id: UUID, case_id: UUID
    ) -> SubjectApplication:
        row = (
            await session.execute(
                text(
                    """SELECT filing_date, application_type, priority_claims
                    FROM case_application_profiles
                    WHERE organization_id=:org_id AND case_id=:case_id"""
                ),
                {"org_id": organization_id, "case_id": case_id},
            )
        ).fetchone()
        if not row or _parse_date(row.filing_date) is None:
            raise HTTPException(status_code=422, detail="application_profile_missing")
        return SubjectApplication(
            filing_date=_parse_date(row.filing_date),
            application_type=str(row.application_type or "invention"),
            priority_claims=_priority_claims(row.priority_claims),
        )

    @staticmethod
    async def _matrix_id(
        session: AsyncSession, organization_id: UUID, case_id: UUID
    ) -> UUID:
        matrix_id = await session.scalar(
            text(
                """SELECT id FROM comparison_matrices
                WHERE organization_id=:org_id AND case_id=:case_id
                ORDER BY confirmed_at DESC NULLS LAST, created_at DESC
                LIMIT 1"""
            ),
            {"org_id": organization_id, "case_id": case_id},
        )
        if matrix_id is None:
            raise HTTPException(status_code=422, detail="no_comparison_matrix")
        return matrix_id

    @staticmethod
    async def _cells(
        session: AsyncSession, organization_id: UUID, case_id: UUID, matrix_id: UUID
    ) -> list[dict[str, Any]]:
        rows = (
            await session.execute(
                text(
                    """SELECT cfc.candidate_id, cf.feature_code, cfc.judgment,
                    cfc.citation_location, cfc.citation_quote
                    FROM claim_feature_comparisons cfc
                    JOIN claim_features cf
                      ON cf.id = cfc.claim_feature_id
                     AND cf.organization_id = cfc.organization_id
                    WHERE cfc.organization_id=:org_id
                      AND cfc.case_id=:case_id
                      AND cfc.matrix_id=:matrix_id
                    ORDER BY cf.sort_order, cf.feature_code"""
                ),
                {"org_id": organization_id, "case_id": case_id, "matrix_id": matrix_id},
            )
        ).fetchall()
        return [
            {
                "candidate_id": r.candidate_id,
                "feature_code": r.feature_code,
                "judgment": r.judgment,
                "citation_location": r.citation_location,
                "citation_quote": r.citation_quote,
            }
            for r in rows
        ]

    @staticmethod
    async def _documents(
        session: AsyncSession, organization_id: UUID, case_id: UUID, candidate_ids: set[Any]
    ) -> "_DocumentBundle":
        rows = (
            await session.execute(
                text(
                    """SELECT c.id, c.publication_number, c.title, c.publication_date,
                    p.filing_date, p.priority_date, p.filed_in_china, p.source_verified
                    FROM search_candidates c
                    LEFT JOIN candidate_document_profiles p
                      ON p.candidate_id = c.id
                     AND p.organization_id = c.organization_id
                    WHERE c.organization_id=:org_id AND c.case_id=:case_id
                    ORDER BY c.created_at"""
                ),
                {"org_id": organization_id, "case_id": case_id},
            )
        ).fetchall()

        documents: list[CandidateDocument] = []
        cell_doc_ids: dict[Any, str] = {}
        gaps: list[str] = []
        used: dict[str, int] = {}

        for row in rows:
            if row.id not in candidate_ids:
                continue
            doc_id = str(row.publication_number or row.id)
            if doc_id in used:
                used[doc_id] += 1
                doc_id = f"{doc_id}#{used[doc_id]}"
            else:
                used[doc_id] = 1
            cell_doc_ids[row.id] = doc_id

            filing_date = _parse_date(row.filing_date)
            priority_date = _parse_date(row.priority_date)
            documents.append(
                CandidateDocument(
                    doc_id=doc_id,
                    publication_number=str(row.publication_number or ""),
                    title=str(row.title or ""),
                    source_verified=bool(row.source_verified),
                    publication_date=_parse_date(row.publication_date),
                    filing_date=filing_date,
                    priority_date=priority_date,
                    filed_in_china=bool(row.filed_in_china) if row.filed_in_china is not None else True,
                )
            )
            if filing_date is None and priority_date is None:
                gaps.append(
                    f"对比文件 {doc_id} 缺申请日与优先权日，"
                    "日期门禁按「日期未知」处理，不参与新颖性与创造性评价"
                )
            if not row.source_verified:
                gaps.append(f"对比文件 {doc_id} 来源未核验")

        return _DocumentBundle(documents=documents, cell_doc_ids=cell_doc_ids, gaps=gaps)

    @staticmethod
    async def _source_runs(
        session: AsyncSession, organization_id: UUID, case_id: UUID
    ) -> list[DataSourceRun]:
        rows = (
            await session.execute(
                text(
                    """SELECT source_type, status, finished_at FROM search_jobs
                    WHERE organization_id=:org_id AND case_id=:case_id
                    ORDER BY created_at"""
                ),
                {"org_id": organization_id, "case_id": case_id},
            )
        ).fetchall()
        runs: list[DataSourceRun] = []
        for row in rows:
            status = str(row.status or "").lower()
            if status in {"ok", "succeeded", "success", "completed"}:
                mapped = "ok"
            elif status in {"failed", "error"}:
                mapped = "failed"
            else:
                mapped = "partial"
            runs.append(
                DataSourceRun(
                    name=str(row.source_type or "unknown"),
                    status=mapped,
                    as_of=_parse_date(row.finished_at),
                )
            )
        return runs


@dataclass(frozen=True)
class _DocumentBundle:
    documents: list[CandidateDocument]
    cell_doc_ids: dict[Any, str]
    gaps: list[str]
