import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from patent_evidence_api.auth.security import digest_secret, issue_opaque_token

INVITATION_LIFETIME = timedelta(hours=72)


@dataclass(frozen=True)
class OrganizationOpening:
    slug: str
    display_name: str
    admin_email: str
    plan_key: str
    monthly_case_allowance: int
    current_period_start: datetime
    current_period_end: datetime
    expires_at: datetime | None

    def fingerprint(self) -> str:
        payload = {
            "slug": self.slug,
            "display_name": self.display_name,
            "admin_email": self.admin_email,
            "plan_key": self.plan_key,
            "monthly_case_allowance": self.monthly_case_allowance,
            "current_period_start": self.current_period_start.isoformat(),
            "current_period_end": self.current_period_end.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class OrganizationLifecycle:
    """Apply one lifecycle rule to reads, authorization, and mutations."""

    @staticmethod
    def effective_status(
        persisted_status: str, expires_at: datetime | None, now: datetime
    ) -> str:
        if expires_at is not None and expires_at <= now:
            return "expired"
        return persisted_status

    def organization_view(self, row: dict[str, Any], now: datetime) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "slug": row["slug"],
            "display_name": row["display_name"],
            "status": self.effective_status(row["status"], row["expires_at"], now),
            "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
            "created_at": row["created_at"].isoformat(),
        }

    def quota_view(self, row: dict[str, Any], now: datetime) -> dict[str, Any]:
        organization_status = self.effective_status(
            row["status"], row["expires_at"], now
        )
        effective_status = (
            organization_status
            if organization_status in {"suspended", "expired"}
            else row["quota_status"]
        )
        return {
            "plan_key": row["plan_key"],
            "monthly_case_allowance": row["monthly_case_allowance"],
            "current_period_start": row["current_period_start"].isoformat(),
            "current_period_end": row["current_period_end"].isoformat(),
            "status": effective_status,
        }


