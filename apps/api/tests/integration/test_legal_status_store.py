"""Global legal-status store (ADR 0006): grants, append-only, reproducible assessments."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
import pytest
from test_support import async_postgres_url, postgres_url

from adapters.legal_status.clients import EpoOpsLegalClient, LegalStatusSourceError, UsptoOdpClient
from adapters.object_storage.client import ObjectStorageClient
from modules.legal_status.ep import assess_ep
from modules.legal_status.serialize import RULES_VERSION, content_sha256
from modules.legal_status.us import assess_us
from patent_evidence_api.core.database import create_engine, create_worker_session_factory
from patent_evidence_worker.legal_status_refresh import LegalStatusRefresher

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "legal-status"
TABLES = ("legal_status_source_records", "legal_status_assessments")
AS_OF = date(2026, 10, 4)
NOW = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)


@pytest.fixture
def migration() -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        postgres_url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration"), autocommit=True
    ) as connection:
        connection.execute("DELETE FROM legal_status_assessments")
        connection.execute("DELETE FROM legal_status_source_records")
        yield connection


def _runtime(variable: str, role: str) -> psycopg.Connection:
    return psycopg.connect(postgres_url(variable, role), autocommit=True)


def _insert_record(connection: psycopg.Connection, **overrides: object) -> None:
    row = {
        "id": uuid4(),
        "pub": "US-1-B2",
        "source": "uspto_odp",
        "ref": "GET test",
        "outcome": "not_found",
        "extract": None,
        "sha": None,
    }
    row.update(overrides)
    connection.execute(
        """INSERT INTO legal_status_source_records
        (id, publication_number, source, request_ref, retrieved_at, outcome, extract, raw_sha256)
        VALUES (%(id)s, %(pub)s, %(source)s, %(ref)s, now(), %(outcome)s, %(extract)s, %(sha)s)""",
        row,
    )


def test_tables_are_global_with_exact_grants(migration: psycopg.Connection) -> None:
    for table in TABLES:
        rls, force, owner = migration.execute(
            """SELECT c.relrowsecurity, c.relforcerowsecurity, o.rolname
            FROM pg_class c JOIN pg_roles o ON o.oid = c.relowner WHERE c.oid = %s::regclass""",
            (table,),
        ).fetchone()
        # Public data shared by all organizations: no tenant RLS, owned by the migration role.
        assert (rls, force, owner) == (False, False, "patent_evidence_migration")
        columns = {r[0] for r in migration.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,)
        )}
        assert not columns & {"organization_id", "case_id", "requested_by"}
    grants = migration.execute(
        """SELECT table_name, grantee, privilege_type FROM information_schema.role_table_grants
        WHERE table_name IN ('legal_status_source_records', 'legal_status_assessments')
          AND grantee IN ('patent_evidence_app', 'patent_evidence_worker', 'patent_evidence_platform')
        ORDER BY 1, 2, 3"""
    ).fetchall()
    assert grants == [
        ("legal_status_assessments", "patent_evidence_app", "SELECT"),
        ("legal_status_assessments", "patent_evidence_worker", "INSERT"),
        ("legal_status_assessments", "patent_evidence_worker", "SELECT"),
        ("legal_status_source_records", "patent_evidence_app", "SELECT"),
        ("legal_status_source_records", "patent_evidence_worker", "INSERT"),
        ("legal_status_source_records", "patent_evidence_worker", "SELECT"),
    ]


def test_app_reads_but_cannot_write(migration: psycopg.Connection) -> None:
    with _runtime("PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app") as app:
        assert app.execute("SELECT count(*) FROM legal_status_source_records").fetchone() == (0,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            _insert_record(app)


def test_worker_appends_but_cannot_rewrite(migration: psycopg.Connection) -> None:
    record_id = uuid4()
    with _runtime("PE_TEST_WORKER_DATABASE_URL", "patent_evidence_worker") as worker:
        _insert_record(worker, id=record_id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            worker.execute("UPDATE legal_status_source_records SET outcome = 'found' WHERE id = %s", (record_id,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            worker.execute("DELETE FROM legal_status_source_records WHERE id = %s", (record_id,))


def test_found_records_must_carry_extract_and_hash(migration: psycopg.Connection) -> None:
    with _runtime("PE_TEST_WORKER_DATABASE_URL", "patent_evidence_worker") as worker:
        with pytest.raises(psycopg.errors.CheckViolation):
            _insert_record(worker, outcome="found")
        with pytest.raises(psycopg.errors.CheckViolation):
            _insert_record(worker, outcome="found", extract=json.dumps({}), sha="not-a-sha")


# ------------------------------------------------------------- refresher end to end


def _odp_transport(body: dict | None, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


def _ops_transport(payload: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/accesstoken"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": "1199"})
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


async def _refresh(publication: str, *, odp=None, ops=None, ep_filing_date=None, storage_dir: Path):
    engine = create_engine(async_postgres_url("PE_TEST_WORKER_DATABASE_URL", "patent_evidence_worker"))
    try:
        refresher = LegalStatusRefresher(
            create_worker_session_factory(engine),
            ObjectStorageClient(storage_dir),
            odp=odp,
            ops=ops,
            clock=lambda: NOW,
        )
        return await refresher.refresh(publication, as_of=AS_OF, ep_filing_date=ep_filing_date)
    finally:
        await engine.dispose()


def test_refresh_us_stores_reproducible_assessment(migration: psycopg.Connection, tmp_path: Path) -> None:
    fixture = json.loads((FIXTURES / "us" / "US-7252747.json").read_text())
    odp = UsptoOdpClient("k", transport=_odp_transport({"count": 1, "patentFileWrapperDataBag": [fixture]}), backoff_seconds=0)
    result = asyncio.run(_refresh("US-7252747-B2", odp=odp, storage_dir=tmp_path))
    assert (result.outcome, result.status) == ("found", "expired")

    record = migration.execute(
        """SELECT source, outcome, extract, raw_sha256, raw_storage_key, raw_size_bytes, source_data_as_of
        FROM legal_status_source_records WHERE id = %s""",
        (result.source_record_id,),
    ).fetchone()
    source, outcome, extract, raw_sha, raw_key, raw_size, data_as_of = record
    assert (source, outcome) == ("uspto_odp", "found")
    # Exact response bytes are archived, content-addressed.
    raw = (tmp_path / raw_key).read_bytes()
    assert len(raw) == raw_size and raw_key.endswith(f"{raw_sha}.json")
    assert data_as_of is not None

    stored = migration.execute(
        "SELECT status, rules_version, content_sha256, term FROM legal_status_assessments WHERE id = %s",
        (result.assessment_id,),
    ).fetchone()
    assert stored[:2] == ("expired", RULES_VERSION)
    assert stored[3]["expiry_date"] == "2023-07-25"
    # Reproducible from the database alone: re-assessing the stored extract gives the same hash.
    again = assess_us(extract, publication_number="US-7252747-B2", as_of=AS_OF)
    assert content_sha256(again) == stored[2]


def test_refresh_ep_stores_country_evidence(migration: psycopg.Connection, tmp_path: Path) -> None:
    payload = json.loads((FIXTURES / "ep" / "EP-1801605-B1.json").read_text())
    ops = EpoOpsLegalClient("id", "s", transport=_ops_transport(payload), backoff_seconds=0)
    result = asyncio.run(
        _refresh("EP-1801605-B1", ops=ops, ep_filing_date=date(2006, 12, 22), storage_dir=tmp_path)
    )
    assert result.status == "lapsed"
    extract, countries, sha = migration.execute(
        """SELECT r.extract, a.countries, a.content_sha256 FROM legal_status_assessments a
        JOIN legal_status_source_records r ON r.id = a.source_record_id WHERE a.id = %s""",
        (result.assessment_id,),
    ).fetchone()
    assert {c["country"] for c in countries} >= {"DE", "FR", "GB"}
    again = assess_ep(extract, publication_number="EP-1801605-B1", filing_date=date(2006, 12, 22), as_of=AS_OF)
    assert content_sha256(again) == sha


def test_not_found_is_recorded_without_any_status(migration: psycopg.Connection, tmp_path: Path) -> None:
    odp = UsptoOdpClient("k", transport=_odp_transport({"count": 0}), backoff_seconds=0)
    result = asyncio.run(_refresh("US-99999999-B2", odp=odp, storage_dir=tmp_path))
    assert (result.outcome, result.assessment_id, result.status) == ("not_found", None, None)
    assert migration.execute(
        "SELECT outcome, extract, raw_sha256 FROM legal_status_source_records WHERE id = %s",
        (result.source_record_id,),
    ).fetchone() == ("not_found", None, None)
    assert migration.execute("SELECT count(*) FROM legal_status_assessments").fetchone() == (0,)


def test_source_failure_writes_nothing(migration: psycopg.Connection, tmp_path: Path) -> None:
    odp = UsptoOdpClient("k", transport=_odp_transport(None, status=500), backoff_seconds=0)
    with pytest.raises(LegalStatusSourceError):
        asyncio.run(_refresh("US-7252747-B2", odp=odp, storage_dir=tmp_path))
    for table in TABLES:
        assert migration.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
