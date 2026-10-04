import base64
import hashlib
import hmac
import os
import struct
from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlsplit

import pytest
from httpx import AsyncClient

from patent_evidence_api.core.settings import Settings


def postgres_url(variable: str, expected_role: str) -> str:
    value = os.environ.get(variable)
    if not value:
        pytest.skip(f"{variable} is provided by scripts/test-postgres.sh")
    assert urlsplit(value).username == expected_role
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def async_postgres_url(variable: str, expected_role: str) -> str:
    return postgres_url(variable, expected_role).replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )


def api_settings(
    *,
    mfa_encryption_key: str,
    production: bool = False,
    platform_uses_application_role: bool = False,
) -> Settings:
    application_url = async_postgres_url(
        "PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app"
    )
    platform_url = (
        application_url
        if platform_uses_application_role
        else async_postgres_url(
            "PE_TEST_PLATFORM_DATABASE_URL", "patent_evidence_platform"
        )
    )
    return Settings(
        environment="production" if production else "development",
        database_url=application_url,
        platform_database_url=platform_url,
        worker_database_url=async_postgres_url(
            "PE_TEST_WORKER_DATABASE_URL", "patent_evidence_worker"
        ),
        mfa_encryption_key=mfa_encryption_key,
        expose_development_tokens=not production,
    )


def totp_code(secret: str, now: datetime) -> str:
    counter = int(now.timestamp()) // 30
    digest = hmac.new(
        base64.b32decode(secret), struct.pack(">Q", counter), hashlib.sha1
    ).digest()
    offset = digest[-1] & 0x0F
    value = (
        struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    ) % 1_000_000
    return f"{value:06d}"


async def login_with_totp(
    client: AsyncClient,
    *,
    clock: Callable[[], datetime],
    email: str,
    password: str,
) -> str:
    """First login of an identity: enroll and confirm TOTP. Returns the TOTP secret."""
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200
    enrollment = await client.post("/api/v1/auth/mfa/totp/enroll")
    assert enrollment.status_code == 201
    confirmation = await client.post(
        "/api/v1/auth/mfa/totp/confirm",
        json={
            "credential_id": enrollment.json()["credential_id"],
            "code": totp_code(enrollment.json()["secret"], clock()),
        },
    )
    assert confirmation.status_code == 200
    return enrollment.json()["secret"]


async def login_with_existing_totp(
    client: AsyncClient,
    *,
    clock: Callable[[], datetime],
    email: str,
    password: str,
    secret: str,
) -> None:
    """Later logins of an identity that already has a confirmed TOTP factor."""
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200
    challenge = await client.post(
        "/api/v1/auth/mfa/challenge", json={"code": totp_code(secret, clock())}
    )
    assert challenge.status_code == 200, challenge.text


# --- Shared database baseline -------------------------------------------------
# Integration tests must not depend on which file ran before them. Each module
# that needs data resets the database and seeds its own baseline.

BASELINE_ORG_A = "00000000-0000-4000-8000-000000000001"
BASELINE_ORG_B = "00000000-0000-4000-8000-000000000002"
BASELINE_IDENTITY_A = "10000000-0000-4000-8000-000000000001"
BASELINE_IDENTITY_B = "10000000-0000-4000-8000-000000000002"
BASELINE_IDENTITY_PLATFORM = "10000000-0000-4000-8000-000000000003"
BASELINE_MEMBERSHIP_A = "20000000-0000-4000-8000-000000000001"
BASELINE_MEMBERSHIP_B = "20000000-0000-4000-8000-000000000002"
BASELINE_MFA_A = "30000000-0000-4000-8000-000000000001"


def reset_database(connection) -> None:  # psycopg.Connection as patent_evidence_migration
    """Truncate every application table (all of public except alembic_version).

    Derived from the catalog rather than a hand-kept list, so it cannot go stale
    when migrations add or rename tables.
    """
    tables = [
        row[0]
        for row in connection.execute(
            """SELECT tablename FROM pg_tables
            WHERE schemaname = 'public' AND tablename <> 'alembic_version'"""
        ).fetchall()
    ]
    if tables:
        connection.execute(
            "TRUNCATE TABLE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"
        )