class OrganizationProvisioning:
    """Open and operate organizations behind one platform transaction seam."""

    def __init__(
        self, clock: Callable[[], datetime], lifecycle: OrganizationLifecycle
    ) -> None:
        self._clock = clock
        self._lifecycle = lifecycle

    def validate_opening(self, opening: OrganizationOpening) -> None:
        if opening.current_period_end <= opening.current_period_start:
            raise HTTPException(status_code=422, detail="invalid_quota_period")
        if opening.expires_at is not None and opening.expires_at <= self._clock():
            raise HTTPException(status_code=422, detail="invalid_organization_expiry")

    async def open(
        self,
        session: AsyncSession,
        *,
        actor_identity_id: UUID,
        idempotency_key: str,
        opening: OrganizationOpening,
    ) -> tuple[int, dict[str, Any], UUID]:
        self.validate_opening(opening)
        fingerprint = opening.fingerprint()
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"{actor_identity_id}:{idempotency_key}"},
        )
        prior = (
            (
                await session.execute(
                    text(
                        """SELECT request_fingerprint,response_snapshot,organization_id
                        FROM organization_provisioning_requests
                        WHERE actor_identity_id=:actor AND idempotency_key=:key"""
                    ),
                    {"actor": actor_identity_id, "key": idempotency_key},
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior is not None:
            if prior["request_fingerprint"] != fingerprint:
                raise HTTPException(status_code=409, detail="idempotency_conflict")
            response = dict(prior["response_snapshot"])
            response["invitation_token"] = None
            return 200, response, prior["organization_id"]

        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"organization-slug:{opening.slug}"},
        )
        if await session.scalar(
            text("SELECT EXISTS(SELECT 1 FROM organizations WHERE slug=:slug)"),
            {"slug": opening.slug},
        ):
            raise HTTPException(status_code=409, detail="organization_slug_conflict")

        now = self._clock()
        organization_id = uuid4()
        invitation_id = uuid4()
        invitation_token = issue_opaque_token()
        invitation_expires_at = now + INVITATION_LIFETIME
        await session.execute(
            text(
                """INSERT INTO organizations
                (id,slug,display_name,status,expires_at,created_by,created_at,updated_at)
                VALUES (:id,:slug,:name,'active',:expires,:actor,:now,:now)"""
            ),
            {
                "id": organization_id,
                "slug": opening.slug,
                "name": opening.display_name,
                "expires": opening.expires_at,
                "actor": actor_identity_id,
                "now": now,
            },
        )
        await session.execute(
            text(
                """INSERT INTO organization_plan_quotas
                (organization_id,plan_key,monthly_case_allowance,current_period_start,
                 current_period_end,status,created_at,updated_at)
                VALUES (:organization,:plan,:allowance,:period_start,:period_end,
                        'active',:now,:now)"""
            ),
            {
                "organization": organization_id,
                "plan": opening.plan_key,
                "allowance": opening.monthly_case_allowance,
                "period_start": opening.current_period_start,
                "period_end": opening.current_period_end,
                "now": now,
            },
        )
        await session.execute(
            text(
                """INSERT INTO organization_invitations
                (id,organization_id,email_normalized,role,token_hash,status,invited_by,
                 expires_at,created_at,updated_at)
                VALUES (:id,:organization,:email,'organization_admin',:token_hash,
                        'pending',:actor,:expires,:now,:now)"""
            ),
            {
                "id": invitation_id,
                "organization": organization_id,
                "email": opening.admin_email,
                "token_hash": digest_secret(invitation_token),
                "actor": actor_identity_id,
                "expires": invitation_expires_at,
                "now": now,
            },
        )
        await session.execute(
            text(
                """INSERT INTO organization_provisioning_records
                (id,organization_id,initial_invitation_id,created_by,status,created_at)
                VALUES (:id,:organization,:invitation,:actor,'ready',:now)"""
            ),
            {
                "id": uuid4(),
                "organization": organization_id,
                "invitation": invitation_id,
                "actor": actor_identity_id,
                "now": now,
            },
        )
        response = {
            "organization": {
                "id": str(organization_id),
                "slug": opening.slug,
                "display_name": opening.display_name,
                "status": "active",
                "expires_at": opening.expires_at.isoformat()
                if opening.expires_at
                else None,
                "created_at": now.isoformat(),
            },
            "quota": {
                "plan_key": opening.plan_key,
                "monthly_case_allowance": opening.monthly_case_allowance,
                "current_period_start": opening.current_period_start.isoformat(),
                "current_period_end": opening.current_period_end.isoformat(),
                "status": "active",
            },
            "invitation": {
                "id": str(invitation_id),
                "email": opening.admin_email,
                "role": "organization_admin",
                "expires_at": invitation_expires_at.isoformat(),
            },
            "invitation_token": invitation_token,
        }
        snapshot = {**response, "invitation_token": None}
        await session.execute(
            text(
                """INSERT INTO organization_provisioning_requests
                (id,actor_identity_id,idempotency_key,request_fingerprint,
                 organization_id,response_snapshot,created_at)
                VALUES (:id,:actor,:key,:fingerprint,:organization,
                        CAST(:snapshot AS jsonb),:now)"""
            ),
            {
                "id": uuid4(),
                "actor": actor_identity_id,
                "key": idempotency_key,
                "fingerprint": fingerprint,
                "organization": organization_id,
                "snapshot": json.dumps(snapshot),
                "now": now,
            },
        )
        return 201, response, organization_id

    async def detail(
        self, session: AsyncSession, organization_id: UUID
    ) -> dict[str, Any] | None:
        row = (
            (
                await session.execute(
                    text(
                        """SELECT o.id,o.slug,o.display_name,o.status,o.expires_at,o.created_at,
                        q.plan_key,q.monthly_case_allowance,q.current_period_start,
                        q.current_period_end,q.status AS quota_status
                        FROM organizations o JOIN organization_plan_quotas q
                          ON q.organization_id=o.id WHERE o.id=:organization"""
                    ),
                    {"organization": organization_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        mapped = dict(row)
        now = self._clock()
        return {
            "organization": self._lifecycle.organization_view(mapped, now),
            "quota": self._lifecycle.quota_view(mapped, now),
        }

    async def list(self, session: AsyncSession) -> list[dict[str, Any]]:
        rows = (
            (
                await session.execute(
                    text(
                        """SELECT o.id,o.slug,o.display_name,o.status,o.expires_at,o.created_at,
                        q.plan_key,q.monthly_case_allowance,q.current_period_start,
                        q.current_period_end,q.status AS quota_status
                        FROM organizations o JOIN organization_plan_quotas q
                          ON q.organization_id=o.id ORDER BY o.created_at,o.id"""
                    )
                )
            )
            .mappings()
            .all()
        )
        now = self._clock()
        return [
            {
                "organization": self._lifecycle.organization_view(dict(row), now),
                "quota": self._lifecycle.quota_view(dict(row), now),
            }
            for row in rows
        ]

    async def set_status(
        self, session: AsyncSession, organization_id: UUID, status: str
    ) -> dict[str, Any]:
        now = self._clock()
        if status == "active" and await session.scalar(
            text(
                """SELECT EXISTS(SELECT 1 FROM organizations
                WHERE id=:organization AND expires_at IS NOT NULL AND expires_at <= :now)"""
            ),
            {"organization": organization_id, "now": now},
        ):
            raise HTTPException(status_code=409, detail="organization_expired")
        changed = await session.scalar(
            text(
                """UPDATE organizations SET status=:status,updated_at=:now
                WHERE id=:organization RETURNING id"""
            ),
            {"organization": organization_id, "status": status, "now": now},
        )
        if changed is None:
            raise HTTPException(status_code=404, detail="organization_not_found")
        detail = await self.detail(session, organization_id)
        if detail is None:
            raise RuntimeError("updated organization could not be read")
        return detail

    async def set_expiry(
        self, session: AsyncSession, organization_id: UUID, expires_at: datetime | None
    ) -> dict[str, Any]:
        changed = await session.scalar(
            text(
                """UPDATE organizations SET expires_at=:expires,updated_at=:now
                WHERE id=:organization RETURNING id"""
            ),
            {
                "organization": organization_id,
                "expires": expires_at,
                "now": self._clock(),
            },
        )
        if changed is None:
            raise HTTPException(status_code=404, detail="organization_not_found")
        detail = await self.detail(session, organization_id)
        if detail is None:
            raise RuntimeError("updated organization could not be read")
        return detail
