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


class UnexpectedDatabaseRoleError(RuntimeError):
    """Raised when a transaction is opened through the wrong database role."""


APPLICATION_DATABASE_ROLE = "patent_evidence_app"
PLATFORM_DATABASE_ROLE = "patent_evidence_platform"
WORKER_DATABASE_ROLE = "patent_evidence_worker"


async def lock_organization_authority(
    session: AsyncSession, organization_id: UUID
) -> None:
    """Serialize lifecycle and administrative authority decisions per tenant."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"organization-admin-invariant:{organization_id}"},
    )


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def _create_role_session_factory(
    engine: AsyncEngine, expected_role: str
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
        info={"expected_database_role": expected_role},
    )


def create_application_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return _create_role_session_factory(engine, APPLICATION_DATABASE_ROLE)


def create_platform_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return _create_role_session_factory(engine, PLATFORM_DATABASE_ROLE)


def create_worker_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return _create_role_session_factory(engine, WORKER_DATABASE_ROLE)


async def verify_database_role(session: AsyncSession, expected_role: str) -> None:
    factory_role = session.info.get("expected_database_role")
    if factory_role != expected_role:
        factory_label = (
            "application"
            if factory_role == APPLICATION_DATABASE_ROLE
            else str(factory_role)
        )
        raise UnexpectedDatabaseRoleError(
            f"expected database role {expected_role}; received {factory_label} session factory"
        )
    actual_role = await session.scalar(text("SELECT current_user"))
    if actual_role != expected_role:
        raise UnexpectedDatabaseRoleError(
            f"expected database role {expected_role}, connected as {actual_role}"
        )


async def bind_session_token_hash(
    session: AsyncSession, session_token_hash: str
) -> None:
    if not session_token_hash:
        raise ValueError("session_token_hash must not be empty")
    if not session.in_transaction():
        raise RuntimeError("session token context must be bound inside a transaction")
    await session.execute(
        text("SELECT set_config('app.current_session_token_hash', :value, true)"),
        {"value": session_token_hash},
    )


async def bind_invitation_token_hash(
    session: AsyncSession, invitation_token_hash: str
) -> None:
    if not invitation_token_hash:
        raise ValueError("invitation_token_hash must not be empty")
    if not session.in_transaction():
        raise RuntimeError(
            "invitation token context must be bound inside a transaction"
        )
    await session.execute(
        text("SELECT set_config('app.current_invitation_token_hash', :value, true)"),
        {"value": invitation_token_hash},
    )


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
        (
            "app.current_organization_id",
            str(organization_id) if organization_id else "",
        ),
        (
            "app.current_actor_identity_id",
            str(actor_identity_id) if actor_identity_id else "",
        ),
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
        raise MissingTenantContextError(
            "organization repository requires tenant context"
        )
    return UUID(str(value))


@asynccontextmanager
async def application_transaction(
    factory: async_sessionmaker[AsyncSession],
    *,
    actor_identity_id: UUID | None = None,
    request_correlation_id: str | None = None,
) -> AsyncIterator[AsyncSession]:
    async with factory() as session, session.begin():
        await verify_database_role(session, APPLICATION_DATABASE_ROLE)
        await bind_transaction_context(
            session,
            organization_id=None,
            actor_identity_id=actor_identity_id,
            request_correlation_id=request_correlation_id,
        )
        yield session


@asynccontextmanager
async def tenant_transaction(
    factory: async_sessionmaker[AsyncSession],
    organization_id: UUID,
    *,
    actor_identity_id: UUID | None = None,
    request_correlation_id: str | None = None,
) -> AsyncIterator[AsyncSession]:
    async with factory() as session, session.begin():
        await verify_database_role(session, APPLICATION_DATABASE_ROLE)
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
        await verify_database_role(session, PLATFORM_DATABASE_ROLE)
        await bind_transaction_context(
            session,
            organization_id=None,
            actor_identity_id=actor_identity_id,
            request_correlation_id=request_correlation_id,
        )
        yield session


@asynccontextmanager
async def worker_transaction(
    factory: async_sessionmaker[AsyncSession],
    organization_id: UUID,
    *,
    actor_identity_id: UUID | None = None,
    request_correlation_id: str | None = None,
) -> AsyncIterator[AsyncSession]:
    async with factory() as session, session.begin():
        await verify_database_role(session, WORKER_DATABASE_ROLE)
        await bind_transaction_context(
            session,
            organization_id=organization_id,
            actor_identity_id=actor_identity_id,
            request_correlation_id=request_correlation_id,
        )
        yield session


@asynccontextmanager
async def session_token_transaction(
    factory: async_sessionmaker[AsyncSession],
    session_token_hash: str,
    *,
    actor_identity_id: UUID | None = None,
    request_correlation_id: str | None = None,
) -> AsyncIterator[AsyncSession]:
    async with factory() as session, session.begin():
        await verify_database_role(session, APPLICATION_DATABASE_ROLE)
        await bind_transaction_context(
            session,
            organization_id=None,
            actor_identity_id=actor_identity_id,
            request_correlation_id=request_correlation_id,
        )
        await bind_session_token_hash(session, session_token_hash)
        yield session


@asynccontextmanager
async def invitation_token_transaction(
    factory: async_sessionmaker[AsyncSession], invitation_token_hash: str
) -> AsyncIterator[AsyncSession]:
    async with factory() as session, session.begin():
        await verify_database_role(session, APPLICATION_DATABASE_ROLE)
        await bind_transaction_context(session, organization_id=None)
        await bind_invitation_token_hash(session, invitation_token_hash)
        yield session
