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
    AsyncPasswordSecurity,
    MinimumResponseTime,
    PasswordWorkCapacityError,
    RESET_LIFETIME,
    SESSION_LIFETIME,
    RateLimiter,
    TotpSecurity,
    digest_secret,
    issue_opaque_token,
)
from patent_evidence_api.auth.guards import PrivilegedPrincipalGuard
from patent_evidence_api.auth.session_authority import Principal, SessionAuthority
from patent_evidence_api.core.database import (
    application_transaction,
    bind_session_token_hash,
)
from patent_evidence_api.platform.access import PlatformAccess


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
    passwords: AsyncPasswordSecurity,
    totp: TotpSecurity,
    rate_limiter: RateLimiter,
    secure_cookies: bool,
    expose_development_tokens: bool,
    reset_response_floor: MinimumResponseTime,
    session_authority: SessionAuthority,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth")

    async def database_session() -> AsyncIterator[AsyncSession]:
        async with application_transaction(session_factory) as session:
            yield session

    def capacity_exhausted() -> HTTPException:
        return HTTPException(
            status_code=503, detail="authentication_temporarily_unavailable"
        )

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

    async def issue_session(
        session: AsyncSession,
        *,
        identity_id: UUID,
        security_version: int,
        now: datetime,
        mfa_verified_at: datetime | None = None,
    ) -> tuple[str, UUID, datetime]:
        locked_identity = (
            (
                await session.execute(
                    text(
                        """SELECT status,security_version FROM global_identities
                    WHERE id=:identity_id FOR UPDATE"""
                    ),
                    {"identity_id": identity_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            locked_identity is None
            or locked_identity["status"] != "active"
            or locked_identity["security_version"] != security_version
        ):
            raise HTTPException(status_code=401, detail="session_required")
        token = issue_opaque_token()
        token_hash = digest_secret(token)
        session_id = uuid4()
        expires_at = now + SESSION_LIFETIME
        await bind_session_token_hash(session, token_hash)
        await session.execute(
            text(
                """INSERT INTO user_sessions
                (id,global_identity_id,security_version,token_hash,mfa_verified_at,expires_at,last_seen_at,
                 created_at,updated_at)
                VALUES (:id,:identity_id,:security_version,:token_hash,:mfa_verified_at,
                        :expires_at,:now,:now,:now)"""
            ),
            {
                "id": session_id,
                "identity_id": identity_id,
                "security_version": security_version,
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
            session,
            identity_id=principal.identity_id,
            security_version=principal.security_version,
            now=now,
            mfa_verified_at=now,
        )
        return token, expires_at

    async def revoke_valid_presented_session(
        request: Request, session: AsyncSession, now: datetime
    ) -> None:
        presented = request.cookies.get("pe_session")
        if not presented:
            return
        token_hash = digest_secret(presented)
        await bind_session_token_hash(session, token_hash)
        session_id = await session.scalar(
            text(
                """SELECT session.id FROM user_sessions session
                JOIN global_identities identity
                  ON identity.id=session.global_identity_id
                WHERE session.token_hash=:token_hash AND session.revoked_at IS NULL
                  AND session.expires_at > :now AND identity.status='active'
                  AND session.security_version=identity.security_version
                FOR UPDATE OF session"""
            ),
            {"token_hash": token_hash, "now": now},
        )
        if session_id is not None:
            await session.execute(
                text(
                    """UPDATE user_sessions SET revoked_at=:now,updated_at=:now
                    WHERE id=:session_id"""
                ),
                {"now": now, "session_id": session_id},
            )

    @router.post("/login")
    async def login(
        body: LoginBody,
        request: Request,
    ) -> JSONResponse:
        now = clock()
        normalized_email = body.email.strip().lower()
        client_host = request.client.host if request.client else "unknown"
        ip_allowed = rate_limiter.allow(f"login-ip:{client_host}", now)
        email_allowed = rate_limiter.allow(
            f"login-email:{digest_secret(normalized_email)}", now
        )
        if not (ip_allowed and email_allowed):
            raise HTTPException(status_code=429, detail="rate_limited")
        try:
            async with passwords.reserve() as password_work:
                async with application_transaction(session_factory) as snapshot_session:
                    row = (
                        (
                            await snapshot_session.execute(
                                text(
                                    """SELECT id,password_hash,status,security_version
                                FROM global_identities WHERE email_normalized=:email"""
                                ),
                                {"email": normalized_email},
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                encoded = row["password_hash"] if row else None
                valid = await password_work.verify(encoded, body.password)
        except PasswordWorkCapacityError as exc:
            raise capacity_exhausted() from exc
        if row is None or row["status"] != "active" or not valid:
            raise HTTPException(status_code=401, detail="invalid_credentials")
        async with application_transaction(session_factory) as session:
            locked_row = (
                (
                    await session.execute(
                        text(
                            """SELECT password_hash,status,security_version
                        FROM global_identities WHERE id=:identity_id FOR UPDATE"""
                        ),
                        {"identity_id": row["id"]},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                locked_row is None
                or locked_row["password_hash"] != row["password_hash"]
                or locked_row["security_version"] != row["security_version"]
                or locked_row["status"] != row["status"]
            ):
                raise HTTPException(status_code=401, detail="invalid_credentials")
            await revoke_valid_presented_session(request, session, now)
            token, _, expires_at = await issue_session(
                session,
                identity_id=row["id"],
                security_version=row["security_version"],
                now=now,
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
        principal = await session_authority.resolve(request, session)
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
        principal = await session_authority.resolve(request, session, lock=True)
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
        principal = await session_authority.resolve(request, session, lock=True)
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
    ) -> dict[str, str]:
        response_started = reset_response_floor.start()
        now = clock()
        normalized_email = body.email.strip().lower()
        client_host = request.client.host if request.client else "unknown"
        token = issue_opaque_token()
        ip_allowed = rate_limiter.allow(f"reset-ip:{client_host}", now)
        email_allowed = rate_limiter.allow(
            f"reset-email:{digest_secret(normalized_email)}", now
        )
        if ip_allowed and email_allowed:
            try:
                async with passwords.reserve() as password_work:
                    await password_work.perform_dummy_work()
            except PasswordWorkCapacityError as exc:
                await reset_response_floor.wait(response_started)
                raise capacity_exhausted() from exc
            async with application_transaction(session_factory) as session:
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
        await reset_response_floor.wait(response_started)
        return response

    @router.post("/password-reset/confirm", status_code=204)
    async def confirm_password_reset(
        body: ResetConfirmBody,
        request: Request,
    ) -> Response:
        now = clock()
        client_host = request.client.host if request.client else "unknown"
        if not rate_limiter.allow(f"reset-confirm-ip:{client_host}", now):
            raise HTTPException(status_code=429, detail="rate_limited")
        token_hash = digest_secret(body.token)
        try:
            async with passwords.reserve() as password_work:
                async with application_transaction(
                    session_factory
                ) as validation_session:
                    token_snapshot = (
                        (
                            await validation_session.execute(
                                text(
                                    """SELECT token_id,identity_id,identity_security_version
                                FROM inspect_password_reset(:token_hash)"""
                                ),
                                {"token_hash": token_hash},
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                if token_snapshot is None:
                    raise HTTPException(
                        status_code=400, detail="invalid_or_expired_reset_token"
                    )
                try:
                    new_hash = await password_work.hash(body.new_password)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=422, detail="password_policy_failed"
                    ) from exc
        except PasswordWorkCapacityError as exc:
            raise capacity_exhausted() from exc
        async with application_transaction(session_factory) as session:
            identity_id = await session.scalar(
                text(
                    """SELECT complete_password_reset(
                    :token_hash,:token_id,:identity_id,:security_version,:password_hash)"""
                ),
                {
                    "token_hash": token_hash,
                    "token_id": token_snapshot["token_id"],
                    "identity_id": token_snapshot["identity_id"],
                    "security_version": token_snapshot["identity_security_version"],
                    "password_hash": new_hash,
                },
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
        principal = await session_authority.resolve(request, session, lock=True)
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
                """DELETE FROM mfa_credentials
                WHERE global_identity_id=:identity_id AND status='pending'"""
            ),
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
        principal = await session_authority.resolve(request, session, lock=True)
        client_host = request.client.host if request.client else "unknown"
        if not rate_limiter.allow(
            f"mfa-confirm:{principal.identity_id}:{client_host}", clock()
        ):
            raise HTTPException(status_code=429, detail="rate_limited")
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
                """UPDATE mfa_credentials SET status='revoked'
                WHERE global_identity_id=:identity_id AND status='active'"""
            ),
            {"identity_id": principal.identity_id},
        )
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
        principal = await session_authority.resolve(request, session, lock=True)
        client_host = request.client.host if request.client else "unknown"
        if not rate_limiter.allow(
            f"mfa-challenge:{principal.identity_id}:{client_host}", clock()
        ):
            raise HTTPException(status_code=429, detail="rate_limited")
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
        principal = await session_authority.resolve(request, session, lock=True)
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
    application_session_factory: async_sessionmaker[AsyncSession],
    *,
    application_guard: PrivilegedPrincipalGuard,
    platform_access: PlatformAccess,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    async def database_session() -> AsyncIterator[AsyncSession]:
        async with application_transaction(application_session_factory) as session:
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
        await application_guard.organization_administrator(
            request,
            session,
            organization_id,
            lower_level_target=target_identity,
        )
        reset = await session.scalar(
            text(
                """SELECT reset_identity_mfa_as_organization_administrator(
                :target,:organization)"""
            ),
            {"target": target_identity, "organization": organization_id},
        )
        if not reset:
            raise HTTPException(status_code=403, detail="forbidden")
        return Response(status_code=204)

    @router.post("/platform/identities/{target_identity}/mfa/reset", status_code=204)
    async def platform_mfa_reset(
        target_identity: UUID,
        request: Request,
    ) -> Response:
        async with platform_access.authorized(request) as (platform_session, principal):
            reset = await platform_session.scalar(
                text(
                    """SELECT reset_identity_mfa_as_platform_administrator(
                    :actor,:security_version,:target)"""
                ),
                {
                    "actor": principal.identity_id,
                    "security_version": principal.security_version,
                    "target": target_identity,
                },
            )
            if not reset:
                raise HTTPException(status_code=403, detail="forbidden")
        return Response(status_code=204)

    return router
