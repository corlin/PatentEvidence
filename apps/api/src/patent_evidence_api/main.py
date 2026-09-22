import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
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
    AsyncPasswordSecurity,
    BoundedPasswordWorkPool,
    DeterministicRateLimiter,
    MinimumResponseTime,
    PasswordSecurity,
    PasswordWorkRunner,
    RateLimiter,
    TotpSecurity,
)
from patent_evidence_api.auth.session_authority import SessionAuthority
from patent_evidence_api.core.database import (
    create_application_session_factory,
    create_engine,
    create_platform_session_factory,
)
from patent_evidence_api.core.organization_lifecycle import OrganizationLifecycle
from patent_evidence_api.core.settings import Settings, get_settings
from patent_evidence_api.platform.access import PlatformAccess
from patent_evidence_api.platform.api import create_platform_router
from patent_evidence_api.platform.audit import PlatformAuditWriter
from patent_evidence_api.platform.organizations import (
    OrganizationDirectory,
    OrganizationProvisioner,
)
from patent_evidence_api.organization.access import OrganizationAccess
from patent_evidence_api.organization.api import (
    create_invitation_router,
    create_organization_router,
)
from patent_evidence_api.organization.audit import OrganizationAuditWriter
from patent_evidence_api.organization.invitations import (
    InvitationAcceptance,
    InvitationService,
)
from patent_evidence_api.organization.members import MemberService
from adapters.object_storage.client import ObjectStorageClient
from patent_evidence_api.cases.api import create_cases_router
from patent_evidence_api.cases.services import CaseService, DocumentService, DrawingService
from patent_evidence_api.features.api import create_features_router
from patent_evidence_api.features.services import FeatureService
from patent_evidence_api.search.api import create_search_router
from patent_evidence_api.search.services import (
    CandidateTriageService,
    SearchExecutionService,
    SearchStrategyService,
)
from patent_evidence_api.comparison.api import create_comparison_router
from patent_evidence_api.comparison.services import ComparisonMatrixService
from patent_evidence_api.reports.api import create_reports_router
from patent_evidence_api.reports.services import EvidenceReportService
from patent_evidence_api.review.api import create_review_router
from patent_evidence_api.review.services import ReviewService
from patent_evidence_api.assessment.api import create_assessment_router
from patent_evidence_api.assessment.assembly import AssessmentAssemblyService
from patent_evidence_api.assessment.input_api import create_assessment_input_router
from patent_evidence_api.assessment.inputs import AssessmentInputService
from patent_evidence_api.assessment.services import AssessmentService


def create_app(
    *,
    settings: Settings | None = None,
    clock: Callable[[], datetime] | None = None,
    rate_limiter: RateLimiter | None = None,
    response_monotonic: Callable[[], float] = time.monotonic,
    response_sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    reset_response_floor_seconds: float = 0.2,
    password_work_runner: PasswordWorkRunner | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_clock = clock or (lambda: datetime.now(UTC))
    owned_password_pool = (
        BoundedPasswordWorkPool(
            workers=resolved_settings.password_work_workers,
            queue_capacity=resolved_settings.password_work_queue,
        )
        if password_work_runner is None
        else None
    )
    resolved_password_runner = password_work_runner or owned_password_pool
    if resolved_password_runner is None:
        raise RuntimeError("password work runner is required")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if owned_password_pool is not None:
                await owned_password_pool.close()

    engine = create_engine(resolved_settings.database_url)
    platform_engine = create_engine(resolved_settings.platform_database_url)
    session_factory = create_application_session_factory(engine)
    platform_session_factory = create_platform_session_factory(platform_engine)
    session_authority = SessionAuthority(
        resolved_clock, disable_mfa=resolved_settings.disable_mfa
    )
    resolved_passwords = AsyncPasswordSecurity(
        PasswordSecurity(), runner=resolved_password_runner
    )
    privileged_guard = PrivilegedPrincipalGuard(session_authority, resolved_clock)
    platform_guard = PlatformPrincipalGuard()
    platform_access = PlatformAccess(
        session_factory,
        platform_session_factory,
        session_authority=session_authority,
        platform_guard=platform_guard,
        audit_writer=PlatformAuditWriter(resolved_clock),
    )
    application = FastAPI(
        title="PatentEvidence API", version="0.1.0", lifespan=lifespan
    )
    application.state.database_engine = engine
    application.state.platform_database_engine = platform_engine
    application.state.password_work_pool = resolved_password_runner
    application.include_router(
        create_auth_router(
            session_factory,
            platform_session_factory=platform_session_factory,
            clock=resolved_clock,
            passwords=resolved_passwords,
            totp=TotpSecurity(resolved_settings.mfa_encryption_key.get_secret_value()),
            rate_limiter=rate_limiter or DeterministicRateLimiter(),
            secure_cookies=resolved_settings.environment != "development",
            expose_development_tokens=resolved_settings.expose_development_tokens,
            reset_response_floor=MinimumResponseTime(
                seconds=reset_response_floor_seconds,
                monotonic=response_monotonic,
                sleeper=response_sleeper,
            ),
            session_authority=session_authority,
        )
    )
    application.include_router(
        create_privileged_auth_router(
            session_factory,
            application_guard=privileged_guard,
            platform_access=platform_access,
        )
    )
    application.include_router(
        create_platform_router(
            platform_access,
            OrganizationProvisioner(resolved_clock),
            OrganizationDirectory(resolved_clock, OrganizationLifecycle()),
        )
    )
    organization_audit = OrganizationAuditWriter(resolved_clock)
    invitation_acceptance = InvitationAcceptance(
        session_factory,
        clock=resolved_clock,
        audit_writer=organization_audit,
    )
    organization_access = OrganizationAccess(
        session_factory,
        session_authority=session_authority,
        audit_writer=organization_audit,
        clock=resolved_clock,
    )
    application.include_router(
        create_organization_router(
            organization_access,
            InvitationService(resolved_clock),
            MemberService(resolved_clock),
        )
    )
    application.include_router(
        create_invitation_router(invitation_acceptance, resolved_passwords)
    )
    storage_client = ObjectStorageClient()
    application.include_router(
        create_cases_router(
            organization_access,
            CaseService(resolved_clock),
            DocumentService(resolved_clock),
            storage_client,
            DrawingService(resolved_clock),
        )
    )
    application.include_router(
        create_features_router(
            organization_access,
            FeatureService(resolved_clock),
        )
    )
    application.include_router(
        create_search_router(
            organization_access,
            SearchStrategyService(resolved_clock),
            SearchExecutionService(resolved_clock),
            CandidateTriageService(resolved_clock),
        )
    )
    application.include_router(
        create_comparison_router(
            organization_access,
            ComparisonMatrixService(resolved_clock),
        )
    )
    application.include_router(
        create_reports_router(
            organization_access,
            EvidenceReportService(resolved_clock),
        )
    )
    application.include_router(
        create_review_router(
            organization_access,
            ReviewService(resolved_clock),
        )
    )
    application.include_router(
        create_assessment_router(
            organization_access,
            AssessmentService(resolved_clock),
            AssessmentAssemblyService(resolved_clock),
        )
    )
    application.include_router(
        create_assessment_input_router(
            organization_access,
            AssessmentInputService(resolved_clock),
        )
    )

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Report process health without probing external dependencies."""
        return {"service": "api", "status": "ok", "phase": "P0"}

    return application


app = create_app()
