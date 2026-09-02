import asyncio
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import psycopg
import pytest
from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from patent_evidence_api.core.database import (
    create_application_session_factory,
    create_engine,
    create_platform_session_factory,
    platform_transaction,
    tenant_transaction,
)
from patent_evidence_api.core.organization_lifecycle import OrganizationLifecycle
from patent_evidence_api.main import create_app
from patent_evidence_api.organization.audit import OrganizationAuditWriter
from patent_evidence_api.organization.invitations import InvitationService
from patent_evidence_api.platform.organizations import OrganizationDirectory
from test_support import api_settings, login_with_totp, postgres_url

ORG_A = UUID("50000000-0000-4000-8000-000000000001")
ORG_B = UUID("50000000-0000-4000-8000-000000000002")
ADMIN_A = UUID("51000000-0000-4000-8000-000000000001")
ADMIN_B = UUID("51000000-0000-4000-8000-000000000002")
AGENT_A = UUID("51000000-0000-4000-8000-000000000003")
REVIEWER_A = UUID("51000000-0000-4000-8000-000000000004")
OUTSIDER = UUID("51000000-0000-4000-8000-000000000005")
MEMBER_ADMIN_A = UUID("52000000-0000-4000-8000-000000000001")
MEMBER_ADMIN_B = UUID("52000000-0000-4000-8000-000000000002")
MEMBER_AGENT_A = UUID("52000000-0000-4000-8000-000000000003")
MEMBER_REVIEWER_A = UUID("52000000-0000-4000-8000-000000000004")
PASSWORD = "Correct horse battery staple 42"
MFA_KEY = Fernet.generate_key().decode()


class Clock:
    def __init__(self) -> None:
        self.value = datetime.now(UTC).replace(microsecond=0)

    def __call__(self) -> datetime:
        return self.value


def _url(variable: str, role: str) -> str:
    return postgres_url(variable, role)


def _settings():
    return api_settings(mfa_encryption_key=MFA_KEY)


async def _wait_for_app_lock_waiters(migration_url: str, minimum: int) -> list[str]:
    with psycopg.connect(migration_url, autocommit=True) as observer:
        for _ in range(100):
            lock_types = [
                row[0]
                for row in observer.execute(
                    """SELECT lock.locktype FROM pg_locks lock
                    JOIN pg_stat_activity activity ON activity.pid=lock.pid
                    WHERE NOT lock.granted
                      AND activity.datname=current_database()
                      AND activity.usename='patent_evidence_app'"""
                ).fetchall()
            ]
            if len(lock_types) >= minimum:
                return lock_types
            await asyncio.sleep(0.05)
    raise AssertionError(f"expected {minimum} application lock waiters")


