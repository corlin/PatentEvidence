import base64
import hashlib
import hmac
import os
import struct
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

import psycopg
import pytest
from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from patent_evidence_api.core.settings import Settings
from patent_evidence_api.main import create_app


IDENTITY = UUID("10000000-0000-4000-8000-000000000101")
ADMIN = UUID("10000000-0000-4000-8000-000000000102")
MEMBER = UUID("10000000-0000-4000-8000-000000000103")
PLATFORM = UUID("10000000-0000-4000-8000-000000000104")
ORGANIZATION = UUID("00000000-0000-4000-8000-000000000101")
OTHER_ORGANIZATION = UUID("00000000-0000-4000-8000-000000000102")
PASSWORD = "Correct horse battery staple 42"
NEW_PASSWORD = "New correct horse battery staple 84"
MFA_KEY = Fernet.generate_key().decode()


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime.now(UTC).replace(microsecond=0)

    def __call__(self) -> datetime:
        return self.value


def _url(variable: str, role: str) -> str:
    value = os.environ.get(variable)
    if not value:
        pytest.skip(f"{variable} is provided by scripts/test-postgres.sh")
    assert urlsplit(value).username == role
    return value


def _settings(*, production: bool = False) -> Settings:
    application_url = _url("PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app")
    return Settings(
        environment="production" if production else "development",
        database_url=application_url.replace(
            "postgresql://", "postgresql+asyncpg://", 1
        ),
        mfa_encryption_key=MFA_KEY,
        expose_development_tokens=not production,
    )


@pytest.fixture(autouse=True)
def seeded_identities() -> Iterator[None]:
    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    password_hash = PasswordHasher().hash(PASSWORD)
    with psycopg.connect(migration_url, autocommit=True) as connection:
        connection.execute(
            "TRUNCATE platform_audit_events,audit_events,mfa_recovery_codes,mfa_credentials,"
            "password_reset_tokens,organization_invitations,platform_operator_grants,"
            "user_sessions,organization_plan_quotas,organization_memberships,organizations,"
            "global_identities CASCADE"
        )
        connection.execute(
            """INSERT INTO global_identities
            (id,email_normalized,display_name,status,password_hash,created_at,updated_at)
            VALUES (%s,'user@example.test','User','active',%s,now(),now()),
                   (%s,'admin@example.test','Admin','active',%s,now(),now()),
                   (%s,'member@example.test','Member','active',%s,now(),now()),
                   (%s,'platform@example.test','Platform','active',%s,now(),now())""",
            (
                IDENTITY,
                password_hash,
                ADMIN,
                password_hash,
                MEMBER,
                password_hash,
                PLATFORM,
                password_hash,
            ),
        )
        connection.execute(
            """INSERT INTO organizations
            (id,slug,display_name,status,created_by,created_at,updated_at)
            VALUES (%s,'alpha','Alpha','active',%s,now(),now()),
                   (%s,'other','Other','active',%s,now(),now())""",
            (ORGANIZATION, ADMIN, OTHER_ORGANIZATION, ADMIN),
        )
        connection.execute(
            """INSERT INTO organization_memberships
            (id,organization_id,global_identity_id,role,status,created_at,updated_at)
            VALUES ('20000000-0000-4000-8000-000000000101',%s,%s,'organization_admin','active',now(),now()),
                   ('20000000-0000-4000-8000-000000000102',%s,%s,'reviewer','active',now(),now())""",
            (ORGANIZATION, ADMIN, ORGANIZATION, MEMBER),
        )
        connection.execute(
            """INSERT INTO platform_operator_grants
            (id,global_identity_id,role,status,granted_at)
            VALUES ('35000000-0000-4000-8000-000000000101',%s,'platform_admin','active',now())""",
            (PLATFORM,),
        )
    yield


def _totp(secret: str, now: datetime) -> str:
    counter = int(now.timestamp()) // 30
    digest = hmac.new(
        base64.b32decode(secret), struct.pack(">Q", counter), hashlib.sha1
    ).digest()
    offset = digest[-1] & 0x0F
    value = (
        struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    ) % 1_000_000
    return f"{value:06d}"


async def _login(client: AsyncClient, email: str = "user@example.test"):
    return await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )


async def _confirm_totp(client: AsyncClient, clock: MutableClock):
    enrollment = await client.post("/api/v1/auth/mfa/totp/enroll")
    assert enrollment.status_code == 201
    valid_code = _totp(enrollment.json()["secret"], clock())
    invalid_code = "000000" if valid_code != "000000" else "000001"
    rejected = await client.post(
        "/api/v1/auth/mfa/totp/confirm",
        json={
            "credential_id": enrollment.json()["credential_id"],
            "code": invalid_code,
        },
    )
    assert rejected.status_code == 401
    assert rejected.json() == {"detail": "invalid_mfa_challenge"}
    confirmation = await client.post(
        "/api/v1/auth/mfa/totp/confirm",
        json={
            "credential_id": enrollment.json()["credential_id"],
            "code": valid_code,
        },
    )
    assert confirmation.status_code == 200
    return enrollment, confirmation


