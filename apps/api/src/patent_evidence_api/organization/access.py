from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from patent_evidence_api.auth.session_authority import Principal, SessionAuthority
from patent_evidence_api.core.database import (
    application_transaction,
    lock_organization_authority,
    tenant_transaction,
)
from patent_evidence_api.core.organization_lifecycle import OrganizationLifecycle
from patent_evidence_api.organization.audit import (
    AuditResult,
    OrganizationAuditEvent,
    OrganizationAuditWriter,
)


def request_correlation_id(request: Request) -> str:
    supplied = request.headers.get("X-Request-ID", "")
    if supplied and len(supplied) <= 128 and supplied.isprintable():
        return supplied
    return str(uuid4())


@dataclass
class OrganizationMutation:
    session: AsyncSession
    principal: Principal
    organization_id: UUID
    correlation_id: str
    target_type: str
    target_id: UUID | None = None
    safe_summary: str = "Organization mutation allowed"

    def describe(self, *, target_id: UUID | None, safe_summary: str) -> None:
        self.target_id = target_id
        self.safe_summary = safe_summary


class OrganizationAccess:
    """Own session, membership, tenant transaction, and mutation evidence."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        session_authority: SessionAuthority,
        audit_writer: OrganizationAuditWriter,
        clock: Callable[[], datetime],
        correlation_id: Callable[[Request], str] = request_correlation_id,
    ) -> None:
        self._session_factory = session_factory
        self._session_authority = session_authority
        self._audit_writer = audit_writer
        self._clock = clock
        self._correlation_id = correlation_id

    async def _principal(self, request: Request) -> Principal:
        async with application_transaction(self._session_factory) as session:
            return await self._session_authority.resolve(request, session)

    async def _authorize(
        self,
        session: AsyncSession,
        principal: Principal,
        organization_id: UUID,
        *,
        lock_authority: bool = False,
    ) -> None:
        organization = (
            (
                await session.execute(
                    text(
                        """SELECT organization.status AS organization_status,
                        organization.expires_at
                        FROM organizations organization
                        WHERE organization.id=:organization"""
                    ),
                    {"organization": organization_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        membership = (
            (
                await session.execute(
                    text(
                        """SELECT role,status FROM organization_memberships
                        WHERE organization_id=:organization
                          AND global_identity_id=:actor"""
                        + (" FOR SHARE" if lock_authority else "")
                    ),
                    {"organization": organization_id, "actor": principal.identity_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if organization is None or membership is None:
            raise HTTPException(status_code=404, detail="organization_not_found")
        if (
            OrganizationLifecycle.effective_status(
                organization["organization_status"],
                organization["expires_at"],
                self._clock(),
            )
            != "active"
            or membership["role"] != "organization_admin"
            or membership["status"] != "active"
        ):
            raise HTTPException(status_code=403, detail="forbidden")

    async def _record(
        self,
        *,
        organization_id: UUID,
        actor: UUID | None,
        action: str,
        target_type: str,
        result: AuditResult,
        correlation_id: str,
        target_id: UUID | None,
        safe_summary: str,
    ) -> None:
        async with tenant_transaction(
            self._session_factory,
            organization_id,
            actor_identity_id=actor,
            request_correlation_id=correlation_id,
        ) as session:
            exists = await session.scalar(
                text("SELECT EXISTS(SELECT 1 FROM organizations WHERE id=:id)"),
                {"id": organization_id},
            )
            if not exists:
                return
            await self._audit_writer.append(
                session,
                OrganizationAuditEvent(
                    organization_id=organization_id,
                    actor_identity_id=actor,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    result=result,
                    request_correlation_id=correlation_id,
                    safe_summary=safe_summary,
                ),
            )

    @asynccontextmanager
    async def authorized(
        self, request: Request, organization_id: UUID
    ) -> AsyncIterator[tuple[AsyncSession, Principal]]:
        principal = await self._principal(request)
        self._session_authority.require_recent_mfa(principal)
        async with tenant_transaction(
            self._session_factory,
            organization_id,
            actor_identity_id=principal.identity_id,
        ) as session:
            await self._authorize(session, principal, organization_id)
            yield session, principal

    @asynccontextmanager
    async def mutation(
        self,
        request: Request,
        organization_id: UUID,
        *,
        action: str,
        target_type: str,
        target_id: UUID | None = None,
    ) -> AsyncIterator[OrganizationMutation]:
        correlation = self._correlation_id(request)
        try:
            principal = await self._principal(request)
        except HTTPException:
            await self._record(
                organization_id=organization_id,
                actor=None,
                action=action,
                target_type=target_type,
                result="denied",
                correlation_id=correlation,
                target_id=target_id,
                safe_summary="Organization mutation rejected",
            )
            raise
        try:
            self._session_authority.require_recent_mfa(principal)
        except HTTPException:
            await self._record(
                organization_id=organization_id,
                actor=principal.identity_id,
                action=action,
                target_type=target_type,
                result="denied",
                correlation_id=correlation,
                target_id=target_id,
                safe_summary="Organization mutation rejected",
            )
            raise
        operation: OrganizationMutation | None = None
        try:
            async with tenant_transaction(
                self._session_factory,
                organization_id,
                actor_identity_id=principal.identity_id,
                request_correlation_id=correlation,
            ) as session:
                await lock_organization_authority(session, organization_id)
                await self._authorize(
                    session, principal, organization_id, lock_authority=True
                )
                operation = OrganizationMutation(
                    session=session,
                    principal=principal,
                    organization_id=organization_id,
                    correlation_id=correlation,
                    target_type=target_type,
                    target_id=target_id,
                )
                yield operation
                await self._audit_writer.append(
                    session,
                    OrganizationAuditEvent(
                        organization_id=organization_id,
                        actor_identity_id=principal.identity_id,
                        action=action,
                        target_type=target_type,
                        target_id=operation.target_id,
                        result="allowed",
                        request_correlation_id=correlation,
                        safe_summary=operation.safe_summary,
                    ),
                )
        except HTTPException:
            await self._record(
                organization_id=organization_id,
                actor=principal.identity_id,
                action=action,
                target_type=target_type,
                result="denied",
                correlation_id=correlation,
                target_id=operation.target_id if operation else target_id,
                safe_summary="Organization mutation rejected",
            )
            raise
        except Exception:
            await self._record(
                organization_id=organization_id,
                actor=principal.identity_id,
                action=action,
                target_type=target_type,
                result="failed",
                correlation_id=correlation,
                target_id=operation.target_id if operation else target_id,
                safe_summary="Organization mutation failed",
            )
            raise
