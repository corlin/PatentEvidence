from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from patent_evidence_api.auth.security import MFA_RECENCY, digest_secret
from patent_evidence_api.core.database import (
    bind_session_token_hash,
    bind_transaction_context,
)


@dataclass(frozen=True)
class Principal:
    session_id: UUID
    identity_id: UUID
    email: str
    token_hash: str
    security_version: int
    expires_at: datetime
    mfa_verified_at: datetime | None

    def has_recent_mfa(self, now: datetime) -> bool:
        return (
            self.mfa_verified_at is not None
            and self.mfa_verified_at >= now - MFA_RECENCY
        )


class PrivilegedPrincipalGuard:
    """Re-derive privileged authority from the URL scope and current database facts."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    async def valid_session(self, request: Request, session: AsyncSession) -> Principal:
        token = request.cookies.get("pe_session")
        if not token:
            raise HTTPException(status_code=401, detail="session_required")
        token_hash = digest_secret(token)
        await bind_session_token_hash(session, token_hash)
        row = (
            (
                await session.execute(
                    text(
                        """SELECT s.id AS session_id,s.global_identity_id AS identity_id,
                    i.email_normalized AS email,i.status AS identity_status,
                    i.security_version AS identity_security_version,
                    s.security_version AS session_security_version,
                    s.expires_at,s.mfa_verified_at
                    FROM user_sessions s JOIN global_identities i ON i.id=s.global_identity_id
                    WHERE s.token_hash=:token_hash AND s.revoked_at IS NULL"""
                    ),
                    {"token_hash": token_hash},
                )
            )
            .mappings()
            .one_or_none()
        )
        now = self._clock()
        if (
            row is None
            or row["expires_at"] <= now
            or row["identity_status"] != "active"
            or row["session_security_version"] != row["identity_security_version"]
        ):
            raise HTTPException(status_code=401, detail="session_required")
        return Principal(
            session_id=row["session_id"],
            identity_id=row["identity_id"],
            email=row["email"],
            token_hash=token_hash,
            security_version=row["session_security_version"],
            expires_at=row["expires_at"],
            mfa_verified_at=row["mfa_verified_at"],
        )

    async def recent_mfa(self, request: Request, session: AsyncSession) -> Principal:
        principal = await self.valid_session(request, session)
        if not principal.has_recent_mfa(self._clock()):
            raise HTTPException(status_code=403, detail="mfa_required")
        return principal

    async def organization_administrator(
        self,
        request: Request,
        session: AsyncSession,
        organization_id: UUID,
        *,
        lower_level_target: UUID,
    ) -> Principal:
        principal = await self.recent_mfa(request, session)
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
                  AND actor.global_identity_id=:actor AND actor.role='organization_admin'
                  AND actor.status='active' AND target.global_identity_id=:target
                  AND target.role <> 'organization_admin' AND target.status='active')"""
            ),
            {
                "organization": organization_id,
                "actor": principal.identity_id,
                "target": lower_level_target,
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
                  AND grant_record.status='active')"""
            ),
            {
                "actor": principal.identity_id,
                "security_version": principal.security_version,
            },
        )
        if not authorized:
            raise HTTPException(status_code=403, detail="forbidden")
        return principal
