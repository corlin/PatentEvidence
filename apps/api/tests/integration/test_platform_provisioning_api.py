import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from patent_evidence_api.main import create_app
from test_support import api_settings, login_with_totp, postgres_url

PLATFORM = UUID("40000000-0000-4000-8000-000000000001")
NON_PLATFORM = UUID("40000000-0000-4000-8000-000000000002")
PASSWORD = "Correct horse battery staple 42"
MFA_KEY = Fernet.generate_key().decode()
ROOT = Path(__file__).parents[4]


class Clock:
    def __init__(self) -> None:
        self.value = datetime.now(UTC).replace(microsecond=0)

    def __call__(self) -> datetime:
        return self.value


def _url(variable: str, role: str) -> str:
    return postgres_url(variable, role)


def _settings():
    return api_settings(mfa_encryption_key=MFA_KEY)


@pytest.fixture(autouse=True)
def seeded_platform_principals() -> Iterator[None]:
    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    password_hash = PasswordHasher().hash(PASSWORD)
    with psycopg.connect(migration_url, autocommit=True) as connection:
        connection.execute(
            "TRUNCATE organization_provisioning_requests,organization_provisioning_records,"
            "platform_audit_events,audit_events,mfa_recovery_codes,mfa_credentials,"
            "password_reset_tokens,organization_invitations,platform_operator_grants,"
            "user_sessions,organization_plan_quotas,organization_memberships,organizations,"
            "global_identities CASCADE"
        )
        connection.execute(
            """INSERT INTO global_identities
            (id,email_normalized,display_name,status,password_hash,created_at,updated_at)
            VALUES (%s,'platform@example.test','Platform','active',%s,now(),now()),
                   (%s,'user@example.test','User','active',%s,now(),now())""",
            (PLATFORM, password_hash, NON_PLATFORM, password_hash),
        )
        connection.execute(
            """INSERT INTO platform_operator_grants
            (id,global_identity_id,role,status,granted_at)
            VALUES ('41000000-0000-4000-8000-000000000001',%s,
                    'platform_admin','active',now())""",
            (PLATFORM,),
        )
    yield


async def _login_with_mfa(client: AsyncClient, clock: Clock, email: str) -> None:
    await login_with_totp(
        client,
        clock=clock,
        email=email,
        password=PASSWORD,
    )


