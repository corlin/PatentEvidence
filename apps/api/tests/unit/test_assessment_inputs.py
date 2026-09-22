from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException

from patent_evidence_api.assessment.inputs import AssessmentInputService

ORG = uuid4()
CASE = uuid4()
CAND = uuid4()


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
    def __init__(self, *, case_exists: bool = True, candidate_exists: bool = True) -> None:
        self.case_exists = case_exists
        self.candidate_exists = candidate_exists
        self.statements: list[str] = []
        self.params: list[dict[str, Any]] = []

    async def execute(self, statement: Any, params: Any = None) -> FakeResult:
        sql = str(statement)
        self.statements.append(sql)
        self.params.append(dict(params or {}))
        if "RETURNING" in sql:
            return FakeResult(rows=[self._echo(sql, dict(params or {}))])
        if "FROM case_application_profiles" in sql:
            return FakeResult(rows=[])
        if "FROM candidate_document_profiles" in sql:
            return FakeResult(rows=[])
        return FakeResult()

    @staticmethod
    def _echo(sql: str, params: dict[str, Any]) -> SimpleNamespace:
        """回显写入参数，模拟 RETURNING。"""
        now = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
        if "case_application_profiles" in sql:
            return row(
                id=uuid4(),
                filing_date=params.get("filing_date"),
                application_type=params.get("application_type"),
                priority_claims=params.get("priority_claims"),
                recorded_by_identity_id=params.get("recorded_by"),
                created_at=now,
                updated_at=now,
            )
        return row(
            id=uuid4(),
            candidate_id=params.get("candidate_id"),
            publication_number="CN1A",
            title="doc one",
            filing_date=params.get("filing_date"),
            priority_date=params.get("priority_date"),
            filed_in_china=params.get("filed_in_china", True),
            source_verified=params.get("source_verified", False),
            verified_by_identity_id=params.get("verified_by"),
            created_at=now,
            updated_at=now,
        )

    async def scalar(self, statement: Any, params: Any = None) -> Any:
        sql = str(statement)
        self.statements.append(sql)
        if "FROM cases" in sql:
            return 1 if self.case_exists else None
        if "FROM search_candidates" in sql:
            return 1 if self.candidate_exists else None
        return None


def _service() -> AssessmentInputService:
    return AssessmentInputService(lambda: datetime(2026, 9, 22, 12, 0, tzinfo=UTC))


@pytest.mark.asyncio
async def test_upsert_application_profile_is_conflict_safe() -> None:
    session = FakeSession()
    profile = await _service().upsert_application_profile(
        session,
        organization_id=ORG,
        case_id=CASE,
        filing_date=date(2025, 6, 1),
        application_type="invention",
    )

    assert profile["filing_date"] == "2025-06-01"
    assert profile["application_type"] == "invention"
    upserts = [s for s in session.statements if "ON CONFLICT" in s]
    assert len(upserts) == 1


@pytest.mark.asyncio
async def test_upsert_application_profile_rejects_unknown_type() -> None:
    session = FakeSession()
    with pytest.raises(HTTPException) as exc:
        await _service().upsert_application_profile(
            session,
            organization_id=ORG,
            case_id=CASE,
            filing_date=date(2025, 6, 1),
            application_type="plant_variety",
        )
    assert exc.value.status_code == 422
    assert [s for s in session.statements if "INSERT" in s] == []


@pytest.mark.asyncio
async def test_upsert_application_profile_rejects_unknown_case() -> None:
    session = FakeSession(case_exists=False)
    with pytest.raises(HTTPException) as exc:
        await _service().upsert_application_profile(
            session, organization_id=ORG, case_id=CASE, filing_date=date(2025, 6, 1)
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_upsert_candidate_profile_validates_candidate_belongs_to_case() -> None:
    session = FakeSession(candidate_exists=False)
    with pytest.raises(HTTPException) as exc:
        await _service().upsert_candidate_profile(
            session,
            organization_id=ORG,
            case_id=CASE,
            candidate_id=CAND,
            filing_date=date(2023, 5, 1),
        )
    assert exc.value.status_code == 404
    assert [s for s in session.statements if "INSERT" in s] == []


@pytest.mark.asyncio
async def test_upsert_candidate_profile_records_dates_and_verification() -> None:
    session = FakeSession()
    profile = await _service().upsert_candidate_profile(
        session,
        organization_id=ORG,
        case_id=CASE,
        candidate_id=CAND,
        filing_date=date(2023, 5, 1),
        priority_date=date(2022, 8, 1),
        source_verified=True,
    )

    assert profile["candidate_id"] == str(CAND)
    assert profile["filing_date"] == "2023-05-01"
    assert profile["priority_date"] == "2022-08-01"
    assert profile["source_verified"] is True


@pytest.mark.asyncio
async def test_get_application_profile_returns_none_when_absent() -> None:
    session = FakeSession()
    assert (
        await _service().get_application_profile(session, organization_id=ORG, case_id=CASE)
        is None
    )


@pytest.mark.asyncio
async def test_list_candidate_profiles_scopes_to_case() -> None:
    session = FakeSession()
    items = await _service().list_candidate_profiles(
        session, organization_id=ORG, case_id=CASE
    )
    assert items == []
    assert any("candidate_document_profiles" in s for s in session.statements)
