from __future__ import annotations

from typing import Any, TypeVar
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from patent_evidence_api.core.http import parse_json_body, parse_uuid_or_404
from patent_evidence_api.features.services import FeatureService
from patent_evidence_api.organization.access import OrganizationAccess


class AddFeatureBody(BaseModel):
    feature_code: str = Field(default="", max_length=32)
    feature_type: str = Field(default="characterizing", max_length=32)
    feature_statement: str = Field(min_length=1)
    source_paragraph_id: str | None = None
    citation_quote: str | None = None


class UpdateFeatureBody(BaseModel):
    feature_code: str | None = None
    feature_type: str | None = None
    feature_statement: str | None = None
    source_paragraph_id: str | None = None
    citation_quote: str | None = None
    sort_order: int | None = None


class SplitFeatureBody(BaseModel):
    part1_statement: str = Field(min_length=1)
    part2_statement: str = Field(min_length=1)


class MergeFeaturesBody(BaseModel):
    feature_id_1: str
    feature_id_2: str
    merged_statement: str = Field(min_length=1)


def create_features_router(
    access: OrganizationAccess,
    feature_service: FeatureService,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/organizations")

    @router.post("/{organization_id}/cases/{case_id}/features/extract", status_code=201)
    async def extract_features(
        organization_id: str,
        case_id: str,
        request: Request,
    ) -> JSONResponse:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.features.extract",
            target_type="feature_set_version",
        ) as operation:
            result = await feature_service.extract_draft_features(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                actor_identity_id=operation.principal.identity_id,
            )
            operation.describe(
                target_id=UUID(result["version"]["id"]),
                safe_summary="Extracted initial draft features",
            )
            return JSONResponse(status_code=201, content=result)

    @router.get("/{organization_id}/cases/{case_id}/features/active")
    async def get_active_features(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.authorized(request, org_uuid) as (session, _):
            data = await feature_service.get_active_feature_set(session, org_uuid, c_uuid)
            if data is None:
                raise HTTPException(status_code=404, detail="no_feature_set_found")
            return data

    @router.get("/{organization_id}/cases/{case_id}/features/versions")
    async def list_versions(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.authorized(request, org_uuid) as (session, _):
            return {
                "items": await feature_service.list_versions(
                    session, org_uuid, c_uuid
                )
            }

    @router.get("/{organization_id}/cases/{case_id}/features/versions/{version_id}")
    async def get_version(
        organization_id: str, case_id: str, version_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        v_uuid = parse_uuid_or_404(version_id)
        async with access.authorized(request, org_uuid) as (session, _):
            return await feature_service.get_feature_set(
                session, org_uuid, c_uuid, v_uuid
            )

    @router.post(
        "/{organization_id}/cases/{case_id}/features/versions/{version_id}/items",
        status_code=201,
    )
    async def add_feature(
        organization_id: str,
        case_id: str,
        version_id: str,
        request: Request,
    ) -> JSONResponse:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        v_uuid = parse_uuid_or_404(version_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.features.add_item",
            target_type="claim_feature",
        ) as operation:
            body = await parse_json_body(request, AddFeatureBody)
            result = await feature_service.add_feature(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                version_id=v_uuid,
                feature_code=body.feature_code,
                feature_type=body.feature_type,
                feature_statement=body.feature_statement,
                source_paragraph_id=body.source_paragraph_id,
                citation_quote=body.citation_quote,
            )
            operation.describe(
                target_id=v_uuid,
                safe_summary=f"Added claim feature {body.feature_code}",
            )
            return JSONResponse(status_code=201, content=result)

    @router.put(
        "/{organization_id}/cases/{case_id}/features/versions/{version_id}/items/{feature_id}"
    )
    async def update_feature(
        organization_id: str,
        case_id: str,
        version_id: str,
        feature_id: str,
        request: Request,
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        v_uuid = parse_uuid_or_404(version_id)
        f_uuid = parse_uuid_or_404(feature_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.features.update_item",
            target_type="claim_feature",
            target_id=f_uuid,
        ) as operation:
            body = await parse_json_body(request, UpdateFeatureBody)
            result = await feature_service.update_feature(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                version_id=v_uuid,
                feature_id=f_uuid,
                feature_code=body.feature_code,
                feature_type=body.feature_type,
                feature_statement=body.feature_statement,
                source_paragraph_id=body.source_paragraph_id,
                citation_quote=body.citation_quote,
                sort_order=body.sort_order,
            )
            operation.describe(
                target_id=f_uuid,
                safe_summary="Updated claim feature",
            )
            return result

    @router.delete(
        "/{organization_id}/cases/{case_id}/features/versions/{version_id}/items/{feature_id}"
    )
    async def delete_feature(
        organization_id: str,
        case_id: str,
        version_id: str,
        feature_id: str,
        request: Request,
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        v_uuid = parse_uuid_or_404(version_id)
        f_uuid = parse_uuid_or_404(feature_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.features.delete_item",
            target_type="claim_feature",
            target_id=f_uuid,
        ) as operation:
            result = await feature_service.delete_feature(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                version_id=v_uuid,
                feature_id=f_uuid,
            )
            operation.describe(
                target_id=f_uuid,
                safe_summary="Deleted claim feature",
            )
            return result

    @router.post(
        "/{organization_id}/cases/{case_id}/features/versions/{version_id}/items/{feature_id}/split"
    )
    async def split_feature(
        organization_id: str,
        case_id: str,
        version_id: str,
        feature_id: str,
        request: Request,
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        v_uuid = parse_uuid_or_404(version_id)
        f_uuid = parse_uuid_or_404(feature_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.features.split_item",
            target_type="claim_feature",
            target_id=f_uuid,
        ) as operation:
            body = await parse_json_body(request, SplitFeatureBody)
            result = await feature_service.split_feature(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                version_id=v_uuid,
                feature_id=f_uuid,
                part1_statement=body.part1_statement,
                part2_statement=body.part2_statement,
            )
            operation.describe(
                target_id=f_uuid,
                safe_summary="Split claim feature into two parts",
            )
            return result

    @router.post(
        "/{organization_id}/cases/{case_id}/features/versions/{version_id}/merge"
    )
    async def merge_features(
        organization_id: str,
        case_id: str,
        version_id: str,
        request: Request,
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        v_uuid = parse_uuid_or_404(version_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.features.merge_items",
            target_type="claim_feature",
        ) as operation:
            body = await parse_json_body(request, MergeFeaturesBody)
            f1_uuid = parse_uuid_or_404(body.feature_id_1)
            f2_uuid = parse_uuid_or_404(body.feature_id_2)
            result = await feature_service.merge_features(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                version_id=v_uuid,
                feature_id_1=f1_uuid,
                feature_id_2=f2_uuid,
                merged_statement=body.merged_statement,
            )
            operation.describe(
                target_id=f1_uuid,
                safe_summary="Merged two claim features",
            )
            return result

    @router.post(
        "/{organization_id}/cases/{case_id}/features/versions/{version_id}/confirm"
    )
    async def confirm_version(
        organization_id: str,
        case_id: str,
        version_id: str,
        request: Request,
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        v_uuid = parse_uuid_or_404(version_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.features.confirm_version",
            target_type="feature_set_version",
            target_id=v_uuid,
        ) as operation:
            result = await feature_service.confirm_version(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                version_id=v_uuid,
                actor_identity_id=operation.principal.identity_id,
            )
            operation.describe(
                target_id=v_uuid,
                safe_summary="Confirmed and locked feature set version",
            )
            return result

    @router.post(
        "/{organization_id}/cases/{case_id}/features/versions/{version_id}/revision"
    )
    async def create_revision(
        organization_id: str,
        case_id: str,
        version_id: str,
        request: Request,
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        v_uuid = parse_uuid_or_404(version_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.features.create_revision",
            target_type="feature_set_version",
            target_id=v_uuid,
        ) as operation:
            result = await feature_service.create_revision(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                base_version_id=v_uuid,
                actor_identity_id=operation.principal.identity_id,
            )
            operation.describe(
                target_id=UUID(result["version"]["id"]),
                safe_summary="Created feature set revision draft from parent",
            )
            return result

    return router
