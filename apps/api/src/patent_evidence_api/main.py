from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import FastAPI

from patent_evidence_api.auth.api import (
    create_auth_router,
    create_privileged_auth_router,
)
from patent_evidence_api.auth.guards import PrivilegedPrincipalGuard
from patent_evidence_api.auth.security import (
    DeterministicRateLimiter,
    PasswordSecurity,
    RateLimiter,
    TotpSecurity,
)
from patent_evidence_api.core.database import (
    create_application_session_factory,
    create_engine,
)
from patent_evidence_api.core.settings import Settings, get_settings


def create_app(
    *,
    settings: Settings | None = None,
    clock: Callable[[], datetime] | None = None,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_clock = clock or (lambda: datetime.now(UTC))
    engine = create_engine(resolved_settings.database_url)
    session_factory = create_application_session_factory(engine)
    privileged_guard = PrivilegedPrincipalGuard(resolved_clock)
    application = FastAPI(title="PatentEvidence API", version="0.1.0")
    application.state.database_engine = engine
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
        )
    )
    application.include_router(
        create_privileged_auth_router(session_factory, guard=privileged_guard)
    )

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Report process health without probing external dependencies."""
        return {"service": "api", "status": "ok", "phase": "P0"}

    return application


app = create_app()