@pytest.mark.asyncio
async def test_login_is_generic_and_rate_limited() -> None:
    app = create_app(settings=_settings())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        unknown = await client.post(
            "/api/v1/auth/login",
            json={"email": "unknown@example.test", "password": "wrong"},
        )
        wrong = await client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.test", "password": "wrong"},
        )
        for _ in range(4):
            limited = await client.post(
                "/api/v1/auth/login",
                json={"email": "unknown@example.test", "password": "wrong"},
            )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json() == {"detail": "invalid_credentials"}
    assert limited.status_code == 429
    assert limited.json() == {"detail": "rate_limited"}


@pytest.mark.asyncio
async def test_login_cookie_session_expiration_and_logout() -> None:
    clock = MutableClock()
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        login = await _login(client)
        token = login.cookies["pe_session"]
        assert login.status_code == 200
        assert len(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))) >= 32
        set_cookie = login.headers["set-cookie"].lower()
        assert "httponly" in set_cookie
        assert "samesite=lax" in set_cookie
        assert "secure" not in set_cookie
        current = await client.get("/api/v1/auth/session")
        assert current.status_code == 200
        assert current.json()["identity_id"] == str(IDENTITY)
        assert current.json()["mfa_recent"] is False

        clock.value += timedelta(hours=12)
        expired = await client.get("/api/v1/auth/session")
        assert expired.status_code == 401

        clock.value -= timedelta(hours=12)
        relogin = await _login(client)
        active_token = relogin.cookies["pe_session"]
        logout = await client.post("/api/v1/auth/logout")
        client.cookies.set("pe_session", active_token)
        after_logout = await client.get("/api/v1/auth/session")

    assert logout.status_code == 204
    assert after_logout.status_code == 401


@pytest.mark.asyncio
async def test_production_cookie_is_secure() -> None:
    app = create_app(settings=_settings(production=True))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as client:
        login = await _login(client)
    assert login.status_code == 200
    assert "secure" in login.headers["set-cookie"].lower()


@pytest.mark.asyncio
async def test_session_rejects_an_identity_suspended_after_login() -> None:
    app = create_app(settings=_settings())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await _login(client)
        migration_url = _url(
            "PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration"
        )
        with psycopg.connect(migration_url, autocommit=True) as connection:
            connection.execute(
                "UPDATE global_identities SET status='suspended' WHERE id=%s",
                (IDENTITY,),
            )
        current = await client.get("/api/v1/auth/session")

    assert current.status_code == 401
    assert current.json() == {"detail": "session_required"}


@pytest.mark.asyncio
async def test_password_reset_is_generic_one_time_and_revokes_sessions() -> None:
    clock = MutableClock()
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        login = await _login(client)
        old_token = login.cookies["pe_session"]
        known = await client.post(
            "/api/v1/auth/password-reset/request", json={"email": "user@example.test"}
        )
        unknown = await client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "unknown@example.test"},
        )
        assert known.status_code == unknown.status_code == 202
        assert set(known.json()) == set(unknown.json()) == {"status", "reset_token"}

        reset_token = known.json()["reset_token"]
        confirmed = await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": reset_token, "new_password": NEW_PASSWORD},
        )
        replay = await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": reset_token, "new_password": "Another valid password 99"},
        )
        client.cookies.set("pe_session", old_token)
        revoked = await client.get("/api/v1/auth/session")
        old_login = await _login(client)
        new_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.test", "password": NEW_PASSWORD},
        )

    assert confirmed.status_code == 204
    assert replay.status_code == 400
    assert replay.json() == {"detail": "invalid_or_expired_reset_token"}
    assert revoked.status_code == 401
    assert old_login.status_code == 401
    assert new_login.status_code == 200
    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    with psycopg.connect(migration_url) as connection:
        audit = connection.execute(
            "SELECT action,target_id,safe_summary FROM platform_audit_events"
        ).fetchall()
    assert audit == [("identity.password_reset", IDENTITY, "Completed password reset")]
    assert reset_token not in audit[0][2]
    assert NEW_PASSWORD not in audit[0][2]


