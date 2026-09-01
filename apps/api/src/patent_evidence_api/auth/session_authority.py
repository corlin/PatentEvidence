from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from patent_evidence_api.auth.security import MFA_RECENCY, digest_secret
from patent_evidence_api.core.database import bind_session_token_hash


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


class SessionAuthority:
    """Resolve current identity authority from an opaque browser session."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    async def resolve(
        self, request: Request, session: AsyncSession, *, lock: bool = False
    ) -> Principal:
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
                    s.expires_at,s.mfa_verified_at,s.revoked_at
                    FROM user_sessions s JOIN global_identities i ON i.id=s.global_identity_id
                    WHERE s.token_hash=:token_hash"""
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
            or row["revoked_at"] is not None
            or row["expires_at"] <= now
            or row["identity_status"] != "active"
            or row["session_security_version"] != row["identity_security_version"]
        ):
            if row is not None and row["revoked_at"] is None:
                await session.execute(
                    text(
                        "UPDATE user_sessions SET revoked_at=:now,updated_at=:now WHERE id=:id"
                    ),
                    {"now": now, "id": row["session_id"]},
                )
            raise HTTPException(status_code=401, detail="session_required")
        if lock:
            locked_identity = (
                (
                    await session.execute(
                        text(
                            """SELECT status,security_version FROM global_identities
                        WHERE id=:identity_id FOR UPDATE"""
                        ),
                        {"identity_id": row["identity_id"]},
                    )
                )
                .mappings()
                .one()
            )
            locked_session = (
                (
                    await session.execute(
                        text(
                            """SELECT revoked_at,expires_at,security_version FROM user_sessions
                        WHERE id=:session_id FOR UPDATE"""
                        ),
                        {"session_id": row["session_id"]},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                locked_identity["status"] != "active"
                or locked_identity["security_version"]
                != row["session_security_version"]
                or locked_session is None
                or locked_session["revoked_at"] is not None
                or locked_session["expires_at"] <= now
                or locked_session["security_version"]
                != locked_identity["security_version"]
            ):
                raise HTTPException(status_code=401, detail="session_required")
        await session.execute(
            text(
                "UPDATE user_sessions SET last_seen_at=:now,updated_at=:now WHERE id=:id"
            ),
            {"now": now, "id": row["session_id"]},
        )
        return Principal(
            session_id=row["session_id"],
            identity_id=row["identity_id"],
            email=row["email"],
            token_hash=token_hash,
            security_version=row["session_security_version"],
            expires_at=row["expires_at"],
            mfa_verified_at=row["mfa_verified_at"],
        )

    def require_recent_mfa(self, principal: Principal) -> Principal:
        if not principal.has_recent_mfa(self._clock()):
            raise HTTPException(status_code=403, detail="mfa_required")
        return principal
