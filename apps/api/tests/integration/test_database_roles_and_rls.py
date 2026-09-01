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
IDENTITY_PLATFORM = UUID("10000000-0000-4000-8000-000000000003")
MEMBERSHIP_A = UUID("20000000-0000-4000-8000-000000000001")
MEMBERSHIP_B = UUID("20000000-0000-4000-8000-000000000002")
MFA_A = UUID("30000000-0000-4000-8000-000000000001")
SESSION_PLATFORM = UUID("50000000-0000-4000-8000-000000000001")
SESSION_HASH = "session-hash-platform"


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
        connection.execute("DELETE FROM user_sessions")
        connection.execute("DELETE FROM platform_operator_grants")
        connection.execute("DELETE FROM mfa_recovery_codes")
        connection.execute("DELETE FROM mfa_credentials")
        connection.execute("DELETE FROM organization_memberships")
        connection.execute("DELETE FROM organizations")
        connection.execute("DELETE FROM global_identities")
        connection.execute(
            """INSERT INTO global_identities
            (id,email_normalized,display_name,status,password_hash,created_at,updated_at)
            VALUES (%s,'a@example.test','A','active','hash-a',%s,%s),
                   (%s,'b@example.test','B','active','hash-b',%s,%s),
                   (%s,'platform@example.test','Platform','active','hash-platform',%s,%s)""",
            (IDENTITY_A, now, now, IDENTITY_B, now, now, IDENTITY_PLATFORM, now, now),
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
            (
                MEMBERSHIP_A,
                ORG_A,
                IDENTITY_A,
                now,
                now,
                MEMBERSHIP_B,
                ORG_B,
                IDENTITY_B,
                now,
                now,
            ),
        )
        connection.execute(
            """INSERT INTO mfa_credentials
            (id,global_identity_id,credential_type,label,encrypted_secret_ciphertext,status,
             created_at)
            VALUES (%s,%s,'totp','primary',
                    %s,'active',%s)""",
            (MFA_A, IDENTITY_A, b"ciphertext-a", now),
        )
        connection.execute(
            """INSERT INTO platform_operator_grants
            (id,global_identity_id,role,status,granted_at)
            VALUES ('35000000-0000-4000-8000-000000000001',%s,'platform_admin','active',%s)""",
            (IDENTITY_PLATFORM, now),
        )
        yield connection


def _runtime_connection(
    variable: str, role: str
) -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(_url(variable, role), autocommit=True)


