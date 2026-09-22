from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, date
from typing import Any, AsyncIterator
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from modules.assessment.approval import AssessmentApprovalError, AssessmentDecisionRecord
from modules.assessment.diff import AssessmentVersionDiff
from modules.assessment.records import AssessmentVersionRecord
from patent_evidence_api.assessment.api import create_assessment_router
from patent_evidence_api.assessment.assembly import AssessmentAssemblyService, AssembledAssessment
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


def _version(*, blockers: list[str] | None = None, version_number: int = 1) -> AssessmentVersionRecord:
    return AssessmentVersionRecord(
        id=uuid4(),
        organization_id=ORG,
        case_id=CASE,
        version_number=version_number,
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
        # 回显请求的版本号，diff 路由据此确定基准方向
        return _version(version_number=kwargs.get("version_number", 1))

    async def list_versions(self, session: Any, **kwargs: Any) -> list[AssessmentVersionRecord]:
        self.calls.append({"method": "list_versions", **kwargs})
        return [_version()]

    async def current_status(self, session: Any, **kwargs: Any) -> str:
        return "submitted"

    async def get_input_snapshot(self, session: Any, **kwargs: Any) -> dict[str, Any] | None:
        self.calls.append({"method": "get_input_snapshot", **kwargs})
        return {
            "application_profile": {
                "filing_date": "2025-06-01",
                "application_type": "invention",
                "priority_claims": [
                    {
                        "claim_id": "P1",
                        "priority_date": "2024-06-01",
                        "country": "CN",
                        "first_application": True,
                        "same_subject": True,
                        "proof_verified": True,
                        "covers": ["F1"],
                    }
                ],
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

    async def submit_version(self, session: Any, **kwargs: Any) -> AssessmentDecisionRecord:
        self.calls.append({"method": "submit_version", **kwargs})
        return _decision("submitted")

    async def decide_version(self, session: Any, **kwargs: Any) -> AssessmentDecisionRecord:
        self.calls.append({"method": "decide_version", **kwargs})
        if self.reject_decision:
            raise AssessmentApprovalError(self.reject_decision, "状态机拒绝")
        return _decision(kwargs.get("decision", "approved"))

    async def diff_versions(self, session: Any, **kwargs: Any) -> AssessmentVersionDiff:
        self.calls.append({"method": "diff_versions", **kwargs})
        # 复刻真实实现的只读路径：按版本号取 older/newer（方向由版本号决定），
        # 但不走 DB 支撑的 get_input_snapshot——本测试桩不涉及输入快照冻结。
        from_v = int(kwargs.get("from_version", 1))
        to_v = int(kwargs.get("to_version", 1))
        older = await self.get_version(
            session,
            organization_id=kwargs.get("organization_id"),
            case_id=kwargs.get("case_id"),
            version_number=min(from_v, to_v),
        )
        newer = await self.get_version(
            session,
            organization_id=kwargs.get("organization_id"),
            case_id=kwargs.get("case_id"),
            version_number=max(from_v, to_v),
        )
        return AssessmentVersionDiff(
            from_version=older.version_number,
            to_version=newer.version_number,
            from_payload_sha256="old",
            to_payload_sha256="new",
            rules_version={},
            rules_version_changed=False,
            prompt_changes=[],
            blockers={},
            flags={},
            findings={},
            evidence={},
            three_step={},
            entity_observations={},
            priority_changed=False,
            requires_human_confirmation=True,
            inputs=None,
            notes=["输入快照缺失：不对照、不推断输入档案的变化"],
        )


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


class FakeAssemblyService(AssessmentAssemblyService):
    def __init__(self, *, refuse: str | None = None, gaps: list[str] | None = None) -> None:
        super().__init__(lambda: datetime(2026, 9, 22, 12, 0, tzinfo=UTC))
        self.refuse = refuse
        self.gaps = gaps if gaps is not None else ["对比文件 CN2A 缺申请日与优先权日"]
        self.calls: list[dict[str, Any]] = []

    async def assemble(self, session: Any, **kwargs: Any) -> AssembledAssessment:
        self.calls.append(kwargs)
        if self.refuse:
            raise HTTPException(status_code=422, detail=self.refuse)
        return AssembledAssessment(
            payload=AssessmentCreateBody.model_validate(VALID_BODY).to_assessment_input(),
            gaps=tuple(self.gaps),
            source={"cell_count": 3},
        )


def _client_with_assembly(
    assembly: FakeAssemblyService,
) -> tuple[TestClient, FakeAccess, FakeService]:
    service = FakeService()
    access = FakeAccess()
    app = FastAPI()
    app.include_router(create_assessment_router(access, service, assembly))  # type: ignore[arg-type]
    return TestClient(app, raise_server_exceptions=False), access, service


def test_assemble_from_case_returns_version_together_with_gaps() -> None:
    assembly = FakeAssemblyService()
    client, access, _ = _client_with_assembly(assembly)
    response = client.post(
        f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments/from-case", json={}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["gaps"] == ["对比文件 CN2A 缺申请日与优先权日"]
    assert body["source"] == {"cell_count": 3}
    assert body["version"]["disclaimer"] == DISCLAIMER
    assert "case.assessment.create_version_from_case" in access.actions


def test_assemble_from_case_surfaces_source_gaps_as_422() -> None:
    client, _, _ = _client_with_assembly(
        FakeAssemblyService(refuse="application_profile_missing")
    )
    response = client.post(
        f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments/from-case", json={}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "application_profile_missing"


def test_assemble_route_is_absent_without_assembly_service() -> None:
    """未配置组装服务时不暴露该路由，避免半可用端点。"""
    app = FastAPI()
    app.include_router(create_assessment_router(FakeAccess(), FakeService()))  # type: ignore[arg-type]
    paths = [getattr(route, "path", "") for route in app.routes]
    assert not any(p.endswith("/assessments/from-case") for p in paths)


def test_diff_route_carries_the_disclaimer_and_needs_no_direction() -> None:
    """diff 是只读的，且必须带免责声明——它不能被当成「阻塞项消失就能出结论」。"""
    client, access, service = _client()
    response = client.get(f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments/2/diff/1")

    assert response.status_code == 200
    body = response.json()
    assert body["diff"]["from_version"] == 1
    assert body["diff"]["to_version"] == 2
    assert body["diff"]["disclaimer"] == DISCLAIMER
    assert body["diff"]["requires_human_confirmation"] is True
    assert not access.actions


def test_diff_route_stays_read_only() -> None:
    client, _, service = _client()
    client.get(f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments/1/diff/2")

    assert all(call["method"] in {"get_version", "diff_versions"} for call in service.calls)


def test_diff_route_surfaces_a_missing_version_as_404() -> None:
    class MissingService(FakeService):
        async def get_version(self, session: Any, **kwargs: Any) -> AssessmentVersionRecord:
            raise HTTPException(status_code=404, detail="assessment_version_not_found")

    client, _, _ = _client(MissingService())
    response = client.get(f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments/1/diff/2")

    assert response.status_code == 404
    assert response.json()["detail"] == "assessment_version_not_found"


def test_deliverable_route_returns_200_with_disclaimers() -> None:
    """导出预评估意见：只读、候选措辞、携带人工确认与免责声明，且不是结论。"""
    client, access, service = _client()
    response = client.get(f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments/1/deliverable")

    assert response.status_code == 200
    body = response.json()
    d = body["deliverable"]
    assert d["version_number"] == 1
    assert d["requires_human_confirmation"] is True
    assert "候选" in d["candidate_notice"]
    assert "不构成专利性结论" in d["publication_disclaimer"]
    assert "冻结" in d["version_freeze_declaration"]
    assert isinstance(d["eligibility"], dict) and "eligible" in d["eligibility"]
    # 路由层信封同样带人工确认与免责声明
    assert d["disclaimer"] == DISCLAIMER
    # 交付物永远是候选，绝不携带任何形式的结论
    assert "conclusion" not in d
    assert not access.actions


def test_deliverable_route_surfaces_a_missing_version_as_404() -> None:
    class MissingService(FakeService):
        async def get_version(self, session: Any, **kwargs: Any) -> AssessmentVersionRecord:
            raise HTTPException(status_code=404, detail="assessment_version_not_found")

    client, _, _ = _client(MissingService())
    response = client.get(f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments/99/deliverable")

    assert response.status_code == 404
    assert response.json()["detail"] == "assessment_version_not_found"


def test_delivery_attachment_route_returns_200_and_stays_read_only() -> None:
    """交付包附件路由：只读、候选措辞、未达门禁时标 attachable=False。"""
    client, access, service = _client()
    response = client.get(
        f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments/delivery-attachment"
    )

    assert response.status_code == 200
    body = response.json()
    attachment = body["attachment"]
    assert attachment is not None
    # FakeService.current_status 恒为 submitted → 未达门禁
    assert attachment["attachable"] is False
    assert "门禁" in attachment["attachment_reason"]
    assert attachment["requires_human_confirmation"] is True
    assert attachment["disclaimer"] == DISCLAIMER
    assert "不构成专利性结论" in attachment["publication_disclaimer"]
    # 附件永远是候选，绝不携带任何形式的结论
    assert "conclusion" not in attachment
    assert not access.actions
    # 只读路径：列版本 + 读版本（构交付物），不做任何写入
    assert all(
        call["method"] in {"list_versions", "get_version"} for call in service.calls
    )


def test_delivery_attachment_route_marks_attachable_when_approved() -> None:
    """当所选版本已批准且无阻塞时，附件标 attachable=True。"""

    class ApprovedService(FakeService):
        async def current_status(self, session: Any, **kwargs: Any) -> str:
            return "approved"

    client, _, _ = _client(ApprovedService())
    response = client.get(
        f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments/delivery-attachment"
    )

    assert response.status_code == 200
    attachment = response.json()["attachment"]
    assert attachment["attachable"] is True
    assert "attachment_reason" not in attachment
    assert attachment["eligibility"]["eligible"] is True


def test_delivery_attachment_route_returns_null_without_versions() -> None:
    """案件没有任何评估版本时返回 {"attachment": null}，不编造附件。"""

    class NoVersionsService(FakeService):
        async def list_versions(
            self, session: Any, **kwargs: Any
        ) -> list[AssessmentVersionRecord]:
            return []

    client, _, _ = _client(NoVersionsService())
    response = client.get(
        f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments/delivery-attachment"
    )

    assert response.status_code == 200
    assert response.json() == {"attachment": None}


def test_input_snapshot_route_returns_200_with_snapshot_and_stays_read_only() -> None:
    """查看冻结输入快照：只读、如实返回快照内容，绝不回读可变档案表推断。"""
    client, access, service = _client()
    response = client.get(
        f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments/1/input-snapshot"
    )

    assert response.status_code == 200
    snapshot = response.json()["snapshot"]
    assert snapshot["application_profile"]["filing_date"] == "2025-06-01"
    assert snapshot["application_profile"]["priority_claims"][0]["claim_id"] == "P1"
    assert snapshot["candidate_profiles"][0]["publication_number"] == "CN1A"
    assert snapshot["rules_version"] == "assessment-rules-v3"
    # 快照绝不携带任何结论
    assert "conclusion" not in snapshot
    # 只读路径：取版本（404 语义）+ 取快照，无任何写入
    assert not access.actions
    assert all(
        call["method"] in {"get_version", "get_input_snapshot"} for call in service.calls
    )


def test_input_snapshot_route_returns_null_for_pre_snapshot_versions() -> None:
    """输入快照功能上线前创建的老版本：如实返回 null，不推断、不报错。"""

    class NoSnapshotService(FakeService):
        async def get_input_snapshot(
            self, session: Any, **kwargs: Any
        ) -> dict[str, Any] | None:
            return None

    client, _, _ = _client(NoSnapshotService())
    response = client.get(
        f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments/1/input-snapshot"
    )

    assert response.status_code == 200
    assert response.json() == {"snapshot": None}


def test_input_snapshot_route_surfaces_a_missing_version_as_404() -> None:
    """版本不存在时返回 404，避免把「无版本」与「无快照」混为一谈。"""

    class MissingService(FakeService):
        async def get_version(self, session: Any, **kwargs: Any) -> AssessmentVersionRecord:
            raise HTTPException(status_code=404, detail="assessment_version_not_found")

    client, _, _ = _client(MissingService())
    response = client.get(
        f"/api/v1/organizations/{ORG}/cases/{CASE}/assessments/99/input-snapshot"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "assessment_version_not_found"

