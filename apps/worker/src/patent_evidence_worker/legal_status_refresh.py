"""Fetch, archive, record and assess public patent legal status (ADR 0006).

Flow for one publication:

1. query the source (USPTO ODP for US, EPO OPS INPADOC for EP);
2. archive the exact response bytes in object storage, content-addressed by SHA-256;
3. insert a ``legal_status_source_records`` row (``not_found`` is recorded too);
4. assess **from the stored extract**, so the result is reproducible from the database;
5. insert a ``legal_status_assessments`` row with the canonical content hash.

If the source fails, the error propagates and nothing is written: no status
is ever fabricated. These tables are global and carry no tenant data, so the
worker needs no organization context here.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from adapters.legal_status.clients import EpoOpsLegalClient, SourceResponse, UsptoOdpClient
from adapters.object_storage.client import ObjectStorageClient
from modules.legal_status.ep import assess_ep
from modules.legal_status.serialize import (
    RULES_VERSION,
    assessment_to_dict,
    content_sha256,
    ep_extract,
    us_extract,
)
from modules.legal_status.us import assess_us


@dataclass(frozen=True)
class RefreshResult:
    publication_number: str
    source_record_id: uuid.UUID
    outcome: str  # "found" | "not_found"
    assessment_id: uuid.UUID | None
    status: str | None


def parse_publication_number(publication_number: str) -> tuple[str, str, str]:
    """``US-7252747-B2`` -> ("US", "7252747", "B2"); US reissues look like ``US-RE49000-E1``.

    Only US and EP are supported.
    """
    parts = publication_number.split("-")
    number_ok = len(parts) == 3 and (
        parts[1].isdigit() or (parts[0] == "US" and parts[1].startswith("RE") and parts[1][2:].isdigit())
    )
    if not number_ok or parts[0] not in ("US", "EP"):
        raise ValueError(f"unsupported publication number: {publication_number!r}")
    return parts[0], parts[1], parts[2]


def raw_storage_key(source: str, sha256: str) -> str:
    return f"public/legal-status/{source}/{sha256}.json"


class LegalStatusRefresher:
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

    async def refresh(
        self, publication_number: str, *, as_of: date, ep_filing_date: date | None = None
    ) -> RefreshResult:
        country, number, kind = parse_publication_number(publication_number)
        if country == "US":
            if self._odp is None:
                raise RuntimeError("USPTO ODP client is not configured")
            source = "uspto_odp"
            response = await self._odp.file_wrapper_response(number)
            extract = us_extract(response.data) if response.data is not None else None
            data_as_of = extract.get("lastIngestionDateTime") if extract else None
            assessment = (
                assess_us(extract, publication_number=publication_number, as_of=as_of)
                if extract is not None
                else None
            )
        else:
            if self._ops is None:
                raise RuntimeError("EPO OPS client is not configured")
            if ep_filing_date is None:
                raise ValueError("EP assessment needs the EP filing date (term start)")
            source = "epo_ops_inpadoc"
            response = await self._ops.legal_response(country, number, kind)
            extract = ep_extract(response.data) if response.data is not None else None
            data_as_of = None  # OPS reports no data snapshot time
            assessment = (
                assess_ep(
                    extract,
                    publication_number=publication_number,
                    filing_date=ep_filing_date,
                    as_of=as_of,
                )
                if extract is not None
                else None
            )

        retrieved_at = self._clock()
        raw_sha, raw_key = await self._archive(source, response)

        record_id = uuid.uuid4()
        assessment_id: uuid.UUID | None = None
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    """INSERT INTO legal_status_source_records
                    (id, publication_number, source, request_ref, retrieved_at, source_data_as_of,
                     outcome, extract, raw_sha256, raw_size_bytes, raw_storage_key)
                    VALUES (:id, :pub, :source, :request_ref, :retrieved_at, :data_as_of,
                            :outcome, CAST(:extract AS jsonb), :raw_sha, :raw_size, :raw_key)"""
                ),
                {
                    "id": record_id,
                    "pub": publication_number,
                    "source": source,
                    "request_ref": response.request_ref,
                    "retrieved_at": retrieved_at,
                    "data_as_of": _parse_timestamp(data_as_of),
                    "outcome": "found" if extract is not None else "not_found",
                    "extract": json.dumps(extract, ensure_ascii=False) if extract is not None else None,
                    "raw_sha": raw_sha,
                    "raw_size": len(response.raw) if response.raw is not None else None,
                    "raw_key": raw_key,
                },
            )
            if assessment is not None:
                assessment_id = uuid.uuid4()
                body = assessment_to_dict(assessment)
                await session.execute(
                    text(
                        """INSERT INTO legal_status_assessments
                        (id, source_record_id, publication_number, jurisdiction, as_of, rules_version,
                         status, term, countries, evidence, review_reasons, content_sha256, assessed_at)
                        VALUES (:id, :record, :pub, :jurisdiction, :as_of, :rules_version, :status,
                                CAST(:term AS jsonb), CAST(:countries AS jsonb), CAST(:evidence AS jsonb),
                                CAST(:reasons AS jsonb), :sha, :assessed_at)"""
                    ),
                    {
                        "id": assessment_id,
                        "record": record_id,
                        "pub": publication_number,
                        "jurisdiction": assessment.jurisdiction,
                        "as_of": as_of,
                        "rules_version": RULES_VERSION,
                        "status": assessment.status,
                        "term": _dumps(body["term"]) if body["term"] is not None else None,
                        "countries": _dumps(body["countries"]),
                        "evidence": _dumps(body["evidence"]),
                        "reasons": _dumps(body["review_reasons"]),
                        "sha": content_sha256(assessment),
                        "assessed_at": retrieved_at,
                    },
                )
        return RefreshResult(
            publication_number,
            record_id,
            "found" if extract is not None else "not_found",
            assessment_id,
            assessment.status if assessment else None,
        )

    async def _archive(self, source: str, response: SourceResponse) -> tuple[str | None, str | None]:
        if response.raw is None:
            return None, None
        sha = hashlib.sha256(response.raw).hexdigest()
        key = raw_storage_key(source, sha)
        await self._storage.put_object(key, response.raw, "application/json")
        return sha, key


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    # ODP gives no UTC offset and documents none that we have verified. The column
    # needs one, so UTC is assumed here; the original string is kept verbatim in
    # ``extract.lastIngestionDateTime`` and is the authoritative value.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