@pytest.mark.asyncio
async def test_password_reset_expires_and_password_policy_is_enforced() -> None:
    clock = MutableClock()
    clock.value -= timedelta(hours=1)
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        request = await client.post(
            "/api/v1/auth/password-reset/request", json={"email": "user@example.test"}
        )
        token = request.json()["reset_token"]
        expired = await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token, "new_password": NEW_PASSWORD},
        )

        fresh = await client.post(
            "/api/v1/auth/password-reset/request", json={"email": "user@example.test"}
        )
        weak = await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": fresh.json()["reset_token"], "new_password": "too-short"},
        )

    assert expired.status_code == 400
    assert expired.json() == {"detail": "invalid_or_expired_reset_token"}
    assert weak.status_code == 422
    assert weak.json() == {"detail": "password_policy_failed"}


@pytest.mark.asyncio
async def test_totp_rotation_recovery_codes_and_secret_safe_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = MutableClock()
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        login = await _login(client)
        old_token = login.cookies["pe_session"]
        enrollment, confirmation = await _confirm_totp(client, clock)
        secret = enrollment.json()["secret"]
        recovery_codes = confirmation.json()["recovery_codes"]
        assert confirmation.cookies["pe_session"] != old_token
        current = await client.get("/api/v1/auth/session")
        assert current.json()["mfa_recent"] is True
        client.cookies.clear()
        client.cookies.set("pe_session", old_token)
        rotated_out = await client.get("/api/v1/auth/session")
        assert rotated_out.status_code == 401

        client.cookies.clear()
        await _login(client)
        totp_challenge = await client.post(
            "/api/v1/auth/mfa/challenge", json={"code": _totp(secret, clock())}
        )
        assert totp_challenge.status_code == 200

        password_session = await _login(client)
        challenged = await client.post(
            "/api/v1/auth/mfa/challenge", json={"recovery_code": recovery_codes[0]}
        )
        assert challenged.status_code == 200
        assert (
            challenged.cookies["pe_session"] != password_session.cookies["pe_session"]
        )

        await _login(client)
        reused = await client.post(
            "/api/v1/auth/mfa/challenge", json={"recovery_code": recovery_codes[0]}
        )

    assert reused.status_code == 401
    captured = "\n".join(record.getMessage() for record in caplog.records)
    assert secret not in captured
    assert all(code not in captured for code in recovery_codes)
    assert PASSWORD not in captured
    assert old_token not in captured


@pytest.mark.asyncio
async def test_recovery_code_regeneration_invalidates_previous_batch() -> None:
    clock = MutableClock()
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await _login(client)
        _, confirmation = await _confirm_totp(client, clock)
        old_codes = confirmation.json()["recovery_codes"]
        regenerated = await client.post("/api/v1/auth/mfa/recovery-codes")
        new_codes = regenerated.json()["recovery_codes"]
        assert regenerated.status_code == 200
        assert set(old_codes).isdisjoint(new_codes)

        await _login(client)
        old_code = await client.post(
            "/api/v1/auth/mfa/challenge", json={"recovery_code": old_codes[1]}
        )
        new_code = await client.post(
            "/api/v1/auth/mfa/challenge", json={"recovery_code": new_codes[0]}
        )

    assert old_code.status_code == 401
    assert new_code.status_code == 200


@pytest.mark.asyncio
async def test_identity_wide_session_revocation_revokes_every_session() -> None:
    app = create_app(settings=_settings())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as first:
        first_login = await _login(first)
        first_token = first_login.cookies["pe_session"]
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as second:
            second_login = await _login(second)
            second_token = second_login.cookies["pe_session"]
            revoked = await first.post("/api/v1/auth/sessions/revoke")
            first.cookies.set("pe_session", first_token)
            second.cookies.set("pe_session", second_token)
            first_after = await first.get("/api/v1/auth/session")
            second_after = await second.get("/api/v1/auth/session")

    assert revoked.status_code == 204
    assert first_after.status_code == second_after.status_code == 401
    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    with psycopg.connect(migration_url) as connection:
        audit = connection.execute(
            "SELECT action,target_id,safe_summary FROM platform_audit_events"
        ).fetchall()
    assert audit == [
        ("identity.sessions_revoke", IDENTITY, "Revoked identity sessions")
    ]


