"""HTTP API for product descriptions and their features (ADR 0010).

Writes go through access.mutation (authorization, tenant transaction, audit).
Audit summaries carry ids and feature codes only, never product text: the
audit log must not become a second copy of confidential descriptions.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from patent_evidence_api.core.http import parse_uuid_or_404
from patent_evidence_api.fto.product_features import MAX_DESCRIPTION_CHARS, ProductFeatureService
from patent_evidence_api.organization.access import OrganizationAccess


class DescriptionBody(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_DESCRIPTION_CHARS)


class FeatureTextBody(BaseModel):
    text: str = Field(min_length=1, max_length=5_000)


class SplitBody(BaseModel):
    at: int = Field(ge=1)


class MergeBody(BaseModel):
    codes: list[str] = Field(min_length=2, max_length=50)


def create_product_features_router(access: OrganizationAccess, service: ProductFeatureService) -> APIRouter:
    router = APIRouter(prefix="/api/v1/organizations")
    base = "/{organization_id}/cases/{case_id}/product"

    async def in_case(session, org: UUID, case: UUID, set_id: UUID) -> dict[str, Any]:
        """Load a set and make sure it belongs to the case in the URL."""
        data = await service.get_set(session, organization_id=org, set_id=set_id)
        if data["case_id"] != str(case):
            raise HTTPException(status_code=404, detail="product_feature_set_not_found")
        return data

    def ids(organization_id: str, case_id: str, set_id: str | None = None) -> tuple[UUID, UUID, UUID | None]:
        return (
            parse_uuid_or_404(organization_id),
            parse_uuid_or_404(case_id),
            parse_uuid_or_404(set_id) if set_id is not None else None,
        )

    # ---------------------------------------------------------------- descriptions

    @router.post(f"{base}/descriptions", status_code=201)
    async def add_description(organization_id: str, case_id: str, body: DescriptionBody, request: Request) -> JSONResponse:
        org, case, _ = ids(organization_id, case_id)
        async with access.mutation(request, org, action="case.product.description.add", target_type="product_description") as op:
            result = await service.add_description(
                op.session, organization_id=org, case_id=case, description=body.text, actor_id=op.principal.identity_id
            )
            op.describe(target_id=UUID(result["id"]), safe_summary=f"Added product description version {result['version_number']}")
            return JSONResponse(status_code=201, content=result)

    @router.get(f"{base}/descriptions")
    async def list_descriptions(organization_id: str, case_id: str, request: Request) -> dict[str, Any]:
        org, case, _ = ids(organization_id, case_id)
        async with access.authorized(request, org) as (session, _):
            return {"items": await service.list_descriptions(session, organization_id=org, case_id=case)}

    # ---------------------------------------------------------------- feature sets

    @router.post(f"{base}/descriptions/{{description_id}}/feature-sets", status_code=201)
    async def create_draft(organization_id: str, case_id: str, description_id: str, request: Request) -> JSONResponse:
        org, case, _ = ids(organization_id, case_id)
        desc = parse_uuid_or_404(description_id)
        async with access.mutation(request, org, action="case.product.features.draft", target_type="product_feature_set") as op:
            result = await service.create_draft(
                op.session, organization_id=org, case_id=case, description_id=desc, actor_id=op.principal.identity_id
            )
            op.describe(
                target_id=UUID(result["id"]),
                safe_summary=f"Created draft product feature set v{result['version_number']} with {len(result['features'])} candidates",
            )
            return JSONResponse(status_code=201, content=result)

    @router.get(f"{base}/feature-sets")
    async def list_sets(organization_id: str, case_id: str, request: Request) -> dict[str, Any]:
        org, case, _ = ids(organization_id, case_id)
        async with access.authorized(request, org) as (session, _):
            return {"items": await service.list_sets(session, organization_id=org, case_id=case)}

    @router.get(f"{base}/feature-sets/{{set_id}}")
    async def get_set(organization_id: str, case_id: str, set_id: str, request: Request) -> dict[str, Any]:
        org, case, sid = ids(organization_id, case_id, set_id)
        async with access.authorized(request, org) as (session, _):
            return await in_case(session, org, case, sid)  # type: ignore[arg-type]

    async def _edit(request: Request, organization_id: str, case_id: str, set_id: str, action: str, summary: str, run):
        org, case, sid = ids(organization_id, case_id, set_id)
        async with access.mutation(request, org, action=action, target_type="product_feature_set", target_id=sid) as op:
            await in_case(op.session, org, case, sid)  # type: ignore[arg-type]
            result = await run(op, org, sid)
            op.describe(target_id=sid, safe_summary=summary)
            return result

    @router.patch(f"{base}/feature-sets/{{set_id}}/features/{{code}}")
    async def edit_feature(organization_id: str, case_id: str, set_id: str, code: str, body: FeatureTextBody, request: Request):
        return await _edit(
            request, organization_id, case_id, set_id, "case.product.features.edit", f"Edited product feature {code}",
            lambda op, org, sid: service.edit_feature(op.session, organization_id=org, set_id=sid, code=code, new_text=body.text),
        )

    @router.post(f"{base}/feature-sets/{{set_id}}/features", status_code=201)
    async def add_feature(organization_id: str, case_id: str, set_id: str, body: FeatureTextBody, request: Request):
        result = await _edit(
            request, organization_id, case_id, set_id, "case.product.features.add", "Added a manual product feature",
            lambda op, org, sid: service.add_feature(op.session, organization_id=org, set_id=sid, feature_text=body.text),
        )
        return JSONResponse(status_code=201, content=result)

    @router.delete(f"{base}/feature-sets/{{set_id}}/features/{{code}}")
    async def delete_feature(organization_id: str, case_id: str, set_id: str, code: str, request: Request):
        return await _edit(
            request, organization_id, case_id, set_id, "case.product.features.delete", f"Deleted product feature {code}",
            lambda op, org, sid: service.delete_feature(op.session, organization_id=org, set_id=sid, code=code),
        )

    @router.post(f"{base}/feature-sets/{{set_id}}/features/{{code}}/split")
    async def split_feature(organization_id: str, case_id: str, set_id: str, code: str, body: SplitBody, request: Request):
        return await _edit(
            request, organization_id, case_id, set_id, "case.product.features.split", f"Split product feature {code}",
            lambda op, org, sid: service.split_feature(op.session, organization_id=org, set_id=sid, code=code, at=body.at),
        )

    @router.post(f"{base}/feature-sets/{{set_id}}/merge")
    async def merge_features(organization_id: str, case_id: str, set_id: str, body: MergeBody, request: Request):
        return await _edit(
            request, organization_id, case_id, set_id, "case.product.features.merge",
            f"Merged product features {', '.join(sorted(set(body.codes)))}",
            lambda op, org, sid: service.merge_features(op.session, organization_id=org, set_id=sid, codes=body.codes),
        )

    @router.post(f"{base}/feature-sets/{{set_id}}/confirm")
    async def confirm(organization_id: str, case_id: str, set_id: str, request: Request):
        return await _edit(
            request, organization_id, case_id, set_id, "case.product.features.confirm", "Confirmed product feature set",
            lambda op, org, sid: service.confirm(op.session, organization_id=org, set_id=sid, actor_id=op.principal.identity_id),
        )

    @router.post(f"{base}/feature-sets/{{set_id}}/revisions", status_code=201)
    async def revise(organization_id: str, case_id: str, set_id: str, request: Request):
        result = await _edit(
            request, organization_id, case_id, set_id, "case.product.features.revise", "Created a revision of a confirmed set",
            lambda op, org, sid: service.create_revision(op.session, organization_id=org, set_id=sid, actor_id=op.principal.identity_id),
        )
        return JSONResponse(status_code=201, content=result)

    return router
