from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from patent_evidence_api.organization.invitations import OrganizationRole


class MemberService:
    """Read and mutate fixed-role memberships under one administrator invariant."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    @staticmethod
    def _view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "organization_id": str(row["organization_id"]),
            "identity_id": str(row["global_identity_id"]),
            "email": row["email_normalized"],
            "display_name": row["display_name"],
            "role": row["role"],
            "status": row["status"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }

    async def list(
        self, session: AsyncSession, organization_id: UUID
    ) -> list[dict[str, Any]]:
        rows = (
            (
                await session.execute(
                    text(
                        """SELECT membership.id,membership.organization_id,
                        membership.global_identity_id,membership.role,membership.status,
                        membership.created_at,membership.updated_at,
                        identity.email_normalized,identity.display_name
                        FROM organization_memberships membership
                        JOIN global_identities identity
                          ON identity.id=membership.global_identity_id
                        WHERE membership.organization_id=:organization
                          AND membership.status <> 'removed'
                        ORDER BY identity.email_normalized,membership.id"""
                    ),
                    {"organization": organization_id},
                )
            )
            .mappings()
            .all()
        )
        return [self._view(dict(row)) for row in rows]

    async def _locked_target(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        actor_identity_id: UUID,
        membership_id: UUID,
    ) -> dict[str, Any]:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"organization-admin-invariant:{organization_id}"},
        )
        actor_authorized = await session.scalar(
            text(
                """SELECT EXISTS(SELECT 1 FROM organization_memberships
                WHERE organization_id=:organization AND global_identity_id=:actor
                  AND role='organization_admin' AND status='active')"""
            ),
            {"organization": organization_id, "actor": actor_identity_id},
        )
        if not actor_authorized:
            raise HTTPException(status_code=403, detail="forbidden")
        row = (
            (
                await session.execute(
                    text(
                        """SELECT membership.id,membership.organization_id,
                        membership.global_identity_id,membership.role,membership.status,
                        membership.created_at,membership.updated_at,
                        identity.email_normalized,identity.display_name
                        FROM organization_memberships membership
                        JOIN global_identities identity
                          ON identity.id=membership.global_identity_id
                        WHERE membership.organization_id=:organization
                          AND membership.id=:membership FOR UPDATE OF membership"""
                    ),
                    {
                        "organization": organization_id,
                        "membership": membership_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="membership_not_found")
        return dict(row)

    async def _protect_last_admin(
        self, session: AsyncSession, organization_id: UUID, target: dict[str, Any]
    ) -> None:
        if target["role"] != "organization_admin" or target["status"] != "active":
            return
        active_admins = await session.scalar(
            text(
                """SELECT count(*) FROM organization_memberships
                WHERE organization_id=:organization
                  AND role='organization_admin' AND status='active'"""
            ),
            {"organization": organization_id},
        )
        if active_admins <= 1:
            raise HTTPException(
                status_code=409, detail="last_active_organization_admin"
            )

    async def set_role(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        actor_identity_id: UUID,
        membership_id: UUID,
        role: OrganizationRole,
    ) -> dict[str, Any]:
        target = await self._locked_target(
            session,
            organization_id=organization_id,
            actor_identity_id=actor_identity_id,
            membership_id=membership_id,
        )
        if target["status"] == "removed":
            raise HTTPException(status_code=409, detail="membership_removed")
        if role != "organization_admin":
            await self._protect_last_admin(session, organization_id, target)
        await session.execute(
            text(
                """UPDATE organization_memberships SET role=:role,updated_at=:now
                WHERE organization_id=:organization AND id=:membership"""
            ),
            {
                "role": role,
                "now": self._clock(),
                "organization": organization_id,
                "membership": membership_id,
            },
        )
        target["role"] = role
        target["updated_at"] = self._clock()
        return self._view(target)

    async def set_status(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        actor_identity_id: UUID,
        membership_id: UUID,
        transition: str,
    ) -> dict[str, Any]:
        target = await self._locked_target(
            session,
            organization_id=organization_id,
            actor_identity_id=actor_identity_id,
            membership_id=membership_id,
        )
        transitions = {
            "suspend": ("active", "suspended"),
            "reactivate": ("suspended", "active"),
            "remove": ("active", "removed"),
        }
        expected, status = transitions[transition]
        if transition == "remove" and target["status"] == "suspended":
            expected = "suspended"
        if target["status"] != expected:
            raise HTTPException(status_code=409, detail="invalid_membership_transition")
        if status != "active":
            await self._protect_last_admin(session, organization_id, target)
        await session.execute(
            text(
                """UPDATE organization_memberships SET status=:status,updated_at=:now
                WHERE organization_id=:organization AND id=:membership"""
            ),
            {
                "status": status,
                "now": self._clock(),
                "organization": organization_id,
                "membership": membership_id,
            },
        )
        target["status"] = status
        target["updated_at"] = self._clock()
        return self._view(target)
