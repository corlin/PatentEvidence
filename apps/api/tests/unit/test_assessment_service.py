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
        input_snapshots: dict[int, Any] | None = None,
    ) -> None:
        super().__init__(case_exists=case_exists, max_version=max_version)
        self._version_row = version_row
        self._decisions = decisions or []
        self._input_snapshots = input_snapshots or {}

    async def execute(self, statement: Any, params: Any = None) -> FakeResult:
        sql = str(statement)
        if "FROM assessment_versions" in sql and "version_number=:version_number" in sql:
            vn = (params or {}).get("version_number")
            if self._version_row is None:
                return FakeResult(rows=[])
            # 让行回显被查询的版本号，否则 older/newer 都会落回默认版本号
            self._version_row.version_number = vn
            return FakeResult(rows=[self._version_row])
        if "FROM assessment_input_snapshots" in sql and "version_number=:version_number" in sql:
            version_number = (params or {}).get("version_number")
            snap = self._input_snapshots.get(version_number)
            if snap is None:
                return FakeResult(rows=[])

            class _SnapshotRow:
                def __init__(self, data: dict[str, Any]) -> None:
                    self.application_profile = data.get("application_profile")
                    self.candidate_profiles = data.get("candidate_profiles")
                    self.rules_version = data.get("rules_version")

            return FakeResult(rows=[_SnapshotRow(snap)])
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


@pytest.mark.asyncio
async def test_extra_blockers_merge_without_entering_the_payload() -> None:
    """组装缺口并入记录 blockers，但不进 payload —— 包摘要仍只覆盖领域层产物。"""
    session = FakeSession(max_version=None)
    record = await _service().create_version(
        session,
        organization_id=uuid4(),
        case_id=uuid4(),
        payload=_input(),
        extra_blockers=["对比文件 CN2A 缺申请日与优先权日"],
    )

    assert "对比文件 CN2A 缺申请日与优先权日" in record.blockers
    assert record.payload["blockers"] == [] if "blockers" in record.payload else True


@pytest.mark.asyncio
async def test_extra_blockers_are_not_duplicated() -> None:
    session = FakeSession(max_version=None)
    record = await _service().create_version(
        session,
        organization_id=uuid4(),
        case_id=uuid4(),
        payload=_input(),
        extra_blockers=["同一条缺口", "同一条缺口"],
    )
    assert record.blockers.count("同一条缺口") == 1


@pytest.mark.asyncio
async def test_create_version_also_freezes_an_input_snapshot() -> None:
    """版本创建时把输入档案冻结进快照表，diff 才能归因输入变化。"""
    session = FakeSession(max_version=None)
    await _service().create_version(
        session, organization_id=uuid4(), case_id=uuid4(), payload=_input()
    )
    snap_inserts = [s for s in session.statements if "INSERT INTO assessment_input_snapshots" in s]
    assert len(snap_inserts) == 1
    # 与版本本身一致：输入快照同样只 INSERT，不 UPDATE/DELETE
    assert all("UPDATE " not in s.upper() for s in snap_inserts)
    snap_params = [p for p in session.params if "candidate_profiles" in p]
    assert snap_params, "输入快照必须携带候选档案"
    cand = json.loads(snap_params[0]["candidate_profiles"])
    assert {c["publication_number"] for c in cand} == {"CN1A", "CN2A"}


