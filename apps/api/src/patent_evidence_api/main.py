import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import FastAPI

from patent_evidence_api.auth.api import (
    create_auth_router,
    create_privileged_auth_router,
)
from patent_evidence_api.auth.guards import (
    PlatformPrincipalGuard,
    PrivilegedPrincipalGuard,
)
from patent_evidence_api.auth.security import (
    DeterministicRateLimiter,
    MinimumResponseTime,
    PasswordSecurity,
    RateLimiter,
    TotpSecurity,
)
from patent_evidence_api.core.database import (
    create_application_session_factory,
    create_engine,
    create_platform_session_factory,
)
from patent_evidence_api.core.settings import Settings, get_settings


def create_app(
    *,
    settings: Settings | None = None,
    clock: Callable[[], datetime] | None = None,
    rate_limiter: RateLimiter | None = None,
    response_monotonic: Callable[[], float] = time.monotonic,
    response_sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    reset_response_floor_seconds: float = 0.2,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_clock = clock or (lambda: datetime.now(UTC))
    engine = create_engine(resolved_settings.database_url)
    platform_engine = create_engine(resolved_settings.platform_database_url)
    session_factory = create_application_session_factory(engine)
    platform_session_factory = create_platform_session_factory(platform_engine)
    privileged_guard = PrivilegedPrincipalGuard(resolved_clock)
    platform_guard = PlatformPrincipalGuard()
    application = FastAPI(title="PatentEvidence API", version="0.1.0")
    application.state.database_engine = engine
    application.state.platform_database_engine = platform_engine
    application.state.privileged_principal_guard = privileged_guard
    application.include_router(
        create_auth_router(
            session_factory,
            clock=resolved_clock,
            passwords=PasswordSecurity(),
            totp=TotpSecurity(resolved_settings.mfa_encryption_key.get_secret_value()),
            rate_limiter=rate_limiter or DeterministicRateLimiter(),
            secure_cookies=resolved_settings.environment != "development",
            expose_development_tokens=resolved_settings.expose_development_tokens,
            reset_response_floor=MinimumResponseTime(
                seconds=reset_response_floor_seconds,
                monotonic=response_monotonic,
                sleeper=response_sleeper,
            ),
        )
    )
    application.include_router(
        create_privileged_auth_router(
            session_factory,
            platform_session_factory,
            application_guard=privileged_guard,
            platform_guard=platform_guard,
        )
    )

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Report process health without probing external dependencies."""
        return {"service": "api", "status": "ok", "phase": "P0"}

    return application


app = create_app()
