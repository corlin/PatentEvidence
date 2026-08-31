import os
from collections.abc import Iterator
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

import psycopg
import pytest


ORG_A = UUID("00000000-0000-4000-8000-000000000001")
ORG_B = UUID("00000000-0000-4000-8000-000000000002")
IDENTITY_A = UUID("10000000-0000-4000-8000-000000000001")
IDENTITY_B = UUID("10000000-0000-4000-8000-000000000002")
MEMBERSHIP_A = UUID("20000000-0000-4000-8000-000000000001")
MEMBERSHIP_B = UUID("20000000-0000-4000-8000-000000000002")


def _url(variable: str, expected_role: str) -> str:
    value = os.environ.get(variable)
    if not value:
        pytest.skip(f"{variable} is provided by scripts/test-postgres.sh")
    assert urlsplit(value).username == expected_role
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="module")
def migration_connection() -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    with psycopg.connect(
        _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration"),
        autocommit=True,
    ) as connection:
        now = datetime.now(UTC)
        connection.execute("DELETE FROM platform_audit_events")
        connection.execute("DELETE FROM audit_events")
        connection.execute("DELETE FROM mfa_credentials")
        connection.execute("DELETE FROM organization_memberships")
        connection.execute("DELETE FROM organizations")
        connection.execute("DELETE FROM global_identities")
        connection.execute(
            """INSERT INTO global_identities
            (id,email_normalized,display_name,status,password_hash,created_at,updated_at)
            VALUES (%s,'a@example.test','A','active','hash-a',%s,%s),
                   (%s,'b@example.test','B','active','hash-b',%s,%s)""",
            (IDENTITY_A, now, now, IDENTITY_B, now, now),
        )
        connection.execute(
            """INSERT INTO organizations
            (id,slug,display_name,status,created_by,created_at,updated_at)
            VALUES (%s,'org-a','Organization A','active',%s,%s,%s),
                   (%s,'org-b','Organization B','active',%s,%s,%s)""",
            (ORG_A, IDENTITY_A, now, now, ORG_B, IDENTITY_B, now, now),
        )
        connection.execute(
            """INSERT INTO organization_memberships
            (id,organization_id,global_identity_id,role,status,created_at,updated_at)
            VALUES (%s,%s,%s,'organization_admin','active',%s,%s),
                   (%s,%s,%s,'reviewer','active',%s,%s)""",
            (MEMBERSHIP_A, ORG_A, IDENTITY_A, now, now, MEMBERSHIP_B, ORG_B, IDENTITY_B, now, now),
        )
        connection.execute(
            """INSERT INTO mfa_credentials
            (id,global_identity_id,credential_type,label,encrypted_secret_ciphertext,status,
             created_at)
            VALUES ('30000000-0000-4000-8000-000000000001',%s,'totp','primary',
                    %s,'active',%s)""",
            (IDENTITY_A, b"ciphertext-a", now),
        )
        yield connection


def _runtime_connection(variable: str, role: str) -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(_url(variable, role), autocommit=True)


def _set_tenant(connection: psycopg.Connection[tuple[object, ...]], organization_id: UUID) -> None:
    connection.execute(
        "SELECT set_config('app.current_organization_id', %s, false)",
        (str(organization_id),),
    )


def test_fresh_migration_creates_expected_tables_roles_and_forced_rls(
    migration_connection: psycopg.Connection[tuple[object, ...]],
) -> None:
    expected_tables = {
        "global_identities",
        "organizations",
        "organization_memberships",
        "organization_plan_quotas",
        "user_sessions",
        "platform_operator_grants",
        "organization_invitations",
        "password_reset_tokens",
        "mfa_credentials",
        "mfa_recovery_codes",
        "audit_events",
        "platform_audit_events",
    }
    tables = {
        row[0]
        for row in migration_connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    }
    assert expected_tables <= tables

    roles = migration_connection.execute(
        """SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolbypassrls
        FROM pg_roles WHERE rolname LIKE 'patent_evidence_%' ORDER BY rolname"""
    ).fetchall()
    assert roles == [
        ("patent_evidence_app", False, False, False, False, False),
        ("patent_evidence_migration", False, False, False, False, False),
        ("patent_evidence_platform", False, False, False, False, False),
        ("patent_evidence_worker", False, False, False, False, False),
    ]

    tenant_tables = (
        "organizations",
        "organization_memberships",
        "organization_plan_quotas",
        "user_sessions",
        "organization_invitations",
        "audit_events",
    )
    for table in tenant_tables:
        row = migration_connection.execute(
            """SELECT c.relrowsecurity, c.relforcerowsecurity, owner.rolname
            FROM pg_class c JOIN pg_roles owner ON owner.oid = c.relowner
            WHERE c.oid = %s::regclass""",
            (table,),
        ).fetchone()
        assert row == (True, True, "patent_evidence_migration")


