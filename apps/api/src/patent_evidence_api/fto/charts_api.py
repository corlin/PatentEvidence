"""HTTP API for FTO claim charts with manual findings (ADR 0011).

Audit summaries carry chart ids, feature ids, claim numbers and finding
values only; never claim text, product text or rationale.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from patent_evidence_api.core.http import parse_uuid_or_404
from patent_evidence_api.fto.charts import FINDINGS, FtoChartService
from patent_evidence_api.organization.access import OrganizationAccess


class ChartCreateBody(BaseModel):
    publication_number: str = Field(pattern=r"^(US|EP)-(RE)?\d{1,10}-[A-Z]\d?$")
    product_feature_set_id: UUID


class FindingBody(BaseModel):
    feature_id: str = Field(pattern=r"^\d+\.\d+$")
    finding: str
    product_feature_codes: list[str] = Field(default_factory=list, max_length=50)
    rationale: str = Field(default="", max_length=10_000)


def create_fto_chart_router(access: OrganizationAccess, service: FtoChartService) -> APIRouter:
    router = APIRouter(prefix="/api/v1/organizations")
    base = "/{organization_id}/cases/{case_id}/fto/charts"

    async def in_case(session, org: UUID, case: UUID, chart: UUID) -> dict[str, Any]:
        data = await service.get_chart(session, organization_id=org, chart_id=chart)
        if data["case_id"] != str(case):
            raise HTTPException(status_code=404, detail="fto_chart_not_found")
        return data

    @router.post(base, status_code=201)
    async def create_chart(organization_id: str, case_id: str, body: ChartCreateBody, request: Request) -> JSONResponse:
        org, case = parse_uuid_or_404(organization_id), parse_uuid_or_404(case_id)
        async with access.mutation(request, org, action="case.fto.chart.create", target_type="fto_chart") as op:
            result = await service.create_chart(
                op.session, organization_id=org, case_id=case, publication_number=body.publication_number,
                product_feature_set_id=body.product_feature_set_id, actor_id=op.principal.identity_id,
            )
            op.describe(
                target_id=UUID(result["id"]),
                safe_summary=f"Created FTO chart for {body.publication_number} with {len(result['claims'])} claims",
            )
            return JSONResponse(status_code=201, content=result)

    @router.get(base)
    async def list_charts(organization_id: str, case_id: str, request: Request) -> dict[str, Any]:
        org, case = parse_uuid_or_404(organization_id), parse_uuid_or_404(case_id)
        async with access.authorized(request, org) as (session, _):
            return {"items": await service.list_charts(session, organization_id=org, case_id=case)}

    @router.get(f"{base}/{{chart_id}}")
    async def get_chart(organization_id: str, case_id: str, chart_id: str, request: Request) -> dict[str, Any]:
        org, case, chart = parse_uuid_or_404(organization_id), parse_uuid_or_404(case_id), parse_uuid_or_404(chart_id)
        async with access.authorized(request, org) as (session, _):
            return await in_case(session, org, case, chart)

    @router.get(f"{base}/{{chart_id}}/features/{{feature_id}}/findings")
    async def finding_history(organization_id: str, case_id: str, chart_id: str, feature_id: str, request: Request) -> dict[str, Any]:
        org, case, chart = parse_uuid_or_404(organization_id), parse_uuid_or_404(case_id), parse_uuid_or_404(chart_id)
        async with access.authorized(request, org) as (session, _):
            await in_case(session, org, case, chart)
            return {"items": await service.finding_history(session, organization_id=org, chart_id=chart, feature_id=feature_id)}

    @router.post(f"{base}/{{chart_id}}/claims/{{claim_number}}/confirm-features")
    async def confirm_features(organization_id: str, case_id: str, chart_id: str, claim_number: int, request: Request) -> dict[str, Any]:
        org, case, chart = parse_uuid_or_404(organization_id), parse_uuid_or_404(case_id), parse_uuid_or_404(chart_id)
        async with access.mutation(request, org, action="case.fto.chart.confirm_features", target_type="fto_chart", target_id=chart) as op:
            await in_case(op.session, org, case, chart)
            result = await service.confirm_claim_features(
                op.session, organization_id=org, chart_id=chart, claim_number=claim_number, actor_id=op.principal.identity_id
            )
            op.describe(target_id=chart, safe_summary=f"Confirmed features of claim {claim_number}")
            return result

    @router.post(f"{base}/{{chart_id}}/findings", status_code=201)
    async def record_finding(organization_id: str, case_id: str, chart_id: str, body: FindingBody, request: Request) -> JSONResponse:
        if body.finding not in FINDINGS:
            raise HTTPException(status_code=422, detail="invalid_finding")
        org, case, chart = parse_uuid_or_404(organization_id), parse_uuid_or_404(case_id), parse_uuid_or_404(chart_id)
        async with access.mutation(request, org, action="case.fto.chart.finding", target_type="fto_chart", target_id=chart) as op:
            await in_case(op.session, org, case, chart)
            result = await service.record_finding(
                op.session, organization_id=org, chart_id=chart, feature_id=body.feature_id, finding=body.finding,
                product_feature_codes=body.product_feature_codes, rationale=body.rationale, actor_id=op.principal.identity_id,
            )
            op.describe(target_id=chart, safe_summary=f"Recorded {body.finding} for claim feature {body.feature_id}")
            return JSONResponse(status_code=201, content=result)

    return router
