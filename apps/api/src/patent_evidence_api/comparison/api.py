from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from patent_evidence_api.comparison.services import ComparisonMatrixService
from patent_evidence_api.core.http import parse_json_body, parse_uuid_or_404
from patent_evidence_api.organization.access import OrganizationAccess


class UpdateComparisonItemBody(BaseModel):
    judgment: str | None = None  # 'identical' | 'equivalent' | 'different'
    citation_location: str | None = None
    citation_quote: str | None = None
    reasoning_analysis: str | None = None


def create_comparison_router(
    access: OrganizationAccess,
    comparison_service: ComparisonMatrixService,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/organizations")

    @router.post(
        "/{organization_id}/cases/{case_id}/comparisons/generate",
        status_code=201,
    )
    async def generate_comparisons(
        organization_id: str, case_id: str, request: Request
    ) -> JSONResponse:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.comparison.matrix.generate",
            target_type="comparison_matrix",
        ) as operation:
            result = await comparison_service.generate_or_rebuild_matrix(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                actor_identity_id=operation.principal.identity_id,
            )
            operation.describe(
                target_id=UUID(result["matrix"]["id"]),
                safe_summary="Generated feature comparison matrix",
            )
            return JSONResponse(status_code=201, content=result)

    @router.get("/{organization_id}/cases/{case_id}/comparisons/active")
    async def get_active_comparison_matrix(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.authorized(request, org_uuid) as (session, _):
            matrix_data = await comparison_service.get_active_matrix(
                session, org_uuid, c_uuid
            )
            if not matrix_data:
                raise HTTPException(status_code=404, detail="no_comparison_matrix_found")
            return matrix_data

    @router.put(
        "/{organization_id}/cases/{case_id}/comparisons/items/{comparison_id}"
    )
    async def update_comparison_item(
        organization_id: str,
        case_id: str,
        comparison_id: str,
        request: Request,
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        comp_uuid = parse_uuid_or_404(comparison_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.comparison.item.update",
            target_type="claim_feature_comparison",
            target_id=comp_uuid,
        ) as operation:
            body = await parse_json_body(request, UpdateComparisonItemBody)
            result = await comparison_service.update_comparison_item(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                comparison_id=comp_uuid,
                judgment=body.judgment,
                citation_location=body.citation_location,
                citation_quote=body.citation_quote,
                reasoning_analysis=body.reasoning_analysis,
            )
            operation.describe(
                target_id=comp_uuid,
                safe_summary="Updated feature comparison judgment and citation",
            )
            return result

    @router.post(
        "/{organization_id}/cases/{case_id}/comparisons/{matrix_id}/confirm"
    )
    async def confirm_comparison_matrix(
        organization_id: str,
        case_id: str,
        matrix_id: str,
        request: Request,
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        m_uuid = parse_uuid_or_404(matrix_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.comparison.matrix.confirm",
            target_type="comparison_matrix",
            target_id=m_uuid,
        ) as operation:
            result = await comparison_service.confirm_matrix(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                matrix_id=m_uuid,
                actor_identity_id=operation.principal.identity_id,
            )
            operation.describe(
                target_id=m_uuid,
                safe_summary="Confirmed and locked feature comparison matrix",
            )
            return result

    return router
