"""Product descriptions and features (ADR 0010): RLS, immutability triggers, edit/confirm flow."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import HTTPException
from test_support import (
    BASELINE_IDENTITY_A,
    BASELINE_ORG_A,
    BASELINE_ORG_B,
    async_postgres_url,
    postgres_url,
    reset_database,
    seed_two_tenant_baseline,
)

from patent_evidence_api.core.database import create_application_session_factory, create_engine, tenant_transaction
from patent_evidence_api.fto.product_features import ProductFeatureService

ORG_A, ORG_B, ACTOR = UUID(BASELINE_ORG_A), UUID(BASELINE_ORG_B), UUID(BASELINE_IDENTITY_A)
CASE_A = UUID("70000000-0000-4000-8000-0000000000aa")
NOW = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)
SYNTHETIC = "1. 液冷板由铝合金挤压成型，厚度为2.5 mm。\n2. 冷却液流道呈蛇形布置；流道入口与出口位于同一侧。\n3. 液冷板与电芯之间设置导热垫。"


@pytest.fixture
def migration() -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        postgres_url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration"), autocommit=True
    ) as connection:
        reset_database(connection)
        seed_two_tenant_baseline(connection, NOW)
        connection.execute(
            """INSERT INTO cases (id, organization_id, case_number, title, technical_field, created_by_identity_id)
            VALUES (%s, %s, 'FTO-1', '液冷板 FTO（合成）', '电池热管理', %s)""",
            (CASE_A, ORG_A, ACTOR),
        )
        yield connection


def _run(organization: UUID, action):
    async def go():
        engine = create_engine(async_postgres_url("PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app"))
        try:
            async with tenant_transaction(create_application_session_factory(engine), organization, actor_identity_id=ACTOR) as session:
                return await action(session, ProductFeatureService(lambda: NOW))
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _draft() -> dict:
    async def action(session, service):
        description = await service.add_description(
            session, organization_id=ORG_A, case_id=CASE_A, description=SYNTHETIC, actor_id=ACTOR
        )
        return await service.create_draft(
            session, organization_id=ORG_A, case_id=CASE_A, description_id=UUID(description["id"]), actor_id=ACTOR
        )

    return _run(ORG_A, action)


def test_draft_from_description_has_exact_spans(migration: psycopg.Connection) -> None:
    draft = _draft()
    assert draft["status"] == "draft" and draft["version_number"] == 1
    assert [f["text"] for f in draft["features"]] == [
        "液冷板由铝合金挤压成型，厚度为2.5 mm。",
        "冷却液流道呈蛇形布置；",
        "流道入口与出口位于同一侧。",
        "液冷板与电芯之间设置导热垫。",
    ]
    for feature in draft["features"]:
        (start, end), = feature["spans"]
        assert SYNTHETIC[start:end] == feature["text"]


def test_other_tenant_cannot_see_product_data(migration: psycopg.Connection) -> None:
    draft = _draft()

    async def peek(session, service):
        return await service.get_set(session, organization_id=ORG_B, set_id=UUID(draft["id"]))

    with pytest.raises(HTTPException) as missing:
        _run(ORG_B, peek)
    assert missing.value.status_code == 404
    with psycopg.connect(postgres_url("PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app"), autocommit=True) as app:
        app.execute("SELECT set_config('app.current_organization_id', %s, false)", (str(ORG_B),))
        assert app.execute("SELECT count(*) FROM product_descriptions").fetchone() == (0,)
        assert app.execute("SELECT count(*) FROM product_features").fetchone() == (0,)


def test_edit_split_merge_add_delete_then_confirm(migration: psycopg.Connection) -> None:
    draft = _draft()
    set_id = UUID(draft["id"])

    async def edits(session, service):
        await service.merge_features(session, organization_id=ORG_A, set_id=set_id, codes=["P2", "P3"])
        await service.split_feature(session, organization_id=ORG_A, set_id=set_id, code="P1", at=12)  # just after the comma (index 11)
        await service.edit_feature(session, organization_id=ORG_A, set_id=set_id, code="P4", new_text="液冷板与电芯底面之间设置导热垫。")
        await service.add_feature(session, organization_id=ORG_A, set_id=set_id, feature_text="箱体为钢制。")
        return await service.delete_feature(session, organization_id=ORG_A, set_id=set_id, code="P6")

    result = _run(ORG_A, edits)
    by_code = {f["code"]: f for f in result["features"]}
    assert by_code["P2"]["text"] == "冷却液流道呈蛇形布置； 流道入口与出口位于同一侧。" and by_code["P2"]["origin"] == "split"
    assert by_code["P1"]["text"] == "液冷板由铝合金挤压成型，" and by_code["P1"]["origin"] == "split"
    (s, e), = by_code["P5"]["spans"]  # right half of the split keeps an exact span
    assert SYNTHETIC[s:e] == by_code["P5"]["text"] == "厚度为2.5 mm。"
    assert by_code["P4"]["origin"] == "edited"
    assert "P6" not in by_code  # the manual feature added above was deleted

    async def confirm(session, service):
        return await service.confirm(session, organization_id=ORG_A, set_id=set_id, actor_id=ACTOR)

    assert _run(ORG_A, confirm)["status"] == "confirmed"

    async def late_edit(session, service):
        return await service.add_feature(session, organization_id=ORG_A, set_id=set_id, feature_text="不应成功")

    with pytest.raises(HTTPException) as conflict:
        _run(ORG_A, late_edit)
    assert conflict.value.status_code == 409

    async def revise(session, service):
        return await service.create_revision(session, organization_id=ORG_A, set_id=set_id, actor_id=ACTOR)

    revision = _run(ORG_A, revise)
    assert revision["status"] == "draft" and revision["version_number"] == 2
    assert revision["parent_set_id"] == str(set_id)
    assert [f["code"] for f in revision["features"]] == [f["code"] for f in result["features"]]


def test_database_enforces_the_approval_boundary(migration: psycopg.Connection) -> None:
    """Even bypassing the service, a confirmed set and its features cannot change."""
    draft = _draft()
    set_id = UUID(draft["id"])
    _run(ORG_A, lambda session, service: service.confirm(session, organization_id=ORG_A, set_id=set_id, actor_id=ACTOR))
    with psycopg.connect(postgres_url("PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app"), autocommit=True) as app:
        app.execute("SELECT set_config('app.current_organization_id', %s, false)", (str(ORG_A),))
        for statement in (
            "UPDATE product_feature_sets SET status = 'draft' WHERE id = %s",
            "DELETE FROM product_feature_sets WHERE id = %s",
            "UPDATE product_features SET feature_text = 'changed' WHERE feature_set_id = %s",
            "DELETE FROM product_features WHERE feature_set_id = %s",
        ):
            with pytest.raises(psycopg.errors.RaiseException):
                app.execute(statement, (set_id,))
        with pytest.raises(psycopg.errors.RaiseException):
            app.execute(
                """INSERT INTO product_features (id, organization_id, case_id, feature_set_id, feature_code,
                   feature_text, origin, sort_order) VALUES (%s, %s, %s, %s, 'P99', 'x', 'manual', 99)""",
                (uuid4(), ORG_A, CASE_A, set_id),
            )
        # Descriptions are append-only for runtime roles.
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute("UPDATE product_descriptions SET description_text = 'x'")


def test_empty_set_cannot_be_confirmed(migration: psycopg.Connection) -> None:
    draft = _draft()
    set_id = UUID(draft["id"])

    async def empty_then_confirm(session, service):
        for feature in draft["features"]:
            await service.delete_feature(session, organization_id=ORG_A, set_id=set_id, code=feature["code"])
        return await service.confirm(session, organization_id=ORG_A, set_id=set_id, actor_id=ACTOR)

    with pytest.raises(HTTPException) as invalid:
        _run(ORG_A, empty_then_confirm)
    assert invalid.value.status_code == 422
