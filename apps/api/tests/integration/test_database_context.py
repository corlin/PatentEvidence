import os
from urllib.parse import urlsplit
from uuid import UUID

import pytest
from sqlalchemy import text

from patent_evidence_api.core.database import (
    MissingTenantContextError,
    create_engine,
    create_session_factory,
    platform_transaction,
    require_tenant_context,
    tenant_transaction,
)


ORG_A = UUID("00000000-0000-4000-8000-000000000001")
ACTOR_A = UUID("10000000-0000-4000-8000-000000000001")


def _async_application_url() -> str:
    value = os.environ.get("PE_TEST_APPLICATION_DATABASE_URL")
    if not value:
        pytest.skip("PE_TEST_APPLICATION_DATABASE_URL is provided by scripts/test-postgres.sh")
    assert urlsplit(value).username == "patent_evidence_app"
    return value.replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest.mark.asyncio
async def test_tenant_transaction_binds_context_and_repository_guard() -> None:
    engine = create_engine(_async_application_url())
    factory = create_session_factory(engine)
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

        async with platform_transaction(factory) as session:
            assert await session.scalar(
                text("SELECT nullif(current_setting('app.current_organization_id', true), '')")
            ) is None
    finally:
        await engine.dispose()
