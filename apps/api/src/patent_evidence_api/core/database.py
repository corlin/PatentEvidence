from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class MissingTenantContextError(RuntimeError):
    """Raised before an organization repository runs without tenant context."""


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def bind_transaction_context(
    session: AsyncSession,
    *,
    organization_id: UUID | None,
    actor_identity_id: UUID | None = None,
    request_correlation_id: str | None = None,
) -> None:
    if not session.in_transaction():
        raise RuntimeError("database context must be bound inside a transaction")
    values = (
        ("app.current_organization_id", str(organization_id) if organization_id else ""),
        ("app.current_actor_identity_id", str(actor_identity_id) if actor_identity_id else ""),
        ("app.current_request_correlation_id", request_correlation_id or ""),
    )
    for key, value in values:
        await session.execute(
            text("SELECT set_config(:key, :value, true)"),
            {"key": key, "value": value},
        )


async def require_tenant_context(session: AsyncSession) -> UUID:
    value = await session.scalar(
        text("SELECT nullif(current_setting('app.current_organization_id', true), '')")
    )
    if value is None:
        raise MissingTenantContextError("organization repository requires tenant context")
    return UUID(str(value))


@asynccontextmanager
async def tenant_transaction(
    factory: async_sessionmaker[AsyncSession],
    organization_id: UUID,
    *,
    actor_identity_id: UUID | None = None,
    request_correlation_id: str | None = None,
) -> AsyncIterator[AsyncSession]:
    async with factory() as session, session.begin():
        await bind_transaction_context(
            session,
            organization_id=organization_id,
            actor_identity_id=actor_identity_id,
            request_correlation_id=request_correlation_id,
        )
        yield session


@asynccontextmanager
async def platform_transaction(
    factory: async_sessionmaker[AsyncSession],
    *,
    actor_identity_id: UUID | None = None,
    request_correlation_id: str | None = None,
) -> AsyncIterator[AsyncSession]:
    async with factory() as session, session.begin():
        await bind_transaction_context(
            session,
            organization_id=None,
            actor_identity_id=actor_identity_id,
            request_correlation_id=request_correlation_id,
        )
        yield session
