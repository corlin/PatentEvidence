from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from patent_evidence_api.core.http import parse_uuid_or_404
from patent_evidence_api.organization.access import OrganizationAccess
from patent_evidence_api.reports.services import EvidenceReportService


def create_reports_router(
    access: OrganizationAccess,
    report_service: EvidenceReportService,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/organizations")

    @router.post(
        "/{organization_id}/cases/{case_id}/evidence/seal",
        status_code=201,
    )
    async def seal_evidence_snapshot(
        organization_id: str, case_id: str, request: Request
    ) -> JSONResponse:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.evidence.seal",
            target_type="evidence_snapshot",
        ) as operation:
            result = await report_service.seal_evidence_snapshot(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                actor_identity_id=operation.principal.identity_id,
                actor_email=operation.principal.email,
            )
            operation.describe(
                target_id=UUID(result["snapshot"]["id"]),
                safe_summary="Sealed tamper-evident case evidence snapshot",
            )
            return JSONResponse(status_code=201, content=result)

    @router.get("/{organization_id}/cases/{case_id}/evidence/active")
    async def get_active_evidence_snapshot(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.authorized(request, org_uuid) as (session, _):
            snapshot_data = await report_service.get_active_snapshot(
                session, org_uuid, c_uuid
            )
            if not snapshot_data:
                raise HTTPException(status_code=404, detail="no_evidence_snapshot_found")
            return snapshot_data

    @router.post("/{organization_id}/cases/{case_id}/reports/generate")
    async def generate_report(
        organization_id: str, case_id: str, request: Request
    ) -> JSONResponse:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.report.generate",
            target_type="analysis_report",
        ) as operation:
            result = await report_service.seal_evidence_snapshot(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                actor_identity_id=operation.principal.identity_id,
                actor_email=operation.principal.email,
            )
            operation.describe(
                target_id=UUID(result["snapshot"]["id"]),
                safe_summary="Generated and archived patent analysis report",
            )
            return JSONResponse(status_code=201, content=result)

    @router.get("/{organization_id}/cases/{case_id}/reports/active")
    async def get_active_report(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.authorized(request, org_uuid) as (session, _):
            snapshot_data = await report_service.get_active_snapshot(
                session, org_uuid, c_uuid
            )
            if not snapshot_data or not snapshot_data.get("report"):
                raise HTTPException(status_code=404, detail="no_report_found")
            return snapshot_data

    return router
