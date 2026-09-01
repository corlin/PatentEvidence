from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from patent_evidence_api.auth.guards import PlatformPrincipalGuard
from patent_evidence_api.auth.session_authority import Principal, SessionAuthority
from patent_evidence_api.core.database import (
    application_transaction,
    platform_transaction,
)
from patent_evidence_api.platform.audit import (
    AuditResult,
    PlatformAuditEvent,
    PlatformAuditWriter,
)


def request_correlation_id(request: Request) -> str:
    supplied = request.headers.get("X-Request-ID", "")
    if supplied and len(supplied) <= 128 and supplied.isprintable():
        return supplied
    return str(uuid4())


@dataclass
class PlatformMutation:
    session: AsyncSession
    principal: Principal
    correlation_id: str
    target_type: str
    target_id: UUID | None = None
    safe_summary: str = "privileged platform mutation allowed"

    def describe(self, *, target_id: UUID | None, safe_summary: str) -> None:
        self.target_id = target_id
        self.safe_summary = safe_summary


class PlatformAccess:
    """Own the application-to-platform authority handoff and mutation evidence."""

    def __init__(
        self,
        application_session_factory: async_sessionmaker[AsyncSession],
        platform_session_factory: async_sessionmaker[AsyncSession],
        *,
        session_authority: SessionAuthority,
        platform_guard: PlatformPrincipalGuard,
        audit_writer: PlatformAuditWriter,
        correlation_id: Callable[[Request], str] = request_correlation_id,
    ) -> None:
        self._application_session_factory = application_session_factory
        self._platform_session_factory = platform_session_factory
        self._session_authority = session_authority
        self._platform_guard = platform_guard
        self._audit_writer = audit_writer
        self._correlation_id = correlation_id

    async def _principal(self, request: Request) -> Principal:
        async with application_transaction(
            self._application_session_factory
        ) as session:
            return await self._session_authority.require_recent_mfa(request, session)

    async def _record(
        self,
        *,
        actor: UUID | None,
        action: str,
        target_type: str,
        result: AuditResult,
        correlation_id: str,
        target_id: UUID | None = None,
        safe_summary: str,
    ) -> None:
        async with platform_transaction(
            self._platform_session_factory,
            actor_identity_id=actor,
            request_correlation_id=correlation_id,
        ) as session:
            await self._audit_writer.append(
                session,
                PlatformAuditEvent(
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
        self, request: Request
    ) -> AsyncIterator[tuple[AsyncSession, Principal]]:
        principal = await self._principal(request)
        async with platform_transaction(
            self._platform_session_factory, actor_identity_id=principal.identity_id
        ) as session:
            await self._platform_guard.platform_administrator(principal, session)
            yield session, principal

    @asynccontextmanager
    async def mutation(
        self, request: Request, *, action: str, target_type: str
    ) -> AsyncIterator[PlatformMutation]:
        correlation = self._correlation_id(request)
        try:
            principal = await self._principal(request)
        except HTTPException:
            await self._record(
                actor=None,
                action=action,
                target_type=target_type,
                result="denied",
                correlation_id=correlation,
                safe_summary="privileged platform mutation rejected",
            )
            raise
        operation: PlatformMutation | None = None
        try:
            async with platform_transaction(
                self._platform_session_factory,
                actor_identity_id=principal.identity_id,
                request_correlation_id=correlation,
            ) as session:
                await self._platform_guard.platform_administrator(principal, session)
                operation = PlatformMutation(
                    session=session,
                    principal=principal,
                    correlation_id=correlation,
                    target_type=target_type,
                )
                yield operation
                await self._audit_writer.append(
                    session,
                    PlatformAuditEvent(
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
                actor=principal.identity_id,
                action=action,
                target_type=target_type,
                result="denied",
                correlation_id=correlation,
                target_id=operation.target_id if operation else None,
                safe_summary="privileged platform mutation rejected",
            )
            raise
        except Exception:
            await self._record(
                actor=principal.identity_id,
                action=action,
                target_type=target_type,
                result="failed",
                correlation_id=correlation,
                target_id=operation.target_id if operation else None,
                safe_summary="privileged platform mutation failed",
            )
            raise
