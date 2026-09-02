import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import psycopg
import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from patent_evidence_api.main import create_app
from test_support import api_settings, postgres_url, totp_code

PLATFORM_EMAIL = "platform-e2e@patentevidence.local"
ADMIN_A_EMAIL = "admin-a@agency-alpha.com"
AGENT_A_EMAIL = "agent-a@agency-alpha.com"
ADMIN_B_EMAIL = "admin-b@agency-beta.com"

PASSWORD_PLATFORM = "Platform-Admin-Secret-Pass-2026!"
PASSWORD_ADMIN_A = "Alpha-Admin-Secure-Password-123!"
PASSWORD_AGENT_A = "Alpha-Agent-Secure-Password-456!"
PASSWORD_ADMIN_B = "Beta-Admin-Secure-Password-789!"

MFA_KEY = Fernet.generate_key().decode()


class Clock:
    def __init__(self) -> None:
        self.value = datetime.now(UTC).replace(microsecond=0)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


@pytest.fixture
def clean_database() -> Iterator[None]:
    migration_url = postgres_url(
        "PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration"
    )
    with psycopg.connect(migration_url, autocommit=True) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """TRUNCATE TABLE
                platform_audit_events,
                organization_audit_events,
                organization_invitations,
                organization_memberships,
                organization_plan_quotas,
                organizations,
                mfa_recovery_codes,
                mfa_credentials,
                user_sessions,
                password_reset_tokens,
                platform_operator_grants,
                platform_organization_idempotency,
                platform_organization_provisioning_records,
                global_identities
                CASCADE"""
            )
    yield