@pytest.fixture(autouse=True)
def seeded_organizations() -> Iterator[None]:
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
            VALUES (%s,'admin-a@example.test','Admin A','active',%s,now(),now()),
                   (%s,'admin-b@example.test','Admin B','active',%s,now(),now()),
                   (%s,'agent-a@example.test','Agent A','active',%s,now(),now()),
                   (%s,'reviewer-a@example.test','Reviewer A','active',%s,now(),now()),
                   (%s,'outsider@example.test','Outsider','active',%s,now(),now())""",
            (
                ADMIN_A,
                password_hash,
                ADMIN_B,
                password_hash,
                AGENT_A,
                password_hash,
                REVIEWER_A,
                password_hash,
                OUTSIDER,
                password_hash,
            ),
        )
        connection.execute(
            """INSERT INTO organizations
            (id,slug,display_name,status,created_by,created_at,updated_at)
            VALUES (%s,'organization-a','Organization A','active',%s,now(),now()),
                   (%s,'organization-b','Organization B','active',%s,now(),now())""",
            (ORG_A, ADMIN_A, ORG_B, ADMIN_B),
        )
        connection.execute(
            """INSERT INTO organization_memberships
            (id,organization_id,global_identity_id,role,status,created_at,updated_at)
            VALUES (%s,%s,%s,
                    'organization_admin','active',now(),now()),
                   (%s,%s,%s,
                    'organization_admin','active',now(),now()),
                   (%s,%s,%s,
                    'patent_agent','active',now(),now()),
                   (%s,%s,%s,
                    'reviewer','active',now(),now())""",
            (
                MEMBER_ADMIN_A,
                ORG_A,
                ADMIN_A,
                MEMBER_ADMIN_B,
                ORG_B,
                ADMIN_B,
                MEMBER_AGENT_A,
                ORG_A,
                AGENT_A,
                MEMBER_REVIEWER_A,
                ORG_A,
                REVIEWER_A,
            ),
        )
        connection.execute(
            """INSERT INTO organization_plan_quotas
            (organization_id,plan_key,monthly_case_allowance,current_period_start,
             current_period_end,status,created_at,updated_at)
            VALUES (%s,'test',10,now(),now()+interval '1 month','active',now(),now()),
                   (%s,'test',10,now(),now()+interval '1 month','active',now(),now())""",
            (ORG_A, ORG_B),
        )
    yield


@pytest.mark.asyncio
async def test_organization_admin_creates_secret_safe_fixed_role_invitation() -> None:
    clock = Clock()
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as client:
        await login_with_totp(
            client,
            clock=clock,
            email="admin-a@example.test",
            password=PASSWORD,
        )
        response = await client.post(
            f"/api/v1/organizations/{ORG_A}/invitations",
            json={"email": "new-agent@example.test", "role": "patent_agent"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["invitation"]["organization_id"] == str(ORG_A)
    assert body["invitation"]["email"] == "new-agent@example.test"
    assert body["invitation"]["role"] == "patent_agent"
    assert body["invitation_token"]

    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    with psycopg.connect(migration_url) as connection:
        invitation = connection.execute(
            """SELECT token_hash,status,expires_at-created_at
            FROM organization_invitations WHERE id=%s""",
            (body["invitation"]["id"],),
        ).fetchone()
        assert invitation == (
            hashlib.sha256(body["invitation_token"].encode()).hexdigest(),
            "pending",
            timedelta(hours=72),
        )
        audits = connection.execute(
            """SELECT actor_identity_id,action,target_type,target_id,result,safe_summary
            FROM audit_events ORDER BY created_at"""
        ).fetchall()
        assert audits == [
            (
                ADMIN_A,
                "organization.invitation.create",
                "organization_invitation",
                UUID(body["invitation"]["id"]),
                "allowed",
                "Created organization invitation",
            )
        ]
        assert body["invitation_token"] not in audits[0][-1]
        assert "new-agent@example.test" not in audits[0][-1]


@pytest.mark.asyncio
async def test_organization_admin_inspects_resends_and_revokes_invitation() -> None:
    clock = Clock()
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as client:
        await login_with_totp(
            client,
            clock=clock,
            email="admin-a@example.test",
            password=PASSWORD,
        )
        created = await client.post(
            f"/api/v1/organizations/{ORG_A}/invitations",
            json={"email": "new-reviewer@example.test", "role": "reviewer"},
        )
        invitation_id = created.json()["invitation"]["id"]
        original_token = created.json()["invitation_token"]

        detail = await client.get(
            f"/api/v1/organizations/{ORG_A}/invitations/{invitation_id}"
        )
        resent = await client.post(
            f"/api/v1/organizations/{ORG_A}/invitations/{invitation_id}/resend"
        )
        replacement_id = resent.json()["invitation"]["id"]
        replacement_token = resent.json()["invitation_token"]
        old_detail = await client.get(
            f"/api/v1/organizations/{ORG_A}/invitations/{invitation_id}"
        )
        revoked = await client.post(
            f"/api/v1/organizations/{ORG_A}/invitations/{replacement_id}/revoke"
        )

    assert detail.status_code == 200
    assert detail.json()["id"] == invitation_id
    assert "token_hash" not in detail.json()
    assert resent.status_code == 201
    assert replacement_id != invitation_id
    assert replacement_token != original_token
    assert old_detail.status_code == 200
    assert old_detail.json()["status"] == "revoked"
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    with psycopg.connect(migration_url) as connection:
        rows = connection.execute(
            """SELECT id,status,token_hash FROM organization_invitations
            ORDER BY created_at,id"""
        ).fetchall()
        assert set(rows) == {
            (
                UUID(invitation_id),
                "revoked",
                hashlib.sha256(original_token.encode()).hexdigest(),
            ),
            (
                UUID(replacement_id),
                "revoked",
                hashlib.sha256(replacement_token.encode()).hexdigest(),
            ),
        }
        actions = connection.execute(
            "SELECT action,result FROM audit_events ORDER BY created_at,id"
        ).fetchall()
        assert sorted(actions) == sorted(
            [
                ("organization.invitation.create", "allowed"),
                ("organization.invitation.resend", "allowed"),
                ("organization.invitation.revoke", "allowed"),
            ]
        )


@pytest.mark.asyncio
async def test_invitation_token_inspection_and_atomic_single_use_acceptance() -> None:
    clock = Clock()
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as client:
        await login_with_totp(
            client,
            clock=clock,
            email="admin-a@example.test",
            password=PASSWORD,
        )
        created = await client.post(
            f"/api/v1/organizations/{ORG_A}/invitations",
            json={"email": "new-member@example.test", "role": "patent_agent"},
        )
        token = created.json()["invitation_token"]
        await client.post("/api/v1/auth/logout")

        inspected = await client.post(
            "/api/v1/invitations/inspect", json={"token": token}
        )
        first, second = await asyncio.gather(
            client.post(
                "/api/v1/invitations/accept",
                json={
                    "token": token,
                    "display_name": "New Member",
                    "password": "New member horse battery staple 42",
                },
            ),
            client.post(
                "/api/v1/invitations/accept",
                json={
                    "token": token,
                    "display_name": "New Member",
                    "password": "New member horse battery staple 42",
                },
            ),
        )
        reused = await client.post(
            "/api/v1/invitations/accept",
            json={
                "token": token,
                "display_name": "New Member",
                "password": "New member horse battery staple 42",
            },
        )

    assert inspected.status_code == 200
    assert token not in str(inspected.request.url)
    assert token not in str(first.request.url)
    assert token not in str(second.request.url)
    assert inspected.json()["organization"] == {
        "id": str(ORG_A),
        "display_name": "Organization A",
    }
    assert inspected.json()["email"] == "new-member@example.test"
    assert inspected.json()["role"] == "patent_agent"
    assert sorted([first.status_code, second.status_code]) == [201, 409]
    accepted = first if first.status_code == 201 else second
    assert accepted.json()["membership"]["role"] == "patent_agent"
    assert accepted.json()["membership"]["status"] == "active"
    assert reused.status_code == 409
    assert reused.json() == {"detail": "invitation_not_pending"}

    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    with psycopg.connect(migration_url) as connection:
        identity = connection.execute(
            """SELECT id,password_hash FROM global_identities
            WHERE email_normalized='new-member@example.test'"""
        ).fetchone()
        assert identity is not None
        assert identity[1].startswith("$argon2id$")
        assert "New member horse" not in identity[1]
        memberships = connection.execute(
            """SELECT role,status FROM organization_memberships
            WHERE organization_id=%s AND global_identity_id=%s""",
            (ORG_A, identity[0]),
        ).fetchall()
        assert memberships == [("patent_agent", "active")]
        assert connection.execute(
            """SELECT status,count(*) FROM organization_invitations
            WHERE token_hash=%s GROUP BY status""",
            (hashlib.sha256(token.encode()).hexdigest(),),
        ).fetchone() == ("accepted", 1)


@pytest.mark.asyncio
async def test_existing_identity_accepts_invitation_without_new_credentials() -> None:
    clock = Clock()
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as client:
        await login_with_totp(
            client,
            clock=clock,
            email="admin-a@example.test",
            password=PASSWORD,
        )
        created = await client.post(
            f"/api/v1/organizations/{ORG_A}/invitations",
            json={"email": "outsider@example.test", "role": "reviewer"},
        )
        token = created.json()["invitation_token"]
        await client.post("/api/v1/auth/logout")
        accepted = await client.post(
            "/api/v1/invitations/accept", json={"token": token}
        )

    assert accepted.status_code == 201
    assert accepted.json()["membership"]["identity_id"] == str(OUTSIDER)
    assert accepted.json()["membership"]["role"] == "reviewer"


@pytest.mark.asyncio
async def test_expired_or_unknown_invitation_cannot_be_accepted() -> None:
    clock = Clock()
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as client:
        await login_with_totp(
            client,
            clock=clock,
            email="admin-a@example.test",
            password=PASSWORD,
        )
        created = await client.post(
            f"/api/v1/organizations/{ORG_A}/invitations",
            json={"email": "expired@example.test", "role": "reviewer"},
        )
        token = created.json()["invitation_token"]
        await client.post("/api/v1/auth/logout")
        clock.value += timedelta(hours=73)
        inspected = await client.post(
            "/api/v1/invitations/inspect", json={"token": token}
        )
        expired = await client.post(
            "/api/v1/invitations/accept",
            json={
                "token": token,
                "display_name": "Expired",
                "password": "Expired horse battery staple 42",
            },
        )
        unknown = await client.post(
            "/api/v1/invitations/inspect", json={"token": "not-a-real-token"}
        )

    assert inspected.status_code == 200
    assert inspected.json()["status"] == "expired"
    assert expired.status_code == 410
    assert expired.json() == {"detail": "invitation_expired"}
    assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_organization_admin_lists_and_manages_member_lifecycle() -> None:
    clock = Clock()
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as client:
        await login_with_totp(
            client,
            clock=clock,
            email="admin-a@example.test",
            password=PASSWORD,
        )
        listed = await client.get(f"/api/v1/organizations/{ORG_A}/members")
        changed = await client.put(
            f"/api/v1/organizations/{ORG_A}/members/{MEMBER_AGENT_A}/role",
            json={"role": "reviewer"},
        )
        suspended = await client.post(
            f"/api/v1/organizations/{ORG_A}/members/{MEMBER_AGENT_A}/suspend"
        )
        reactivated = await client.post(
            f"/api/v1/organizations/{ORG_A}/members/{MEMBER_AGENT_A}/reactivate"
        )
        removed = await client.post(
            f"/api/v1/organizations/{ORG_A}/members/{MEMBER_AGENT_A}/remove"
        )

    assert listed.status_code == 200
    assert {item["id"] for item in listed.json()["items"]} == {
        str(MEMBER_ADMIN_A),
        str(MEMBER_AGENT_A),
        str(MEMBER_REVIEWER_A),
    }
    assert all("password_hash" not in item for item in listed.json()["items"])
    assert changed.status_code == 200
    assert changed.json()["role"] == "reviewer"
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"
    assert reactivated.status_code == 200
    assert reactivated.json()["status"] == "active"
    assert removed.status_code == 200
    assert removed.json()["status"] == "removed"


@pytest.mark.parametrize("email", ["agent-a@example.test", "reviewer-a@example.test"])
@pytest.mark.asyncio
async def test_non_admin_fixed_roles_cannot_administer_members(email: str) -> None:
    clock = Clock()
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as client:
        await login_with_totp(client, clock=clock, email=email, password=PASSWORD)
        listed = await client.get(f"/api/v1/organizations/{ORG_A}/members")
        responses = [
            listed,
            await client.post(
                f"/api/v1/organizations/{ORG_A}/invitations",
                json={"email": "forbidden@example.test", "role": "reviewer"},
            ),
            await client.get(
                f"/api/v1/organizations/{ORG_A}/invitations/"
                "53000000-0000-4000-8000-000000000099"
            ),
            await client.post(
                f"/api/v1/organizations/{ORG_A}/invitations/"
                "53000000-0000-4000-8000-000000000099/revoke"
            ),
            await client.post(
                f"/api/v1/organizations/{ORG_A}/invitations/"
                "53000000-0000-4000-8000-000000000099/resend"
            ),
            await client.put(
                f"/api/v1/organizations/{ORG_A}/members/{MEMBER_REVIEWER_A}/role",
                json={"role": "patent_agent"},
            ),
            *[
                await client.post(
                    f"/api/v1/organizations/{ORG_A}/members/"
                    f"{MEMBER_REVIEWER_A}/{transition}"
                )
                for transition in ("suspend", "reactivate", "remove")
            ],
        ]
    assert all(response.status_code == 403 for response in responses)


@pytest.mark.asyncio
async def test_cross_tenant_members_and_invitations_are_safe_not_found_both_ways() -> (
    None
):
    clock = Clock()
    app = create_app(settings=_settings(), clock=clock)
    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    invitation_a = UUID("53000000-0000-4000-8000-000000000001")
    invitation_b = UUID("53000000-0000-4000-8000-000000000002")
    with psycopg.connect(migration_url, autocommit=True) as connection:
        connection.execute(
            """INSERT INTO organization_invitations
            (id,organization_id,email_normalized,role,token_hash,status,invited_by,
             expires_at,created_at,updated_at)
            VALUES (%s,%s,'a-invite@example.test','reviewer','a-token','pending',%s,
                    now()+interval '72 hours',now(),now()),
                   (%s,%s,'b-invite@example.test','reviewer','b-token','pending',%s,
                    now()+interval '72 hours',now(),now())""",
            (invitation_a, ORG_A, ADMIN_A, invitation_b, ORG_B, ADMIN_B),
        )

    async with (
        AsyncClient(
            transport=ASGITransport(app=app), base_url="https://admin-a"
        ) as admin_a,
        AsyncClient(
            transport=ASGITransport(app=app), base_url="https://admin-b"
        ) as admin_b,
    ):
        await login_with_totp(
            admin_a,
            clock=clock,
            email="admin-a@example.test",
            password=PASSWORD,
        )
        await login_with_totp(
            admin_b,
            clock=clock,
            email="admin-b@example.test",
            password=PASSWORD,
        )

        async def matrix(
            client: AsyncClient,
            *,
            own_org: UUID,
            foreign_org: UUID,
            foreign_member: UUID,
            foreign_invitation: UUID,
        ) -> list:
            responses = [
                await client.get(f"/api/v1/organizations/{foreign_org}/members"),
                await client.post(
                    f"/api/v1/organizations/{foreign_org}/invitations",
                    json={"email": "cross@example.test", "role": "reviewer"},
                ),
                await client.get(
                    f"/api/v1/organizations/{foreign_org}/invitations/"
                    f"{foreign_invitation}"
                ),
            ]
            for invitation_org in (foreign_org, own_org):
                for operation in ("revoke", "resend"):
                    responses.append(
                        await client.post(
                            f"/api/v1/organizations/{invitation_org}/invitations/"
                            f"{foreign_invitation}/{operation}"
                        )
                    )
            for member_org in (foreign_org, own_org):
                responses.append(
                    await client.put(
                        f"/api/v1/organizations/{member_org}/members/"
                        f"{foreign_member}/role",
                        json={"role": "reviewer"},
                    )
                )
                for operation in ("suspend", "reactivate", "remove"):
                    responses.append(
                        await client.post(
                            f"/api/v1/organizations/{member_org}/members/"
                            f"{foreign_member}/{operation}"
                        )
                    )
            responses.append(
                await client.get(
                    f"/api/v1/organizations/{own_org}/invitations/{foreign_invitation}"
                )
            )
            return responses

        responses = await matrix(
            admin_a,
            own_org=ORG_A,
            foreign_org=ORG_B,
            foreign_member=MEMBER_ADMIN_B,
            foreign_invitation=invitation_b,
        )
        responses += await matrix(
            admin_b,
            own_org=ORG_B,
            foreign_org=ORG_A,
            foreign_member=MEMBER_ADMIN_A,
            foreign_invitation=invitation_a,
        )

    assert all(response.status_code == 404 for response in responses)


@pytest.mark.asyncio
async def test_last_active_admin_cannot_be_demoted_suspended_or_removed() -> None:
    clock = Clock()
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as client:
        await login_with_totp(
            client,
            clock=clock,
            email="admin-a@example.test",
            password=PASSWORD,
        )
        demoted = await client.put(
            f"/api/v1/organizations/{ORG_A}/members/{MEMBER_ADMIN_A}/role",
            json={"role": "reviewer"},
        )
        suspended = await client.post(
            f"/api/v1/organizations/{ORG_A}/members/{MEMBER_ADMIN_A}/suspend"
        )
        removed = await client.post(
            f"/api/v1/organizations/{ORG_A}/members/{MEMBER_ADMIN_A}/remove"
        )

    for response in (demoted, suspended, removed):
        assert response.status_code == 409
        assert response.json() == {"detail": "last_active_organization_admin"}


@pytest.mark.asyncio
async def test_last_active_admin_is_protected_under_concurrent_mutations() -> None:
    clock = Clock()
    app = create_app(settings=_settings(), clock=clock)
    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    second_admin_membership = UUID("52000000-0000-4000-8000-000000000005")
    with psycopg.connect(migration_url, autocommit=True) as connection:
        connection.execute(
            """INSERT INTO organization_memberships
            (id,organization_id,global_identity_id,role,status,created_at,updated_at)
            VALUES (%s,%s,%s,'organization_admin','active',now(),now())""",
            (second_admin_membership, ORG_A, OUTSIDER),
        )

    async with (
        AsyncClient(
            transport=ASGITransport(app=app), base_url="https://admin-a"
        ) as admin_a,
        AsyncClient(
            transport=ASGITransport(app=app), base_url="https://admin-two"
        ) as admin_two,
    ):
        await login_with_totp(
            admin_a,
            clock=clock,
            email="admin-a@example.test",
            password=PASSWORD,
        )
        await login_with_totp(
            admin_two,
            clock=clock,
            email="outsider@example.test",
            password=PASSWORD,
        )
        results = await asyncio.gather(
            admin_a.post(
                f"/api/v1/organizations/{ORG_A}/members/{second_admin_membership}/suspend"
            ),
            admin_two.post(
                f"/api/v1/organizations/{ORG_A}/members/{MEMBER_ADMIN_A}/suspend"
            ),
        )

    assert sum(response.status_code == 200 for response in results) == 1
    rejected = next(response for response in results if response.status_code != 200)
    assert rejected.status_code in {403, 409}
    assert rejected.json()["detail"] in {
        "forbidden",
        "last_active_organization_admin",
    }
    with psycopg.connect(migration_url) as connection:
        assert connection.execute(
            """SELECT count(*) FROM organization_memberships
            WHERE organization_id=%s AND role='organization_admin' AND status='active'""",
            (ORG_A,),
        ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_rejected_organization_mutations_are_actor_bound_and_secret_safe() -> (
    None
):
    clock = Clock()
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as client:
        await login_with_totp(
            client,
            clock=clock,
            email="admin-a@example.test",
            password=PASSWORD,
        )
        invalid_role = await client.post(
            f"/api/v1/organizations/{ORG_A}/invitations",
            json={"email": "secret@example.test", "role": "platform_admin"},
        )
        malformed_organization = await client.post(
            "/api/v1/organizations/not-a-uuid/invitations",
            json={"email": "secret@example.test", "role": "reviewer"},
        )
        invalid_target = await client.post(
            f"/api/v1/organizations/{ORG_A}/members/not-a-uuid/suspend"
        )
        invalid_member_role = await client.put(
            f"/api/v1/organizations/{ORG_A}/members/{MEMBER_REVIEWER_A}/role",
            json={"role": "platform_admin"},
        )
        created = await client.post(
            f"/api/v1/organizations/{ORG_A}/invitations",
            json={"email": "accept-audit@example.test", "role": "reviewer"},
        )
        token = created.json()["invitation_token"]
        await client.post("/api/v1/auth/logout")
        await login_with_totp(
            client,
            clock=clock,
            email="agent-a@example.test",
            password=PASSWORD,
        )
        non_admin = await client.put(
            f"/api/v1/organizations/{ORG_A}/members/{MEMBER_REVIEWER_A}/role",
            json={"role": "patent_agent"},
        )
        await client.post("/api/v1/auth/logout")
        missing_credentials = await client.post(
            "/api/v1/invitations/accept", json={"token": token}
        )
        weak_password = await client.post(
            "/api/v1/invitations/accept",
            json={
                "token": token,
                "display_name": "Accept Audit",
                "password": "short",
            },
        )

    assert invalid_role.status_code == 422
    assert invalid_role.json() == {"detail": "invalid_organization_mutation_request"}
    assert malformed_organization.status_code == 404
    assert malformed_organization.json() == {"detail": "organization_not_found"}
    assert invalid_target.status_code == 422
    assert invalid_target.json() == {"detail": "invalid_membership_id"}
    assert invalid_member_role.status_code == 422
    assert invalid_member_role.json() == {
        "detail": "invalid_organization_mutation_request"
    }
    assert non_admin.status_code == 403
    assert missing_credentials.status_code == 422
    assert weak_password.status_code == 422

    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    with psycopg.connect(migration_url) as connection:
        denied = connection.execute(
            """SELECT actor_identity_id,action,target_id,result,safe_summary
            FROM audit_events WHERE result='denied' ORDER BY action,target_id NULLS FIRST"""
        ).fetchall()
        assert (
            ADMIN_A,
            "organization.invitation.create",
            None,
            "denied",
            "Organization mutation rejected",
        ) in denied
        assert (
            ADMIN_A,
            "organization.member.suspend",
            None,
            "denied",
            "Organization mutation rejected",
        ) in denied
        assert (
            AGENT_A,
            "organization.member.role_change",
            MEMBER_REVIEWER_A,
            "denied",
            "Organization mutation rejected",
        ) in denied
        assert (
            sum(
                row[0] is None
                and row[1] == "organization.invitation.accept"
                and row[3] == "denied"
                for row in denied
            )
            == 2
        )
        summaries = [row[4] for row in denied]
        assert all("secret@example.test" not in summary for summary in summaries)
        assert all(token not in summary for summary in summaries)


@pytest.mark.asyncio
async def test_concurrent_same_email_invitation_creation_has_one_winner() -> None:
    clock = Clock()
    app = create_app(settings=_settings(), clock=clock)
    payload = {"email": "race@example.test", "role": "patent_agent"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as client:
        await login_with_totp(
            client,
            clock=clock,
            email="admin-a@example.test",
            password=PASSWORD,
        )
        responses = await asyncio.gather(
            client.post(f"/api/v1/organizations/{ORG_A}/invitations", json=payload),
            client.post(f"/api/v1/organizations/{ORG_A}/invitations", json=payload),
        )

    assert sorted(response.status_code for response in responses) == [201, 409]
    rejected = next(response for response in responses if response.status_code == 409)
    assert rejected.json() == {"detail": "invitation_already_pending"}
    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    with psycopg.connect(migration_url) as connection:
        assert connection.execute(
            """SELECT count(*) FROM organization_invitations
            WHERE organization_id=%s AND email_normalized='race@example.test'
              AND status='pending'""",
            (ORG_A,),
        ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_concurrent_resend_and_create_share_one_lock_order() -> None:
    clock = Clock()
    settings = _settings()
    app = create_app(settings=settings, clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as client:
        await login_with_totp(
            client,
            clock=clock,
            email="admin-a@example.test",
            password=PASSWORD,
        )
        original = await client.post(
            f"/api/v1/organizations/{ORG_A}/invitations",
            json={"email": "lock-order@example.test", "role": "reviewer"},
        )
    invitation_id = UUID(original.json()["invitation"]["id"])
    clock.value += timedelta(hours=73)
    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    engine = create_engine(settings.database_url)
    sessions = create_application_session_factory(engine)
    invitations = InvitationService(clock)
    tasks: list[asyncio.Task] = []

    async def resend():
        async with tenant_transaction(
            sessions, ORG_A, actor_identity_id=ADMIN_A
        ) as session:
            return await invitations.resend(
                session,
                organization_id=ORG_A,
                invitation_id=invitation_id,
                actor_identity_id=ADMIN_A,
            )

    async def create():
        async with tenant_transaction(
            sessions, ORG_A, actor_identity_id=ADMIN_A
        ) as session:
            return await invitations.create(
                session,
                organization_id=ORG_A,
                actor_identity_id=ADMIN_A,
                email="lock-order@example.test",
                role="reviewer",
            )

    try:
        with psycopg.connect(migration_url) as blocker:
            blocker.execute(
                "SELECT id FROM organization_invitations WHERE id=%s FOR UPDATE",
                (invitation_id,),
            )
            resend_task = asyncio.create_task(resend())
            tasks.append(resend_task)
            await _wait_for_app_lock_waiters(migration_url, 1)
            create_task = asyncio.create_task(create())
            tasks.append(create_task)
            waiting_locks = await _wait_for_app_lock_waiters(migration_url, 2)
            assert "advisory" in waiting_locks
            assert any(lock_type != "advisory" for lock_type in waiting_locks)
            blocker.commit()
            results = await asyncio.wait_for(
                asyncio.gather(resend_task, create_task, return_exceptions=True),
                timeout=10,
            )
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await engine.dispose()

    assert sum(isinstance(result, tuple) for result in results) == 1
    failures = [result for result in results if isinstance(result, Exception)]
    assert len(failures) == 1
    assert isinstance(failures[0], HTTPException)
    assert failures[0].status_code == 409
    assert failures[0].detail == "invitation_already_pending"
    with psycopg.connect(migration_url) as connection:
        assert connection.execute(
            """SELECT count(*) FROM organization_invitations
            WHERE organization_id=%s AND email_normalized='lock-order@example.test'
              AND status='pending'""",
            (ORG_A,),
        ).fetchone() == (1,)


@pytest.mark.parametrize("lifecycle_change", ["suspend", "expire"])
@pytest.mark.asyncio
async def test_platform_lifecycle_serializes_acceptance_and_admin_recheck(
    lifecycle_change: str,
) -> None:
    clock = Clock()
    settings = _settings()
    app = create_app(settings=settings, clock=clock)
    platform_engine = create_engine(settings.platform_database_url)
    platform_sessions = create_platform_session_factory(platform_engine)
    directory = OrganizationDirectory(clock, OrganizationLifecycle())
    tasks: list[asyncio.Task] = []
    async with (
        AsyncClient(
            transport=ASGITransport(app=app), base_url="https://admin"
        ) as admin_client,
        AsyncClient(
            transport=ASGITransport(app=app), base_url="https://public"
        ) as public_client,
    ):
        await login_with_totp(
            admin_client,
            clock=clock,
            email="admin-a@example.test",
            password=PASSWORD,
        )
        invitation = await admin_client.post(
            f"/api/v1/organizations/{ORG_A}/invitations",
            json={"email": "outsider@example.test", "role": "reviewer"},
        )
        token = invitation.json()["invitation_token"]
        migration_url = _url(
            "PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration"
        )
        try:
            async with platform_transaction(platform_sessions) as session:
                if lifecycle_change == "suspend":
                    await directory.set_status(session, ORG_A, "suspended")
                else:
                    await directory.set_expiry(session, ORG_A, clock.value)
                admin_task = asyncio.create_task(
                    admin_client.post(
                        f"/api/v1/organizations/{ORG_A}/invitations",
                        json={"email": "blocked@example.test", "role": "reviewer"},
                    )
                )
                tasks.append(admin_task)
                accept_task = asyncio.create_task(
                    public_client.post(
                        "/api/v1/invitations/accept", json={"token": token}
                    )
                )
                tasks.append(accept_task)
                waiting_locks = await _wait_for_app_lock_waiters(migration_url, 2)
                assert not admin_task.done()
                assert not accept_task.done()
            admin_response, accept_response = await asyncio.gather(
                admin_task, accept_task
            )
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await platform_engine.dispose()

    assert waiting_locks.count("advisory") >= 2
    assert admin_response.status_code == 403
    assert accept_response.status_code == 409
    assert accept_response.json() == {"detail": "organization_unavailable"}
    with psycopg.connect(migration_url) as connection:
        assert connection.execute(
            """SELECT count(*) FROM organization_memberships
            WHERE organization_id=%s AND global_identity_id=%s""",
            (ORG_A, OUTSIDER),
        ).fetchone() == (0,)
        assert connection.execute(
            """SELECT count(*) FROM organization_invitations
            WHERE organization_id=%s AND email_normalized='blocked@example.test'""",
            (ORG_A,),
        ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_acceptance_rolls_back_identity_and_membership_if_audit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    original_append = OrganizationAuditWriter.append

    async def fail_allowed_acceptance(self, session, event):
        if (
            event.action == "organization.invitation.accept"
            and event.result == "allowed"
        ):
            raise RuntimeError("injected acceptance audit failure")
        await original_append(self, session, event)

    monkeypatch.setattr(OrganizationAuditWriter, "append", fail_allowed_acceptance)
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="https://test",
    ) as client:
        await login_with_totp(
            client,
            clock=clock,
            email="admin-a@example.test",
            password=PASSWORD,
        )
        created = await client.post(
            f"/api/v1/organizations/{ORG_A}/invitations",
            json={"email": "rollback@example.test", "role": "reviewer"},
        )
        invitation_id = created.json()["invitation"]["id"]
        token = created.json()["invitation_token"]
        await client.post("/api/v1/auth/logout")
        accepted = await client.post(
            "/api/v1/invitations/accept",
            json={
                "token": token,
                "display_name": "Roll Back",
                "password": "Rollback horse battery staple 42",
            },
        )

    assert accepted.status_code == 500
    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    with psycopg.connect(migration_url) as connection:
        assert connection.execute(
            """SELECT count(*) FROM global_identities
            WHERE email_normalized='rollback@example.test'"""
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT status FROM organization_invitations WHERE id=%s",
            (invitation_id,),
        ).fetchone() == ("pending",)
        assert connection.execute(
            """SELECT count(*) FROM audit_events
            WHERE action='organization.invitation.accept' AND result='failed'
              AND target_id=%s
              AND safe_summary='Organization invitation acceptance failed'""",
            (invitation_id,),
        ).fetchone() == (1,)
