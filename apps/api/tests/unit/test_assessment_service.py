from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException

from modules.assessment.approval import AssessmentApprovalError
from modules.assessment.package import AssessmentInput, assess_case
from modules.assessment.records import (
    assessment_payload_sha256,
    build_assessment_version_record,
    canonical_payload_json,
)
from modules.assessment.rules import (
    CandidateDocument,
    DataSourceRun,
    EvidenceCitation,
    FeatureComparisonRow,
    MotivationChecklist,
    SubjectApplication,
)
from patent_evidence_api.assessment.services import AssessmentService


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
    """记录所有执行过的 SQL，便于断言不可变约束（不得出现 UPDATE/DELETE）。"""

    def __init__(self, *, case_exists: bool = True, max_version: int | None = None) -> None:
        self.statements: list[str] = []
        self.params: list[dict[str, Any]] = []
        self._case_exists = case_exists
        self._max_version = max_version

    async def execute(self, statement: Any, params: Any = None) -> FakeResult:
        sql = str(statement)
        self.statements.append(sql)
        self.params.append(dict(params or {}))
        if "FROM assessment_versions" in sql and "MAX(version_number)" in sql:
            return FakeResult(scalar=self._max_version)
        if "FROM cases" in sql:
            return FakeResult(scalar=1 if self._case_exists else None)
        return FakeResult()

    async def scalar(self, statement: Any, params: Any = None) -> Any:
        return (await self.execute(statement, params)).scalar()


def _service() -> AssessmentService:
    fixed = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    return AssessmentService(lambda: fixed)


def _input() -> AssessmentInput:
    return AssessmentInput(
        subject=SubjectApplication(filing_date=datetime(2025, 6, 1).date()),
        documents=[
            CandidateDocument(
                "D1",
                "CN1A",
                "doc one",
                source_verified=True,
                publication_date=datetime(2024, 1, 10).date(),
                filing_date=datetime(2023, 5, 1).date(),
            ),
            CandidateDocument(
                "D2",
                "CN2A",
                "doc two",
                source_verified=True,
                publication_date=datetime(2024, 3, 20).date(),
                filing_date=datetime(2023, 8, 1).date(),
            ),
        ],
        rows=[
            FeatureComparisonRow("F1", "D1", "identical"),
            FeatureComparisonRow("F2", "D1", "different"),
            FeatureComparisonRow("F1", "D2", "different"),
            FeatureComparisonRow("F2", "D2", "identical"),
        ],
        citations=[
            EvidenceCitation("D1", "F1", location="[0012]", quote="低位宽映射", verified=True),
            EvidenceCitation("D1", "F2", location="[0015]", quote="无此特征", verified=True),
            EvidenceCitation("D2", "F1", location="[0021]", quote="无此特征", verified=True),
            EvidenceCitation("D2", "F2", location="[0024]", quote="混合精度调度", verified=True),
        ],
        source_runs=[DataSourceRun("epo", "ok")],
        motivation_checklist=MotivationChecklist(
            common_knowledge="no",
            explicit_teaching="no",
            prejudice_or_teaching_away="no",
            combination_obstacle="no",
            effect_predictability="unexpected",
        ),
    )


@pytest.mark.asyncio
async def test_create_version_inserts_once_and_numbers_from_one() -> None:
    session = FakeSession(max_version=None)
    record = await _service().create_version(
        session,
        organization_id=uuid4(),
        case_id=uuid4(),
        payload=_input(),
        actor_identity_id=uuid4(),
    )

    assert record.version_number == 1
    inserts = [s for s in session.statements if "INSERT INTO assessment_versions" in s]
    assert len(inserts) == 1


@pytest.mark.asyncio
async def test_create_version_increments_after_existing_versions() -> None:
    session = FakeSession(max_version=7)
    record = await _service().create_version(
        session, organization_id=uuid4(), case_id=uuid4(), payload=_input()
    )
    assert record.version_number == 8


