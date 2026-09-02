#!/usr/bin/env python3
"""P0-02 release gate verifier.

Validates that migrations, API routes, security matrices, operational runbooks,
and provenance records for the P0-02 tenancy phase are complete and uncompromised.
"""

from __future__ import annotations

import sys
from pathlib import Path
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent


def check(description: str, condition: bool, details: str = "") -> None:
    if not condition:
        message = f"FAIL: {description}"
        if details:
            message += f" ({details})"
        print(message, file=sys.stderr)
        sys.exit(1)
    print(f"PASS: {description}")


def verify_migrations() -> None:
    migration_dir = ROOT / "apps/api/migrations/versions"
    helpers_dir = ROOT / "apps/api/migrations/helpers"
    check("migrations directory exists", migration_dir.is_dir())

    m0001 = migration_dir / "0001_identity_tenancy.py"
    m0002 = migration_dir / "0002_platform_provisioning.py"
    m0003 = migration_dir / "0003_organization_administration.py"
    tenancy_helper = helpers_dir / "tenancy.py"

    check("0001_identity_tenancy migration exists", m0001.is_file())
    check("0002_platform_provisioning migration exists", m0002.is_file())
    check("0003_organization_administration migration exists", m0003.is_file())
    check("tenancy helper exists", tenancy_helper.is_file())

    c0001 = m0001.read_text(encoding="utf-8")
    c0002 = m0002.read_text(encoding="utf-8")
    c0003 = m0003.read_text(encoding="utf-8")
    c_helper = tenancy_helper.read_text(encoding="utf-8")

    check("tenancy helper defines force RLS", "FORCE ROW LEVEL SECURITY" in c_helper)
    check("0001 enables force RLS helper", "enable_force_rls" in c0001)
    check("0001 defines tenant tables", "TENANT_TABLES" in c0001)
    check("0001 protects audit immutability", "audit_events" in c0001)
    check("0002 links to 0001", "0001_identity_tenancy" in c0002)
    check("0003 links to 0002", "0002_platform_provisioning" in c0003)


def verify_api_routes() -> None:
    # Add src to sys.path
    api_src = ROOT / "apps/api/src"
    if str(api_src) not in sys.path:
        sys.path.insert(0, str(api_src))

    from patent_evidence_api.main import create_app
    from patent_evidence_api.core.settings import Settings

    dummy_settings = Settings(
        environment="development",
        database_url="postgresql+asyncpg://patent_evidence_app:dummy@localhost:5432/patent_evidence",
        platform_database_url="postgresql+asyncpg://patent_evidence_platform:dummy@localhost:5432/patent_evidence",
        mfa_encryption_key=Fernet.generate_key().decode(),
        expose_development_tokens=False,
    )
    app = create_app(settings=dummy_settings)
    openapi_spec = app.openapi()
    routes = set(openapi_spec.get("paths", {}).keys())

    required_routes = [
        "/health",
        "/api/v1/auth/login",
        "/api/v1/auth/session",
        "/api/v1/auth/logout",
        "/api/v1/auth/sessions/revoke",
        "/api/v1/auth/password-reset/request",
        "/api/v1/auth/password-reset/confirm",
        "/api/v1/auth/mfa/totp/enroll",
        "/api/v1/auth/mfa/totp/confirm",
        "/api/v1/auth/mfa/challenge",
        "/api/v1/auth/mfa/recovery-codes",
        "/api/v1/platform/organizations",
        "/api/v1/platform/organizations/{organization_id}",
        "/api/v1/platform/organizations/{organization_id}/suspend",
        "/api/v1/platform/organizations/{organization_id}/reactivate",
        "/api/v1/platform/organizations/{organization_id}/expiry",
        "/api/v1/organizations/{organization_id}/invitations",
        "/api/v1/organizations/{organization_id}/members",
        "/api/v1/organizations/{organization_id}/members/{membership_id}/role",
        "/api/v1/organizations/{organization_id}/members/{membership_id}/suspend",
        "/api/v1/organizations/{organization_id}/members/{membership_id}/reactivate",
        "/api/v1/organizations/{organization_id}/members/{membership_id}/remove",
        "/api/v1/invitations/inspect",
        "/api/v1/invitations/accept",
    ]

    for req in required_routes:
        check(f"route mounted: {req}", req in routes)


def verify_runbooks() -> None:
    ops_dir = ROOT / "docs/operations"
    runbooks = [
        "runbook-platform-bootstrap.md",
        "runbook-organization-provisioning.md",
        "runbook-credential-rotation.md",
        "runbook-incident-containment.md",
        "runbook-backup-restore.md",
    ]
    for rb in runbooks:
        p = ops_dir / rb
        check(f"operational runbook exists: {rb}", p.is_file() and p.stat().st_size > 100)


def verify_file_map() -> None:
    file_map = ROOT / "provenance/FILE_MAP.md"
    check("FILE_MAP.md exists", file_map.is_file())
    content = file_map.read_text(encoding="utf-8")
    check("FILE_MAP records PatentQ commit", "eb63654464e51fa0d68027679c6626fb2a0c608b" in content)
    check("FILE_MAP records organization administration", "0003_organization_administration.py" in content)


def verify_web_surfaces() -> None:
    web_src = ROOT / "apps/web/src"
    views = [
        "views/LoginView.tsx",
        "views/MfaChallengeView.tsx",
        "views/MfaEnrollView.tsx",
        "views/PasswordResetView.tsx",
        "views/PlatformOrganizationsView.tsx",
        "views/OrganizationMembersView.tsx",
        "views/OrganizationSelectView.tsx",
        "views/InvitationAcceptView.tsx",
    ]
    for v in views:
        p = web_src / v
        check(f"web view exists: {v}", p.is_file())


def main() -> None:
    print("=== PatentEvidence P0-02 Phase Release Gate Verification ===")
    verify_migrations()
    verify_api_routes()
    verify_runbooks()
    verify_file_map()
    verify_web_surfaces()
    print("=== ALL P0-02 RELEASE GATES PASSED SUCCESSFULLY ===")


if __name__ == "__main__":
    main()
