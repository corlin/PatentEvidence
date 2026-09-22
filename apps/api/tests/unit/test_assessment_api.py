from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, date
from typing import Any, AsyncIterator
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.assessment.approval import AssessmentApprovalError, AssessmentDecisionRecord
from modules.assessment.records import AssessmentVersionRecord
from patent_evidence_api.assessment.api import create_assessment_router
from patent_evidence_api.assessment.schemas import (
    AssessmentCreateBody,
    DISCLAIMER,
    render_version,
)
from patent_evidence_api.assessment.services import AssessmentService

ORG = uuid4()
CASE = uuid4()
ACTOR = uuid4()


class FakePrincipal:
    def __init__(self, identity_id: UUID) -> None:
        self.identity_id = identity_id


class FakeOperation:
    def __init__(self, session: Any, principal: FakePrincipal) -> None:
        self.session = session
        self.principal = principal
        self.described: list[dict[str, Any]] = []

    def describe(self, **kwargs: Any) -> None:
        self.described.append(kwargs)


class FakeAccess:
    """替身 OrganizationAccess：不做真实鉴权，只记录审计动作。"""

    def __init__(self) -> None:
        self.operations: list[FakeOperation] = []
        self.actions: list[str] = []

    @asynccontextmanager
    async def authorized(self, request: Any, organization_id: UUID) -> AsyncIterator[tuple[Any, FakePrincipal]]:
        yield object(), FakePrincipal(ACTOR)

    @asynccontextmanager
    async def mutation(
        self,
        request: Any,
        organization_id: UUID,
        *,
        action: str,
        target_type: str,
        target_id: UUID | None = None,
    ) -> AsyncIterator[FakeOperation]:
        self.actions.append(action)
        operation = FakeOperation(object(), FakePrincipal(ACTOR))
        self.operations.append(operation)
        yield operation


def _version(*, blockers: list[str] | None = None) -> AssessmentVersionRecord:
    return AssessmentVersionRecord(
        id=uuid4(),
        organization_id=ORG,
        case_id=CASE,
        version_number=1,
        rules_version="assessment-rules-v3",
        prompt_versions={"novelty": "novelty-v2"},
        payload={"findings": [], "blockers": blockers or []},
        payload_sha256="a" * 64,
        blockers=blockers or [],
        flags=["priority_partial"],
        requires_human_confirmation=True,
        created_by_identity_id=ACTOR,
        created_at=datetime(2026, 9, 22, 12, 0, tzinfo=UTC),
    )


def _decision(decision: str = "submitted", version_id: UUID | None = None) -> AssessmentDecisionRecord:
    return AssessmentDecisionRecord(
        version_id=str(version_id or uuid4()),
        version_number=1,
        payload_sha256="a" * 64,
        decision=decision,
        reviewer_identity_id=str(ACTOR),
        comments="",
        open_blockers=(),
        accepts_insufficient_evidence=False,
        decision_signature="s" * 64,
        decided_at="2026-09-22T12:00:00+00:00",
    )


class FakeService(AssessmentService):
    def __init__(self, *, reject_decision: str | None = None) -> None:
        super().__init__(lambda: datetime(2026, 9, 22, 12, 0, tzinfo=UTC))
        self.reject_decision = reject_decision
        self.calls: list[dict[str, Any]] = []

    async def create_version(self, session: Any, **kwargs: Any) -> AssessmentVersionRecord:
        self.calls.append({"method": "create_version", **kwargs})
        return _version()

    async def get_version(self, session: Any, **kwargs: Any) -> AssessmentVersionRecord:
        self.calls.append({"method": "get_version", **kwargs})
        return _version()

    async def list_versions(self, session: Any, **kwargs: Any) -> list[AssessmentVersionRecord]:
        self.calls.append({"method": "list_versions", **kwargs})
        return [_version()]

    async def current_status(self, session: Any, **kwargs: Any) -> str:
        return "submitted"

    async def submit_version(self, session: Any, **kwargs: Any) -> AssessmentDecisionRecord:
        self.calls.append({"method": "submit_version", **kwargs})
        return _decision("submitted")

    async def decide_version(self, session: Any, **kwargs: Any) -> AssessmentDecisionRecord:
        self.calls.append({"method": "decide_version", **kwargs})
        if self.reject_decision:
            raise AssessmentApprovalError(self.reject_decision, "状态机拒绝")
        return _decision(kwargs.get("decision", "approved"))


def _client(service: FakeService | None = None) -> tuple[TestClient, FakeAccess, FakeService]:
    resolved = service or FakeService()
    access = FakeAccess()
    app = FastAPI()
    app.include_router(create_assessment_router(access, resolved))  # type: ignore[arg-type]
    return TestClient(app, raise_server_exceptions=False), access, resolved