@pytest.mark.asyncio
async def test_platform_creation_is_atomic_and_idempotent() -> None:
    clock = Clock()
    app = create_app(settings=_settings(), clock=clock)
    payload = {
        "slug": "acme-ip",
        "display_name": "Acme IP",
        "admin_email": "owner@acme.test",
        "plan_key": "starter",
        "monthly_case_allowance": 25,
        "current_period_start": clock().isoformat(),
        "current_period_end": clock().replace(year=clock().year + 1).isoformat(),
        "expires_at": None,
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as client:
        unauthenticated = await client.post(
            "/api/v1/platform/organizations",
            json=payload,
            headers={"Idempotency-Key": "unauthenticated-open-1"},
        )
        assert unauthenticated.status_code == 401
        await _login_with_mfa(client, clock, "platform@example.test")
        created = await client.post(
            "/api/v1/platform/organizations",
            json=payload,
            headers={"Idempotency-Key": "open-acme-2026"},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["organization"]["slug"] == "acme-ip"
        assert body["quota"]["monthly_case_allowance"] == 25
        assert body["invitation"]["role"] == "organization_admin"
        assert body["invitation_token"]

        replay = await client.post(
            "/api/v1/platform/organizations",
            json=payload,
            headers={"Idempotency-Key": "open-acme-2026"},
        )
        assert replay.status_code == 200
        assert replay.json()["organization"]["id"] == body["organization"]["id"]
        assert replay.json()["invitation_token"] is None

        conflict = await client.post(
            "/api/v1/platform/organizations",
            json={**payload, "display_name": "Different"},
            headers={"Idempotency-Key": "open-acme-2026"},
        )
        assert conflict.status_code == 409
        assert conflict.json() == {"detail": "idempotency_conflict"}

        slug_conflict = await client.post(
            "/api/v1/platform/organizations",
            json=payload,
            headers={"Idempotency-Key": "same-slug-new-key"},
        )
        assert slug_conflict.status_code == 409
        assert slug_conflict.json() == {"detail": "organization_slug_conflict"}

        invalid_period = await client.post(
            "/api/v1/platform/organizations",
            json={
                **payload,
                "slug": "invalid-period",
                "current_period_end": payload["current_period_start"],
            },
            headers={"Idempotency-Key": "invalid-period-1"},
        )
        assert invalid_period.status_code == 422
        assert invalid_period.json() == {"detail": "invalid_quota_period"}

        invalid_expiry = await client.post(
            "/api/v1/platform/organizations",
            json={
                **payload,
                "slug": "already-expired",
                "expires_at": clock().isoformat(),
            },
            headers={"Idempotency-Key": "invalid-expiry-1"},
        )
        assert invalid_expiry.status_code == 422
        assert invalid_expiry.json() == {"detail": "invalid_organization_expiry"}

        concurrent_payload = {
            **payload,
            "slug": "concurrent-open",
            "display_name": "Concurrent",
        }
        concurrent_responses = await asyncio.gather(
            client.post(
                "/api/v1/platform/organizations",
                json=concurrent_payload,
                headers={"Idempotency-Key": "concurrent-open-1"},
            ),
            client.post(
                "/api/v1/platform/organizations",
                json=concurrent_payload,
                headers={"Idempotency-Key": "concurrent-open-1"},
            ),
        )
        assert sorted(response.status_code for response in concurrent_responses) == [
            200,
            201,
        ]
        assert (
            len(
                {
                    response.json()["organization"]["id"]
                    for response in concurrent_responses
                }
            )
            == 1
        )
        assert (
            sum(
                response.json()["invitation_token"] is not None
                for response in concurrent_responses
            )
            == 1
        )

        migration_url = _url(
            "PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration"
        )
        with psycopg.connect(migration_url, autocommit=True) as connection:
            connection.execute(
                """INSERT INTO platform_operator_grants
                (id,global_identity_id,role,status,granted_at)
                VALUES ('41000000-0000-4000-8000-000000000099',%s,
                        'platform_admin','active',now())""",
                (NON_PLATFORM,),
            )
        await client.post("/api/v1/auth/logout")
        await _login_with_mfa(client, clock, "user@example.test")
        actor_bound = await client.post(
            "/api/v1/platform/organizations",
            json={**payload, "slug": "actor-bound", "display_name": "Actor Bound"},
            headers={"Idempotency-Key": "open-acme-2026"},
        )
        assert actor_bound.status_code == 201
        assert actor_bound.json()["organization"]["slug"] == "actor-bound"

    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    with psycopg.connect(migration_url) as connection:
        counts = connection.execute(
            """SELECT
            (SELECT count(*) FROM organizations WHERE slug='acme-ip'),
            (SELECT count(*) FROM organization_plan_quotas q JOIN organizations o
               ON o.id=q.organization_id WHERE o.slug='acme-ip'),
            (SELECT count(*) FROM organization_invitations i JOIN organizations o
               ON o.id=i.organization_id WHERE o.slug='acme-ip'),
            (SELECT count(*) FROM organization_provisioning_records r JOIN organizations o
               ON o.id=r.organization_id WHERE o.slug='acme-ip')"""
        ).fetchone()
        assert counts == (1, 1, 1, 1)
        assert connection.execute(
            "SELECT count(*) FROM organizations WHERE slug='concurrent-open'"
        ).fetchone() == (1,)
        summaries = connection.execute(
            "SELECT safe_summary FROM platform_audit_events ORDER BY created_at"
        ).fetchall()
        assert summaries
        assert any("idempotent" in row[0] for row in summaries)
        assert all("owner@acme.test" not in row[0] for row in summaries)
        assert all(body["invitation_token"] not in row[0] for row in summaries)
        assert connection.execute(
            """SELECT count(*) FROM platform_audit_events
            WHERE action='platform.organization.create' AND result='denied'
              AND actor_identity_id IS NULL"""
        ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_platform_lifecycle_and_non_platform_rejection_are_audited() -> None:
    clock = Clock()
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as client:
        await _login_with_mfa(client, clock, "platform@example.test")
        created = await client.post(
            "/api/v1/platform/organizations",
            json={
                "slug": "lifecycle",
                "display_name": "Lifecycle",
                "admin_email": "admin@lifecycle.test",
                "plan_key": "manual",
                "monthly_case_allowance": 7,
                "current_period_start": clock().isoformat(),
                "current_period_end": clock()
                .replace(year=clock().year + 1)
                .isoformat(),
            },
            headers={"Idempotency-Key": "lifecycle-1"},
        )
        organization_id = created.json()["organization"]["id"]
        assert (await client.get("/api/v1/platform/organizations")).status_code == 200
        detail = await client.get(f"/api/v1/platform/organizations/{organization_id}")
        assert detail.status_code == 200

        suspended = await client.post(
            f"/api/v1/platform/organizations/{organization_id}/suspend"
        )
        assert suspended.status_code == 200
        assert suspended.json()["organization"]["status"] == "suspended"
        reactivated = await client.post(
            f"/api/v1/platform/organizations/{organization_id}/reactivate"
        )
        assert reactivated.status_code == 200
        assert reactivated.json()["organization"]["status"] == "active"
        migration_url = _url(
            "PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration"
        )
        with psycopg.connect(migration_url, autocommit=True) as connection:
            connection.execute(
                "UPDATE organization_plan_quotas SET status='suspended' "
                "WHERE organization_id=%s",
                (organization_id,),
            )
        expiry = clock() + timedelta(minutes=1)
        changed = await client.put(
            f"/api/v1/platform/organizations/{organization_id}/expiry",
            json={"expires_at": expiry.isoformat()},
        )
        assert changed.status_code == 200
        assert changed.json()["organization"]["expires_at"].startswith(str(expiry.year))

        clock.value = clock() + timedelta(minutes=2)
        expired = await client.get(f"/api/v1/platform/organizations/{organization_id}")
        assert expired.status_code == 200
        assert expired.json()["organization"]["status"] == "expired"
        assert expired.json()["quota"]["status"] == "expired"
        persisted_expired = await client.put(
            f"/api/v1/platform/organizations/{organization_id}/expiry",
            json={"expires_at": expiry.isoformat()},
        )
        assert persisted_expired.status_code == 200
        assert persisted_expired.json()["organization"]["status"] == "expired"
        rejected_reactivation = await client.post(
            f"/api/v1/platform/organizations/{organization_id}/reactivate"
        )
        assert rejected_reactivation.status_code == 409
        assert rejected_reactivation.json() == {"detail": "organization_expired"}
        cleared = await client.put(
            f"/api/v1/platform/organizations/{organization_id}/expiry",
            json={"expires_at": None},
        )
        assert cleared.status_code == 200
        assert cleared.json()["organization"]["status"] == "active"
        assert cleared.json()["quota"]["status"] == "suspended"

        await client.post("/api/v1/auth/logout")
        await _login_with_mfa(client, clock, "user@example.test")
        denied = await client.post(
            f"/api/v1/platform/organizations/{organization_id}/suspend"
        )
        assert denied.status_code == 403

    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    with psycopg.connect(migration_url) as connection:
        rows = connection.execute(
            """SELECT action,result FROM platform_audit_events
            WHERE action LIKE 'platform.organization.%' ORDER BY created_at"""
        ).fetchall()
        assert ("platform.organization.suspend", "allowed") in rows
        assert ("platform.organization.reactivate", "allowed") in rows
        assert ("platform.organization.set_expiry", "allowed") in rows
        assert ("platform.organization.suspend", "denied") in rows


def test_bootstrap_cli_creates_only_the_first_admin_without_printing_secrets() -> None:
    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    with psycopg.connect(migration_url, autocommit=True) as connection:
        connection.execute(
            "TRUNCATE platform_audit_events,mfa_recovery_codes,mfa_credentials,"
            "platform_operator_grants,user_sessions,global_identities CASCADE"
        )
    secret = "Bootstrap horse battery staple 73"
    environment = {
        **os.environ,
        "PATENT_EVIDENCE_MIGRATION_DATABASE_URL": migration_url,
        "PATENT_EVIDENCE_BOOTSTRAP_PASSWORD": secret,
    }
    command = [
        sys.executable,
        str(ROOT / "scripts" / "bootstrap-platform-admin.py"),
        "first-admin@example.test",
        "First Admin",
    ]
    first = subprocess.run(
        command, check=False, capture_output=True, text=True, env=environment
    )
    assert first.returncode == 0
    assert "No credential material was printed" in first.stdout
    assert "handoff deadline" in first.stdout
    assert secret not in first.stdout + first.stderr
    second = subprocess.run(
        command, check=False, capture_output=True, text=True, env=environment
    )
    assert second.returncode == 1
    assert "already exists" in second.stderr
    assert secret not in second.stdout + second.stderr
    with psycopg.connect(migration_url) as connection:
        row = connection.execute(
            """SELECT i.email_normalized,g.role,g.status,
                      g.bootstrap_mfa_enrollment_expires_at > g.granted_at
            FROM global_identities i JOIN platform_operator_grants g
              ON g.global_identity_id=i.id"""
        ).fetchone()
        assert row == ("first-admin@example.test", "platform_admin", "active", True)
        audit_rows = connection.execute(
            """SELECT result,safe_summary FROM platform_audit_events
            WHERE action='platform.admin.bootstrap' ORDER BY created_at"""
        ).fetchall()
        assert audit_rows == [
            ("allowed", "first platform administrator created"),
            ("denied", "platform administrator bootstrap rejected"),
        ]


def test_application_role_cannot_read_platform_provisioning_records() -> None:
    application_url = _url("PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app")
    with psycopg.connect(application_url) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT * FROM organization_provisioning_records")
        connection.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT * FROM organization_provisioning_requests")


def test_expired_lifecycle_is_derived_and_cannot_be_persisted() -> None:
    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    organization_id = UUID("40000000-0000-4000-8000-000000000099")
    with psycopg.connect(migration_url, autocommit=True) as connection:
        connection.execute(
            """INSERT INTO organizations
            (id,slug,display_name,status,created_by,created_at,updated_at)
            VALUES (%s,'derived-expiry','Derived Expiry','active',%s,now(),now())""",
            (organization_id, PLATFORM),
        )
        connection.execute(
            """INSERT INTO organization_plan_quotas
            (organization_id,plan_key,monthly_case_allowance,current_period_start,
             current_period_end,status,created_at,updated_at)
            VALUES (%s,'manual',1,now(),now() + interval '1 month','active',now(),now())""",
            (organization_id,),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE organizations SET status='expired' WHERE id=%s",
                (organization_id,),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE organization_plan_quotas SET status='expired' "
                "WHERE organization_id=%s",
                (organization_id,),
            )