def _set_tenant(
    connection: psycopg.Connection[tuple[object, ...]], organization_id: UUID
) -> None:
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

    session_columns = {
        row[0]
        for row in migration_connection.execute(
            """SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'user_sessions'"""
        ).fetchall()
    }
    assert "global_identity_id" in session_columns
    assert "security_version" in session_columns
    assert "organization_id" not in session_columns
    assert "membership_id" not in session_columns

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
    with _runtime_connection(
        "PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app"
    ) as app:
        _set_tenant(app, ORG_A)
        assert app.execute(
            "SELECT id FROM organization_memberships ORDER BY id"
        ).fetchall() == [(MEMBERSHIP_A,)]
        assert (
            app.execute(
                "UPDATE organization_memberships SET status='suspended' WHERE id=%s",
                (MEMBERSHIP_B,),
            ).rowcount
            == 0
        )
        assert (
            app.execute(
                "DELETE FROM organization_memberships WHERE id=%s", (MEMBERSHIP_B,)
            ).rowcount
            == 0
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute(
                """INSERT INTO organization_memberships
                (id,organization_id,global_identity_id,role,status,created_at,updated_at)
                VALUES ('20000000-0000-4000-8000-000000000003',%s,%s,'reviewer','active',now(),now())""",
                (ORG_B, IDENTITY_A),
            )


def test_missing_tenant_context_sees_no_rows_and_cannot_insert() -> None:
    with _runtime_connection(
        "PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app"
    ) as app:
        assert app.execute(
            "SELECT count(*) FROM organization_memberships"
        ).fetchone() == (0,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute(
                """INSERT INTO organization_memberships
                (id,organization_id,global_identity_id,role,status,created_at,updated_at)
                VALUES ('20000000-0000-4000-8000-000000000004',%s,%s,'reviewer','active',now(),now())""",
                (ORG_A, IDENTITY_B),
            )


def test_worker_role_uses_the_same_rls_boundary() -> None:
    with _runtime_connection(
        "PE_TEST_WORKER_DATABASE_URL", "patent_evidence_worker"
    ) as worker:
        assert worker.execute(
            "SELECT count(*) FROM organization_memberships"
        ).fetchone() == (0,)
        _set_tenant(worker, ORG_B)
        assert worker.execute("SELECT id FROM organization_memberships").fetchall() == [
            (MEMBERSHIP_B,)
        ]


def test_worker_role_cannot_read_password_hashes() -> None:
    with _runtime_connection(
        "PE_TEST_WORKER_DATABASE_URL", "patent_evidence_worker"
    ) as worker:
        assert worker.execute(
            "SELECT display_name FROM global_identities WHERE id=%s", (IDENTITY_A,)
        ).fetchone() == ("A",)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            worker.execute("SELECT password_hash FROM global_identities")


def test_application_role_cannot_read_password_reset_token_hashes() -> None:
    with _runtime_connection(
        "PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app"
    ) as app:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute("SELECT token_hash FROM password_reset_tokens")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute("SELECT role FROM platform_operator_grants")


def test_session_token_hash_rls_allows_only_matching_session_and_platform_identity() -> (
    None
):
    with _runtime_connection(
        "PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app"
    ) as app:
        app.execute(
            "SELECT set_config('app.current_session_token_hash', %s, false)",
            (SESSION_HASH,),
        )
        app.execute(
            """INSERT INTO user_sessions
            (id,global_identity_id,token_hash,expires_at,last_seen_at,created_at,updated_at)
            VALUES (%s,%s,%s,now() + interval '1 hour',now(),now(),now())""",
            (SESSION_PLATFORM, IDENTITY_PLATFORM, SESSION_HASH),
        )
        assert app.execute(
            "SELECT global_identity_id FROM user_sessions WHERE id=%s",
            (SESSION_PLATFORM,),
        ).fetchone() == (IDENTITY_PLATFORM,)

        app.execute(
            "SELECT set_config('app.current_session_token_hash', 'another-session-hash', false)"
        )
        assert app.execute("SELECT count(*) FROM user_sessions").fetchone() == (0,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute(
                """INSERT INTO user_sessions
                (id,global_identity_id,token_hash,expires_at,last_seen_at,created_at,updated_at)
                VALUES ('50000000-0000-4000-8000-000000000002',%s,%s,
                        now() + interval '1 hour',now(),now(),now())""",
                (IDENTITY_A, SESSION_HASH),
            )

    with _runtime_connection(
        "PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app"
    ) as app:
        assert app.execute("SELECT count(*) FROM user_sessions").fetchone() == (0,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute(
                """INSERT INTO user_sessions
                (id,global_identity_id,token_hash,expires_at,last_seen_at,created_at,updated_at)
                VALUES ('50000000-0000-4000-8000-000000000003',%s,'missing-context-hash',
                        now() + interval '1 hour',now(),now(),now())""",
                (IDENTITY_A,),
            )


def test_recovery_code_identity_must_match_mfa_credential() -> None:
    with psycopg.connect(
        _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration"),
        autocommit=True,
    ) as migration_connection:
        migration_connection.execute(
            """INSERT INTO mfa_recovery_codes
            (id,global_identity_id,mfa_credential_id,batch_id,code_hash,created_at)
            VALUES ('31000000-0000-4000-8000-000000000002',%s,%s,
                    '32000000-0000-4000-8000-000000000002','valid-code-hash',now())""",
            (IDENTITY_A, MFA_A),
        )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            migration_connection.execute(
                """INSERT INTO mfa_recovery_codes
                (id,global_identity_id,mfa_credential_id,batch_id,code_hash,created_at)
                VALUES ('31000000-0000-4000-8000-000000000001',%s,%s,
                        '32000000-0000-4000-8000-000000000001','code-hash',now())""",
                (IDENTITY_B, MFA_A),
            )


@pytest.mark.parametrize("status", ["active", "pending"])
def test_identity_cannot_have_duplicate_current_totp_credentials(status: str) -> None:
    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    duplicate_id = {
        "active": "30000000-0000-4000-8000-000000000098",
        "pending": "30000000-0000-4000-8000-000000000099",
    }[status]
    with psycopg.connect(migration_url) as connection:
        if status == "pending":
            connection.execute(
                "UPDATE mfa_credentials SET status='pending' WHERE id=%s", (MFA_A,)
            )
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                """INSERT INTO mfa_credentials
                (id,global_identity_id,credential_type,label,encrypted_secret_ciphertext,
                 status,created_at)
                VALUES (%s,%s,'totp','duplicate',
                        %s,%s,now())""",
                (duplicate_id, IDENTITY_A, b"duplicate-ciphertext", status),
            )


def test_platform_role_can_provision_but_cannot_read_credentials() -> None:
    with _runtime_connection(
        "PE_TEST_PLATFORM_DATABASE_URL", "patent_evidence_platform"
    ) as platform:
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
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            platform.execute("SELECT token_hash FROM user_sessions")


def test_platform_mfa_reset_cannot_impersonate_a_different_context_actor() -> None:
    with _runtime_connection(
        "PE_TEST_PLATFORM_DATABASE_URL", "patent_evidence_platform"
    ) as platform:
        platform.execute(
            "SELECT set_config('app.current_actor_identity_id', %s, true)",
            (str(IDENTITY_B),),
        )
        reset = platform.execute(
            "SELECT reset_identity_mfa_as_platform_administrator(%s, %s, %s)",
            (IDENTITY_A, 1, IDENTITY_B),
        ).fetchone()

    assert reset == (False,)


def test_application_and_platform_audit_rows_are_append_only() -> None:
    event_a = UUID("40000000-0000-4000-8000-000000000001")
    event_platform = UUID("40000000-0000-4000-8000-000000000002")
    with _runtime_connection(
        "PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app"
    ) as app:
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
            app.execute(
                "UPDATE audit_events SET safe_summary='changed' WHERE id=%s", (event_a,)
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute("DELETE FROM audit_events WHERE id=%s", (event_a,))

    with _runtime_connection(
        "PE_TEST_PLATFORM_DATABASE_URL", "patent_evidence_platform"
    ) as platform:
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
            platform.execute(
                "DELETE FROM platform_audit_events WHERE id=%s", (event_platform,)
            )
