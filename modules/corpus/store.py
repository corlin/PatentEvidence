"""Persist one corpus load atomically (ADR 0007)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.corpus.query import SOURCE_TABLE, CorpusScope, query_sha256

_INSERT_MEMBER = text(
    """INSERT INTO patent_corpus_members
    (load_id, publication_number, jurisdiction, kind, application_number, family_id,
     filing_date, grant_date, priority_date, cpc_codes, ipc_codes, assignees_original,
     assignees_harmonized, title_en, title_original, scope_match)
    VALUES (:load_id, :publication_number, :jurisdiction, :kind, :application_number, :family_id,
            :filing_date, :grant_date, :priority_date, :cpc_codes, :ipc_codes, :assignees_original,
            :assignees_harmonized, :title_en, :title_original, :scope_match)"""
)


async def record_load(
    session: AsyncSession,
    *,
    scope: CorpusScope,
    sql: str,
    members: Sequence[dict[str, Any]],
    started_at: datetime,
    finished_at: datetime,
    bytes_billed: int | None,
    source_table_modified_at: datetime | None,
    batch_size: int = 1000,
) -> tuple[uuid.UUID, int]:
    """Insert the load row and all members in the caller's transaction.

    The tables are append-only (no UPDATE grant), so the row count is known before
    the load row is written. Run inside one transaction: a load that fails part-way
    leaves nothing behind.
    """
    load_id = uuid.uuid4()
    batch: list[dict[str, Any]] = []
    count = 0
    await session.execute(
        text(
            """INSERT INTO patent_corpus_loads
            (id, as_of, scope, source, source_table_modified_at, query_text, query_sha256,
             bytes_billed, row_count, started_at, finished_at)
            VALUES (:id, :as_of, CAST(:scope AS jsonb), :source, :modified, :sql, :sha,
                    :bytes, :row_count, :started, :finished)"""
        ),
        {
            "id": load_id,
            "as_of": scope.as_of,
            "scope": json.dumps(scope.as_record()),
            "source": f"bigquery:{SOURCE_TABLE}",
            "modified": source_table_modified_at,
            "sql": sql,
            "sha": query_sha256(sql),
            "bytes": bytes_billed,
            "row_count": len(members),
            "started": started_at,
            "finished": finished_at,
        },
    )
    for member in members:
        batch.append({"load_id": load_id, **member})
        if len(batch) >= batch_size:
            await session.execute(_INSERT_MEMBER, batch)
            count += len(batch)
            batch = []
    if batch:
        await session.execute(_INSERT_MEMBER, batch)
        count += len(batch)
    if count != len(members):  # defensive: the recorded count must match what was written
        raise RuntimeError(f"wrote {count} members but recorded {len(members)}")
    return load_id, count
