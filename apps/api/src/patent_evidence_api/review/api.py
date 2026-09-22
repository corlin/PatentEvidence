from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from patent_evidence_api.core.http import parse_json_body, parse_uuid_or_404
from patent_evidence_api.organization.access import OrganizationAccess
from patent_evidence_api.assessment.services import AssessmentService
from patent_evidence_api.review.services import ReviewService


class ReviewSubmitBody(BaseModel):
    submitter_notes: str = ""


class ItemizedFeedbackItem(BaseModel):
    feature_id: str
    feature_code: str = ""
    comment: str
    suggested_judgment: str | None = None


class ReviewDecideBody(BaseModel):
    decision: str  # 'approved' | 'changes_requested' | 'rejected'
    overall_comments: str = ""
    itemized_feedback: list[ItemizedFeedbackItem] = Field(default_factory=list)
    is_self_audit: bool = False


class DeliveryBody(BaseModel):
    client_recipient: str = ""


def create_review_router(
    access: OrganizationAccess,
    review_service: ReviewService,
    assessment_service: AssessmentService,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/organizations")

    @router.post("/{organization_id}/cases/{case_id}/review/submit", status_code=201)
    async def submit_case_review(
        organization_id: str, case_id: str, request: Request
    ) -> JSONResponse:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        body = await parse_json_body(request, ReviewSubmitBody)

        async with access.mutation(
            request,
            org_uuid,
            action="case.review.submit",
            target_type="review_submission",
        ) as operation:
            result = await review_service.submit_case_for_review(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                actor_identity_id=operation.principal.identity_id,
                submitter_notes=body.submitter_notes,
            )
            operation.describe(
                target_id=UUID(result["id"]),
                safe_summary=f"Submitted case for review round {result['round_number']}",
            )
            return JSONResponse(status_code=201, content={"submission": result})

    @router.get("/{organization_id}/cases/{case_id}/review/current")
    async def get_current_case_review(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)

        async with access.authorized(request, org_uuid) as (session, _):
            result = await review_service.get_current_review(session, org_uuid, c_uuid)
            return {"review": result}

    @router.get("/{organization_id}/cases/{case_id}/review/history")
    async def list_case_review_history(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)

        async with access.authorized(request, org_uuid) as (session, _):
            items = await review_service.list_review_history(session, org_uuid, c_uuid)
            return {"items": items}

    @router.post("/{organization_id}/cases/{case_id}/review/decide")
    async def record_case_review_decision(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        body = await parse_json_body(request, ReviewDecideBody)

        # Retrieve current pending submission
        async with access.authorized(request, org_uuid) as (session, _):
            current = await review_service.get_current_review(session, org_uuid, c_uuid)
            if not current:
                raise HTTPException(status_code=404, detail="no_active_review_submission")
            submission_id = UUID(current["id"])

        async with access.mutation(
            request,
            org_uuid,
            action="case.review.decide",
            target_type="review_decision",
            target_id=submission_id,
        ) as operation:
            feedback_dicts = [f.model_dump() for f in body.itemized_feedback]
            result = await review_service.record_review_decision(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                submission_id=submission_id,
                actor_identity_id=operation.principal.identity_id,
                decision=body.decision,
                overall_comments=body.overall_comments,
                itemized_feedback=feedback_dicts,
                is_self_audit=body.is_self_audit,
            )
            operation.describe(
                target_id=UUID(result["decision_id"]),
                safe_summary=f"Review decision: {body.decision}",
            )
            return result

    @router.post("/{organization_id}/cases/{case_id}/delivery/deliver")
    async def deliver_case(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        body = await parse_json_body(request, DeliveryBody)

        async with access.mutation(
            request,
            org_uuid,
            action="case.delivery.deliver",
            target_type="delivery_record",
        ) as operation:
            # 案件交付门禁：正式交付不可逆，执行前须确认存在「已批准且无阻塞项」
            # 的预评估版本（与 report 结论门禁同口径，但落在案件级）。
            # 不满足时拒绝并给出明确原因，绝不乐观默认。
            await assessment_service.assert_delivery_gate(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
            )
            result = await review_service.deliver_case(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                actor_identity_id=operation.principal.identity_id,
                client_recipient=body.client_recipient,
            )
            operation.describe(
                target_id=UUID(result["id"]),
                safe_summary=f"Delivered case to {body.client_recipient or 'client'}",
            )
            return {"delivery": result}

    @router.get("/{organization_id}/cases/{case_id}/delivery/record")
    async def get_case_delivery_record(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)

        async with access.authorized(request, org_uuid) as (session, _):
            result = await review_service.get_delivery_record(session, org_uuid, c_uuid)
            return {"delivery": result}

    return router
