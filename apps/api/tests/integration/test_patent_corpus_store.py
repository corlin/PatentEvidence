"""US/EP corpus loads (ADR 0007): grants, append-only, atomic loads."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, date, datetime

import psycopg
import pytest
from test_support import async_postgres_url, postgres_url

from modules.corpus.query import CorpusScope, build_corpus_query, query_sha256
from modules.corpus.store import record_load
from patent_evidence_api.core.database import create_engine, create_worker_session_factory

SCOPE = CorpusScope(as_of=date(2026, 10, 4))
NOW = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)


@pytest.fixture
def migration() -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        postgres_url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration"), autocommit=True
    ) as connection:
        connection.execute("DELETE FROM patent_corpus_members")
        connection.execute("DELETE FROM patent_corpus_loads")
        yield connection


def _member(number: str, **overrides):
    member = {
        "publication_number": number, "jurisdiction": "US", "kind": "B2",
        "application_number": f"US-{number}-A", "family_id": "1", "filing_date": date(2010, 1, 1),
        "grant_date": date(2012, 1, 1), "priority_date": None, "cpc_codes": ["H01M50/20"],
        "ipc_codes": ["H01M2/10"], "assignees_original": ["A CORP"], "assignees_harmonized": ["A CORP"],
        "title_en": "Battery module", "title_original": None, "scope_match": "both",
    }
    member.update(overrides)
    return member


async def _load(members):
    engine = create_engine(async_postgres_url("PE_TEST_WORKER_DATABASE_URL", "patent_evidence_worker"))
    try:
        async with create_worker_session_factory(engine)() as session, session.begin():
            sql = build_corpus_query(SCOPE)
            return await record_load(
                session, scope=SCOPE, sql=sql, members=members, started_at=NOW, finished_at=NOW,
                bytes_billed=123, source_table_modified_at=NOW, batch_size=2,
            )
    finally:
        await engine.dispose()


def test_tables_are_global_append_only_with_exact_grants(migration: psycopg.Connection) -> None:
    grants = migration.execute(
        """SELECT table_name, grantee, privilege_type FROM information_schema.role_table_grants
        WHERE table_name IN ('patent_corpus_loads', 'patent_corpus_members')
          AND grantee IN ('patent_evidence_app', 'patent_evidence_worker', 'patent_evidence_platform')
        ORDER BY 1, 2, 3"""
    ).fetchall()
    assert grants == [
        ("patent_corpus_loads", "patent_evidence_app", "SELECT"),
        ("patent_corpus_loads", "patent_evidence_worker", "INSERT"),
        ("patent_corpus_loads", "patent_evidence_worker", "SELECT"),
        ("patent_corpus_members", "patent_evidence_app", "SELECT"),
        ("patent_corpus_members", "patent_evidence_worker", "INSERT"),
        ("patent_corpus_members", "patent_evidence_worker", "SELECT"),
    ]
    for table in ("patent_corpus_loads", "patent_corpus_members"):
        columns = {r[0] for r in migration.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,)
        )}
        assert not columns & {"organization_id", "case_id"}


def test_load_round_trip_records_scope_query_and_count(migration: psycopg.Connection) -> None:
    members = [_member(f"US-{n}-B2") for n in (1, 2, 3, 4, 5)]
    load_id, count = asyncio.run(_load(members))
    assert count == 5
    row = migration.execute(
        "SELECT row_count, query_sha256, scope->>'us_filing_date_cutoff', bytes_billed FROM patent_corpus_loads WHERE id = %s",
        (load_id,),
    ).fetchone()
    assert row == (5, query_sha256(build_corpus_query(SCOPE)), "2001-10-04", 123)
    stored = migration.execute(
        "SELECT publication_number, cpc_codes, filing_date FROM patent_corpus_members WHERE load_id = %s ORDER BY 1",
        (load_id,),
    ).fetchall()
    assert [r[0] for r in stored] == [m["publication_number"] for m in members]
    assert stored[0][1] == ["H01M50/20"] and stored[0][2] == date(2010, 1, 1)


def test_failed_load_leaves_nothing_behind(migration: psycopg.Connection) -> None:
    members = [_member("US-1-B2"), _member("US-2-B2"), _member("US-3-B2", jurisdiction="XX")]
    with pytest.raises(Exception):
        asyncio.run(_load(members))
    assert migration.execute("SELECT count(*) FROM patent_corpus_loads").fetchone() == (0,)
    assert migration.execute("SELECT count(*) FROM patent_corpus_members").fetchone() == (0,)


def test_runtime_roles_cannot_rewrite_loads(migration: psycopg.Connection) -> None:
    load_id, _ = asyncio.run(_load([_member("US-1-B2")]))
    for variable, role in (
        ("PE_TEST_WORKER_DATABASE_URL", "patent_evidence_worker"),
        ("PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app"),
    ):
        with psycopg.connect(postgres_url(variable, role), autocommit=True) as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("UPDATE patent_corpus_loads SET row_count = 99 WHERE id = %s", (load_id,))
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("DELETE FROM patent_corpus_members WHERE load_id = %s", (load_id,))
