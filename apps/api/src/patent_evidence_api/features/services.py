from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.features.extractor import DraftFeature, RuleFeatureExtractor


class FeatureService:
    """Manages feature extraction, draft editing, version confirmation, and revisions."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._extractor = RuleFeatureExtractor()

    async def extract_draft_features(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        document_version_id: UUID | None = None,
        actor_identity_id: UUID,
    ) -> dict[str, Any]:
        now = self._clock()

        # 1. Fetch target document version (or latest for this case)
        if document_version_id:
            doc_ver = (
                (
                    await session.execute(
                        text(
                            """SELECT id, structure_json, parsed_text
                            FROM document_versions
                            WHERE id=:ver_id AND case_id=:case_id AND organization_id=:org_id"""
                        ),
                        {"ver_id": document_version_id, "case_id": case_id, "org_id": organization_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        else:
            doc_ver = (
                (
                    await session.execute(
                        text(
                            """SELECT id, structure_json, parsed_text
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

        if doc_ver is None:
            raise HTTPException(status_code=404, detail="no_document_version_available_for_case")

        doc_ver_id = doc_ver["id"]
        raw_struct = doc_ver["structure_json"]
        paragraphs = json.loads(raw_struct) if isinstance(raw_struct, str) else (raw_struct or [])

        # Query case title
        case_res = await session.execute(
            text("SELECT title FROM cases WHERE id = :case_id AND organization_id = :org_id"),
            {"case_id": case_id, "org_id": organization_id},
        )
        case_row = case_res.fetchone()
        case_title = case_row[0] if case_row else ""

        # 2. Extract draft features (AI-powered with rule fallback)
        from modules.features.extractor import extract_features_with_ai
        draft_features = await extract_features_with_ai(title=case_title, paragraphs=paragraphs)
        if not draft_features:
            # Fallback draft feature
            draft_features = [
                DraftFeature(
                    feature_code="F1",
                    feature_type="characterizing",
                    feature_statement="本发明的主体技术方案",
                    source_paragraph_id=paragraphs[0]["id"] if paragraphs else "p1",
                    citation_quote=paragraphs[0]["text"][:60] if paragraphs else "引文",
                    sort_order=1,
                )
            ]

        # 3. Check if draft version exists
        existing_draft = (
            (
                await session.execute(
                    text(
                        """SELECT id, version_number FROM feature_set_versions
                        WHERE case_id=:case_id AND organization_id=:org_id AND status='draft'
                        FOR UPDATE"""
                    ),
                    {"case_id": case_id, "org_id": organization_id},
                )
            )
            .mappings()
            .one_or_none()
        )

        if existing_draft:
            version_id = existing_draft["id"]
            ver_num = existing_draft["version_number"]
            # Clear existing features in draft
            await session.execute(
                text("DELETE FROM claim_features WHERE feature_set_version_id=:vid"),
                {"vid": version_id},
            )
            await session.execute(
                text(
                    """UPDATE feature_set_versions
                    SET document_version_id=:dvid, updated_at=:now
                    WHERE id=:vid"""
                ),
                {"dvid": doc_ver_id, "now": now, "vid": version_id},
            )
        else:
            ver_num = (
                await session.scalar(
                    text(
                        """SELECT COALESCE(MAX(version_number), 0) + 1
                        FROM feature_set_versions
                        WHERE case_id=:case_id"""
                    ),
                    {"case_id": case_id},
                )
                or 1
            )
            version_id = uuid4()
            await session.execute(
                text(
                    """INSERT INTO feature_set_versions
                    (id, organization_id, case_id, document_version_id, version_number,
                     parent_version_id, status, summary, created_at, updated_at)
                    VALUES
                    (:id, :org_id, :case_id, :dvid, :ver_num,
                     NULL, 'draft', 'AI 自动提取技术特征草稿', :now, :now)"""
                ),
                {
                    "id": version_id,
                    "org_id": organization_id,
                    "case_id": case_id,
                    "dvid": doc_ver_id,
                    "ver_num": ver_num,
                    "now": now,
                },
            )

        # 4. Insert extracted features
        for f in draft_features:
            await session.execute(
                text(
                    """INSERT INTO claim_features
                    (id, organization_id, case_id, feature_set_version_id, feature_code,
                     feature_type, feature_statement, source_paragraph_id, citation_quote,
                     sort_order, created_at, updated_at)
                    VALUES
                    (:id, :org_id, :case_id, :vid, :code,
                     :ftype, :statement, :para_id, :quote,
                     :sort, :now, :now)"""
                ),
                {
                    "id": uuid4(),
                    "org_id": organization_id,
                    "case_id": case_id,
                    "vid": version_id,
                    "code": f.feature_code,
                    "ftype": f.feature_type,
                    "statement": f.feature_statement,
                    "para_id": f.source_paragraph_id,
                    "quote": f.citation_quote,
                    "sort": f.sort_order,
                    "now": now,
                },
            )

        return await self.get_feature_set(session, organization_id, case_id, version_id)

    async def get_feature_set(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
        version_id: UUID,
    ) -> dict[str, Any]:
        ver_row = (
            (
                await session.execute(
                    text(
                        """SELECT id, organization_id, case_id, document_version_id, version_number,
                               parent_version_id, status, summary, confirmed_by_identity_id,
                               confirmed_at, created_at, updated_at
                        FROM feature_set_versions
                        WHERE id=:vid AND case_id=:case_id AND organization_id=:org_id"""
                    ),
                    {"vid": version_id, "case_id": case_id, "org_id": organization_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if ver_row is None:
            raise HTTPException(status_code=404, detail="feature_set_version_not_found")

        feature_rows = (
            (
                await session.execute(
                    text(
                        """SELECT id, feature_code, feature_type, feature_statement,
                               source_paragraph_id, citation_quote, sort_order, created_at, updated_at
                        FROM claim_features
                        WHERE feature_set_version_id=:vid AND organization_id=:org_id
                        ORDER BY sort_order ASC, feature_code ASC"""
                    ),
                    {"vid": version_id, "org_id": organization_id},
                )
            )
            .mappings()
            .all()
        )

        return {
            "version": {
                "id": str(ver_row["id"]),
                "organization_id": str(ver_row["organization_id"]),
                "case_id": str(ver_row["case_id"]),
                "document_version_id": str(ver_row["document_version_id"]),
                "version_number": ver_row["version_number"],
                "parent_version_id": str(ver_row["parent_version_id"]) if ver_row["parent_version_id"] else None,
                "status": ver_row["status"],
                "summary": ver_row["summary"],
                "confirmed_by": str(ver_row["confirmed_by_identity_id"]) if ver_row["confirmed_by_identity_id"] else None,
                "confirmed_at": ver_row["confirmed_at"].isoformat() if ver_row["confirmed_at"] else None,
                "created_at": ver_row["created_at"].isoformat(),
                "updated_at": ver_row["updated_at"].isoformat(),
            },
            "features": [
                {
                    "id": str(f["id"]),
                    "feature_code": f["feature_code"],
                    "feature_type": f["feature_type"],
                    "feature_statement": f["feature_statement"],
                    "source_paragraph_id": f["source_paragraph_id"],
                    "citation_quote": f["citation_quote"],
                    "sort_order": f["sort_order"],
                    "created_at": f["created_at"].isoformat(),
                    "updated_at": f["updated_at"].isoformat(),
                }
                for f in feature_rows
            ],
        }

    async def get_active_feature_set(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
    ) -> dict[str, Any] | None:
        # Prefer active draft, otherwise latest confirmed
        ver_row = (
            (
                await session.execute(
                    text(
                        """SELECT id FROM feature_set_versions
                        WHERE case_id=:case_id AND organization_id=:org_id
                        ORDER BY (CASE WHEN status='draft' THEN 1 ELSE 2 END), version_number DESC
                        LIMIT 1"""
                    ),
                    {"case_id": case_id, "org_id": organization_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if ver_row is None:
            return None
        return await self.get_feature_set(session, organization_id, case_id, ver_row["id"])

    async def list_versions(
        self, session: AsyncSession, organization_id: UUID, case_id: UUID
    ) -> list[dict[str, Any]]:
        rows = (
            (
                await session.execute(
                    text(
                        """SELECT id, version_number, parent_version_id, status, summary,
                               confirmed_at, created_at
                        FROM feature_set_versions
                        WHERE case_id=:case_id AND organization_id=:org_id
                        ORDER BY version_number DESC"""
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
                "status": r["status"],
                "summary": r["summary"],
                "confirmed_at": r["confirmed_at"].isoformat() if r["confirmed_at"] else None,
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]

    async def _assert_draft_version(
        self, session: AsyncSession, organization_id: UUID, case_id: UUID, version_id: UUID
    ) -> None:
        status = await session.scalar(
            text(
                """SELECT status FROM feature_set_versions
                WHERE id=:vid AND case_id=:case_id AND organization_id=:org_id"""
            ),
            {"vid": version_id, "case_id": case_id, "org_id": organization_id},
        )
        if status is None:
            raise HTTPException(status_code=404, detail="feature_set_version_not_found")
        if status != "draft":
            raise HTTPException(
                status_code=400,
                detail="version_is_locked_and_immutable_create_revision_to_edit",
            )

    async def add_feature(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        version_id: UUID,
        feature_code: str,
        feature_type: str,
        feature_statement: str,
        source_paragraph_id: str | None = None,
        citation_quote: str | None = None,
    ) -> dict[str, Any]:
        await self._assert_draft_version(session, organization_id, case_id, version_id)
        now = self._clock()
        f_id = uuid4()
        max_sort = (
            await session.scalar(
                text(
                    """SELECT COALESCE(MAX(sort_order), 0) + 1
                    FROM claim_features WHERE feature_set_version_id=:vid"""
                ),
                {"vid": version_id},
            )
            or 1
        )

        await session.execute(
            text(
                """INSERT INTO claim_features
                (id, organization_id, case_id, feature_set_version_id, feature_code,
                 feature_type, feature_statement, source_paragraph_id, citation_quote,
                 sort_order, created_at, updated_at)
                VALUES
                (:id, :org_id, :case_id, :vid, :code,
                 :ftype, :statement, :para_id, :quote,
                 :sort, :now, :now)"""
            ),
            {
                "id": f_id,
                "org_id": organization_id,
                "case_id": case_id,
                "vid": version_id,
                "code": feature_code.strip() or f"F{max_sort}",
                "ftype": feature_type or "characterizing",
                "statement": feature_statement.strip(),
                "para_id": source_paragraph_id,
                "quote": citation_quote,
                "sort": max_sort,
                "now": now,
            },
        )
        return await self.get_feature_set(session, organization_id, case_id, version_id)

    async def update_feature(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        version_id: UUID,
        feature_id: UUID,
        feature_code: str | None = None,
        feature_type: str | None = None,
        feature_statement: str | None = None,
        source_paragraph_id: str | None = None,
        citation_quote: str | None = None,
        sort_order: int | None = None,
    ) -> dict[str, Any]:
        await self._assert_draft_version(session, organization_id, case_id, version_id)
        now = self._clock()

        await session.execute(
            text(
                """UPDATE claim_features
                SET feature_code = COALESCE(:code, feature_code),
                    feature_type = COALESCE(:ftype, feature_type),
                    feature_statement = COALESCE(:statement, feature_statement),
                    source_paragraph_id = COALESCE(:para_id, source_paragraph_id),
                    citation_quote = COALESCE(:quote, citation_quote),
                    sort_order = COALESCE(:sort, sort_order),
                    updated_at = :now
                WHERE id=:fid AND feature_set_version_id=:vid AND organization_id=:org_id"""
            ),
            {
                "fid": feature_id,
                "vid": version_id,
                "org_id": organization_id,
                "code": feature_code.strip() if feature_code else None,
                "ftype": feature_type,
                "statement": feature_statement.strip() if feature_statement else None,
                "para_id": source_paragraph_id,
                "quote": citation_quote,
                "sort": sort_order,
                "now": now,
            },
        )
        return await self.get_feature_set(session, organization_id, case_id, version_id)

    async def delete_feature(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        version_id: UUID,
        feature_id: UUID,
    ) -> dict[str, Any]:
        await self._assert_draft_version(session, organization_id, case_id, version_id)
        await session.execute(
            text(
                """DELETE FROM claim_features
                WHERE id=:fid AND feature_set_version_id=:vid AND organization_id=:org_id"""
            ),
            {"fid": feature_id, "vid": version_id, "org_id": organization_id},
        )
        return await self.get_feature_set(session, organization_id, case_id, version_id)

    async def split_feature(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        version_id: UUID,
        feature_id: UUID,
        part1_statement: str,
        part2_statement: str,
    ) -> dict[str, Any]:
        await self._assert_draft_version(session, organization_id, case_id, version_id)
        now = self._clock()

        old = (
            (
                await session.execute(
                    text(
                        """SELECT feature_code, feature_type, source_paragraph_id, citation_quote, sort_order
                        FROM claim_features
                        WHERE id=:fid AND feature_set_version_id=:vid AND organization_id=:org_id"""
                    ),
                    {"fid": feature_id, "vid": version_id, "org_id": organization_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if old is None:
            raise HTTPException(status_code=404, detail="feature_not_found")

        code = old["feature_code"]
        ftype = old["feature_type"]
        para_id = old["source_paragraph_id"]
        sort = old["sort_order"]

        # Update part 1 into existing feature
        await session.execute(
            text(
                """UPDATE claim_features
                SET feature_statement=:stmt, updated_at=:now
                WHERE id=:fid"""
            ),
            {"stmt": part1_statement.strip(), "now": now, "fid": feature_id},
        )

        # Insert part 2 with sub-code
        part2_code = f"{code}.1" if "." not in code else f"{code}b"
        await session.execute(
            text(
                """INSERT INTO claim_features
                (id, organization_id, case_id, feature_set_version_id, feature_code,
                 feature_type, feature_statement, source_paragraph_id, citation_quote,
                 sort_order, created_at, updated_at)
                VALUES
                (:id, :org_id, :case_id, :vid, :code,
                 :ftype, :statement, :para_id, :quote,
                 :sort, :now, :now)"""
            ),
            {
                "id": uuid4(),
                "org_id": organization_id,
                "case_id": case_id,
                "vid": version_id,
                "code": part2_code,
                "ftype": ftype,
                "statement": part2_statement.strip(),
                "para_id": para_id,
                "quote": part2_statement[:80],
                "sort": sort + 1,
                "now": now,
            },
        )
        return await self.get_feature_set(session, organization_id, case_id, version_id)

    async def merge_features(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        version_id: UUID,
        feature_id_1: UUID,
        feature_id_2: UUID,
        merged_statement: str,
    ) -> dict[str, Any]:
        await self._assert_draft_version(session, organization_id, case_id, version_id)
        now = self._clock()

        await session.execute(
            text(
                """UPDATE claim_features
                SET feature_statement=:stmt, updated_at=:now
                WHERE id=:fid AND feature_set_version_id=:vid"""
            ),
            {"stmt": merged_statement.strip(), "now": now, "fid": feature_id_1, "vid": version_id},
        )
        await session.execute(
            text(
                """DELETE FROM claim_features
                WHERE id=:fid AND feature_set_version_id=:vid"""
            ),
            {"fid": feature_id_2, "vid": version_id},
        )
        return await self.get_feature_set(session, organization_id, case_id, version_id)

    async def confirm_version(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        version_id: UUID,
        actor_identity_id: UUID,
    ) -> dict[str, Any]:
        await self._assert_draft_version(session, organization_id, case_id, version_id)
        now = self._clock()

        # Check that there is at least 1 feature
        feature_count = await session.scalar(
            text("SELECT COUNT(*) FROM claim_features WHERE feature_set_version_id=:vid"),
            {"vid": version_id},
        ) or 0
        if feature_count == 0:
            raise HTTPException(status_code=400, detail="cannot_confirm_empty_feature_set")

        await session.execute(
            text(
                """UPDATE feature_set_versions
                SET status='confirmed', confirmed_by_identity_id=:actor_id,
                    confirmed_at=:now, updated_at=:now
                WHERE id=:vid"""
            ),
            {"actor_id": actor_identity_id, "now": now, "vid": version_id},
        )

        # Advance case status to features_confirmed
        await session.execute(
            text(
                """UPDATE cases
                SET status='features_confirmed', updated_at=:now
                WHERE id=:case_id"""
            ),
            {"case_id": case_id, "now": now},
        )

        return await self.get_feature_set(session, organization_id, case_id, version_id)

    async def create_revision(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        base_version_id: UUID,
        actor_identity_id: UUID,
    ) -> dict[str, Any]:
        now = self._clock()

        base_ver = (
            (
                await session.execute(
                    text(
                        """SELECT document_version_id, version_number, status
                        FROM feature_set_versions
                        WHERE id=:vid AND case_id=:case_id AND organization_id=:org_id"""
                    ),
                    {"vid": base_version_id, "case_id": case_id, "org_id": organization_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if base_ver is None:
            raise HTTPException(status_code=404, detail="base_feature_set_version_not_found")

        # Check if an existing draft is already open
        existing_draft = (
            (
                await session.execute(
                    text(
                        """SELECT id FROM feature_set_versions
                        WHERE case_id=:case_id AND organization_id=:org_id AND status='draft'"""
                    ),
                    {"case_id": case_id, "org_id": organization_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing_draft:
            return await self.get_feature_set(session, organization_id, case_id, existing_draft["id"])

        next_ver = (
            await session.scalar(
                text(
                    """SELECT COALESCE(MAX(version_number), 0) + 1
                    FROM feature_set_versions
                    WHERE case_id=:case_id"""
                ),
                {"case_id": case_id},
            )
            or 2
        )

        new_vid = uuid4()
        await session.execute(
            text(
                """INSERT INTO feature_set_versions
                (id, organization_id, case_id, document_version_id, version_number,
                 parent_version_id, status, summary, created_at, updated_at)
                VALUES
                (:id, :org_id, :case_id, :dvid, :ver_num,
                 :parent_id, 'draft', '基于上个版本的新修订草稿', :now, :now)"""
            ),
            {
                "id": new_vid,
                "org_id": organization_id,
                "case_id": case_id,
                "dvid": base_ver["document_version_id"],
                "ver_num": next_ver,
                "parent_id": base_version_id,
                "now": now,
            },
        )

        # Copy existing features
        old_features = (
            (
                await session.execute(
                    text(
                        """SELECT feature_code, feature_type, feature_statement,
                               source_paragraph_id, citation_quote, sort_order
                        FROM claim_features
                        WHERE feature_set_version_id=:vid
                        ORDER BY sort_order ASC"""
                    ),
                    {"vid": base_version_id},
                )
            )
            .mappings()
            .all()
        )

        for f in old_features:
            await session.execute(
                text(
                    """INSERT INTO claim_features
                    (id, organization_id, case_id, feature_set_version_id, feature_code,
                     feature_type, feature_statement, source_paragraph_id, citation_quote,
                     sort_order, created_at, updated_at)
                    VALUES
                    (:id, :org_id, :case_id, :vid, :code,
                     :ftype, :statement, :para_id, :quote,
                     :sort, :now, :now)"""
                ),
                {
                    "id": uuid4(),
                    "org_id": organization_id,
                    "case_id": case_id,
                    "vid": new_vid,
                    "code": f["feature_code"],
                    "ftype": f["feature_type"],
                    "statement": f["feature_statement"],
                    "para_id": f["source_paragraph_id"],
                    "quote": f["citation_quote"],
                    "sort": f["sort_order"],
                    "now": now,
                },
            )

        return await self.get_feature_set(session, organization_id, case_id, new_vid)
