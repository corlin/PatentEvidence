from typing import Any, Literal, TypeVar
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from patent_evidence_api.auth.security import (
    AsyncPasswordSecurity,
    PasswordWorkCapacityError,
)
from patent_evidence_api.organization.access import OrganizationAccess
from patent_evidence_api.organization.invitations import (
    InvitationAcceptance,
    InvitationService,
)
from patent_evidence_api.organization.members import MemberService

RequestModel = TypeVar("RequestModel", bound=BaseModel)


class InvitationCreateBody(BaseModel):
    email: str
    role: Literal["organization_admin", "patent_agent", "reviewer"]


class InvitationAcceptBody(BaseModel):
    display_name: str | None = None
    password: str | None = None


class MemberRoleBody(BaseModel):
    role: Literal["organization_admin", "patent_agent", "reviewer"]


def create_organization_router(
    access: OrganizationAccess,
    invitations: InvitationService,
    members: MemberService,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/organizations")

    async def request_model(
        request: Request, model: type[RequestModel]
    ) -> RequestModel:
        try:
            return model.model_validate(await request.json())
        except (ValueError, ValidationError) as exc:
            raise HTTPException(
                status_code=422, detail="invalid_organization_mutation_request"
            ) from exc

    def target_uuid(value: str) -> UUID | None:
        try:
            return UUID(value)
        except ValueError:
            return None

    @router.post("/{organization_id}/invitations", status_code=201)
    async def create_invitation(
        organization_id: UUID, request: Request
    ) -> JSONResponse:
        async with access.mutation(
            request,
            organization_id,
            action="organization.invitation.create",
            target_type="organization_invitation",
        ) as operation:
            body = await request_model(request, InvitationCreateBody)
            invitation, token = await invitations.create(
                operation.session,
                organization_id=organization_id,
                actor_identity_id=operation.principal.identity_id,
                email=body.email,
                role=body.role,
            )
            operation.describe(
                target_id=UUID(invitation["id"]),
                safe_summary="Created organization invitation",
            )
        return JSONResponse(
            status_code=201,
            content={"invitation": invitation, "invitation_token": token},
        )

    @router.get("/{organization_id}/invitations/{invitation_id}")
    async def get_invitation(
        organization_id: UUID, invitation_id: UUID, request: Request
    ) -> dict[str, Any]:
        async with access.authorized(request, organization_id) as (session, _):
            detail = await invitations.detail(session, organization_id, invitation_id)
            if detail is None:
                raise HTTPException(status_code=404, detail="invitation_not_found")
            return detail

    @router.post("/{organization_id}/invitations/{invitation_id}/revoke")
    async def revoke_invitation(
        organization_id: UUID, invitation_id: str, request: Request
    ) -> dict[str, Any]:
        target = target_uuid(invitation_id)
        async with access.mutation(
            request,
            organization_id,
            action="organization.invitation.revoke",
            target_type="organization_invitation",
            target_id=target,
        ) as operation:
            if target is None:
                raise HTTPException(status_code=422, detail="invalid_invitation_id")
            detail = await invitations.revoke(
                operation.session, organization_id, target
            )
            operation.describe(
                target_id=target,
                safe_summary="Revoked organization invitation",
            )
            return detail

    @router.post(
        "/{organization_id}/invitations/{invitation_id}/resend", status_code=201
    )
    async def resend_invitation(
        organization_id: UUID, invitation_id: str, request: Request
    ) -> JSONResponse:
        target = target_uuid(invitation_id)
        async with access.mutation(
            request,
            organization_id,
            action="organization.invitation.resend",
            target_type="organization_invitation",
            target_id=target,
        ) as operation:
            if target is None:
                raise HTTPException(status_code=422, detail="invalid_invitation_id")
            invitation, token = await invitations.resend(
                operation.session,
                organization_id=organization_id,
                invitation_id=target,
                actor_identity_id=operation.principal.identity_id,
            )
            operation.describe(
                target_id=UUID(invitation["id"]),
                safe_summary="Replaced organization invitation",
            )
        return JSONResponse(
            status_code=201,
            content={"invitation": invitation, "invitation_token": token},
        )

    @router.get("/{organization_id}/members")
    async def list_members(organization_id: UUID, request: Request) -> dict[str, Any]:
        async with access.authorized(request, organization_id) as (session, _):
            return {"items": await members.list(session, organization_id)}

    @router.put("/{organization_id}/members/{membership_id}/role")
    async def change_member_role(
        organization_id: UUID,
        membership_id: str,
        request: Request,
    ) -> dict[str, Any]:
        target = target_uuid(membership_id)
        async with access.mutation(
            request,
            organization_id,
            action="organization.member.role_change",
            target_type="organization_membership",
            target_id=target,
        ) as operation:
            if target is None:
                raise HTTPException(status_code=422, detail="invalid_membership_id")
            body = await request_model(request, MemberRoleBody)
            member = await members.set_role(
                operation.session,
                organization_id=organization_id,
                actor_identity_id=operation.principal.identity_id,
                membership_id=target,
                role=body.role,
            )
            operation.describe(
                target_id=target,
                safe_summary="Changed organization member role",
            )
            return member

    async def change_member_status(
        organization_id: UUID,
        membership_id: str,
        request: Request,
        *,
        transition: str,
    ) -> dict[str, Any]:
        target = target_uuid(membership_id)
        async with access.mutation(
            request,
            organization_id,
            action=f"organization.member.{transition}",
            target_type="organization_membership",
            target_id=target,
        ) as operation:
            if target is None:
                raise HTTPException(status_code=422, detail="invalid_membership_id")
            member = await members.set_status(
                operation.session,
                organization_id=organization_id,
                actor_identity_id=operation.principal.identity_id,
                membership_id=target,
                transition=transition,
            )
            operation.describe(
                target_id=target,
                safe_summary=f"Changed organization member status: {transition}",
            )
            return member

    @router.post("/{organization_id}/members/{membership_id}/suspend")
    async def suspend_member(
        organization_id: UUID, membership_id: str, request: Request
    ) -> dict[str, Any]:
        return await change_member_status(
            organization_id,
            membership_id,
            request,
            transition="suspend",
        )

    @router.post("/{organization_id}/members/{membership_id}/reactivate")
    async def reactivate_member(
        organization_id: UUID, membership_id: str, request: Request
    ) -> dict[str, Any]:
        return await change_member_status(
            organization_id,
            membership_id,
            request,
            transition="reactivate",
        )

    @router.post("/{organization_id}/members/{membership_id}/remove")
    async def remove_member(
        organization_id: UUID, membership_id: str, request: Request
    ) -> dict[str, Any]:
        return await change_member_status(
            organization_id,
            membership_id,
            request,
            transition="remove",
        )

    return router


def create_invitation_router(
    acceptance: InvitationAcceptance, passwords: AsyncPasswordSecurity
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/invitations")

    @router.get("/{token}")
    async def inspect_invitation(token: str) -> dict[str, Any]:
        preview = await acceptance.inspect(token)
        if preview is None:
            raise HTTPException(status_code=404, detail="invitation_not_found")
        return {
            "id": str(preview["id"]),
            "organization": {
                "id": str(preview["organization_id"]),
                "display_name": preview["organization_display_name"],
            },
            "email": preview["email"],
            "role": preview["role"],
            "status": preview["status"],
            "expires_at": preview["expires_at"].isoformat(),
            "existing_identity": preview["identity_id"] is not None,
        }

    @router.post("/{token}/accept", status_code=201)
    async def accept_invitation(token: str, request: Request) -> JSONResponse:
        preview = await acceptance.inspect(token)
        if preview is None:
            raise HTTPException(status_code=404, detail="invitation_not_found")
        correlation = request.headers.get("X-Request-ID", "")
        if not correlation or len(correlation) > 128 or not correlation.isprintable():
            correlation = str(uuid4())
        try:
            body = InvitationAcceptBody.model_validate(await request.json())
        except (ValueError, ValidationError) as exc:
            await acceptance.record(
                preview, result="denied", correlation_id=correlation
            )
            raise HTTPException(
                status_code=422, detail="invalid_invitation_acceptance_request"
            ) from exc
        new_password_hash: str | None = None
        if preview["identity_id"] is None:
            if not body.display_name or body.password is None:
                await acceptance.record(
                    preview, result="denied", correlation_id=correlation
                )
                raise HTTPException(
                    status_code=422, detail="new_identity_credentials_required"
                )
            try:
                new_password_hash = await passwords.hash(body.password)
            except ValueError as exc:
                await acceptance.record(
                    preview, result="denied", correlation_id=correlation
                )
                raise HTTPException(
                    status_code=422, detail="password_policy_failed"
                ) from exc
            except PasswordWorkCapacityError as exc:
                await acceptance.record(
                    preview, result="failed", correlation_id=correlation
                )
                raise HTTPException(
                    status_code=503, detail="authentication_temporarily_unavailable"
                ) from exc
        membership = await acceptance.accept(
            preview,
            display_name=body.display_name,
            new_password_hash=new_password_hash,
            correlation_id=correlation,
        )
        return JSONResponse(status_code=201, content={"membership": membership})

    return router