@pytest.mark.asyncio
async def test_p0_02_full_security_and_lifecycle_e2e(clean_database: None) -> None:
    """End-to-end multi-role lifecycle proof for P0-02."""
    clock = Clock()
    settings = api_settings(mfa_encryption_key=MFA_KEY)
    migration_url = postgres_url(
        "PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration"
    )

    app = create_app(
        settings=settings,
        clock=clock,
        reset_response_floor_seconds=0.0,
    )

    # 1. Bootstrap Platform Admin CLI
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../../..")
    )
    bootstrap_script = os.path.join(repo_root, "scripts/bootstrap-platform-admin.py")
    env = {
        **os.environ,
        "PE_MIGRATION_DATABASE_URL": migration_url,
        "PE_BOOTSTRAP_PLATFORM_ADMIN_EMAIL": PLATFORM_EMAIL,
        "PE_BOOTSTRAP_PLATFORM_ADMIN_PASSWORD": PASSWORD_PLATFORM,
        "PE_MFA_ENCRYPTION_KEY": MFA_KEY,
    }

    result = subprocess.run(
        [sys.executable, bootstrap_script],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert "Platform administrator initialized" in result.stdout
    assert PLATFORM_EMAIL in result.stdout

    # 2. Platform Admin Log In & Enroll TOTP MFA
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as platform_client:
        login_res = await platform_client.post(
            "/api/v1/auth/login",
            json={"email": PLATFORM_EMAIL, "password": PASSWORD_PLATFORM},
        )
        assert login_res.status_code == 200

        enroll_res = await platform_client.post("/api/v1/auth/mfa/totp/enroll")
        assert enroll_res.status_code == 201
        cred_id = enroll_res.json()["credential_id"]
        secret = enroll_res.json()["secret"]

        confirm_res = await platform_client.post(
            "/api/v1/auth/mfa/totp/confirm",
            json={"credential_id": cred_id, "code": totp_code(secret, clock())},
        )
        assert confirm_res.status_code == 200
        assert confirm_res.json()["status"] == "verified"

        session_res = await platform_client.get("/api/v1/auth/session")
        assert session_res.status_code == 200
        assert session_res.json()["email"] == PLATFORM_EMAIL
        assert session_res.json()["mfa_recent"] is True

        # 3. Platform Admin Provisions Organization A
        create_org_a_res = await platform_client.post(
            "/api/v1/platform/organizations",
            headers={"Idempotency-Key": "e2e-open-org-alpha-001"},
            json={
                "slug": "agency-alpha",
                "display_name": "北京阿尔法知识产权事务所",
                "admin_email": ADMIN_A_EMAIL,
                "plan_key": "standard_plan",
                "monthly_case_allowance": 50,
                "current_period_start": clock().isoformat(),
                "current_period_end": (clock() + timedelta(days=30)).isoformat(),
            },
        )
        assert create_org_a_res.status_code == 201
        org_a_data = create_org_a_res.json()
        org_a_id = org_a_data["organization"]["id"]
        invitation_token_a = org_a_data["invitation_token"]
        assert org_a_data["organization"]["slug"] == "agency-alpha"

        # 4. Platform Admin Provisions Organization B
        create_org_b_res = await platform_client.post(
            "/api/v1/platform/organizations",
            headers={"Idempotency-Key": "e2e-open-org-beta-002"},
            json={
                "slug": "agency-beta",
                "display_name": "上海贝塔知识产权事务所",
                "admin_email": ADMIN_B_EMAIL,
                "plan_key": "standard_plan",
                "monthly_case_allowance": 30,
                "current_period_start": clock().isoformat(),
                "current_period_end": (clock() + timedelta(days=30)).isoformat(),
            },
        )
        assert create_org_b_res.status_code == 201
        org_b_data = create_org_b_res.json()
        org_b_id = org_b_data["organization"]["id"]
        invitation_token_b = org_b_data["invitation_token"]

    # 5. Admin A Inspects and Accepts Invitation
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as admin_a_client:
        inspect_res = await admin_a_client.post(
            "/api/v1/invitations/inspect",
            json={"token": invitation_token_a},
        )
        assert inspect_res.status_code == 200
        assert inspect_res.json()["organization"]["id"] == org_a_id
        assert inspect_res.json()["email"] == ADMIN_A_EMAIL
        assert inspect_res.json()["role"] == "organization_admin"

        accept_res = await admin_a_client.post(
            "/api/v1/invitations/accept",
            json={
                "token": invitation_token_a,
                "display_name": "阿尔法主管理员",
                "password": PASSWORD_ADMIN_A,
            },
        )
        assert accept_res.status_code == 201
        membership_a = accept_res.json()["membership"]
        assert membership_a["role"] == "organization_admin"

        # Log in as Admin A and setup TOTP
        await admin_a_client.post(
            "/api/v1/auth/login",
            json={"email": ADMIN_A_EMAIL, "password": PASSWORD_ADMIN_A},
        )
        mfa_enroll = await admin_a_client.post("/api/v1/auth/mfa/totp/enroll")
        await admin_a_client.post(
            "/api/v1/auth/mfa/totp/confirm",
            json={
                "credential_id": mfa_enroll.json()["credential_id"],
                "code": totp_code(mfa_enroll.json()["secret"], clock()),
            },
        )

        # 6. Admin A Invites Patent Agent A
        invite_agent_res = await admin_a_client.post(
            f"/api/v1/organizations/{org_a_id}/invitations",
            json={"email": AGENT_A_EMAIL, "role": "patent_agent"},
        )
        assert invite_agent_res.status_code == 201
        agent_a_token = invite_agent_res.json()["invitation_token"]

    # 7. Agent A Accepts Invitation
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as agent_a_client:
        accept_agent_res = await agent_a_client.post(
            "/api/v1/invitations/accept",
            json={
                "token": agent_a_token,
                "display_name": "张三代理师",
                "password": PASSWORD_AGENT_A,
            },
        )
        assert accept_agent_res.status_code == 201

    # 8. Admin B Accepts Organization B Invitation
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as admin_b_client:
        accept_b = await admin_b_client.post(
            "/api/v1/invitations/accept",
            json={
                "token": invitation_token_b,
                "display_name": "贝塔主管理员",
                "password": PASSWORD_ADMIN_B,
            },
        )
        assert accept_b.status_code == 201

        await admin_b_client.post(
            "/api/v1/auth/login",
            json={"email": ADMIN_B_EMAIL, "password": PASSWORD_ADMIN_B},
        )
        mfa_enroll_b = await admin_b_client.post("/api/v1/auth/mfa/totp/enroll")
        await admin_b_client.post(
            "/api/v1/auth/mfa/totp/confirm",
            json={
                "credential_id": mfa_enroll_b.json()["credential_id"],
                "code": totp_code(mfa_enroll_b.json()["secret"], clock()),
            },
        )

        # 9. Cross-Tenant Security Invariant: Org B Admin attempts to access Org A -> Safe 404
        cross_read = await admin_b_client.get(
            f"/api/v1/organizations/{org_a_id}/members"
        )
        assert cross_read.status_code == 404

        cross_invite = await admin_b_client.post(
            f"/api/v1/organizations/{org_a_id}/invitations",
            json={"email": "attacker@fake.com", "role": "patent_agent"},
        )
        assert cross_invite.status_code == 404

    # 10. Platform Admin Suspends Organization A -> Reject future sessions
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as platform_client:
        await platform_client.post(
            "/api/v1/auth/login",
            json={"email": PLATFORM_EMAIL, "password": PASSWORD_PLATFORM},
        )
        # Verify MFA challenge
        challenge_res = await platform_client.post(
            "/api/v1/auth/mfa/challenge",
            json={"code": totp_code(secret, clock())},
        )
        assert challenge_res.status_code == 200

        suspend_res = await platform_client.post(
            f"/api/v1/platform/organizations/{org_a_id}/suspend",
            headers={"Idempotency-Key": "suspend-alpha-org-001"},
        )
        assert suspend_res.status_code == 200
        assert suspend_res.json()["organization"]["effective_status"] == "suspended"

    # 11. Admin A attempts access after suspension -> safe 404
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as admin_a_client:
        await admin_a_client.post(
            "/api/v1/auth/login",
            json={"email": ADMIN_A_EMAIL, "password": PASSWORD_ADMIN_A},
        )
        # Access members of suspended org -> returns 404
        post_suspend_access = await admin_a_client.get(
            f"/api/v1/organizations/{org_a_id}/members"
        )
        assert post_suspend_access.status_code == 404
