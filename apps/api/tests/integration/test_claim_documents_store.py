"""Claim-text store (ADR 0009): grants, US two-step fetch, EP fetch, parse round trip."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg
import pytest
from test_support import async_postgres_url, postgres_url

from adapters.legal_status.clients import EpoOpsLegalClient, LegalStatusSourceError, UsptoOdpClient
from adapters.object_storage.client import ObjectStorageClient
from modules.fto.ep_claims import parse_ep_claims
from modules.fto.us_claims import parse_us_claims
from patent_evidence_api.core.database import create_engine, create_worker_session_factory
from patent_evidence_worker.claim_documents import ClaimDocumentFetcher

FTO = Path(__file__).resolve().parents[4] / "fixtures" / "fto"
NOW = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)
GRANT_URI = "https://api.uspto.gov/api/v1/datasets/products/files/PTGRXML-SPLT/2026/ipg260519/17780957_12630442.xml"


@pytest.fixture
def migration() -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        postgres_url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration"), autocommit=True
    ) as connection:
        connection.execute("DELETE FROM patent_claim_documents")
        yield connection


def _grant_xml() -> bytes:
    claims = (FTO / "us" / "US-12630442-claims.xml").read_text()
    return (
        '<?xml version="1.0"?><us-patent-grant><us-bibliographic-data-grant>'
        "<inventor>Personal Name</inventor></us-bibliographic-data-grant>"
        f"{claims}</us-patent-grant>"
    ).encode()


def _odp(file_wrapper: dict | None, xml: bytes | None = None, xml_status: int = 200) -> UsptoOdpClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/applications/search"):
            if file_wrapper is None:
                return httpx.Response(200, json={"count": 0})
            return httpx.Response(200, json={"count": 1, "patentFileWrapperDataBag": [file_wrapper]})
        if request.url.host == "api.uspto.gov":
            return httpx.Response(302, headers={"location": "https://data.uspto.gov/files/x.xml?Signature=s"})
        return httpx.Response(xml_status, content=xml or b"")

    return UsptoOdpClient("k", transport=httpx.MockTransport(handler), backoff_seconds=0)


def _ops(payload: dict | None) -> EpoOpsLegalClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/accesstoken"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": "1199"})
        return httpx.Response(404) if payload is None else httpx.Response(200, json=payload)

    return EpoOpsLegalClient("id", "s", transport=httpx.MockTransport(handler), backoff_seconds=0)


async def _fetch(publication: str, tmp_path: Path, *, odp=None, ops=None):
    engine = create_engine(async_postgres_url("PE_TEST_WORKER_DATABASE_URL", "patent_evidence_worker"))
    try:
        fetcher = ClaimDocumentFetcher(
            create_worker_session_factory(engine), ObjectStorageClient(tmp_path), odp=odp, ops=ops, clock=lambda: NOW
        )
        return await fetcher.fetch(publication)
    finally:
        await engine.dispose()


WRAPPER = {"grantDocumentMetaData": {"fileLocationURI": GRANT_URI, "fileCreateDateTime": "2026-05-19T08:10:04"}}


def test_grants_are_exact_and_append_only(migration: psycopg.Connection) -> None:
    grants = migration.execute(
        """SELECT grantee, privilege_type FROM information_schema.role_table_grants
        WHERE table_name = 'patent_claim_documents'
          AND grantee IN ('patent_evidence_app', 'patent_evidence_worker', 'patent_evidence_platform')
        ORDER BY 1, 2"""
    ).fetchall()
    assert grants == [
        ("patent_evidence_app", "SELECT"),
        ("patent_evidence_worker", "INSERT"),
        ("patent_evidence_worker", "SELECT"),
    ]


def test_us_fetch_stores_claims_only_and_parses(migration: psycopg.Connection, tmp_path: Path) -> None:
    result = asyncio.run(_fetch("US-12630442-B2", tmp_path, odp=_odp(WRAPPER, _grant_xml())))
    assert (result.outcome, result.text_represents) == ("found", "as_granted")
    claims_text, ref, key, file_created = migration.execute(
        "SELECT claims_text, request_ref, raw_storage_key, source_file_created_at FROM patent_claim_documents WHERE id = %s",
        (result.document_id,),
    ).fetchone()
    assert claims_text.startswith("<claims") and "Personal Name" not in claims_text  # personal data stays out of the DB
    assert "Personal Name" in (tmp_path / key).read_text()  # full XML archived as received
    assert "Signature" not in ref and ref.count("->") == 2  # ODP lookup -> grant URI -> signed redirect
    assert file_created is not None
    parsed = parse_us_claims(claims_text, publication_number="US-12630442-B2")
    assert len(parsed.claims) == 11 and parsed.claim(2).depends_on == (1,)


def test_ep_fetch_stores_published_claims_and_parses(migration: psycopg.Connection, tmp_path: Path) -> None:
    payload = json.loads((FTO / "ep" / "EP-3467934-B1-claims.json").read_text())
    result = asyncio.run(_fetch("EP-3467934-B1", tmp_path, ops=_ops(payload)))
    assert (result.outcome, result.text_represents) == ("found", "as_published")
    claims_text = migration.execute(
        "SELECT claims_text FROM patent_claim_documents WHERE id = %s", (result.document_id,)
    ).fetchone()[0]
    assert parse_ep_claims(json.loads(claims_text), publication_number="EP-3467934-B1").claim(6).depends_on == (1, 2, 3, 4, 5)


@pytest.mark.parametrize(
    ("publication", "kwargs"),
    [
        ("US-99999999-B2", {"odp": _odp(None)}),
        ("US-12630442-B2", {"odp": _odp({"grantDocumentMetaData": {}})}),
        ("EP-1819002-A1", {"ops": _ops(None)}),
    ],
)
def test_not_found_is_recorded_without_text(migration: psycopg.Connection, tmp_path: Path, publication, kwargs) -> None:
    result = asyncio.run(_fetch(publication, tmp_path, **kwargs))
    assert result.outcome == "not_found"
    assert migration.execute(
        "SELECT outcome, claims_text, raw_sha256 FROM patent_claim_documents WHERE id = %s", (result.document_id,)
    ).fetchone() == ("not_found", None, None)


@pytest.mark.parametrize(
    "odp",
    [
        _odp(WRAPPER, b"<us-patent-grant>no claims here</us-patent-grant>"),  # no <claims> element
        _odp(WRAPPER, xml_status=500),  # source failure
    ],
)
def test_failures_write_nothing(migration: psycopg.Connection, tmp_path: Path, odp) -> None:
    with pytest.raises(LegalStatusSourceError):
        asyncio.run(_fetch("US-12630442-B2", tmp_path, odp=odp))
    assert migration.execute("SELECT count(*) FROM patent_claim_documents").fetchone() == (0,)