VALID_BODY = {
    "subject": {"filing_date": "2025-06-01", "priority_date": "2024-06-01"},
    "documents": [
        {
            "doc_id": "D1",
            "publication_number": "CN1A",
            "title": "doc one",
            "source_verified": True,
            "publication_date": "2024-01-10",
            "filing_date": "2023-05-01",
        }
    ],
    "rows": [{"feature_code": "F1", "doc_id": "D1", "judgment": "identical"}],
    "citations": [
        {"doc_id": "D1", "feature_code": "F1", "location": "[0012]", "quote": "q", "verified": True}
    ],
    "source_runs": [{"name": "epo", "status": "ok", "as_of": "2026-09-01"}],
}


def test_create_version_returns_201_with_confirmation_flag_and_disclaimer() -> None:
    client, access, service = _client()
    response = client.post(f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments", json=VALID_BODY)

    assert response.status_code == 201
    version = response.json()["version"]
    assert version["status"] == "draft"
    assert version["requires_human_confirmation"] is True
    assert version["disclaimer"] == DISCLAIMER
    # 领域层从不产出专利性结论，路由层也不得凭空造出一个
    assert "conclusion" not in version
    assert "case.assessment.create_version" in access.actions
    assert service.calls[0]["organization_id"] == ORG


def test_create_version_rejects_malformed_body_with_422() -> None:
    client, _, _ = _client()
    response = client.post(
        f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments",
        json={"subject": {"filing_date": "not-a-date"}},
    )
    assert response.status_code == 422


def test_list_versions_returns_summaries_only() -> None:
    client, _, _ = _client()
    response = client.get(f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert "payload" not in item  # 列表不回传完整 payload
    assert item["disclaimer"] == DISCLAIMER
    assert item["payload_sha256"] == "a" * 64


def test_get_version_includes_event_stream_status() -> None:
    client, _, _ = _client()
    response = client.get(f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments/1")

    assert response.status_code == 200
    version = response.json()["version"]
    assert version["status"] == "submitted"
    assert version["rules_version"] == "assessment-rules-v3"


def test_submit_appends_decision_record() -> None:
    client, access, service = _client()
    response = client.post(f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments/1/submit", json={})

    assert response.status_code == 200
    assert response.json()["decision"]["decision"] == "submitted"
    assert "case.assessment.submit_version" in access.actions
    assert service.calls[0]["version_number"] == 1


def test_decide_forwards_explicit_insufficient_evidence_acceptance() -> None:
    client, _, service = _client()
    response = client.post(
        f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments/1/decide",
        json={
            "decision": "approved",
            "comments": "客户确认接受证据不足",
            "accepts_insufficient_evidence": True,
        },
    )

    assert response.status_code == 200
    assert service.calls[0]["accepts_insufficient_evidence"] is True
    assert service.calls[0]["comments"] == "客户确认接受证据不足"


def test_decide_surfaces_state_machine_rejection_as_409() -> None:
    client, _, _ = _client(FakeService(reject_decision="blocked_by_open_blockers"))
    response = client.post(
        f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments/1/decide",
        json={"decision": "approved"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "blocked_by_open_blockers"


def test_router_exposes_no_mutation_of_existing_versions() -> None:
    """审批边界依赖「版本不可改写」：路由层不得出现 PUT/PATCH/DELETE。"""
    access = FakeAccess()
    app = FastAPI()
    app.include_router(create_assessment_router(access, FakeService()))  # type: ignore[arg-type]
    methods = {method for route in app.routes for method in getattr(route, "methods", set())}

    assert methods <= {"GET", "HEAD", "POST"}  # HEAD 由 FastAPI 为 GET 自动附加
    assert "DELETE" not in methods
    assert "PUT" not in methods
    assert "PATCH" not in methods


def test_create_body_builds_domain_input_with_parsed_dates() -> None:
    body = AssessmentCreateBody.model_validate(
        {
            **VALID_BODY,
            "subject": {
                "filing_date": "2025-06-01",
                "priority_claims": [
                    {
                        "claim_id": "P1",
                        "priority_date": "2024-06-01",
                        "covers": ["F1", "F2"],
                        "proof_verified": True,
                    }
                ],
            },
            "legal_status_as_of": {"D1": "2026-08-01"},
            "total_features": 3,
        }
    )
    payload = body.to_assessment_input()

    assert payload.subject.filing_date == date(2025, 6, 1)
    assert payload.subject.priority_claims[0].priority_date == date(2024, 6, 1)
    assert payload.subject.priority_claims[0].covers == frozenset({"F1", "F2"})
    assert payload.legal_status_as_of["D1"] == date(2026, 8, 1)
    assert payload.total_features == 3
    assert payload.documents[0].source_verified is True
    assert payload.citations[0].verified is True


def test_render_version_always_carries_disclaimer() -> None:
    rendered = render_version(_version(blockers=["missing_anchor"]), status="draft")
    assert rendered["disclaimer"] == DISCLAIMER
    assert rendered["blockers"] == ["missing_anchor"]