def test_application_role_cannot_select_or_mutate_another_organization() -> None:
    with _runtime_connection("PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app") as app:
        _set_tenant(app, ORG_A)
        assert app.execute(
            "SELECT id FROM organization_memberships ORDER BY id"
        ).fetchall() == [(MEMBERSHIP_A,)]
        assert app.execute(
            "UPDATE organization_memberships SET status='suspended' WHERE id=%s",
            (MEMBERSHIP_B,),
        ).rowcount == 0
        assert app.execute(
            "DELETE FROM organization_memberships WHERE id=%s", (MEMBERSHIP_B,)
        ).rowcount == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute(
                """INSERT INTO organization_memberships
                (id,organization_id,global_identity_id,role,status,created_at,updated_at)
                VALUES ('20000000-0000-4000-8000-000000000003',%s,%s,'reviewer','active',now(),now())""",
                (ORG_B, IDENTITY_A),
            )


def test_missing_tenant_context_sees_no_rows_and_cannot_insert() -> None:
    with _runtime_connection("PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app") as app:
        assert app.execute("SELECT count(*) FROM organization_memberships").fetchone() == (0,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute(
                """INSERT INTO organization_memberships
                (id,organization_id,global_identity_id,role,status,created_at,updated_at)
                VALUES ('20000000-0000-4000-8000-000000000004',%s,%s,'reviewer','active',now(),now())""",
                (ORG_A, IDENTITY_B),
            )


def test_worker_role_uses_the_same_rls_boundary() -> None:
    with _runtime_connection("PE_TEST_WORKER_DATABASE_URL", "patent_evidence_worker") as worker:
        assert worker.execute("SELECT count(*) FROM organization_memberships").fetchone() == (0,)
        _set_tenant(worker, ORG_B)
        assert worker.execute("SELECT id FROM organization_memberships").fetchall() == [
            (MEMBERSHIP_B,)
        ]


def test_platform_role_can_provision_but_cannot_read_credentials() -> None:
    with _runtime_connection("PE_TEST_PLATFORM_DATABASE_URL", "patent_evidence_platform") as platform:
        provisioned_id = UUID("00000000-0000-4000-8000-000000000003")
        platform.execute(
            """INSERT INTO organizations
            (id,slug,display_name,status,created_by,created_at,updated_at)
            VALUES (%s,'org-c','Organization C','active',%s,now(),now())""",
            (provisioned_id, IDENTITY_A),
        )
        assert platform.execute(
            "SELECT slug FROM organizations WHERE id=%s", (provisioned_id,)
        ).fetchone() == ("org-c",)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            platform.execute("SELECT password_hash FROM global_identities")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            platform.execute("SELECT encrypted_secret_ciphertext FROM mfa_credentials")


def test_application_and_platform_audit_rows_are_append_only() -> None:
    event_a = UUID("40000000-0000-4000-8000-000000000001")
    event_platform = UUID("40000000-0000-4000-8000-000000000002")
    with _runtime_connection("PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app") as app:
        _set_tenant(app, ORG_A)
        app.execute(
            """INSERT INTO audit_events
            (id,organization_id,actor_identity_id,action,target_type,target_id,result,
             request_correlation_id,safe_summary,created_at)
            VALUES (%s,%s,%s,'membership.view','membership',%s,'allowed','request-a',
                    'Viewed membership',now())""",
            (event_a, ORG_A, IDENTITY_A, MEMBERSHIP_A),
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute("UPDATE audit_events SET safe_summary='changed' WHERE id=%s", (event_a,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute("DELETE FROM audit_events WHERE id=%s", (event_a,))

    with _runtime_connection("PE_TEST_PLATFORM_DATABASE_URL", "patent_evidence_platform") as platform:
        platform.execute(
            """INSERT INTO platform_audit_events
            (id,actor_identity_id,action,target_type,target_id,result,request_correlation_id,
             safe_summary,created_at)
            VALUES (%s,%s,'organization.create','organization',%s,'allowed','request-platform',
                    'Created organization',now())""",
            (event_platform, IDENTITY_A, ORG_A),
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            platform.execute(
                "UPDATE platform_audit_events SET safe_summary='changed' WHERE id=%s",
                (event_platform,),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            platform.execute("DELETE FROM platform_audit_events WHERE id=%s", (event_platform,))
