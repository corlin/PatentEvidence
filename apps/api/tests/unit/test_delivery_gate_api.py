from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, AsyncIterator
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from patent_evidence_api.assessment.services import AssessmentService
from patent_evidence_api.review.api import create_review_router
from patent_evidence_api.review.services import ReviewService

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


class FakeReviewService(ReviewService):
    """只记录调用；交付成功时返回最小交付记录。"""

    def __init__(self) -> None:
        super().__init__(lambda: datetime(2026, 9, 22, 12, 0, tzinfo=UTC))
        self.calls: list[dict[str, Any]] = []

    async def deliver_case(
        self, session: Any, **kwargs: Any
    ) -> dict[str, Any]:
        self.calls.append({"method": "deliver_case", **kwargs})
        return {
            "id": str(uuid4()),
            "case_id": str(kwargs.get("case_id")),
            "status": "delivered",
            "client_recipient": kwargs.get("client_recipient", ""),
            "download_token": "dlv_" + "t" * 44,
            "delivered_at": "2026-09-22T12:00:00+00:00",
        }


class GateRefusedService(AssessmentService):
    """门禁不满足：没有任何「已批准且无阻塞项」的评估版本。"""

    def __init__(self) -> None:
        super().__init__(lambda: datetime(2026, 9, 22, 12, 0, tzinfo=UTC))
        self.calls: list[dict[str, Any]] = []

    async def assert_delivery_gate(self, session: Any, **kwargs: Any) -> None:
        self.calls.append({"method": "assert_delivery_gate", **kwargs})
        raise HTTPException(
            status_code=409, detail="assessment_delivery_gate_not_satisfied"
        )


class GateSatisfiedService(AssessmentService):
    """门禁满足：存在「已批准且无阻塞项」的评估版本。"""

    def __init__(self) -> None:
        super().__init__(lambda: datetime(2026, 9, 22, 12, 0, tzinfo=UTC))
        self.calls: list[dict[str, Any]] = []

    async def assert_delivery_gate(self, session: Any, **kwargs: Any) -> None:
        self.calls.append({"method": "assert_delivery_gate", **kwargs})


def _client(
    review_service: FakeReviewService,
    gate_service: AssessmentService,
) -> tuple[TestClient, FakeAccess]:
    access = FakeAccess()
    app = FastAPI()
    app.include_router(
        create_review_router(access, review_service, gate_service)  # type: ignore[arg-type]
    )
    return TestClient(app, raise_server_exceptions=False), access


def test_deliver_is_refused_when_assessment_gate_not_satisfied() -> None:
    """门禁不满足时拒绝正式交付（409），且绝不执行不可逆的交付动作。"""
    review = FakeReviewService()
    client, access = _client(review, GateRefusedService())

    response = client.post(
        f"/api/v1/organizations/{ORG}/cases/{CASE}/delivery/deliver",
        json={"client_recipient": "苏州精工仿生机器人科技有限公司"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "assessment_delivery_gate_not_satisfied"
    # 关键：交付动作本身从未执行（不可逆操作被门禁拦下）
    assert review.calls == []
    # 审计仍记录了这次被拒绝的尝试
    assert "case.delivery.deliver" in access.actions


def test_deliver_proceeds_when_assessment_gate_satisfied() -> None:
    """门禁满足时正式交付正常执行。"""
    review = FakeReviewService()
    client, _ = _client(review, GateSatisfiedService())

    response = client.post(
        f"/api/v1/organizations/{ORG}/cases/{CASE}/delivery/deliver",
        json={"client_recipient": "苏州精工仿生机器人科技有限公司"},
    )

    assert response.status_code == 200
    delivery = response.json()["delivery"]
    assert delivery["status"] == "delivered"
    assert delivery["client_recipient"] == "苏州精工仿生机器人科技有限公司"
    assert len(review.calls) == 1
    assert review.calls[0]["organization_id"] == ORG
    assert review.calls[0]["case_id"] == CASE
