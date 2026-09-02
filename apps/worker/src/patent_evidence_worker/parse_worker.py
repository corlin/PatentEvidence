from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from adapters.object_storage.client import ObjectStorageClient
from modules.cases.parser import DocumentParser


class ParseTaskWorker:
    """Processes document parse runs using PostgreSQL FOR UPDATE SKIP LOCKED."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        storage: ObjectStorageClient,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._clock = clock or (lambda: datetime.now(UTC))
        self._parser = DocumentParser()

    async def run_once(self) -> bool:
        """Attempt to claim and process one queued parse task. Returns True if work was done."""
        now = self._clock()

        async with self._session_factory() as session:
            # 1. Claim next task with row lock
            claim_row = (
                (
                    await session.execute(
                        text(
                            """SELECT pr.id, pr.organization_id, pr.case_id, pr.source_document_id,
                                   sd.filename, sd.mime_type, sd.storage_key
                            FROM parse_runs pr
                            JOIN source_documents sd ON sd.id=pr.source_document_id
                            WHERE pr.status='queued'
                            ORDER BY pr.created_at ASC
                            LIMIT 1
                            FOR UPDATE OF pr SKIP LOCKED"""
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )

            if claim_row is None:
                await session.rollback()
                return False

            run_id = claim_row["id"]
            org_id = claim_row["organization_id"]
            case_id = claim_row["case_id"]
            doc_id = claim_row["source_document_id"]
            filename = claim_row["filename"]
            mime_type = claim_row["mime_type"]
            storage_key = claim_row["storage_key"]

            # Mark running
            await session.execute(
                text(
                    """UPDATE parse_runs
                    SET status='running', started_at=:now
                    WHERE id=:run_id"""
                ),
                {"run_id": run_id, "now": now},
            )
            await session.commit()

        # 2. Process outside lock to avoid long transaction
        try:
            raw_bytes = await self._storage.get_object(storage_key)
            if raw_bytes is None:
                raise ValueError(f"source file not found in storage at {storage_key}")

            parsed = self._parser.parse_bytes(raw_bytes, filename, mime_type)

            async with self._session_factory() as session:
                # Bind tenant context
                await session.execute(
                    text("SELECT set_config('app.current_organization_id', :org_id, false)"),
                    {"org_id": str(org_id)},
                )

                # Get next version number
                next_ver = (
                    await session.scalar(
                        text(
                            """SELECT COALESCE(MAX(version_number), 0) + 1
                            FROM document_versions
                            WHERE case_id=:case_id"""
                        ),
                        {"case_id": case_id},
                    )
                    or 1
                )

                ver_id = uuid4()
                await session.execute(
                    text(
                        """INSERT INTO document_versions
                        (id, organization_id, case_id, source_document_id, version_number,
                         parent_version_id, parsed_text, structure_json, sha256, is_confirmed, created_at)
                        VALUES
                        (:id, :org_id, :case_id, :doc_id, :ver_num,
                         NULL, :text, :json_data, :sha256, false, :now)"""
                    ),
                    {
                        "id": ver_id,
                        "org_id": org_id,
                        "case_id": case_id,
                        "doc_id": doc_id,
                        "ver_num": next_ver,
                        "text": parsed.parsed_text,
                        "json_data": json.dumps(parsed.paragraphs),
                        "sha256": parsed.sha256,
                        "now": self._clock(),
                    },
                )

                # Save extracted drawings to object storage and database
                for d in parsed.drawings:
                    drawing_key = f"org/{org_id}/case/{case_id}/drawings/{d.sha256}_{d.filename}"
                    await self._storage.put_object(drawing_key, d.data, d.mime_type)
                    drawing_id = uuid4()
                    await session.execute(
                        text(
                            """INSERT INTO case_drawings
                            (id, organization_id, case_id, source_document_id, document_version_id,
                             figure_label, figure_title, reference_marks, storage_key, mime_type,
                             file_size, sha256, page_number, order_index, is_manually_added, created_at, updated_at)
                            VALUES
                            (:id, :org_id, :case_id, :doc_id, :ver_id,
                             :label, :title, :marks, :key, :mime,
                             :size, :sha256, :page_num, :order, false, :now, :now)"""
                        ),
                        {
                            "id": drawing_id,
                            "org_id": org_id,
                            "case_id": case_id,
                            "doc_id": doc_id,
                            "ver_id": ver_id,
                            "label": d.figure_label,
                            "title": d.figure_title,
                            "marks": json.dumps(d.reference_marks),
                            "key": drawing_key,
                            "mime": d.mime_type,
                            "size": len(d.data),
                            "sha256": d.sha256,
                            "page_num": d.page_number,
                            "order": d.order_index,
                            "now": self._clock(),
                        },
                    )

                # Mark parse_run completed
                await session.execute(
                    text(
                        """UPDATE parse_runs
                        SET status='completed', finished_at=:now
                        WHERE id=:run_id"""
                    ),
                    {"run_id": run_id, "now": self._clock()},
                )
                await session.commit()
                return True

        except Exception as exc:
            async with self._session_factory() as session:
                await session.execute(
                    text(
                        """UPDATE parse_runs
                        SET status='failed', error_summary=:err, finished_at=:now
                        WHERE id=:run_id"""
                    ),
                    {"run_id": run_id, "err": str(exc)[:500], "now": self._clock()},
                )
                await session.commit()
                return True
