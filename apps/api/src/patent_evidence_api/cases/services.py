import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.object_storage.client import ObjectStorageClient, build_source_key
from modules.cases.parser import DocumentParser
from modules.cases.upload_guard import UploadRejected, inspect_upload


class CaseService:
    """Manages cases, quota allocation, and document version confirmation."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    async def create_case(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        actor_identity_id: UUID,
        case_number: str,
        title: str,
        technical_field: str,
        target_jurisdiction: str = "CN",
    ) -> dict[str, Any]:
        now = self._clock()
        clean_case_num = case_number.strip()
        clean_title = title.strip()
        clean_field = technical_field.strip()

        if not clean_case_num or not clean_title or not clean_field:
            raise HTTPException(status_code=422, detail="missing_case_required_fields")

        # 1. Lock and check quota
        quota_row = (
            (
                await session.execute(
                    text(
                        """SELECT monthly_case_allowance, current_period_start, current_period_end
                        FROM organization_plan_quotas
                        WHERE organization_id=:org_id
                        FOR UPDATE"""
                    ),
                    {"org_id": organization_id},
                )
            )
            .mappings()
            .one_or_none()
        )

        if quota_row is not None:
            allowance = quota_row["monthly_case_allowance"]
            start = quota_row["current_period_start"]
            end = quota_row["current_period_end"]

            # Count cases in current period
            case_count = await session.scalar(
                text(
                    """SELECT COUNT(*) FROM cases
                    WHERE organization_id=:org_id AND created_at >= :start AND created_at < :end"""
                ),
                {"org_id": organization_id, "start": start, "end": end},
            ) or 0

            if case_count >= allowance:
                raise HTTPException(
                    status_code=422,
                    detail=f"monthly_case_quota_exceeded_limit_{allowance}",
                )

        # 2. Check unique case_number in organization
        exists = await session.scalar(
            text(
                """SELECT EXISTS(
                    SELECT 1 FROM cases WHERE organization_id=:org_id AND case_number=:case_num
                )"""
            ),
            {"org_id": organization_id, "case_num": clean_case_num},
        )
        if exists:
            raise HTTPException(status_code=409, detail="case_number_already_exists")

        case_id = uuid4()
        await session.execute(
            text(
                """INSERT INTO cases
                (id, organization_id, case_number, title, technical_field, target_jurisdiction,
                 status, created_by_identity_id, created_at, updated_at)
                VALUES
                (:id, :org_id, :case_num, :title, :tech_field, :jurisdiction,
                 'draft', :actor_id, :now, :now)"""
            ),
            {
                "id": case_id,
                "org_id": organization_id,
                "case_num": clean_case_num,
                "title": clean_title,
                "tech_field": clean_field,
                "jurisdiction": target_jurisdiction,
                "actor_id": actor_identity_id,
                "now": now,
            },
        )

        return {
            "id": str(case_id),
            "organization_id": str(organization_id),
            "case_number": clean_case_num,
            "title": clean_title,
            "technical_field": clean_field,
            "target_jurisdiction": target_jurisdiction,
            "status": "draft",
            "created_by": str(actor_identity_id),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

    async def list_cases(
        self, session: AsyncSession, organization_id: UUID
    ) -> list[dict[str, Any]]:
        rows = (
            (
                await session.execute(
                    text(
                        """SELECT id, organization_id, case_number, title, technical_field,
                               target_jurisdiction, status, created_by_identity_id,
                               created_at, updated_at
                        FROM cases
                        WHERE organization_id=:org_id
                        ORDER BY created_at DESC"""
                    ),
                    {"org_id": organization_id},
                )
            )
            .mappings()
            .all()
        )
        return [
            {
                "id": str(r["id"]),
                "organization_id": str(r["organization_id"]),
                "case_number": r["case_number"],
                "title": r["title"],
                "technical_field": r["technical_field"],
                "target_jurisdiction": r["target_jurisdiction"],
                "status": r["status"],
                "created_by": str(r["created_by_identity_id"]),
                "created_at": r["created_at"].isoformat(),
                "updated_at": r["updated_at"].isoformat(),
            }
            for r in rows
        ]

    async def get_case(
        self, session: AsyncSession, organization_id: UUID, case_id: UUID
    ) -> dict[str, Any] | None:
        case_row = (
            (
                await session.execute(
                    text(
                        """SELECT id, organization_id, case_number, title, technical_field,
                               target_jurisdiction, status, created_by_identity_id,
                               created_at, updated_at
                        FROM cases
                        WHERE id=:case_id AND organization_id=:org_id"""
                    ),
                    {"case_id": case_id, "org_id": organization_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if case_row is None:
            return None

        # Fetch latest source document
        doc_row = (
            (
                await session.execute(
                    text(
                        """SELECT id, filename, file_size, mime_type, sha256, storage_key,
                               security_findings, created_at
                        FROM source_documents
                        WHERE case_id=:case_id AND organization_id=:org_id
                        ORDER BY created_at DESC LIMIT 1"""
                    ),
                    {"case_id": case_id, "org_id": organization_id},
                )
            )
            .mappings()
            .one_or_none()
        )

        # Fetch latest parse run
        run_row = (
            (
                await session.execute(
                    text(
                        """SELECT id, status, error_summary, started_at, finished_at, created_at
                        FROM parse_runs
                        WHERE case_id=:case_id AND organization_id=:org_id
                        ORDER BY created_at DESC LIMIT 1"""
                    ),
                    {"case_id": case_id, "org_id": organization_id},
                )
            )
            .mappings()
            .one_or_none()
        )

        # Fetch active document version
        ver_row = (
            (
                await session.execute(
                    text(
                        """SELECT id, version_number, parent_version_id, parsed_text,
                               structure_json, sha256, is_confirmed, created_at
                        FROM document_versions
                        WHERE case_id=:case_id AND organization_id=:org_id
                        ORDER BY version_number DESC LIMIT 1"""
                    ),
                    {"case_id": case_id, "org_id": organization_id},
                )
            )
            .mappings()
            .one_or_none()
        )

        return {
            "id": str(case_row["id"]),
            "organization_id": str(case_row["organization_id"]),
            "case_number": case_row["case_number"],
            "title": case_row["title"],
            "technical_field": case_row["technical_field"],
            "target_jurisdiction": case_row["target_jurisdiction"],
            "status": case_row["status"],
            "created_by": str(case_row["created_by_identity_id"]),
            "created_at": case_row["created_at"].isoformat(),
            "updated_at": case_row["updated_at"].isoformat(),
            "document": (
                {
                    "id": str(doc_row["id"]),
                    "filename": doc_row["filename"],
                    "file_size": doc_row["file_size"],
                    "mime_type": doc_row["mime_type"],
                    "sha256": doc_row["sha256"],
                    "security_findings": list(doc_row["security_findings"] or []),
                    "created_at": doc_row["created_at"].isoformat(),
                }
                if doc_row
                else None
            ),
            "parse_run": (
                {
                    "id": str(run_row["id"]),
                    "status": run_row["status"],
                    "error_summary": run_row["error_summary"],
                    "started_at": run_row["started_at"].isoformat() if run_row["started_at"] else None,
                    "finished_at": run_row["finished_at"].isoformat() if run_row["finished_at"] else None,
                    "created_at": run_row["created_at"].isoformat(),
                }
                if run_row
                else None
            ),
            "document_version": (
                {
                    "id": str(ver_row["id"]),
                    "version_number": ver_row["version_number"],
                    "parent_version_id": str(ver_row["parent_version_id"]) if ver_row["parent_version_id"] else None,
                    "parsed_text": ver_row["parsed_text"],
                    "structure_json": ver_row["structure_json"],
                    "sha256": ver_row["sha256"],
                    "is_confirmed": ver_row["is_confirmed"],
                    "created_at": ver_row["created_at"].isoformat(),
                }
                if ver_row
                else None
            ),
        }

    async def confirm_document_version(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        version_id: UUID,
        actor_identity_id: UUID,
    ) -> dict[str, Any]:
        now = self._clock()
        ver_row = (
            (
                await session.execute(
                    text(
                        """SELECT id, version_number, is_confirmed FROM document_versions
                        WHERE id=:ver_id AND case_id=:case_id AND organization_id=:org_id
                        FOR UPDATE"""
                    ),
                    {"ver_id": version_id, "case_id": case_id, "org_id": organization_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if ver_row is None:
            raise HTTPException(status_code=404, detail="document_version_not_found")

        await session.execute(
            text(
                """UPDATE document_versions
                SET is_confirmed=true, created_by_identity_id=:actor_id
                WHERE id=:ver_id"""
            ),
            {"ver_id": version_id, "actor_id": actor_identity_id},
        )

        await session.execute(
            text(
                """UPDATE cases
                SET status='document_ready', updated_at=:now
                WHERE id=:case_id"""
            ),
            {"case_id": case_id, "now": now},
        )

        return {"status": "confirmed", "version_id": str(version_id), "case_status": "document_ready"}


class DocumentService:
    """Manages document uploads, storage persistence, and parse run jobs."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._parser = DocumentParser()

    async def upload_document(
        self,
        session: AsyncSession,
        storage: ObjectStorageClient,
        *,
        organization_id: UUID,
        case_id: UUID,
        filename: str,
        data: bytes,
    ) -> dict[str, Any]:
        now = self._clock()

        # 服务端按内容检查大小、扩展名、真实类型与主动内容（spec §6.2）；
        # 客户端声明的 Content-Type 不可信，只保留按内容判定的 MIME
        try:
            verdict = inspect_upload(filename, data)
        except UploadRejected as rejected:
            raise HTTPException(status_code=422, detail=rejected.code) from rejected
        content_type = verdict.mime_type
        findings = list(verdict.findings)

        # Compute SHA-256
        sha256 = self._parser.compute_sha256(data)
        storage_key = build_source_key(organization_id, case_id, sha256, filename)

        # Store to S3 / Object Storage
        await storage.put_object(storage_key, data, content_type)

        doc_id = uuid4()
        run_id = uuid4()

        # Insert source document
        await session.execute(
            text(
                """INSERT INTO source_documents
                (id, organization_id, case_id, filename, file_size, mime_type, sha256, storage_key,
                 security_findings, created_at)
                VALUES
                (:id, :org_id, :case_id, :filename, :file_size, :mime_type, :sha256, :storage_key,
                 CAST(:security_findings AS jsonb), :now)"""
            ),
            {
                "id": doc_id,
                "org_id": organization_id,
                "case_id": case_id,
                "filename": filename,
                "file_size": len(data),
                "mime_type": content_type,
                "sha256": sha256,
                "storage_key": storage_key,
                "security_findings": json.dumps(findings),
                "now": now,
            },
        )

        # Insert queued parse run
        await session.execute(
            text(
                """INSERT INTO parse_runs
                (id, organization_id, case_id, source_document_id, status, created_at)
                VALUES
                (:id, :org_id, :case_id, :doc_id, 'queued', :now)"""
            ),
            {
                "id": run_id,
                "org_id": organization_id,
                "case_id": case_id,
                "doc_id": doc_id,
                "now": now,
            },
        )

        return {
            "document": {
                "id": str(doc_id),
                "filename": filename,
                "file_size": len(data),
                "mime_type": content_type,
                "sha256": sha256,
                "storage_key": storage_key,
                "security_findings": findings,
            },
            "parse_run": {
                "id": str(run_id),
                "status": "queued",
                "created_at": now.isoformat(),
            },
        }

    async def list_versions(
        self, session: AsyncSession, organization_id: UUID, case_id: UUID
    ) -> list[dict[str, Any]]:
        rows = (
            (
                await session.execute(
                    text(
                        """SELECT id, version_number, parent_version_id, parsed_text,
                               structure_json, sha256, is_confirmed, created_at
                        FROM document_versions
                        WHERE case_id=:case_id AND organization_id=:org_id
                        ORDER BY version_number ASC"""
                    ),
                    {"case_id": case_id, "org_id": organization_id},
                )
            )
            .mappings()
            .all()
        )
        return [
            {
                "id": str(r["id"]),
                "version_number": r["version_number"],
                "parent_version_id": str(r["parent_version_id"]) if r["parent_version_id"] else None,
                "parsed_text": r["parsed_text"],
                "structure_json": r["structure_json"],
                "sha256": r["sha256"],
                "is_confirmed": r["is_confirmed"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]


class DrawingService:
    """Manages patent drawings, figure labels, reference marks, and storage."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    async def list_drawings(
        self, session: AsyncSession, organization_id: UUID, case_id: UUID
    ) -> list[dict[str, Any]]:
        rows = (
            (
                await session.execute(
                    text(
                        """SELECT id, organization_id, case_id, source_document_id,
                               document_version_id, figure_label, figure_title,
                               reference_marks, storage_key, mime_type, file_size,
                               sha256, page_number, order_index, is_manually_added,
                               created_at, updated_at
                        FROM case_drawings
                        WHERE case_id=:case_id AND organization_id=:org_id
                        ORDER BY order_index ASC, created_at ASC"""
                    ),
                    {"case_id": case_id, "org_id": organization_id},
                )
            )
            .mappings()
            .all()
        )
        return [
            {
                "id": str(r["id"]),
                "organization_id": str(r["organization_id"]),
                "case_id": str(r["case_id"]),
                "source_document_id": str(r["source_document_id"]) if r["source_document_id"] else None,
                "document_version_id": str(r["document_version_id"]) if r["document_version_id"] else None,
                "figure_label": r["figure_label"],
                "figure_title": r["figure_title"],
                "reference_marks": r["reference_marks"],
                "storage_key": r["storage_key"],
                "mime_type": r["mime_type"],
                "file_size": r["file_size"],
                "sha256": r["sha256"],
                "page_number": r["page_number"],
                "order_index": r["order_index"],
                "is_manually_added": r["is_manually_added"],
                "created_at": r["created_at"].isoformat(),
                "updated_at": r["updated_at"].isoformat(),
            }
            for r in rows
        ]

    async def get_drawing(
        self, session: AsyncSession, organization_id: UUID, case_id: UUID, drawing_id: UUID
    ) -> dict[str, Any] | None:
        row = (
            (
                await session.execute(
                    text(
                        """SELECT id, organization_id, case_id, source_document_id,
                               document_version_id, figure_label, figure_title,
                               reference_marks, storage_key, mime_type, file_size,
                               sha256, page_number, order_index, is_manually_added,
                               created_at, updated_at
                        FROM case_drawings
                        WHERE id=:id AND case_id=:case_id AND organization_id=:org_id"""
                    ),
                    {"id": drawing_id, "case_id": case_id, "org_id": organization_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "organization_id": str(row["organization_id"]),
            "case_id": str(row["case_id"]),
            "source_document_id": str(row["source_document_id"]) if row["source_document_id"] else None,
            "document_version_id": str(row["document_version_id"]) if row["document_version_id"] else None,
            "figure_label": row["figure_label"],
            "figure_title": row["figure_title"],
            "reference_marks": row["reference_marks"],
            "storage_key": row["storage_key"],
            "mime_type": row["mime_type"],
            "file_size": row["file_size"],
            "sha256": row["sha256"],
            "page_number": row["page_number"],
            "order_index": row["order_index"],
            "is_manually_added": row["is_manually_added"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }

    async def add_drawing(
        self,
        session: AsyncSession,
        storage: ObjectStorageClient,
        *,
        organization_id: UUID,
        case_id: UUID,
        data: bytes,
        filename: str,
        figure_label: str = "附图",
        figure_title: str = "",
        reference_marks: list[dict[str, str]] | None = None,
        mime_type: str = "image/png",
    ) -> dict[str, Any]:
        now = self._clock()
        sha256 = hashlib.sha256(data).hexdigest()
        storage_key = f"org/{organization_id}/case/{case_id}/drawings/{sha256}_{filename}"
        await storage.put_object(storage_key, data, mime_type)

        drawing_id = uuid4()
        marks = reference_marks or []

        # Get next order index
        max_order = (
            await session.scalar(
                text(
                    """SELECT COALESCE(MAX(order_index), 0) + 1
                    FROM case_drawings
                    WHERE case_id=:case_id AND organization_id=:org_id"""
                ),
                {"case_id": case_id, "org_id": organization_id},
            )
            or 1
        )

        import json
        await session.execute(
            text(
                """INSERT INTO case_drawings
                (id, organization_id, case_id, source_document_id, document_version_id,
                 figure_label, figure_title, reference_marks, storage_key, mime_type,
                 file_size, sha256, page_number, order_index, is_manually_added, created_at, updated_at)
                VALUES
                (:id, :org_id, :case_id, NULL, NULL,
                 :label, :title, :marks, :key, :mime,
                 :size, :sha256, NULL, :order, true, :now, :now)"""
            ),
            {
                "id": drawing_id,
                "org_id": organization_id,
                "case_id": case_id,
                "label": figure_label,
                "title": figure_title,
                "marks": json.dumps(marks),
                "key": storage_key,
                "mime": mime_type,
                "size": len(data),
                "sha256": sha256,
                "order": max_order,
                "now": now,
            },
        )

        return {
            "id": str(drawing_id),
            "organization_id": str(organization_id),
            "case_id": str(case_id),
            "figure_label": figure_label,
            "figure_title": figure_title,
            "reference_marks": marks,
            "storage_key": storage_key,
            "mime_type": mime_type,
            "file_size": len(data),
            "sha256": sha256,
            "order_index": max_order,
            "is_manually_added": True,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

    async def update_drawing_metadata(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        drawing_id: UUID,
        figure_label: str | None = None,
        figure_title: str | None = None,
        reference_marks: list[dict[str, str]] | None = None,
        order_index: int | None = None,
    ) -> dict[str, Any]:
        existing = await self.get_drawing(session, organization_id, case_id, drawing_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="drawing_not_found")

        now = self._clock()
        new_label = figure_label if figure_label is not None else existing["figure_label"]
        new_title = figure_title if figure_title is not None else existing["figure_title"]
        new_marks = reference_marks if reference_marks is not None else existing["reference_marks"]
        new_order = order_index if order_index is not None else existing["order_index"]

        import json
        await session.execute(
            text(
                """UPDATE case_drawings
                SET figure_label=:label, figure_title=:title, reference_marks=:marks,
                    order_index=:order, updated_at=:now
                WHERE id=:id AND case_id=:case_id AND organization_id=:org_id"""
            ),
            {
                "id": drawing_id,
                "case_id": case_id,
                "org_id": organization_id,
                "label": new_label,
                "title": new_title,
                "marks": json.dumps(new_marks),
                "order": new_order,
                "now": now,
            },
        )

        return {
            **existing,
            "figure_label": new_label,
            "figure_title": new_title,
            "reference_marks": new_marks,
            "order_index": new_order,
            "updated_at": now.isoformat(),
        }

    async def delete_drawing(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        drawing_id: UUID,
    ) -> None:
        existing = await self.get_drawing(session, organization_id, case_id, drawing_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="drawing_not_found")

        await session.execute(
            text(
                """DELETE FROM case_drawings
                WHERE id=:id AND case_id=:case_id AND organization_id=:org_id"""
            ),
            {"id": drawing_id, "case_id": case_id, "org_id": organization_id},
        )

    async def re_extract_drawings(
        self,
        session: AsyncSession,
        storage: ObjectStorageClient,
        *,
        organization_id: UUID,
        case_id: UUID,
        source_document_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Re-extract drawings from source documents for a case."""
        from modules.cases.drawing_extractor import DrawingExtractor
        extractor = DrawingExtractor()

        # Find documents to process
        doc_query = """SELECT id, filename, mime_type, storage_key
                       FROM source_documents
                       WHERE case_id=:case_id AND organization_id=:org_id"""
        params: dict[str, Any] = {"case_id": case_id, "org_id": organization_id}
        if source_document_id:
            doc_query += " AND id=:doc_id"
            params["doc_id"] = source_document_id

        docs = (await session.execute(text(doc_query), params)).mappings().all()
        if not docs:
            return []

        # Get latest parsed text for context
        latest_text = (
            await session.scalar(
                text(
                    """SELECT parsed_text FROM document_versions
                    WHERE case_id=:case_id AND organization_id=:org_id
                    ORDER BY version_number DESC LIMIT 1"""
                ),
                {"case_id": case_id, "org_id": organization_id},
            )
            or ""
        )

        now = self._clock()
        import json
        new_drawings: list[dict[str, Any]] = []

        for doc in docs:
            raw_bytes = await storage.get_object(doc["storage_key"])
            if not raw_bytes:
                continue

            extracted = extractor.extract_drawings(
                raw_bytes, doc["filename"], doc["mime_type"], document_text=latest_text
            )

            for d in extracted:
                drawing_key = f"org/{organization_id}/case/{case_id}/drawings/{d.sha256}_{d.filename}"
                await storage.put_object(drawing_key, d.data, d.mime_type)

                # Check if this drawing already exists by sha256
                exists = await session.scalar(
                    text(
                        """SELECT id FROM case_drawings
                        WHERE case_id=:case_id AND organization_id=:org_id AND sha256=:sha256"""
                    ),
                    {"case_id": case_id, "org_id": organization_id, "sha256": d.sha256},
                )
                if exists:
                    continue

                drawing_id = uuid4()
                await session.execute(
                    text(
                        """INSERT INTO case_drawings
                        (id, organization_id, case_id, source_document_id, document_version_id,
                         figure_label, figure_title, reference_marks, storage_key, mime_type,
                         file_size, sha256, page_number, order_index, is_manually_added, created_at, updated_at)
                        VALUES
                        (:id, :org_id, :case_id, :doc_id, NULL,
                         :label, :title, :marks, :key, :mime,
                         :size, :sha256, :page_num, :order, false, :now, :now)"""
                    ),
                    {
                        "id": drawing_id,
                        "org_id": organization_id,
                        "case_id": case_id,
                        "doc_id": doc["id"],
                        "label": d.figure_label,
                        "title": d.figure_title,
                        "marks": json.dumps(d.reference_marks),
                        "key": drawing_key,
                        "mime": d.mime_type,
                        "size": len(d.data),
                        "sha256": d.sha256,
                        "page_num": d.page_number,
                        "order": d.order_index,
                        "now": now,
                    },
                )
                new_drawings.append({
                    "id": str(drawing_id),
                    "figure_label": d.figure_label,
                    "figure_title": d.figure_title,
                    "sha256": d.sha256,
                })

        return await self.list_drawings(session, organization_id, case_id)