@pytest.mark.asyncio
async def test_get_input_snapshot_returns_frozen_snapshot() -> None:
    snapshot = {
        "application_profile": {
            "filing_date": "2025-06-01",
            "application_type": "invention",
            "priority_claims": [],
        },
        "candidate_profiles": [
            {
                "publication_number": "CN1A",
                "filing_date": "2023-05-01",
                "priority_date": None,
                "filed_in_china": True,
                "source_verified": True,
            }
        ],
        "rules_version": "assessment-rules-v3",
    }

    class SnapshotRow:
        application_profile = snapshot["application_profile"]
        candidate_profiles = snapshot["candidate_profiles"]
        rules_version = snapshot["rules_version"]

    class SnapSession(FakeSession):
        async def execute(self, statement: Any, params: Any = None) -> FakeResult:
            if "FROM assessment_input_snapshots" in str(statement):
                return FakeResult(rows=[SnapshotRow()])
            return await super().execute(statement, params)

    result = await _service().get_input_snapshot(
        SnapSession(), organization_id=uuid4(), case_id=uuid4(), version_number=1
    )
    assert result is not None
    assert result["application_profile"]["filing_date"] == "2025-06-01"
    assert result["candidate_profiles"][0]["publication_number"] == "CN1A"
    assert result["rules_version"] == "assessment-rules-v3"


@pytest.mark.asyncio
async def test_get_input_snapshot_is_none_when_absent() -> None:
    """老版本（输入建档前创建）没有快照，返回 None 而非空默认。"""

    class EmptySnapSession(FakeSession):
        async def execute(self, statement: Any, params: Any = None) -> FakeResult:
            if "FROM assessment_input_snapshots" in str(statement):
                return FakeResult(rows=[])
            return await super().execute(statement, params)

    result = await _service().get_input_snapshot(
        EmptySnapSession(), organization_id=uuid4(), case_id=uuid4(), version_number=99
    )
    assert result is None


@pytest.mark.asyncio
async def test_diff_versions_returns_input_diff_when_snapshots_present() -> None:
    snap1 = {
        "application_profile": {
            "filing_date": "2025-06-01",
            "application_type": "invention",
            "priority_claims": [],
        },
        "candidate_profiles": [
            {
                "publication_number": "CN1A",
                "filing_date": "2023-05-01",
                "priority_date": None,
                "filed_in_china": True,
                "source_verified": True,
            }
        ],
        "rules_version": "assessment-rules-v3",
    }
    snap2 = {
        "application_profile": {
            "filing_date": "2025-07-01",
            "application_type": "utility_model",
            "priority_claims": [],
        },
        "candidate_profiles": [
            {
                "publication_number": "CN1A",
                "filing_date": "2023-05-01",
                "priority_date": None,
                "filed_in_china": True,
                "source_verified": False,
            },
            {
                "publication_number": "CN2A",
                "filing_date": "2023-08-01",
                "priority_date": None,
                "filed_in_china": True,
                "source_verified": True,
            },
        ],
        "rules_version": "assessment-rules-v3",
    }
    session = FakeAssessmentSession(
        version_row=_version_row(blockers=[]),
        decisions=[],
        input_snapshots={1: snap1, 2: snap2},
    )
    diff = await _service().diff_versions(
        session, organization_id=uuid4(), case_id=uuid4(), from_version=1, to_version=2
    )
    assert diff.inputs is not None
    fields = {f["field"]: f for f in diff.inputs["application_profile"]["changed_fields"]}
    assert fields["filing_date"]["from"] == "2025-06-01"
    assert fields["application_type"]["to"] == "utility_model"
    assert "CN2A" in diff.inputs["candidate_profiles"]["added"]
    assert diff.inputs["candidate_profiles"]["removed"] == []
    changed = {c["publication_number"]: c for c in diff.inputs["candidate_profiles"]["changed"]}
    assert "CN1A" in changed
    assert any(f["field"] == "source_verified" for f in changed["CN1A"]["changed_fields"])
    # 关键：diff 展示输入变化，但绝不声称因果
    assert any("不做自动因果判断" in note for note in diff.notes)


@pytest.mark.asyncio
async def test_diff_versions_inputs_none_when_snapshot_absent() -> None:
    session = FakeAssessmentSession(
        version_row=_version_row(blockers=[]),
        decisions=[],
        input_snapshots={},
    )
    diff = await _service().diff_versions(
        session, organization_id=uuid4(), case_id=uuid4(), from_version=1, to_version=2
    )
    assert diff.inputs is None
    assert any("不对照、不推断输入档案的变化" in note for note in diff.notes)

