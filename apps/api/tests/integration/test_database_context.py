import os
from urllib.parse import urlsplit
from uuid import UUID

import pytest
from sqlalchemy import text

from patent_evidence_api.core.database import (
    MissingTenantContextError,
    UnexpectedDatabaseRoleError,
    create_application_session_factory,
    create_engine,
    create_platform_session_factory,
    platform_transaction,
    require_tenant_context,
    session_token_transaction,
    tenant_transaction,
)


ORG_A = UUID("00000000-0000-4000-8000-000000000001")
ACTOR_A = UUID("10000000-0000-4000-8000-000000000001")
SESSION_HASH = "session-hash-runtime-context"
RUNTIME_IDENTITY = UUID("10000000-0000-4000-8000-000000000004")
RUNTIME_SESSION = UUID("50000000-0000-4000-8000-000000000004")


def _async_application_url() -> str:
    value = os.environ.get("PE_TEST_APPLICATION_DATABASE_URL")
    if not value:
        pytest.skip("PE_TEST_APPLICATION_DATABASE_URL is provided by scripts/test-postgres.sh")
    assert urlsplit(value).username == "patent_evidence_app"
    return value.replace("postgresql://", "postgresql+asyncpg://", 1)


def _async_platform_url() -> str:
    value = os.environ.get("PE_TEST_PLATFORM_DATABASE_URL")
    if not value:
        pytest.skip("PE_TEST_PLATFORM_DATABASE_URL is provided by scripts/test-postgres.sh")
    assert urlsplit(value).username == "patent_evidence_platform"
    return value.replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest.mark.asyncio
async def test_tenant_transaction_binds_context_and_repository_guard() -> None:
    engine = create_engine(_async_application_url())
    factory = create_application_session_factory(engine)
    try:
        async with factory() as session, session.begin():
            with pytest.raises(MissingTenantContextError):
                await require_tenant_context(session)

        async with tenant_transaction(
            factory,
            ORG_A,
            actor_identity_id=ACTOR_A,
            request_correlation_id="request-context-test",
        ) as session:
            assert await require_tenant_context(session) == ORG_A
            assert await session.scalar(
                text("SELECT current_setting('app.current_actor_identity_id')")
            ) == str(ACTOR_A)
            assert await session.scalar(
                text("SELECT current_setting('app.current_request_correlation_id')")
            ) == "request-context-test"
            assert await session.scalar(text("SELECT count(*) FROM organization_memberships")) == 1

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_platform_transaction_rejects_application_database_role() -> None:
    engine = create_engine(_async_application_url())
    factory = create_application_session_factory(engine)
    try:
        with pytest.raises(UnexpectedDatabaseRoleError, match="patent_evidence_platform"):
            async with platform_transaction(factory):
                pass
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_platform_transaction_uses_platform_database_role() -> None:
    engine = create_engine(_async_platform_url())
    factory = create_platform_session_factory(engine)
    try:
        async with platform_transaction(factory) as session:
            assert await session.scalar(text("SELECT current_user")) == "patent_evidence_platform"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_platform_transaction_rejects_application_factory_on_platform_connection() -> None:
    engine = create_engine(_async_platform_url())
    factory = create_application_session_factory(engine)
    try:
        with pytest.raises(UnexpectedDatabaseRoleError, match="application session factory"):
            async with platform_transaction(factory):
                pass
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_token_transaction_binds_hash_for_insert_and_lookup() -> None:
    engine = create_engine(_async_application_url())
    factory = create_application_session_factory(engine)
    try:
        async with session_token_transaction(factory, SESSION_HASH) as session:
            await session.execute(
                text(
                    """INSERT INTO global_identities
                    (id,email_normalized,display_name,status,password_hash,created_at,updated_at)
                    VALUES (:identity_id,'runtime-session@example.test','Runtime Session',
                            'active','runtime-hash',now(),now())"""
                ),
                {"identity_id": RUNTIME_IDENTITY},
            )
            await session.execute(
                text(
                    """INSERT INTO user_sessions
                    (id,global_identity_id,token_hash,expires_at,last_seen_at,created_at,updated_at)
                    VALUES (:session_id,:identity_id,:token_hash,
                            now() + interval '1 hour',now(),now(),now())"""
                ),
                {
                    "session_id": RUNTIME_SESSION,
                    "identity_id": RUNTIME_IDENTITY,
                    "token_hash": SESSION_HASH,
                },
            )
            assert await session.scalar(
                text("SELECT global_identity_id FROM user_sessions WHERE id=:session_id"),
                {"session_id": RUNTIME_SESSION},
            ) == RUNTIME_IDENTITY

        async with session_token_transaction(factory, "wrong-runtime-hash") as session:
            assert await session.scalar(
                text("SELECT count(*) FROM user_sessions WHERE id=:session_id"),
                {"session_id": RUNTIME_SESSION},
            ) == 0
    finally:
        await engine.dispose()
