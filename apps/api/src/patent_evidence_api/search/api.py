from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from adapters.search.google_patents import GooglePatentsSearchAdapter
from adapters.search.openalex import OpenAlexSearchAdapter
from adapters.search.epo import EpoSearchAdapter
from adapters.search.uspto import UsptoSearchAdapter
from patent_evidence_api.core.http import parse_json_body, parse_uuid_or_404
from patent_evidence_api.organization.access import OrganizationAccess
from patent_evidence_api.search.services import (
    CandidateTriageService,
    SearchExecutionService,
    SearchStrategyService,
)


class UpdateStrategyBody(BaseModel):
    keywords_matrix: dict[str, list[str]] | None = None
    ipc_classes: list[dict[str, str]] | None = None
    boolean_query_cnipr: str | None = None
    boolean_query_standard: str | None = None


class ExecutePublicSearchBody(BaseModel):
    source_type: str = Field(default="google_patents")


class ImportCniprBody(BaseModel):
    raw_content: str = Field(min_length=1)


class UpdateTriageBody(BaseModel):
    triage_status: str = Field(min_length=1)  # 'pending' | 'included' | 'excluded'
    exclusion_reason: str | None = None
    notes: str | None = None


def create_search_router(
    access: OrganizationAccess,
    strategy_service: SearchStrategyService,
    execution_service: SearchExecutionService,
    triage_service: CandidateTriageService,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/organizations")

    google_adapter = GooglePatentsSearchAdapter()
    openalex_adapter = OpenAlexSearchAdapter()
    epo_adapter = EpoSearchAdapter()
    uspto_adapter = UsptoSearchAdapter()

    @router.post(
        "/{organization_id}/cases/{case_id}/search/strategies/generate",
        status_code=201,
    )
    async def generate_strategy(
        organization_id: str, case_id: str, request: Request
    ) -> JSONResponse:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.search.strategy.generate",
            target_type="search_strategy",
        ) as operation:
            result = await strategy_service.generate_strategy(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                actor_identity_id=operation.principal.identity_id,
            )
            operation.describe(
                target_id=UUID(result["id"]),
                safe_summary="Generated patent search strategy and CNIPR query",
            )
            return JSONResponse(status_code=201, content=result)

    @router.get("/{organization_id}/cases/{case_id}/search/strategies/active")
    async def get_active_strategy(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.authorized(request, org_uuid) as (session, _):
            strat = await strategy_service.get_active_strategy(
                session, org_uuid, c_uuid
            )
            if not strat:
                raise HTTPException(status_code=404, detail="no_search_strategy_found")
            return strat

    @router.put(
        "/{organization_id}/cases/{case_id}/search/strategies/{strategy_id}"
    )
    async def update_strategy(
        organization_id: str,
        case_id: str,
        strategy_id: str,
        request: Request,
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        s_uuid = parse_uuid_or_404(strategy_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.search.strategy.update",
            target_type="search_strategy",
            target_id=s_uuid,
        ) as operation:
            body = await parse_json_body(request, UpdateStrategyBody)
            result = await strategy_service.update_strategy(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                strategy_id=s_uuid,
                keywords_matrix=body.keywords_matrix,
                ipc_classes=body.ipc_classes,
                boolean_query_cnipr=body.boolean_query_cnipr,
                boolean_query_standard=body.boolean_query_standard,
            )
            operation.describe(
                target_id=s_uuid,
                safe_summary="Updated search strategy keywords and boolean queries",
            )
            return result

    @router.get(
        "/{organization_id}/cases/{case_id}/search/strategies/{strategy_id}/handoff"
    )
    async def get_handoff_package(
        organization_id: str,
        case_id: str,
        strategy_id: str,
        request: Request,
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        s_uuid = parse_uuid_or_404(strategy_id)
        async with access.authorized(request, org_uuid) as (session, _):
            return await strategy_service.get_handoff_package(
                session, org_uuid, c_uuid, s_uuid
            )

    @router.post(
        "/{organization_id}/cases/{case_id}/search/jobs/execute-public",
        status_code=201,
    )
    async def execute_public_search(
        organization_id: str,
        case_id: str,
        request: Request,
    ) -> JSONResponse:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.search.job.execute",
            target_type="search_job",
        ) as operation:
            body = await parse_json_body(request, ExecutePublicSearchBody)
            strat = await strategy_service.get_active_strategy(
                operation.session, org_uuid, c_uuid
            )
            if body.source_type == "epo":
                adapter = epo_adapter
            elif body.source_type == "uspto":
                adapter = uspto_adapter
            elif body.source_type == "openalex":
                adapter = openalex_adapter
            else:
                adapter = google_adapter
            result = await execution_service.execute_public_search(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                strategy=strat,
                adapter=adapter,
                actor_identity_id=operation.principal.identity_id,
                source_type=body.source_type,
            )
            operation.describe(
                target_id=UUID(result["job_id"]),
                safe_summary=f"Executed public patent search via {body.source_type}",
            )
            return JSONResponse(status_code=201, content=result)

    @router.post(
        "/{organization_id}/cases/{case_id}/search/candidates/import-cnipr",
        status_code=201,
    )
    async def import_cnipr_results(
        organization_id: str,
        case_id: str,
        request: Request,
    ) -> JSONResponse:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.search.candidate.import_cnipr",
            target_type="search_candidate",
        ) as operation:
            body = await parse_json_body(request, ImportCniprBody)
            strat = await strategy_service.get_active_strategy(
                operation.session, org_uuid, c_uuid
            )
            result = await triage_service.import_cnipr_candidates(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                raw_content=body.raw_content,
                actor_identity_id=operation.principal.identity_id,
                strategy=strat,
            )
            operation.describe(
                target_id=c_uuid,
                safe_summary=f"Imported {result['imported_count']} candidates from CNIPR results",
            )
            return JSONResponse(status_code=201, content=result)

    @router.get("/{organization_id}/cases/{case_id}/search/candidates")
    async def list_candidates(
        organization_id: str,
        case_id: str,
        request: Request,
        triage_status: str | None = None,
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.authorized(request, org_uuid) as (session, _):
            items = await triage_service.list_candidates(
                session, org_uuid, c_uuid, triage_status=triage_status
            )
            return {"items": items}

    @router.post(
        "/{organization_id}/cases/{case_id}/search/candidates/{candidate_id}/triage"
    )
    async def update_candidate_triage(
        organization_id: str,
        case_id: str,
        candidate_id: str,
        request: Request,
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        cand_uuid = parse_uuid_or_404(candidate_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.search.candidate.triage",
            target_type="candidate_triage_record",
            target_id=cand_uuid,
        ) as operation:
            body = await parse_json_body(request, UpdateTriageBody)
            result = await triage_service.update_triage(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                candidate_id=cand_uuid,
                triage_status=body.triage_status,
                exclusion_reason=body.exclusion_reason,
                notes=body.notes,
                actor_identity_id=operation.principal.identity_id,
            )
            operation.describe(
                target_id=cand_uuid,
                safe_summary=f"Triaged candidate as {body.triage_status}",
            )
            return result

    return router
