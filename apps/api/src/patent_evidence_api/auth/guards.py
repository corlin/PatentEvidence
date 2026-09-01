from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from patent_evidence_api.auth.session_authority import Principal, SessionAuthority
from patent_evidence_api.core.database import bind_transaction_context


class PrivilegedPrincipalGuard:
    """Re-derive privileged authority from the URL scope and current database facts."""

    def __init__(
        self, session_authority: SessionAuthority, clock: Callable[[], datetime]
    ) -> None:
        self._session_authority = session_authority
        self._clock = clock

    async def organization_administrator(
        self,
        request: Request,
        session: AsyncSession,
        organization_id: UUID,
        *,
        lower_level_target: UUID,
    ) -> Principal:
        principal = await self._session_authority.require_recent_mfa(request, session)
        await bind_transaction_context(
            session,
            organization_id=organization_id,
            actor_identity_id=principal.identity_id,
        )
        authorized = await session.scalar(
            text(
                """SELECT EXISTS(
                SELECT 1 FROM organizations organization
                JOIN organization_memberships actor
                  ON actor.organization_id=organization.id
                JOIN organization_memberships target
                  ON target.organization_id=organization.id
                WHERE organization.id=:organization AND organization.status='active'
                  AND (organization.expires_at IS NULL OR organization.expires_at > :now)
                  AND actor.global_identity_id=:actor AND actor.role='organization_admin'
                  AND actor.status='active' AND target.global_identity_id=:target
                  AND target.role <> 'organization_admin' AND target.status='active')"""
            ),
            {
                "organization": organization_id,
                "actor": principal.identity_id,
                "target": lower_level_target,
                "now": self._clock(),
            },
        )
        if not authorized:
            raise HTTPException(status_code=403, detail="forbidden")
        return principal


class PlatformPrincipalGuard:
    """Authorize an application-authenticated principal through the platform role."""

    async def platform_administrator(
        self, principal: Principal, session: AsyncSession
    ) -> Principal:
        authorized = await session.scalar(
            text(
                """SELECT EXISTS(
                SELECT 1 FROM global_identities identity
                JOIN platform_operator_grants grant_record
                  ON grant_record.global_identity_id=identity.id
                WHERE identity.id=:actor AND identity.status='active'
                  AND identity.security_version=:security_version
                  AND grant_record.role='platform_admin'
                  AND grant_record.status='active'
                  AND (
                    grant_record.bootstrap_mfa_enrollment_expires_at IS NULL
                    OR EXISTS(
                      SELECT 1 FROM mfa_credentials factor
                      WHERE factor.global_identity_id=identity.id
                        AND factor.status='active'
                        AND factor.confirmed_at IS NOT NULL
                        AND factor.confirmed_at <= grant_record.bootstrap_mfa_enrollment_expires_at
                    )
                  ))"""
            ),
            {
                "actor": principal.identity_id,
                "security_version": principal.security_version,
            },
        )
        if not authorized:
            raise HTTPException(status_code=403, detail="forbidden")
        return principal
