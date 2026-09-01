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
) -> None:
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
