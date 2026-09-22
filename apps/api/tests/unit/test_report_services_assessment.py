"""报告封存时取评估事实的那段查询——它决定报告引用哪个版本。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from patent_evidence_api.reports.services import EvidenceReportService


def row(**kwargs: Any) -> Any:
    return type("Row", (), kwargs)


def _version_row(
    *,
    version_number: int = 3,
    sha: str = "deadbeef",
    blockers: Any = None,
    flags: Any = None,
    payload: Any = None,
) -> Any:
    return row(
        id=uuid4(),
        version_number=version_number,
        payload_sha256=sha,
        blockers=blockers if blockers is not None else ["引文未核验"],
        flags=flags if flags is not None else ["部分优先权"],
        rules_version="assessment-rules-v3",
        prompt_versions={"assessment/novelty": "novelty-v2"},
        payload=payload if payload is not None else {"findings": [], "three_step": None},
        created_at=datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc),
    )


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Any]:
        return self._rows


class FakeSession:
    """按 SQL 特征回显：版本行、决策流。"""

    def __init__(
        self, *, version: Any = None, decisions: list[str] | None = None
    ) -> None:
        self.version = version
        self.decisions = decisions if decisions is not None else []
        self.statements: list[str] = []
        self.params: list[dict[str, Any]] = []

    async def execute(self, statement: Any, params: Any = None) -> FakeResult:
        sql = str(statement)
        self.statements.append(sql)
        self.params.append(dict(params or {}))
        if "FROM assessment_versions" in sql:
            return FakeResult([self.version] if self.version is not None else [])
        if "FROM assessment_version_reviews" in sql:
            return FakeResult([row(decision=d) for d in self.decisions])
        return FakeResult([])


ORG = uuid4()
CASE = uuid4()
OTHER_CASE = uuid4()


def _service() -> EvidenceReportService:
    return EvidenceReportService(clock=lambda: datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc))


@pytest.mark.asyncio
async def test_picks_the_highest_version_number() -> None:
    session = FakeSession(version=_version_row(version_number=5), decisions=["approved"])
    facts = await _service()._latest_assessment_facts(session, ORG, CASE)

    assert facts["version_number"] == 5
    version_sql = [s for s in session.statements if "FROM assessment_versions" in s]
    assert version_sql
    assert "ORDER BY version_number DESC" in version_sql[0]
    assert "LIMIT 1" in version_sql[0]


@pytest.mark.asyncio
async def test_status_is_derived_from_the_decision_stream() -> None:
    session = FakeSession(version=_version_row(), decisions=["submitted", "approved"])
    facts = await _service()._latest_assessment_facts(session, ORG, CASE)
    assert facts["status"] == "approved"

    rejected = FakeSession(version=_version_row(), decisions=["submitted", "rejected"])
    facts = await _service()._latest_assessment_facts(rejected, ORG, CASE)
    assert facts["status"] == "rejected"

    # 打回修改回到草稿，报告因此照实写「草稿」而不是沿用上一次的通过
    changed = FakeSession(
        version=_version_row(), decisions=["submitted", "approved", "changes_requested"]
    )
    assert (await _service()._latest_assessment_facts(changed, ORG, CASE))["status"] == "draft"

    # 没有任何决策 = 草稿
    draft = FakeSession(version=_version_row(), decisions=[])
    assert (await _service()._latest_assessment_facts(draft, ORG, CASE))["status"] == "draft"


@pytest.mark.asyncio
async def test_returns_the_payload_the_report_will_render() -> None:
    payload = {"findings": [{"risk_kind": "novelty"}], "three_step": {"closest_prior_art": "D1"}}
    session = FakeSession(version=_version_row(payload=payload), decisions=["approve"])
    facts = await _service()._latest_assessment_facts(session, ORG, CASE)

    assert facts["payload"] == payload
    assert facts["rules_version"] == "assessment-rules-v3"
    assert facts["prompt_versions"] == {"assessment/novelty": "novelty-v2"}
    assert facts["payload_sha256"] == "deadbeef"
    assert facts["created_at"].startswith("2026-09-22")


@pytest.mark.asyncio
async def test_jsonb_arrives_as_string_is_parsed() -> None:
    """JSONB 可能被驱动回传成字符串，阻塞项不能因此变成逐字符。"""
    import json

    session = FakeSession(
        version=_version_row(blockers=json.dumps(["a", "b"]), flags=json.dumps(["f"])),
        decisions=[],
    )
    facts = await _service()._latest_assessment_facts(session, ORG, CASE)
    assert facts["blockers"] == ["a", "b"]
    assert facts["flags"] == ["f"]


@pytest.mark.asyncio
async def test_no_version_means_no_facts_not_empty_defaults() -> None:
    session = FakeSession(version=None)
    facts = await _service()._latest_assessment_facts(session, ORG, CASE)
    assert facts == {"has_version": False}


@pytest.mark.asyncio
async def test_every_query_is_scoped_to_tenant_and_case() -> None:
    session = FakeSession(version=_version_row(), decisions=["approve"])
    await _service()._latest_assessment_facts(session, ORG, CASE)

    version_sql = [s for s in session.statements if "FROM assessment_versions" in s][0]
    assert "organization_id = :org_id" in version_sql
    assert "case_id = :case_id" in version_sql
    assert session.params[0] == {"org_id": ORG, "case_id": CASE}

    # 决策流也要带租户，否则会读到别的机构的决策
    review_sql = [s for s in session.statements if "FROM assessment_version_reviews" in s][0]
    assert "organization_id = :org_id" in review_sql
    assert session.params[1]["org_id"] == ORG


@pytest.mark.asyncio
async def test_case_isolation_comes_from_parameters_not_luck() -> None:
    session = FakeSession(version=_version_row(), decisions=[])
    await _service()._latest_assessment_facts(session, ORG, OTHER_CASE)
    assert session.params[0]["case_id"] == OTHER_CASE