@pytest.mark.asyncio
async def test_service_never_writes_update_or_delete() -> None:
    """不可变边界：service 只 INSERT/SELECT，没有任何改写路径。"""
    session = FakeSession()
    org_id, case_id = uuid4(), uuid4()
    await _service().create_version(session, organization_id=org_id, case_id=case_id, payload=_input())
    try:
        await _service().get_version(session, organization_id=org_id, case_id=case_id, version_number=1)
    except HTTPException:
        pass
    await _service().list_versions(session, organization_id=org_id, case_id=case_id)

    for sql in session.statements:
        assert "UPDATE " not in sql.upper()
        assert "DELETE " not in sql.upper()


@pytest.mark.asyncio
async def test_create_version_scopes_every_statement_to_the_organization() -> None:
    org_id = uuid4()
    session = FakeSession()
    await _service().create_version(
        session, organization_id=org_id, case_id=uuid4(), payload=_input()
    )
    assert all(params.get("org_id") == org_id for params in session.params if "org_id" in params)


@pytest.mark.asyncio
async def test_create_version_rejects_unknown_case() -> None:
    session = FakeSession(case_exists=False)
    with pytest.raises(HTTPException) as exc:
        await _service().create_version(
            session, organization_id=uuid4(), case_id=uuid4(), payload=_input()
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_missing_version_is_404() -> None:
    session = FakeSession()
    with pytest.raises(HTTPException) as exc:
        await _service().get_version(
            session, organization_id=uuid4(), case_id=uuid4(), version_number=99
        )
    assert exc.value.status_code == 404


def test_payload_hash_is_stable_and_key_order_insensitive() -> None:
    payload_a = {"rules_version": "assessment-rules-v3", "blockers": ["a", "b"]}
    payload_b = {"blockers": ["a", "b"], "rules_version": "assessment-rules-v3"}

    assert assessment_payload_sha256(payload_a) == assessment_payload_sha256(payload_b)
    assert len(assessment_payload_sha256(payload_a)) == 64
    assert canonical_payload_json(payload_a) == canonical_payload_json(payload_b)


def test_payload_hash_changes_when_content_changes() -> None:
    assert assessment_payload_sha256({"blockers": ["a"]}) != assessment_payload_sha256(
        {"blockers": ["b"]}
    )


def test_record_carries_versions_and_is_serialisable() -> None:
    package = assess_case(_input())
    record = build_assessment_version_record(
        package,
        record_id=uuid4(),
        organization_id=uuid4(),
        case_id=uuid4(),
        version_number=3,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
    )

    assert record.rules_version == package.rules_version
    assert record.prompt_versions == package.prompt_versions
    assert record.payload_sha256 == assessment_payload_sha256(record.payload)
    assert isinstance(record.to_dict()["id"], str)
    assert json.loads(json.dumps(record.to_dict()))["version_number"] == 3


def test_record_hash_matches_stored_payload_bytes() -> None:
    package = assess_case(_input())
    record = build_assessment_version_record(
        package,
        record_id=uuid4(),
        organization_id=uuid4(),
        case_id=uuid4(),
        version_number=1,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
    )
    stored = json.dumps(record.payload, ensure_ascii=False, sort_keys=True)
    assert assessment_payload_sha256(json.loads(stored)) == record.payload_sha256


def test_record_requires_human_confirmation_follows_package() -> None:
    package = assess_case(_input())
    record = build_assessment_version_record(
        package,
        record_id=uuid4(),
        organization_id=uuid4(),
        case_id=uuid4(),
        version_number=1,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
    )
    assert record.requires_human_confirmation == package.requires_human_confirmation
    assert isinstance(record.blockers, list)
    assert isinstance(record.flags, list)


class Row:
    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakeAssessmentSession(FakeSession):
    """带版本行与决策事件流的假 session。"""

    def __init__(
        self,
        *,
        version_row: Row | None = None,
        decisions: list[str] | None = None,
        case_exists: bool = True,
        max_version: int | None = None,
    ) -> None:
        super().__init__(case_exists=case_exists, max_version=max_version)
        self._version_row = version_row
        self._decisions = decisions or []

    async def execute(self, statement: Any, params: Any = None) -> FakeResult:
        sql = str(statement)
        if "FROM assessment_versions" in sql and "version_number=:version_number" in sql:
            return FakeResult(rows=[self._version_row] if self._version_row else [])
        if "FROM assessment_version_reviews" in sql and "ORDER BY decided_at" in sql:
            return FakeResult(rows=[Row(decision=d) for d in self._decisions])
        return await super().execute(statement, params)


def _version_row(*, blockers: list[str], version_number: int = 1) -> Row:
    return Row(
        id=uuid4(),
        organization_id=uuid4(),
        case_id=uuid4(),
        version_number=version_number,
        rules_version="assessment-rules-v3",
        prompt_versions=json.dumps({"assessment/novelty": "novelty-v2"}),
        payload=json.dumps({"rules_version": "assessment-rules-v3"}),
        payload_sha256="a" * 64,
        blockers=json.dumps(blockers),
        flags=json.dumps([]),
        requires_human_confirmation=bool(blockers),
        created_by_identity_id=None,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_submit_then_approve_appends_two_events() -> None:
    session = FakeAssessmentSession(version_row=_version_row(blockers=[]))
    service = _service()

    await service.submit_version(
        session, organization_id=uuid4(), case_id=uuid4(), version_number=1,
        actor_identity_id=uuid4(),
    )
    session._decisions = ["submitted"]
    record = await service.decide_version(
        session, organization_id=uuid4(), case_id=uuid4(), version_number=1,
        decision="approved", reviewer_identity_id=uuid4(),
    )

    assert record.decision == "approved"
    inserts = [s for s in session.statements if "INSERT INTO assessment_version_reviews" in s]
    assert len(inserts) == 2


@pytest.mark.asyncio
async def test_approve_blocked_version_raises_and_writes_nothing() -> None:
    session = FakeAssessmentSession(
        version_row=_version_row(blockers=["引证未定位：D1/F2"]), decisions=["submitted"]
    )
    before = len(session.statements)
    with pytest.raises(AssessmentApprovalError) as exc:
        await _service().decide_version(
            session, organization_id=uuid4(), case_id=uuid4(), version_number=1,
            decision="approved", reviewer_identity_id=uuid4(),
        )
    assert exc.value.code == "blockers_open"
    inserts = [s for s in session.statements[before:] if "INSERT" in s]
    assert inserts == []


@pytest.mark.asyncio
async def test_deciding_an_already_approved_version_is_refused() -> None:
    session = FakeAssessmentSession(
        version_row=_version_row(blockers=[]), decisions=["submitted", "approved"]
    )
    with pytest.raises(AssessmentApprovalError) as exc:
        await _service().decide_version(
            session, organization_id=uuid4(), case_id=uuid4(), version_number=1,
            decision="rejected", reviewer_identity_id=uuid4(),
        )
    assert exc.value.code == "version_frozen"


@pytest.mark.asyncio
async def test_unsupported_decision_is_rejected_before_any_write() -> None:
    session = FakeAssessmentSession(version_row=_version_row(blockers=[]), decisions=["submitted"])
    before = len(session.statements)
    with pytest.raises(HTTPException) as exc:
        await _service().decide_version(
            session, organization_id=uuid4(), case_id=uuid4(), version_number=1,
            decision="maybe", reviewer_identity_id=uuid4(),
        )
    assert exc.value.status_code == 422
    assert [s for s in session.statements[before:] if "INSERT" in s] == []


@pytest.mark.asyncio
async def test_current_status_is_derived_from_the_event_stream() -> None:
    session = FakeAssessmentSession(version_row=_version_row(blockers=[]))
    assert await _service().current_status(
        session, organization_id=uuid4(), case_id=uuid4(), version_number=1
    ) == "draft"

    session._decisions = ["submitted"]
    assert await _service().current_status(
        session, organization_id=uuid4(), case_id=uuid4(), version_number=1
    ) == "submitted"

    session._decisions = ["submitted", "changes_requested"]
    assert await _service().current_status(
        session, organization_id=uuid4(), case_id=uuid4(), version_number=1
    ) == "draft"
