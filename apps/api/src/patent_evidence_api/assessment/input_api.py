"""HTTP routes for pre-assessment input profiles.

Kept in a router of its own so the version router can stay strictly
read-or-append. These profiles are human-entered input, not approval
records, so they may be rewritten; that cannot alter a version already
written, because a version freezes its package and digest at creation.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from patent_evidence_api.assessment.inputs import AssessmentInputService
from patent_evidence_api.core.http import parse_json_body, parse_uuid_or_404
from patent_evidence_api.organization.access import OrganizationAccess


class ApplicationProfileBody(BaseModel):
    filing_date: date
    application_type: str = "invention"
    priority_claims: list[dict[str, Any]] = Field(default_factory=list)


class CandidateProfileBody(BaseModel):
    filing_date: date | None = None
    priority_date: date | None = None
    filed_in_china: bool = True
    source_verified: bool = False


def create_assessment_input_router(
    access: OrganizationAccess,
    input_service: AssessmentInputService,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/organizations")

    @router.get("/{organization_id}/cases/{case_id}/assessment-input/application")
    async def get_application_profile(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        case_uuid = parse_uuid_or_404(case_id)

        async with access.authorized(request, org_uuid) as (session, _):
            profile = await input_service.get_application_profile(
                session, organization_id=org_uuid, case_id=case_uuid
            )
            return {"profile": profile}

    @router.post("/{organization_id}/cases/{case_id}/assessment-input/application")
    async def upsert_application_profile(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        case_uuid = parse_uuid_or_404(case_id)
        body = await parse_json_body(request, ApplicationProfileBody)

        async with access.mutation(
            request,
            org_uuid,
            action="case.assessment_input.upsert_application",
            target_type="case_application_profile",
        ) as operation:
            profile = await input_service.upsert_application_profile(
                operation.session,
                organization_id=org_uuid,
                case_id=case_uuid,
                filing_date=body.filing_date,
                application_type=body.application_type,
                priority_claims=body.priority_claims,
                actor_identity_id=operation.principal.identity_id,
            )
            operation.describe(
                target_id=UUID(profile["id"]),
                safe_summary="Updated subject application profile",
            )
            return {"profile": profile}

    @router.get("/{organization_id}/cases/{case_id}/assessment-input/candidates")
    async def list_candidate_profiles(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        case_uuid = parse_uuid_or_404(case_id)

        async with access.authorized(request, org_uuid) as (session, _):
            items = await input_service.list_candidate_profiles(
                session, organization_id=org_uuid, case_id=case_uuid
            )
            return {"items": items}

    @router.post(
        "/{organization_id}/cases/{case_id}/assessment-input/candidates/{candidate_id}"
    )
    async def upsert_candidate_profile(
        organization_id: str, case_id: str, candidate_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        case_uuid = parse_uuid_or_404(case_id)
        cand_uuid = parse_uuid_or_404(candidate_id)
        body = await parse_json_body(request, CandidateProfileBody)

        async with access.mutation(
            request,
            org_uuid,
            action="case.assessment_input.upsert_candidate",
            target_type="candidate_document_profile",
        ) as operation:
            profile = await input_service.upsert_candidate_profile(
                operation.session,
                organization_id=org_uuid,
                case_id=case_uuid,
                candidate_id=cand_uuid,
                filing_date=body.filing_date,
                priority_date=body.priority_date,
                filed_in_china=body.filed_in_china,
                source_verified=body.source_verified,
                actor_identity_id=operation.principal.identity_id,
            )
            operation.describe(
                target_id=UUID(profile["id"]),
                safe_summary="Updated candidate document profile",
            )
            return {"profile": profile}

    return router