@pytest.mark.asyncio
async def test_auth_material_is_hashed_encrypted_and_cross_identity_revocation_is_denied() -> (
    None
):
    clock = MutableClock()
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        login = await _login(client)
        token = login.cookies["pe_session"]
        enrollment, confirmation = await _confirm_totp(client, clock)
        secret = enrollment.json()["secret"]
        codes = confirmation.json()["recovery_codes"]
        reset = await client.post(
            "/api/v1/auth/password-reset/request", json={"email": "user@example.test"}
        )
        reset_token = reset.json()["reset_token"]

    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    with psycopg.connect(migration_url) as connection:
        session_hashes = {
            row[0] for row in connection.execute("SELECT token_hash FROM user_sessions")
        }
        reset_hashes = {
            row[0]
            for row in connection.execute(
                "SELECT token_hash FROM password_reset_tokens"
            )
        }
        ciphertext = connection.execute(
            "SELECT encrypted_secret_ciphertext FROM mfa_credentials WHERE global_identity_id=%s",
            (IDENTITY,),
        ).fetchone()[0]
        recovery_hashes = {
            row[0]
            for row in connection.execute(
                "SELECT code_hash FROM mfa_recovery_codes WHERE global_identity_id=%s",
                (IDENTITY,),
            )
        }
        password_hash = connection.execute(
            "SELECT password_hash FROM global_identities WHERE id=%s", (IDENTITY,)
        ).fetchone()[0]

    digest = hashlib.sha256(token.encode()).hexdigest()
    assert digest in session_hashes and token not in session_hashes
    assert hashlib.sha256(reset_token.encode()).hexdigest() in reset_hashes
    assert reset_token not in reset_hashes
    assert secret.encode() not in ciphertext
    assert all(code not in recovery_hashes for code in codes)
    assert all(len(value) == 64 for value in recovery_hashes)
    assert password_hash.startswith("$argon2id$") and PASSWORD not in password_hash

    application_url = _url("PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app")
    with psycopg.connect(application_url, autocommit=True) as connection:
        connection.execute(
            "SELECT set_config('app.current_session_token_hash', %s, false)",
            (hashlib.sha256(confirmation.cookies["pe_session"].encode()).hexdigest(),),
        )
        with pytest.raises(psycopg.errors.RaiseException, match="identity mismatch"):
            connection.execute("SELECT revoke_current_identity_sessions(%s)", (MEMBER,))


@pytest.mark.asyncio
async def test_organization_and_platform_mfa_reset_require_recent_mfa() -> None:
    clock = MutableClock()
    app = create_app(settings=_settings(), clock=clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        member_login = await _login(client, "member@example.test")
        member_token = member_login.cookies["pe_session"]

        await _login(client, "admin@example.test")
        blocked_org = await client.post(
            f"/api/v1/organizations/{ORGANIZATION}/members/{MEMBER}/mfa/reset"
        )
        await _confirm_totp(client, clock)
        wrong_org = await client.post(
            f"/api/v1/organizations/{OTHER_ORGANIZATION}/members/{MEMBER}/mfa/reset"
        )
        migration_url = _url(
            "PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration"
        )
        with psycopg.connect(migration_url, autocommit=True) as connection:
            connection.execute(
                "UPDATE organizations SET status='suspended' WHERE id=%s",
                (ORGANIZATION,),
            )
        suspended_org = await client.post(
            f"/api/v1/organizations/{ORGANIZATION}/members/{MEMBER}/mfa/reset"
        )
        with psycopg.connect(migration_url, autocommit=True) as connection:
            connection.execute(
                "UPDATE organizations SET status='active' WHERE id=%s", (ORGANIZATION,)
            )
        reset_org = await client.post(
            f"/api/v1/organizations/{ORGANIZATION}/members/{MEMBER}/mfa/reset"
        )

        await _login(client, "platform@example.test")
        blocked_platform = await client.post(
            f"/api/v1/platform/identities/{IDENTITY}/mfa/reset"
        )
        await _confirm_totp(client, clock)
        clock.value += timedelta(minutes=11)
        stale_platform = await client.post(
            f"/api/v1/platform/identities/{IDENTITY}/mfa/reset"
        )
        clock.value -= timedelta(minutes=11)
        reset_platform = await client.post(
            f"/api/v1/platform/identities/{IDENTITY}/mfa/reset"
        )

        client.cookies.set("pe_session", member_token)
        member_revoked = await client.get("/api/v1/auth/session")

    assert blocked_org.status_code == blocked_platform.status_code == 403
    assert blocked_org.json() == blocked_platform.json() == {"detail": "mfa_required"}
    assert wrong_org.status_code == 403
    assert suspended_org.status_code == 403
    assert stale_platform.status_code == 403
    assert stale_platform.json() == {"detail": "mfa_required"}
    assert reset_org.status_code == reset_platform.status_code == 204
    assert member_revoked.status_code == 401

    migration_url = _url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    with psycopg.connect(migration_url) as connection:
        summaries = [
            row[0]
            for row in connection.execute(
                "SELECT safe_summary FROM audit_events UNION ALL "
                "SELECT safe_summary FROM platform_audit_events"
            )
        ]
    assert summaries == ["Reset member MFA", "Reset identity MFA"]
    assert all("pe_session" not in summary.lower() for summary in summaries)
