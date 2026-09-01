from datetime import datetime
from typing import Any, TypeVar
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.exc import IntegrityError

from patent_evidence_api.platform.access import PlatformAccess
from patent_evidence_api.platform.organizations import (
    OrganizationDirectory,
    OrganizationOpening,
    OrganizationProvisioner,
)

RequestModel = TypeVar("RequestModel", bound=BaseModel)


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
    access: PlatformAccess,
    provisioner: OrganizationProvisioner,
    directory: OrganizationDirectory,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/platform")

    async def request_model(
        request: Request, model: type[RequestModel]
    ) -> RequestModel:
        try:
            return model.model_validate(await request.json())
        except (ValueError, ValidationError) as exc:
            raise HTTPException(
                status_code=422, detail="invalid_platform_mutation_request"
            ) from exc

    def idempotency_key(request: Request) -> str:
        value = request.headers.get("Idempotency-Key", "")
        if not 8 <= len(value) <= 128 or not value.isprintable():
            raise HTTPException(status_code=422, detail="invalid_idempotency_key")
        return value

    def organization_target(value: str) -> UUID | None:
        try:
            return UUID(value)
        except ValueError:
            return None

    @router.post("/organizations", status_code=201)
    async def create_organization(request: Request) -> JSONResponse:
        try:
            async with access.mutation(
                request,
                action="platform.organization.create",
                target_type="organization",
            ) as operation:
                body = await request_model(request, OrganizationCreateBody)
                status, response, organization_id = await provisioner.open(
                    operation.session,
                    actor_identity_id=operation.principal.identity_id,
                    idempotency_key=idempotency_key(request),
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
            return {"items": await directory.list(session)}

    @router.get("/organizations/{organization_id}")
    async def get_organization(
        organization_id: UUID, request: Request
    ) -> dict[str, Any]:
        async with access.authorized(request) as (session, _):
            detail = await directory.detail(session, organization_id)
            if detail is None:
                raise HTTPException(status_code=404, detail="organization_not_found")
            return detail

    async def mutate_status(
        organization_id: str, request: Request, *, status: str, action: str
    ) -> dict[str, Any]:
        target = organization_target(organization_id)
        async with access.mutation(
            request,
            action=action,
            target_type="organization",
            target_id=target,
        ) as operation:
            if target is None:
                raise HTTPException(status_code=422, detail="invalid_organization_id")
            operation.describe(
                target_id=target,
                safe_summary="organization lifecycle status changed",
            )
            detail = await directory.set_status(operation.session, target, status)
            return detail

    @router.post("/organizations/{organization_id}/suspend")
    async def suspend_organization(
        organization_id: str, request: Request
    ) -> dict[str, Any]:
        return await mutate_status(
            organization_id,
            request,
            status="suspended",
            action="platform.organization.suspend",
        )

    @router.post("/organizations/{organization_id}/reactivate")
    async def reactivate_organization(
        organization_id: str, request: Request
    ) -> dict[str, Any]:
        return await mutate_status(
            organization_id,
            request,
            status="active",
            action="platform.organization.reactivate",
        )

    @router.put("/organizations/{organization_id}/expiry")
    async def set_expiry(organization_id: str, request: Request) -> dict[str, Any]:
        target = organization_target(organization_id)
        async with access.mutation(
            request,
            action="platform.organization.set_expiry",
            target_type="organization",
            target_id=target,
        ) as operation:
            if target is None:
                raise HTTPException(status_code=422, detail="invalid_organization_id")
            body = await request_model(request, ExpiryBody)
            operation.describe(
                target_id=target,
                safe_summary="organization expiry changed",
            )
            detail = await directory.set_expiry(
                operation.session, target, body.expires_at
            )
            return detail

    return router
