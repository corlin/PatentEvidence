from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException

from patent_evidence_api.assessment.assembly import (
    AssessmentAssemblyService,
    _parse_date,
)

ORG = uuid4()
CASE = uuid4()
MATRIX = uuid4()
CAND_1 = uuid4()
CAND_2 = uuid4()


def row(**kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


class FakeResult:
    def __init__(self, rows: list[Any] | None = None, scalar: Any = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Any]:
        return self._rows

    def scalar(self) -> Any:
        return self._scalar


class FakeSession:
    """按 SQL 特征分派的会话替身。"""

    def __init__(
        self,
        *,
        case_exists: bool = True,
        profile: Any = None,
        matrix_id: Any = MATRIX,
        cells: list[Any] | None = None,
        candidates: list[Any] | None = None,
        jobs: list[Any] | None = None,
    ) -> None:
        self.case_exists = case_exists
        self.profile = profile
        self.matrix_id = matrix_id
        self.cells = cells if cells is not None else []
        self.candidates = candidates if candidates is not None else []
        self.jobs = jobs if jobs is not None else []
        self.statements: list[str] = []

    async def execute(self, statement: Any, params: Any = None) -> FakeResult:
        sql = str(statement)
        self.statements.append(sql)
        if "FROM cases" in sql:
            return FakeResult(scalar=1 if self.case_exists else None)
        if "FROM case_application_profiles" in sql:
            return FakeResult(rows=[self.profile] if self.profile else [])
        if "FROM claim_feature_comparisons" in sql:
            return FakeResult(rows=self.cells)
        if "FROM search_candidates" in sql:
            return FakeResult(rows=self.candidates)
        if "FROM search_jobs" in sql:
            return FakeResult(rows=self.jobs)
        return FakeResult()

    async def scalar(self, statement: Any, params: Any = None) -> Any:
        sql = str(statement)
        self.statements.append(sql)
        if "FROM cases" in sql:
            return 1 if self.case_exists else None
        if "FROM comparison_matrices" in sql:
            return self.matrix_id
        return None


def _service() -> AssessmentAssemblyService:
    return AssessmentAssemblyService(lambda: datetime(2026, 9, 22, 12, 0, tzinfo=UTC))


def _profile() -> SimpleNamespace:
    return row(
        filing_date=date(2025, 6, 1),
        application_type="invention",
        priority_claims=[
            {"claim_id": "P1", "priority_date": "2024-06-01", "proof_verified": True}
        ],
    )


def _candidates() -> list[SimpleNamespace]:
    return [
        row(
            id=CAND_1,
            publication_number="CN1A",
            title="doc one",
            publication_date="2024-01-10",
            filing_date=date(2023, 5, 1),
            priority_date=None,
            filed_in_china=True,
            source_verified=True,
        ),
        row(
            id=CAND_2,
            publication_number="CN2A",
            title="doc two",
            publication_date="2024-03-20",
            filing_date=None,
            priority_date=None,
            filed_in_china=True,
            source_verified=False,
        ),
    ]


def _cells() -> list[SimpleNamespace]:
    return [
        row(
            candidate_id=CAND_1,
            feature_code="F1",
            judgment="identical",
            citation_location="[0012]",
            citation_quote="低位宽映射",
        ),
        row(
            candidate_id=CAND_1,
            feature_code="F2",
            judgment="different",
            citation_location="[0015]",
            citation_quote="无此特征",
        ),
        row(
            candidate_id=CAND_2,
            feature_code="F2",
            judgment="identical",
            citation_location="[0024]",
            citation_quote="混合精度调度",
        ),
    ]


def _jobs() -> list[SimpleNamespace]:
    return [
        row(source_type="epo", status="ok", finished_at=datetime(2026, 9, 1, 10, 0)),
        row(source_type="cnipr", status="failed", finished_at=None),
    ]


@pytest.mark.asyncio
async def test_assemble_builds_input_from_case_data() -> None:
    session = FakeSession(profile=_profile(), cells=_cells(), candidates=_candidates(), jobs=_jobs())
    assembled = await _service().assemble(session, organization_id=ORG, case_id=CASE)

    assert assembled.payload.subject.filing_date == date(2025, 6, 1)
    assert assembled.payload.subject.priority_claims[0].priority_date == date(2024, 6, 1)
    assert len(assembled.payload.documents) == 2
    assert len(assembled.payload.rows) == 3
    assert len(assembled.payload.citations) == 3
    assert assembled.payload.total_features == 2
    assert [r.name for r in assembled.payload.source_runs] == ["epo", "cnipr"]
    assert assembled.payload.source_runs[1].status == "failed"


@pytest.mark.asyncio
async def test_assemble_reports_rather_than_defaults_missing_candidate_dates() -> None:
    session = FakeSession(profile=_profile(), cells=_cells(), candidates=_candidates(), jobs=_jobs())
    assembled = await _service().assemble(session, organization_id=ORG, case_id=CASE)

    # CN2A 无申请日与优先权日：不得填默认值，必须出现在 gaps 里
    assert any("CN2A" in gap and "日期未知" in gap for gap in assembled.gaps)
    doc_cn2 = next(d for d in assembled.payload.documents if d.doc_id == "CN2A")
    assert doc_cn2.filing_date is None
    assert doc_cn2.priority_date is None

    # 未核验来源同样显式报出
    assert any("CN2A" in gap and "来源未核验" in gap for gap in assembled.gaps)


@pytest.mark.asyncio
async def test_assemble_never_marks_citations_verified() -> None:
    """无逐字核验记录时一律 False —— 不得拿矩阵确认状态冒充逐字核验。"""
    session = FakeSession(profile=_profile(), cells=_cells(), candidates=_candidates(), jobs=_jobs())
    assembled = await _service().assemble(session, organization_id=ORG, case_id=CASE)

    assert all(c.verified is False for c in assembled.payload.citations)
    assert any("逐字核验" in gap for gap in assembled.gaps)


@pytest.mark.asyncio
async def test_assemble_refuses_without_application_profile() -> None:
    session = FakeSession(profile=None, cells=_cells(), candidates=_candidates())
    with pytest.raises(HTTPException) as exc:
        await _service().assemble(session, organization_id=ORG, case_id=CASE)
    assert exc.value.status_code == 422
    assert exc.value.detail == "application_profile_missing"


@pytest.mark.asyncio
async def test_assemble_refuses_without_comparison_matrix() -> None:
    session = FakeSession(profile=_profile(), matrix_id=None, cells=_cells())
    with pytest.raises(HTTPException) as exc:
        await _service().assemble(session, organization_id=ORG, case_id=CASE)
    assert exc.value.detail == "no_comparison_matrix"


@pytest.mark.asyncio
async def test_assemble_refuses_without_comparison_cells() -> None:
    session = FakeSession(profile=_profile(), cells=[], candidates=_candidates())
    with pytest.raises(HTTPException) as exc:
        await _service().assemble(session, organization_id=ORG, case_id=CASE)
    assert exc.value.detail == "no_comparison_cells"


@pytest.mark.asyncio
async def test_assemble_reports_missing_case_as_404() -> None:
    session = FakeSession(case_exists=False)
    with pytest.raises(HTTPException) as exc:
        await _service().assemble(session, organization_id=ORG, case_id=CASE)
    assert exc.value.status_code == 404


def test_parse_date_handles_iso_compact_and_junk() -> None:
    assert _parse_date("2024-01-10") == date(2024, 1, 10)
    assert _parse_date("20240110") == date(2024, 1, 10)
    assert _parse_date(date(2024, 1, 10)) == date(2024, 1, 10)
    assert _parse_date("") is None
    assert _parse_date(None) is None
    assert _parse_date("不是日期") is None
    assert _parse_date("2024-13-45") is None
