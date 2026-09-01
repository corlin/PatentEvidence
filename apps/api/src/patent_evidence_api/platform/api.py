from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError

from patent_evidence_api.platform.access import PlatformAccess
from patent_evidence_api.platform.organizations import (
    OrganizationOpening,
    OrganizationProvisioning,
)


class OrganizationCreateBody(BaseModel):
    slug: str = Field(
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=2, max_length=63
    )
    display_name: str = Field(min_length=1, max_length=160)
    admin_email: str = Field(min_length=3, max_length=320)
    plan_key: str = Field(pattern=r"^[a-z0-9_-]+$", min_length=1, max_length=64)
    monthly_case_allowance: int = Field(ge=0, le=1_000_000)
    current_period_start: datetime
    current_period_end: datetime
    expires_at: datetime | None = None

    @field_validator("admin_email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized:
            raise ValueError("invalid email")
        return normalized

    @field_validator("current_period_start", "current_period_end", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timezone required")
        return value

    def opening(self) -> OrganizationOpening:
        return OrganizationOpening(**self.model_dump())


class ExpiryBody(BaseModel):
    expires_at: datetime | None

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timezone required")
        return value


def create_platform_router(
    access: PlatformAccess, organizations: OrganizationProvisioning
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/platform")

    @router.post("/organizations", status_code=201)
    async def create_organization(
        body: OrganizationCreateBody,
        request: Request,
        idempotency_key: str = Header(
            alias="Idempotency-Key", min_length=8, max_length=128
        ),
    ) -> JSONResponse:
        try:
            async with access.mutation(
                request,
                action="platform.organization.create",
                target_type="organization",
            ) as operation:
                status, response, organization_id = await organizations.open(
                    operation.session,
                    actor_identity_id=operation.principal.identity_id,
                    idempotency_key=idempotency_key,
                    opening=body.opening(),
                )
                operation.describe(
                    target_id=organization_id,
                    safe_summary=(
                        "idempotent organization creation replayed"
                        if status == 200
                        else "organization and initial administrator invitation created"
                    ),
                )
        except IntegrityError:
            raise HTTPException(
                status_code=409, detail="organization_creation_conflict"
            ) from None
        return JSONResponse(status_code=status, content=response)

    @router.get("/organizations")
    async def list_organizations(request: Request) -> dict[str, Any]:
        async with access.authorized(request) as (session, _):
            return {"items": await organizations.list(session)}

    @router.get("/organizations/{organization_id}")
    async def get_organization(
        organization_id: UUID, request: Request
    ) -> dict[str, Any]:
        async with access.authorized(request) as (session, _):
            detail = await organizations.detail(session, organization_id)
            if detail is None:
                raise HTTPException(status_code=404, detail="organization_not_found")
            return detail

    async def mutate_status(
        organization_id: UUID, request: Request, *, status: str, action: str
    ) -> dict[str, Any]:
        async with access.mutation(
            request, action=action, target_type="organization"
        ) as operation:
            detail = await organizations.set_status(
                operation.session, organization_id, status
            )
            operation.describe(
                target_id=organization_id,
                safe_summary="organization lifecycle status changed",
            )
            return detail

    @router.post("/organizations/{organization_id}/suspend")
    async def suspend_organization(
        organization_id: UUID, request: Request
    ) -> dict[str, Any]:
        return await mutate_status(
            organization_id,
            request,
            status="suspended",
            action="platform.organization.suspend",
        )

    @router.post("/organizations/{organization_id}/reactivate")
    async def reactivate_organization(
        organization_id: UUID, request: Request
    ) -> dict[str, Any]:
        return await mutate_status(
            organization_id,
            request,
            status="active",
            action="platform.organization.reactivate",
        )

    @router.put("/organizations/{organization_id}/expiry")
    async def set_expiry(
        organization_id: UUID, body: ExpiryBody, request: Request
    ) -> dict[str, Any]:
        async with access.mutation(
            request,
            action="platform.organization.set_expiry",
            target_type="organization",
        ) as operation:
            detail = await organizations.set_expiry(
                operation.session, organization_id, body.expires_at
            )
            operation.describe(
                target_id=organization_id,
                safe_summary="organization expiry changed",
            )
            return detail

    return router
