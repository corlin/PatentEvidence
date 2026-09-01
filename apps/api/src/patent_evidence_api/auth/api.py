import secrets
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from patent_evidence_api.auth.security import (
    RESET_LIFETIME,
    SESSION_LIFETIME,
    PasswordSecurity,
    RateLimiter,
    TotpSecurity,
    digest_secret,
    issue_opaque_token,
)
from patent_evidence_api.auth.guards import Principal, PrivilegedPrincipalGuard
from patent_evidence_api.core.database import (
    APPLICATION_DATABASE_ROLE,
    bind_session_token_hash,
    bind_transaction_context,
    verify_database_role,
)


class LoginBody(BaseModel):
    email: str
    password: str


class ResetRequestBody(BaseModel):
    email: str


class ResetConfirmBody(BaseModel):
    token: str
    new_password: str


class TotpConfirmBody(BaseModel):
    credential_id: UUID
    code: str


class MfaChallengeBody(BaseModel):
    code: str | None = None
    recovery_code: str | None = None


def create_auth_router(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    clock: Callable[[], datetime],
    passwords: PasswordSecurity,
    totp: TotpSecurity,
    rate_limiter: RateLimiter,
    secure_cookies: bool,
    expose_development_tokens: bool,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth")

    async def database_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session, session.begin():
            await verify_database_role(session, APPLICATION_DATABASE_ROLE)
            await bind_transaction_context(session, organization_id=None)
            yield session

    def set_session_cookie(response: Response, token: str) -> None:
        response.set_cookie(
            "pe_session",
            token,
            max_age=int(SESSION_LIFETIME.total_seconds()),
            httponly=True,
            secure=secure_cookies,
            samesite="lax",
            path="/",
        )

    async def authenticate(
        request: Request, session: AsyncSession, *, lock: bool = False
    ) -> Principal:
        token = request.cookies.get("pe_session")
        if not token:
            raise HTTPException(status_code=401, detail="session_required")
        token_hash = digest_secret(token)
        await bind_session_token_hash(session, token_hash)
        lock_sql = " FOR UPDATE" if lock else ""
        row = (
            (
                await session.execute(
                    text(
                        """SELECT s.id AS session_id,s.global_identity_id AS identity_id,
                    i.email_normalized AS email,i.status AS identity_status,
                    s.expires_at,s.mfa_verified_at,s.revoked_at
                    FROM user_sessions s JOIN global_identities i ON i.id=s.global_identity_id
                    WHERE s.token_hash=:token_hash"""
                        + lock_sql
                    ),
                    {"token_hash": token_hash},
                )
            )
            .mappings()
            .one_or_none()
        )
        now = clock()
        if (
            row is None
            or row["revoked_at"] is not None
            or row["expires_at"] <= now
            or row["identity_status"] != "active"
        ):
            if row is not None and row["revoked_at"] is None:
                await session.execute(
                    text(
                        "UPDATE user_sessions SET revoked_at=:now,updated_at=:now WHERE id=:id"
                    ),
                    {"now": now, "id": row["session_id"]},
                )
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
            expires_at=row["expires_at"],
            mfa_verified_at=row["mfa_verified_at"],
        )

    async def issue_session(
        session: AsyncSession,
        *,
        identity_id: UUID,
        now: datetime,
        mfa_verified_at: datetime | None = None,
    ) -> tuple[str, UUID, datetime]:
        token = issue_opaque_token()
        token_hash = digest_secret(token)
        session_id = uuid4()
        expires_at = now + SESSION_LIFETIME
        await bind_session_token_hash(session, token_hash)
        await session.execute(
            text(
                """INSERT INTO user_sessions
                (id,global_identity_id,token_hash,mfa_verified_at,expires_at,last_seen_at,
                 created_at,updated_at)
                VALUES (:id,:identity_id,:token_hash,:mfa_verified_at,:expires_at,:now,:now,:now)"""
            ),
            {
                "id": session_id,
                "identity_id": identity_id,
                "token_hash": token_hash,
                "mfa_verified_at": mfa_verified_at,
                "expires_at": expires_at,
                "now": now,
            },
        )
        return token, session_id, expires_at

    async def rotate_session(
        session: AsyncSession, principal: Principal, now: datetime
    ) -> tuple[str, datetime]:
        await session.execute(
            text(
                "UPDATE user_sessions SET revoked_at=:now,updated_at=:now WHERE id=:id"
            ),
            {"now": now, "id": principal.session_id},
        )
        token, _, expires_at = await issue_session(
            session, identity_id=principal.identity_id, now=now, mfa_verified_at=now
        )
        return token, expires_at

    @router.post("/login")
    async def login(
        body: LoginBody,
        request: Request,
        session: AsyncSession = Depends(database_session),
    ) -> JSONResponse:
        now = clock()
        normalized_email = body.email.strip().lower()
        client_host = request.client.host if request.client else "unknown"
        if not rate_limiter.allow(f"login:{client_host}:{normalized_email}", now):
            raise HTTPException(status_code=429, detail="rate_limited")
        row = (
            (
                await session.execute(
                    text(
                        """SELECT id,password_hash,status FROM global_identities
                    WHERE email_normalized=:email"""
                    ),
                    {"email": normalized_email},
                )
            )
            .mappings()
            .one_or_none()
        )
        encoded = row["password_hash"] if row else None
        valid = passwords.verify(encoded, body.password)
        if row is None or row["status"] != "active" or not valid:
            raise HTTPException(status_code=401, detail="invalid_credentials")
        token, _, expires_at = await issue_session(
            session, identity_id=row["id"], now=now
        )
        response = JSONResponse(
            {"identity_id": str(row["id"]), "expires_at": expires_at.isoformat()}
        )
        set_session_cookie(response, token)
        return response

    @router.get("/session")
    async def current_session(
        request: Request, session: AsyncSession = Depends(database_session)
    ) -> dict[str, object]:
        principal = await authenticate(request, session)
        return {
            "identity_id": str(principal.identity_id),
            "email": principal.email,
            "expires_at": principal.expires_at.isoformat(),
            "mfa_recent": principal.has_recent_mfa(clock()),
        }

    @router.post("/logout", status_code=204)
    async def logout(
        request: Request, session: AsyncSession = Depends(database_session)
    ) -> Response:
        principal = await authenticate(request, session, lock=True)
        now = clock()
        await session.execute(
            text(
                "UPDATE user_sessions SET revoked_at=:now,updated_at=:now WHERE id=:id"
            ),
            {"now": now, "id": principal.session_id},
        )
        response = Response(status_code=204)
        response.delete_cookie(
            "pe_session", path="/", httponly=True, secure=secure_cookies, samesite="lax"
        )
        return response

    @router.post("/sessions/revoke", status_code=204)
    async def revoke_sessions(
        request: Request, session: AsyncSession = Depends(database_session)
    ) -> Response:
        principal = await authenticate(request, session, lock=True)
        await session.scalar(
            text("SELECT revoke_current_identity_sessions(:identity_id)"),
            {"identity_id": principal.identity_id},
        )
        response = Response(status_code=204)
        response.delete_cookie(
            "pe_session", path="/", httponly=True, secure=secure_cookies, samesite="lax"
        )
        return response

    @router.post("/password-reset/request", status_code=202)
    async def request_password_reset(
        body: ResetRequestBody,
        request: Request,
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, str]:
        now = clock()
        normalized_email = body.email.strip().lower()
        client_host = request.client.host if request.client else "unknown"
        token = issue_opaque_token()
        if rate_limiter.allow(f"reset:{client_host}:{normalized_email}", now):
            identity_id = await session.scalar(
                text(
                    """SELECT id FROM global_identities
                    WHERE email_normalized=:email AND status='active'"""
                ),
                {"email": normalized_email},
            )
            if identity_id is not None:
                await session.execute(
                    text(
                        """UPDATE password_reset_tokens SET used_at=:now
                        WHERE global_identity_id=:identity_id AND used_at IS NULL"""
                    ),
                    {"now": now, "identity_id": identity_id},
                )
                await session.execute(
                    text(
                        """INSERT INTO password_reset_tokens
                        (id,global_identity_id,token_hash,expires_at,created_at)
                        VALUES (:id,:identity_id,:token_hash,:expires_at,:now)"""
                    ),
                    {
                        "id": uuid4(),
                        "identity_id": identity_id,
                        "token_hash": digest_secret(token),
                        "expires_at": now + RESET_LIFETIME,
                        "now": now,
                    },
                )
        response = {"status": "accepted"}
        if expose_development_tokens:
            response["reset_token"] = token
        return response

    @router.post("/password-reset/confirm", status_code=204)
    async def confirm_password_reset(
        body: ResetConfirmBody, session: AsyncSession = Depends(database_session)
    ) -> Response:
        try:
            new_hash = passwords.hash(body.new_password)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="password_policy_failed"
            ) from exc
        identity_id = await session.scalar(
            text("SELECT complete_password_reset(:token_hash,:password_hash)"),
            {"token_hash": digest_secret(body.token), "password_hash": new_hash},
        )
        if identity_id is None:
            raise HTTPException(
                status_code=400, detail="invalid_or_expired_reset_token"
            )
        return Response(status_code=204)

    @router.post("/mfa/totp/enroll", status_code=201)
    async def enroll_totp(
        request: Request, session: AsyncSession = Depends(database_session)
    ) -> dict[str, str]:
        principal = await authenticate(request, session, lock=True)
        active_exists = await session.scalar(
            text(
                """SELECT EXISTS(SELECT 1 FROM mfa_credentials
                WHERE global_identity_id=:identity_id AND status='active')"""
            ),
            {"identity_id": principal.identity_id},
        )
        if active_exists and not principal.has_recent_mfa(clock()):
            raise HTTPException(status_code=403, detail="mfa_required")
        await session.execute(
            text(
                "DELETE FROM mfa_recovery_codes WHERE global_identity_id=:identity_id"
            ),
            {"identity_id": principal.identity_id},
        )
        await session.execute(
            text("DELETE FROM mfa_credentials WHERE global_identity_id=:identity_id"),
            {"identity_id": principal.identity_id},
        )
        secret = totp.issue_secret()
        credential_id = uuid4()
        await session.execute(
            text(
                """INSERT INTO mfa_credentials
                (id,global_identity_id,credential_type,label,encrypted_secret_ciphertext,
                 status,created_at)
                VALUES (:id,:identity_id,'totp','primary',:ciphertext,'pending',:now)"""
            ),
            {
                "id": credential_id,
                "identity_id": principal.identity_id,
                "ciphertext": totp.encrypt(secret),
                "now": clock(),
            },
        )
        return {"credential_id": str(credential_id), "secret": secret}

    async def store_recovery_codes(
        session: AsyncSession, identity_id: UUID, credential_id: UUID
    ) -> list[str]:
        await session.execute(
            text(
                "DELETE FROM mfa_recovery_codes WHERE global_identity_id=:identity_id"
            ),
            {"identity_id": identity_id},
        )
        batch_id = uuid4()
        codes = [secrets.token_urlsafe(12) for _ in range(8)]
        for code in codes:
            await session.execute(
                text(
                    """INSERT INTO mfa_recovery_codes
                    (id,global_identity_id,mfa_credential_id,batch_id,code_hash,created_at)
                    VALUES (:id,:identity_id,:credential_id,:batch_id,:code_hash,:now)"""
                ),
                {
                    "id": uuid4(),
                    "identity_id": identity_id,
                    "credential_id": credential_id,
                    "batch_id": batch_id,
                    "code_hash": digest_secret(code),
                    "now": clock(),
                },
            )
        return codes

    @router.post("/mfa/totp/confirm")
    async def confirm_totp(
        body: TotpConfirmBody,
        request: Request,
        session: AsyncSession = Depends(database_session),
    ) -> JSONResponse:
        principal = await authenticate(request, session, lock=True)
        row = (
            (
                await session.execute(
                    text(
                        """SELECT encrypted_secret_ciphertext,created_at FROM mfa_credentials
                    WHERE id=:credential_id AND global_identity_id=:identity_id
                      AND status='pending' FOR UPDATE"""
                    ),
                    {
                        "credential_id": body.credential_id,
                        "identity_id": principal.identity_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        now = clock()
        if (
            row is None
            or row["created_at"] < now - timedelta(minutes=10)
            or not totp.verify(
                totp.decrypt(row["encrypted_secret_ciphertext"]), body.code, now
            )
        ):
            raise HTTPException(status_code=401, detail="invalid_mfa_challenge")
        await session.execute(
            text(
                """UPDATE mfa_credentials SET status='active',confirmed_at=:now,last_used_at=:now
                WHERE id=:credential_id"""
            ),
            {"now": now, "credential_id": body.credential_id},
        )
        codes = await store_recovery_codes(
            session, principal.identity_id, body.credential_id
        )
        token, expires_at = await rotate_session(session, principal, now)
        response = JSONResponse(
            {
                "status": "confirmed",
                "recovery_codes": codes,
                "expires_at": expires_at.isoformat(),
            }
        )
        set_session_cookie(response, token)
        return response

    @router.post("/mfa/challenge")
    async def challenge_mfa(
        body: MfaChallengeBody,
        request: Request,
        session: AsyncSession = Depends(database_session),
    ) -> JSONResponse:
        principal = await authenticate(request, session, lock=True)
        credential = (
            (
                await session.execute(
                    text(
                        """SELECT id,encrypted_secret_ciphertext FROM mfa_credentials
                    WHERE global_identity_id=:identity_id AND status='active'
                    ORDER BY confirmed_at DESC LIMIT 1 FOR UPDATE"""
                    ),
                    {"identity_id": principal.identity_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        now = clock()
        verified = False
        if credential is not None and body.code:
            verified = totp.verify(
                totp.decrypt(credential["encrypted_secret_ciphertext"]), body.code, now
            )
        elif credential is not None and body.recovery_code:
            result = await session.execute(
                text(
                    """UPDATE mfa_recovery_codes SET used_at=:now
                    WHERE global_identity_id=:identity_id AND mfa_credential_id=:credential_id
                      AND code_hash=:code_hash AND used_at IS NULL RETURNING id"""
                ),
                {
                    "now": now,
                    "identity_id": principal.identity_id,
                    "credential_id": credential["id"],
                    "code_hash": digest_secret(body.recovery_code),
                },
            )
            verified = result.scalar_one_or_none() is not None
        if not verified:
            raise HTTPException(status_code=401, detail="invalid_mfa_challenge")
        await session.execute(
            text("UPDATE mfa_credentials SET last_used_at=:now WHERE id=:id"),
            {"now": now, "id": credential["id"]},
        )
        token, expires_at = await rotate_session(session, principal, now)
        response = JSONResponse(
            {"status": "verified", "expires_at": expires_at.isoformat()}
        )
        set_session_cookie(response, token)
        return response

    @router.post("/mfa/recovery-codes")
    async def regenerate_recovery_codes(
        request: Request, session: AsyncSession = Depends(database_session)
    ) -> dict[str, object]:
        principal = await authenticate(request, session, lock=True)
        if not principal.has_recent_mfa(clock()):
            raise HTTPException(status_code=403, detail="mfa_required")
        credential_id = await session.scalar(
            text(
                """SELECT id FROM mfa_credentials WHERE global_identity_id=:identity_id
                AND status='active' ORDER BY confirmed_at DESC LIMIT 1"""
            ),
            {"identity_id": principal.identity_id},
        )
        if credential_id is None:
            raise HTTPException(status_code=409, detail="mfa_not_configured")
        codes = await store_recovery_codes(
            session, principal.identity_id, credential_id
        )
        return {"recovery_codes": codes}

    return router


def create_privileged_auth_router(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    guard: PrivilegedPrincipalGuard,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    async def database_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session, session.begin():
            await verify_database_role(session, APPLICATION_DATABASE_ROLE)
            await bind_transaction_context(session, organization_id=None)
            yield session

    @router.post(
        "/organizations/{organization_id}/members/{target_identity}/mfa/reset",
        status_code=204,
    )
    async def organization_mfa_reset(
        organization_id: UUID,
        target_identity: UUID,
        request: Request,
        session: AsyncSession = Depends(database_session),
    ) -> Response:
        await guard.organization_administrator(
            request,
            session,
            organization_id,
            lower_level_target=target_identity,
        )
        reset = await session.scalar(
            text("SELECT reset_identity_mfa_as_administrator(:target,:organization)"),
            {"target": target_identity, "organization": organization_id},
        )
        if not reset:
            raise HTTPException(status_code=403, detail="forbidden")
        return Response(status_code=204)

    @router.post("/platform/identities/{target_identity}/mfa/reset", status_code=204)
    async def platform_mfa_reset(
        target_identity: UUID,
        request: Request,
        session: AsyncSession = Depends(database_session),
    ) -> Response:
        await guard.platform_administrator(request, session)
        reset = await session.scalar(
            text("SELECT reset_identity_mfa_as_administrator(:target,NULL)"),
            {"target": target_identity},
        )
        if not reset:
            raise HTTPException(status_code=403, detail="forbidden")
        return Response(status_code=204)

    return router
