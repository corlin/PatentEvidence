"""Fetch, archive and record claim texts (ADR 0009).

US: ODP lookup by patent number -> grant XML link -> grant XML; only the
<claims> element is stored in the database (the full XML, which names
inventors, goes to object storage). EP: OPS claims JSON for the exact
publication. A source failure writes nothing; "not found" is recorded.

The stored text is what the source publishes: US claims *as granted* (later
reexamination, IPR or correction certificates are not in the grant XML), EP
claims of that specific publication (a B2/B3 replaces B1).
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from adapters.legal_status.clients import (
    EpoOpsLegalClient,
    LegalStatusSourceError,
    SourceResponse,
    UsptoOdpClient,
)
from adapters.object_storage.client import ObjectStorageClient
from patent_evidence_worker.legal_status_refresh import parse_publication_number


@dataclass(frozen=True)
class ClaimFetchResult:
    publication_number: str
    document_id: uuid.UUID
    outcome: str  # "found" | "not_found"
    text_represents: str | None


def extract_claims_element(xml: str) -> str:
    """The <claims>...</claims> element of a USPTO grant XML; raises if absent."""
    start = xml.find("<claims")
    end = xml.find("</claims>")
    if start < 0 or end < 0 or end < start:
        raise LegalStatusSourceError("grant XML has no <claims> element")
    return xml[start : end + len("</claims>")]


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    # USPTO gives no UTC offset; UTC is assumed for the column (file time, not a data date).
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class ClaimDocumentFetcher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        storage: ObjectStorageClient,
        *,
        odp: UsptoOdpClient | None = None,
        ops: EpoOpsLegalClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._odp = odp
        self._ops = ops
        self._clock = clock or (lambda: datetime.now(UTC))

    async def fetch(self, publication_number: str) -> ClaimFetchResult:
        country, number, kind = parse_publication_number(publication_number)
        file_created: datetime | None = None
        if country == "US":
            if self._odp is None:
                raise RuntimeError("USPTO ODP client is not configured")
            source, represents, extension = "uspto_grant_xml", "as_granted", "xml"
            record = await self._odp.file_wrapper_response(number)
            grant = (record.data or {}).get("grantDocumentMetaData") or {}
            uri = grant.get("fileLocationURI")
            if record.data is None or not uri:
                response = SourceResponse(None, None, record.request_ref)
                claims_text = None
            else:
                response = await self._odp.grant_xml_response(uri)
                response = SourceResponse(response.data, response.raw, f"{record.request_ref} -> {response.request_ref}")
                claims_text = (
                    extract_claims_element(response.raw.decode("utf-8")) if response.raw is not None else None
                )
                file_created = _timestamp(grant.get("fileCreateDateTime"))
        else:
            if self._ops is None:
                raise RuntimeError("EPO OPS client is not configured")
            source, represents, extension = "epo_ops_claims", "as_published", "json"
            response = await self._ops.claims_response(country, number, kind)
            claims_text = response.raw.decode("utf-8") if response.raw is not None and response.data else None

        retrieved_at = self._clock()
        raw_sha = raw_key = None
        if response.raw is not None and claims_text is not None:
            raw_sha = hashlib.sha256(response.raw).hexdigest()
            raw_key = f"public/claim-documents/{source}/{raw_sha}.{extension}"
            await self._storage.put_object(raw_key, response.raw, "application/octet-stream")

        found = claims_text is not None
        document_id = uuid.uuid4()
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    """INSERT INTO patent_claim_documents
                    (id, publication_number, source, request_ref, retrieved_at, source_file_created_at,
                     outcome, claims_text, text_represents, raw_sha256, raw_size_bytes, raw_storage_key)
                    VALUES (:id, :pub, :source, :ref, :retrieved, :file_created, :outcome, :claims,
                            :represents, :sha, :size, :key)"""
                ),
                {
                    "id": document_id,
                    "pub": publication_number,
                    "source": source,
                    "ref": response.request_ref,
                    "retrieved": retrieved_at,
                    "file_created": file_created,
                    "outcome": "found" if found else "not_found",
                    "claims": claims_text,
                    "represents": represents if found else None,
                    "sha": raw_sha,
                    "size": len(response.raw) if found and response.raw is not None else None,
                    "key": raw_key,
                },
            )
        return ClaimFetchResult(publication_number, document_id, "found" if found else "not_found", represents if found else None)