def seed_two_tenant_baseline(connection, now: datetime) -> None:
    """Two organizations (A admin, B reviewer), one platform admin, one TOTP credential."""
    connection.execute(
        """INSERT INTO global_identities
        (id,email_normalized,display_name,status,password_hash,created_at,updated_at)
        VALUES (%s,'a@example.test','A','active','hash-a',%s,%s),
               (%s,'b@example.test','B','active','hash-b',%s,%s),
               (%s,'platform@example.test','Platform','active','hash-platform',%s,%s)""",
        (BASELINE_IDENTITY_A, now, now, BASELINE_IDENTITY_B, now, now, BASELINE_IDENTITY_PLATFORM, now, now),
    )
    connection.execute(
        """INSERT INTO organizations
        (id,slug,display_name,status,created_by,created_at,updated_at)
        VALUES (%s,'org-a','Organization A','active',%s,%s,%s),
               (%s,'org-b','Organization B','active',%s,%s,%s)""",
        (BASELINE_ORG_A, BASELINE_IDENTITY_A, now, now, BASELINE_ORG_B, BASELINE_IDENTITY_B, now, now),
    )
    connection.execute(
        """INSERT INTO organization_memberships
        (id,organization_id,global_identity_id,role,status,created_at,updated_at)
        VALUES (%s,%s,%s,'organization_admin','active',%s,%s),
               (%s,%s,%s,'reviewer','active',%s,%s)""",
        (
            BASELINE_MEMBERSHIP_A, BASELINE_ORG_A, BASELINE_IDENTITY_A, now, now,
            BASELINE_MEMBERSHIP_B, BASELINE_ORG_B, BASELINE_IDENTITY_B, now, now,
        ),
    )
    connection.execute(
        """INSERT INTO mfa_credentials
        (id,global_identity_id,credential_type,label,encrypted_secret_ciphertext,status,created_at)
        VALUES (%s,%s,'totp','primary',%s,'active',%s)""",
        (BASELINE_MFA_A, BASELINE_IDENTITY_A, b"ciphertext-a", now),
    )
    connection.execute(
        """INSERT INTO platform_operator_grants
        (id,global_identity_id,role,status,granted_at)
        VALUES ('35000000-0000-4000-8000-000000000001',%s,'platform_admin','active',%s)""",
        (BASELINE_IDENTITY_PLATFORM, now),
    )


def seed_admin_tenants(connection, *, password_hash: str, tenants: list[dict]) -> None:
    """Organizations with one active organization_admin each, written to the real schema.

    Each tenant dict: org_id, slug, display_name, admin_id, admin_email, membership_id,
    monthly_case_allowance.
    """
    for t in tenants:
        connection.execute(
            """INSERT INTO global_identities
            (id,email_normalized,display_name,status,password_hash,created_at,updated_at)
            VALUES (%s,%s,%s,'active',%s,now(),now())""",
            (t["admin_id"], t["admin_email"], t["admin_email"].split("@")[0], password_hash),
        )
        connection.execute(
            """INSERT INTO organizations
            (id,slug,display_name,status,created_by,created_at,updated_at)
            VALUES (%s,%s,%s,'active',%s,now(),now())""",
            (t["org_id"], t["slug"], t["display_name"], t["admin_id"]),
        )
        connection.execute(
            """INSERT INTO organization_memberships
            (id,organization_id,global_identity_id,role,status,created_at,updated_at)
            VALUES (%s,%s,%s,'organization_admin','active',now(),now())""",
            (t["membership_id"], t["org_id"], t["admin_id"]),
        )
        connection.execute(
            """INSERT INTO organization_plan_quotas
            (organization_id,plan_key,monthly_case_allowance,current_period_start,
             current_period_end,status,created_at,updated_at)
            VALUES (%s,'test',%s,now() - interval '1 day',now() + interval '29 days','active',now(),now())""",
            (t["org_id"], t["monthly_case_allowance"]),
        )


def seed_platform_admin(connection, *, identity_id, email: str, password_hash: str) -> None:
    connection.execute(
        """INSERT INTO global_identities
        (id,email_normalized,display_name,status,password_hash,created_at,updated_at)
        VALUES (%s,%s,%s,'active',%s,now(),now())""",
        (identity_id, email, email.split("@")[0], password_hash),
    )
    connection.execute(
        """INSERT INTO platform_operator_grants (id,global_identity_id,role,status,granted_at)
        VALUES (gen_random_uuid(),%s,'platform_admin','active',now())""",
        (identity_id,),
    )
