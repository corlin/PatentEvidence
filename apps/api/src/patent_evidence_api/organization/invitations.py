from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from patent_evidence_api.auth.security import digest_secret, issue_opaque_token
from patent_evidence_api.core.database import (
    invitation_token_transaction,
    lock_organization_authority,
    tenant_transaction,
)
from patent_evidence_api.core.organization_lifecycle import OrganizationLifecycle
from patent_evidence_api.organization.audit import (
    AuditResult,
    OrganizationAuditEvent,
    OrganizationAuditWriter,
)

OrganizationRole = Literal["organization_admin", "patent_agent", "reviewer"]
INVITATION_LIFETIME = timedelta(hours=72)


class InvitationAcceptance:
    """Inspect and atomically consume one invitation-token capability."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime],
        audit_writer: OrganizationAuditWriter,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._audit_writer = audit_writer

    async def inspect(self, token: str) -> dict[str, Any] | None:
        token_hash = digest_secret(token)
        async with invitation_token_transaction(
            self._session_factory, token_hash
        ) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """SELECT invitation.id,invitation.organization_id,
                            invitation.email_normalized,invitation.role,invitation.status,
                            invitation.expires_at,identity.id AS identity_id
                            FROM organization_invitations invitation
                            LEFT JOIN global_identities identity
                              ON identity.email_normalized=invitation.email_normalized
                            WHERE invitation.token_hash=:token_hash"""
                        ),
                        {"token_hash": token_hash},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        async with tenant_transaction(
            self._session_factory, row["organization_id"]
        ) as session:
            organization = (
                (
                    await session.execute(
                        text(
                            """SELECT id,display_name,status,expires_at
                            FROM organizations WHERE id=:organization"""
                        ),
                        {"organization": row["organization_id"]},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if organization is None:
            return None
        now = self._clock()
        status = (
            "expired"
            if row["status"] == "pending" and row["expires_at"] <= now
            else row["status"]
        )
        return {
            "id": row["id"],
            "organization_id": row["organization_id"],
            "organization_display_name": organization["display_name"],
            "organization_status": organization["status"],
            "organization_expires_at": organization["expires_at"],
            "email": row["email_normalized"],
            "role": row["role"],
            "status": status,
            "expires_at": row["expires_at"],
            "identity_id": row["identity_id"],
            "token_hash": token_hash,
        }

    async def record(
        self,
        preview: dict[str, Any],
        *,
        result: AuditResult,
        correlation_id: str,
    ) -> None:
        async with tenant_transaction(
            self._session_factory,
            preview["organization_id"],
            actor_identity_id=preview["identity_id"],
            request_correlation_id=correlation_id,
        ) as session:
            await self._audit_writer.append(
                session,
                OrganizationAuditEvent(
                    organization_id=preview["organization_id"],
                    actor_identity_id=preview["identity_id"],
                    action="organization.invitation.accept",
                    target_type="organization_invitation",
                    target_id=preview["id"],
                    result=result,
                    request_correlation_id=correlation_id,
                    safe_summary={
                        "allowed": "Accepted organization invitation",
                        "denied": "Organization invitation acceptance rejected",
                        "failed": "Organization invitation acceptance failed",
                    }[result],
                ),
            )

    async def accept(
        self,
        preview: dict[str, Any],
        *,
        display_name: str | None,
        new_password_hash: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        try:
            return await self._accept(
                preview,
                display_name=display_name,
                new_password_hash=new_password_hash,
                correlation_id=correlation_id,
            )
        except HTTPException:
            await self.record(preview, result="denied", correlation_id=correlation_id)
            raise
        except Exception:
            await self.record(preview, result="failed", correlation_id=correlation_id)
            raise

    async def _accept(
        self,
        preview: dict[str, Any],
        *,
        display_name: str | None,
        new_password_hash: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        now = self._clock()
        async with tenant_transaction(
            self._session_factory,
            preview["organization_id"],
            actor_identity_id=preview["identity_id"],
            request_correlation_id=correlation_id,
        ) as session:
            await lock_organization_authority(session, preview["organization_id"])
            invitation = (
                (
                    await session.execute(
                        text(
                            """SELECT id,email_normalized,role,status,expires_at
                            FROM organization_invitations
                            WHERE id=:invitation AND organization_id=:organization
                              AND token_hash=:token_hash FOR UPDATE"""
                        ),
                        {
                            "invitation": preview["id"],
                            "organization": preview["organization_id"],
                            "token_hash": preview["token_hash"],
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if invitation is None:
                raise HTTPException(status_code=404, detail="invitation_not_found")
            if invitation["status"] != "pending":
                raise HTTPException(status_code=409, detail="invitation_not_pending")
            if invitation["expires_at"] <= now:
                raise HTTPException(status_code=410, detail="invitation_expired")
            organization = (
                (
                    await session.execute(
                        text(
                            """SELECT status,expires_at FROM organizations
                            WHERE id=:organization"""
                        ),
                        {"organization": preview["organization_id"]},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                organization is None
                or OrganizationLifecycle.effective_status(
                    organization["status"], organization["expires_at"], now
                )
                != "active"
            ):
                raise HTTPException(status_code=409, detail="organization_unavailable")
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"global-identity-email:{invitation['email_normalized']}"},
            )
            identity = (
                (
                    await session.execute(
                        text(
                            """SELECT id,status FROM global_identities
                            WHERE email_normalized=:email FOR UPDATE"""
                        ),
                        {"email": invitation["email_normalized"]},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if identity is None:
                normalized_display_name = (display_name or "").strip()
                if not normalized_display_name or new_password_hash is None:
                    raise HTTPException(
                        status_code=422, detail="new_identity_credentials_required"
                    )
                identity_id = uuid4()
                await session.execute(
                    text(
                        """INSERT INTO global_identities
                        (id,email_normalized,display_name,status,password_hash,
                         security_version,created_at,updated_at)
                        VALUES (:id,:email,:name,'active',:password_hash,1,:now,:now)"""
                    ),
                    {
                        "id": identity_id,
                        "email": invitation["email_normalized"],
                        "name": normalized_display_name,
                        "password_hash": new_password_hash,
                        "now": now,
                    },
                )
            else:
                if identity["status"] != "active":
                    raise HTTPException(status_code=409, detail="identity_unavailable")
                identity_id = identity["id"]
            membership = (
                (
                    await session.execute(
                        text(
                            """SELECT id,status FROM organization_memberships
                            WHERE organization_id=:organization
                              AND global_identity_id=:identity FOR UPDATE"""
                        ),
                        {
                            "organization": preview["organization_id"],
                            "identity": identity_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if membership is not None and membership["status"] != "removed":
                raise HTTPException(status_code=409, detail="membership_already_exists")
            membership_id = membership["id"] if membership else uuid4()
            if membership is None:
                await session.execute(
                    text(
                        """INSERT INTO organization_memberships
                        (id,organization_id,global_identity_id,role,status,created_at,updated_at)
                        VALUES (:id,:organization,:identity,:role,'active',:now,:now)"""
                    ),
                    {
                        "id": membership_id,
                        "organization": preview["organization_id"],
                        "identity": identity_id,
                        "role": invitation["role"],
                        "now": now,
                    },
                )
            else:
                await session.execute(
                    text(
                        """UPDATE organization_memberships
                        SET role=:role,status='active',updated_at=:now
                        WHERE id=:id AND organization_id=:organization"""
                    ),
                    {
                        "role": invitation["role"],
                        "now": now,
                        "id": membership_id,
                        "organization": preview["organization_id"],
                    },
                )
            await session.execute(
                text(
                    """UPDATE organization_invitations
                    SET status='accepted',accepted_at=:now,updated_at=:now
                    WHERE id=:invitation AND organization_id=:organization"""
                ),
                {
                    "now": now,
                    "invitation": preview["id"],
                    "organization": preview["organization_id"],
                },
            )
            await self._audit_writer.append(
                session,
                OrganizationAuditEvent(
                    organization_id=preview["organization_id"],
                    actor_identity_id=identity_id,
                    action="organization.invitation.accept",
                    target_type="organization_invitation",
                    target_id=preview["id"],
                    result="allowed",
                    request_correlation_id=correlation_id,
                    safe_summary="Accepted organization invitation",
                ),
            )
            return {
                "id": str(membership_id),
                "organization_id": str(preview["organization_id"]),
                "identity_id": str(identity_id),
                "role": invitation["role"],
                "status": "active",
            }


class InvitationService:
    """Create organization invitations and expose each raw token once."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    async def create(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        actor_identity_id: UUID,
        email: str,
        role: OrganizationRole,
    ) -> tuple[dict[str, Any], str]:
        normalized_email = email.strip().lower()
        if "@" not in normalized_email:
            raise HTTPException(status_code=422, detail="invalid_invitation_email")
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"organization-invitation:{organization_id}:{normalized_email}"},
        )
        return await self._create_locked(
            session,
            organization_id=organization_id,
            actor_identity_id=actor_identity_id,
            normalized_email=normalized_email,
            role=role,
        )

    async def _create_locked(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        actor_identity_id: UUID,
        normalized_email: str,
        role: OrganizationRole,
    ) -> tuple[dict[str, Any], str]:
        await session.execute(
            text(
                """UPDATE organization_invitations
                SET status='expired',updated_at=:now
                WHERE organization_id=:organization AND email_normalized=:email
                  AND status='pending' AND expires_at <= :now"""
            ),
            {
                "organization": organization_id,
                "email": normalized_email,
                "now": self._clock(),
            },
        )
        membership_exists = await session.scalar(
            text(
                """SELECT EXISTS(
                SELECT 1 FROM organization_memberships membership
                JOIN global_identities identity
                  ON identity.id=membership.global_identity_id
                WHERE membership.organization_id=:organization
                  AND identity.email_normalized=:email
                  AND membership.status <> 'removed')"""
            ),
            {"organization": organization_id, "email": normalized_email},
        )
        if membership_exists:
            raise HTTPException(status_code=409, detail="membership_already_exists")
        pending_exists = await session.scalar(
            text(
                """SELECT EXISTS(SELECT 1 FROM organization_invitations
                WHERE organization_id=:organization AND email_normalized=:email
                  AND status='pending' AND expires_at > :now)"""
            ),
            {
                "organization": organization_id,
                "email": normalized_email,
                "now": self._clock(),
            },
        )
        if pending_exists:
            raise HTTPException(status_code=409, detail="invitation_already_pending")
        now = self._clock()
        invitation_id = uuid4()
        token = issue_opaque_token()
        expires_at = now + INVITATION_LIFETIME
        await session.execute(
            text(
                """INSERT INTO organization_invitations
                (id,organization_id,email_normalized,role,token_hash,status,invited_by,
                 expires_at,created_at,updated_at)
                VALUES (:id,:organization,:email,:role,:token_hash,'pending',:actor,
                        :expires,:now,:now)"""
            ),
            {
                "id": invitation_id,
                "organization": organization_id,
                "email": normalized_email,
                "role": role,
                "token_hash": digest_secret(token),
                "actor": actor_identity_id,
                "expires": expires_at,
                "now": now,
            },
        )
        return (
            {
                "id": str(invitation_id),
                "organization_id": str(organization_id),
                "email": normalized_email,
                "role": role,
                "status": "pending",
                "expires_at": expires_at.isoformat(),
            },
            token,
        )

    async def detail(
        self, session: AsyncSession, organization_id: UUID, invitation_id: UUID
    ) -> dict[str, Any] | None:
        row = (
            (
                await session.execute(
                    text(
                        """SELECT id,organization_id,email_normalized,role,status,
                        expires_at,accepted_at,revoked_at,created_at
                        FROM organization_invitations
                        WHERE organization_id=:organization AND id=:invitation"""
                    ),
                    {"organization": organization_id, "invitation": invitation_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        status = (
            "expired"
            if row["status"] == "pending" and row["expires_at"] <= self._clock()
            else row["status"]
        )
        return {
            "id": str(row["id"]),
            "organization_id": str(row["organization_id"]),
            "email": row["email_normalized"],
            "role": row["role"],
            "status": status,
            "expires_at": row["expires_at"].isoformat(),
            "accepted_at": row["accepted_at"].isoformat()
            if row["accepted_at"]
            else None,
            "revoked_at": row["revoked_at"].isoformat() if row["revoked_at"] else None,
            "created_at": row["created_at"].isoformat(),
        }

    async def revoke(
        self, session: AsyncSession, organization_id: UUID, invitation_id: UUID
    ) -> dict[str, Any]:
        now = self._clock()
        row = (
            (
                await session.execute(
                    text(
                        """SELECT id,status,expires_at FROM organization_invitations
                        WHERE organization_id=:organization AND id=:invitation
                        FOR UPDATE"""
                    ),
                    {"organization": organization_id, "invitation": invitation_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="invitation_not_found")
        if row["status"] != "pending" or row["expires_at"] <= now:
            raise HTTPException(status_code=409, detail="invitation_not_pending")
        await session.execute(
            text(
                """UPDATE organization_invitations
                SET status='revoked',revoked_at=:now,updated_at=:now
                WHERE organization_id=:organization AND id=:invitation"""
            ),
            {
                "organization": organization_id,
                "invitation": invitation_id,
                "now": now,
            },
        )
        detail = await self.detail(session, organization_id, invitation_id)
        if detail is None:
            raise RuntimeError("revoked invitation could not be read")
        return detail

    async def resend(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        invitation_id: UUID,
        actor_identity_id: UUID,
    ) -> tuple[dict[str, Any], str]:
        snapshot = (
            (
                await session.execute(
                    text(
                        """SELECT email_normalized
                        FROM organization_invitations
                        WHERE organization_id=:organization AND id=:invitation"""
                    ),
                    {"organization": organization_id, "invitation": invitation_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if snapshot is None:
            raise HTTPException(status_code=404, detail="invitation_not_found")
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {
                "key": (
                    f"organization-invitation:{organization_id}:"
                    f"{snapshot['email_normalized']}"
                )
            },
        )
        row = (
            (
                await session.execute(
                    text(
                        """SELECT email_normalized,role,status,expires_at
                        FROM organization_invitations
                        WHERE organization_id=:organization AND id=:invitation
                        FOR UPDATE"""
                    ),
                    {"organization": organization_id, "invitation": invitation_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="invitation_not_found")
        now = self._clock()
        effective_status = (
            "expired"
            if row["status"] == "pending" and row["expires_at"] <= now
            else row["status"]
        )
        if effective_status not in {"pending", "expired"}:
            raise HTTPException(status_code=409, detail="invitation_not_resendable")
        await session.execute(
            text(
                """UPDATE organization_invitations
                SET status=:status,revoked_at=:revoked,updated_at=:now
                WHERE organization_id=:organization AND id=:invitation"""
            ),
            {
                "status": "expired" if effective_status == "expired" else "revoked",
                "revoked": now if effective_status == "pending" else None,
                "now": now,
                "organization": organization_id,
                "invitation": invitation_id,
            },
        )
        return await self._create_locked(
            session,
            organization_id=organization_id,
            actor_identity_id=actor_identity_id,
            normalized_email=row["email_normalized"],
            role=row["role"],
        )
