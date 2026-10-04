"""Product descriptions and their technical features (ADR 0010).

Descriptions are append-only versions. A feature set starts as a draft from
the deterministic splitter, is edited by a person (edit, add, delete, split,
merge) and is then confirmed; confirmed sets are immutable (database triggers)
and change only through a new revision. All tables are tenant-scoped (RLS).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.fto.product import SPLITTER_VERSION, split_description

MAX_DESCRIPTION_CHARS = 50_000


class ProductFeatureService:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    # ------------------------------------------------------------ descriptions

    async def add_description(
        self, session: AsyncSession, *, organization_id: UUID, case_id: UUID, description: str, actor_id: UUID
    ) -> dict[str, Any]:
        body = description.strip()
        if not body:
            raise HTTPException(status_code=422, detail="product_description_empty")
        if len(body) > MAX_DESCRIPTION_CHARS:
            raise HTTPException(status_code=422, detail="product_description_too_long")
        await self._require_case(session, organization_id, case_id)
        version = await self._next_version(session, "product_descriptions", case_id)
        description_id = uuid4()
        await session.execute(
            text(
                """INSERT INTO product_descriptions
                (id, organization_id, case_id, version_number, description_text, text_sha256,
                 created_by_identity_id, created_at)
                VALUES (:id, :org, :case, :version, :text, :sha, :actor, :now)"""
            ),
            {
                "id": description_id, "org": organization_id, "case": case_id, "version": version,
                "text": body, "sha": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "actor": actor_id, "now": self._clock(),
            },
        )
        return {"id": str(description_id), "version_number": version}

    # ------------------------------------------------------------ feature sets

    async def create_draft(
        self, session: AsyncSession, *, organization_id: UUID, case_id: UUID, description_id: UUID, actor_id: UUID
    ) -> dict[str, Any]:
        row = (
            await session.execute(
                text(
                    """SELECT description_text FROM product_descriptions
                    WHERE id = :id AND case_id = :case AND organization_id = :org"""
                ),
                {"id": description_id, "case": case_id, "org": organization_id},
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="product_description_not_found")
        result = split_description(row[0])
        set_id = await self._insert_set(session, organization_id, case_id, description_id, actor_id, parent=None)
        for order, feature in enumerate(result.features):
            await self._insert_feature(
                session, organization_id, case_id, set_id, feature.feature_id, feature.text,
                [list(s) for s in feature.spans], "split", order,
            )
        return {**(await self.get_set(session, organization_id=organization_id, set_id=set_id)), "warnings": list(result.warnings)}

    async def create_revision(
        self, session: AsyncSession, *, organization_id: UUID, set_id: UUID, actor_id: UUID
    ) -> dict[str, Any]:
        source = await self._load_set(session, organization_id, set_id)
        if source["status"] != "confirmed":
            raise HTTPException(status_code=409, detail="only_confirmed_sets_can_be_revised")
        new_id = await self._insert_set(
            session, organization_id, source["case_id"], source["description_id"], actor_id, parent=set_id
        )
        for feature in source["features"]:
            await self._insert_feature(
                session, organization_id, source["case_id"], new_id, feature["code"], feature["text"],
                feature["spans"], feature["origin"], feature["sort_order"],
            )
        return await self.get_set(session, organization_id=organization_id, set_id=new_id)

    async def confirm(self, session: AsyncSession, *, organization_id: UUID, set_id: UUID, actor_id: UUID) -> dict[str, Any]:
        current = await self._load_draft(session, organization_id, set_id)
        if not current["features"]:
            raise HTTPException(status_code=422, detail="cannot_confirm_empty_feature_set")
        now = self._clock()
        await session.execute(
            text(
                """UPDATE product_feature_sets
                SET status = 'confirmed', confirmed_by_identity_id = :actor, confirmed_at = :now, updated_at = :now
                WHERE id = :id AND organization_id = :org"""
            ),
            {"actor": actor_id, "now": now, "id": set_id, "org": organization_id},
        )
        return await self.get_set(session, organization_id=organization_id, set_id=set_id)

    # ------------------------------------------------------------ draft edits

    async def edit_feature(
        self, session: AsyncSession, *, organization_id: UUID, set_id: UUID, code: str, new_text: str
    ) -> dict[str, Any]:
        draft = await self._load_draft(session, organization_id, set_id)
        feature = self._feature(draft, code)
        body = new_text.strip()
        if not body:
            raise HTTPException(status_code=422, detail="feature_text_empty")
        origin = feature["origin"] if body == feature["text"] else ("manual" if feature["origin"] == "manual" else "edited")
        await self._update_feature(session, organization_id, set_id, code, body, feature["spans"], origin)
        return await self.get_set(session, organization_id=organization_id, set_id=set_id)

    async def add_feature(
        self, session: AsyncSession, *, organization_id: UUID, set_id: UUID, feature_text: str
    ) -> dict[str, Any]:
        draft = await self._load_draft(session, organization_id, set_id)
        body = feature_text.strip()
        if not body:
            raise HTTPException(status_code=422, detail="feature_text_empty")
        order = max((f["sort_order"] for f in draft["features"]), default=-1) + 1
        await self._insert_feature(
            session, organization_id, draft["case_id"], set_id, self._next_code(draft), body, [], "manual", order
        )
        return await self.get_set(session, organization_id=organization_id, set_id=set_id)

    async def delete_feature(self, session: AsyncSession, *, organization_id: UUID, set_id: UUID, code: str) -> dict[str, Any]:
        draft = await self._load_draft(session, organization_id, set_id)
        self._feature(draft, code)
        await session.execute(
            text("DELETE FROM product_features WHERE feature_set_id = :set AND feature_code = :code AND organization_id = :org"),
            {"set": set_id, "code": code, "org": organization_id},
        )
        return await self.get_set(session, organization_id=organization_id, set_id=set_id)

    async def split_feature(
        self, session: AsyncSession, *, organization_id: UUID, set_id: UUID, code: str, at: int
    ) -> dict[str, Any]:
        """Split one feature's text at character index ``at`` into two features."""
        draft = await self._load_draft(session, organization_id, set_id)
        feature = self._feature(draft, code)
        left, right = feature["text"][:at].strip(), feature["text"][at:].strip()
        if not left or not right:
            raise HTTPException(status_code=422, detail="split_would_create_empty_feature")
        left_spans, right_spans = feature["spans"], []
        # Unedited, contiguous split features keep exact spans on both sides.
        if feature["origin"] == "split" and len(feature["spans"]) == 1:
            start, end = feature["spans"][0]
            raw_left, raw_right = feature["text"][:at], feature["text"][at:]
            left_end = start + len(raw_left.rstrip())
            right_start = start + at + (len(raw_right) - len(raw_right.lstrip()))
            left_spans, right_spans = [[start, left_end]], [[right_start, end]]
            left_origin = right_origin = "split"
        else:
            left_origin = right_origin = "edited" if feature["origin"] != "manual" else "manual"
        await self._update_feature(session, organization_id, set_id, code, left, left_spans, left_origin)
        await self._shift_orders_after(session, organization_id, set_id, feature["sort_order"])
        await self._insert_feature(
            session, organization_id, draft["case_id"], set_id, self._next_code(draft), right,
            right_spans, right_origin, feature["sort_order"] + 1,
        )
        return await self.get_set(session, organization_id=organization_id, set_id=set_id)

    async def merge_features(
        self, session: AsyncSession, *, organization_id: UUID, set_id: UUID, codes: list[str]
    ) -> dict[str, Any]:
        """Merge features (in their current order) into the first of them."""
        draft = await self._load_draft(session, organization_id, set_id)
        if len(set(codes)) < 2:
            raise HTTPException(status_code=422, detail="merge_needs_two_features")
        chosen = sorted((self._feature(draft, c) for c in set(codes)), key=lambda f: f["sort_order"])
        first, rest = chosen[0], chosen[1:]
        merged_text = " ".join(f["text"] for f in chosen)
        merged_spans = [s for f in chosen for s in f["spans"]]
        origin = "split" if all(f["origin"] == "split" for f in chosen) else "edited"
        await self._update_feature(session, organization_id, set_id, first["code"], merged_text, merged_spans, origin)
        for feature in rest:
            await session.execute(
                text("DELETE FROM product_features WHERE feature_set_id = :set AND feature_code = :code AND organization_id = :org"),
                {"set": set_id, "code": feature["code"], "org": organization_id},
            )
        return await self.get_set(session, organization_id=organization_id, set_id=set_id)

    # ------------------------------------------------------------ reads

    async def get_set(self, session: AsyncSession, *, organization_id: UUID, set_id: UUID) -> dict[str, Any]:
        data = await self._load_set(session, organization_id, set_id)
        return {
            "id": str(data["id"]), "case_id": str(data["case_id"]), "description_id": str(data["description_id"]),
            "version_number": data["version_number"], "status": data["status"],
            "parent_set_id": str(data["parent_set_id"]) if data["parent_set_id"] else None,
            "splitter_version": data["splitter_version"],
            "confirmed_at": data["confirmed_at"].isoformat() if data["confirmed_at"] else None,
            "features": [
                {"code": f["code"], "text": f["text"], "spans": f["spans"], "origin": f["origin"]}
                for f in data["features"]
            ],
        }

    async def list_descriptions(self, session: AsyncSession, *, organization_id: UUID, case_id: UUID) -> list[dict[str, Any]]:
        rows = (
            await session.execute(
                text(
                    """SELECT id, version_number, description_text, text_sha256, created_at
                    FROM product_descriptions WHERE case_id = :case AND organization_id = :org
                    ORDER BY version_number DESC"""
                ),
                {"case": case_id, "org": organization_id},
            )
        ).mappings().all()
        return [
            {"id": str(r["id"]), "version_number": r["version_number"], "text": r["description_text"],
             "text_sha256": r["text_sha256"], "created_at": r["created_at"].isoformat()}
            for r in rows
        ]

    async def list_sets(self, session: AsyncSession, *, organization_id: UUID, case_id: UUID) -> list[dict[str, Any]]:
        rows = (
            await session.execute(
                text(
                    """SELECT s.id, s.version_number, s.status, s.description_id, s.parent_set_id, s.confirmed_at,
                              (SELECT count(*) FROM product_features f WHERE f.feature_set_id = s.id) AS feature_count
                    FROM product_feature_sets s WHERE s.case_id = :case AND s.organization_id = :org
                    ORDER BY s.version_number DESC"""
                ),
                {"case": case_id, "org": organization_id},
            )
        ).mappings().all()
        return [
            {"id": str(r["id"]), "version_number": r["version_number"], "status": r["status"],
             "description_id": str(r["description_id"]),
             "parent_set_id": str(r["parent_set_id"]) if r["parent_set_id"] else None,
             "confirmed_at": r["confirmed_at"].isoformat() if r["confirmed_at"] else None,
             "feature_count": r["feature_count"]}
            for r in rows
        ]

    # ------------------------------------------------------------ internals

    async def _require_case(self, session: AsyncSession, organization_id: UUID, case_id: UUID) -> None:
        found = (
            await session.execute(
                text("SELECT 1 FROM cases WHERE id = :case AND organization_id = :org"),
                {"case": case_id, "org": organization_id},
            )
        ).one_or_none()
        if found is None:
            raise HTTPException(status_code=404, detail="case_not_found")

    async def _next_version(self, session: AsyncSession, table: str, case_id: UUID) -> int:
        current = (
            await session.execute(text(f"SELECT max(version_number) FROM {table} WHERE case_id = :case"), {"case": case_id})
        ).scalar_one_or_none()
        return (current or 0) + 1

    async def _insert_set(
        self, session: AsyncSession, organization_id: UUID, case_id: UUID, description_id: UUID, actor_id: UUID, *, parent: UUID | None
    ) -> UUID:
        set_id = uuid4()
        now = self._clock()
        await session.execute(
            text(
                """INSERT INTO product_feature_sets
                (id, organization_id, case_id, description_id, version_number, parent_set_id, status,
                 splitter_version, created_by_identity_id, created_at, updated_at)
                VALUES (:id, :org, :case, :desc, :version, :parent, 'draft', :splitter, :actor, :now, :now)"""
            ),
            {
                "id": set_id, "org": organization_id, "case": case_id, "desc": description_id,
                "version": await self._next_version(session, "product_feature_sets", case_id),
                "parent": parent, "splitter": SPLITTER_VERSION, "actor": actor_id, "now": now,
            },
        )
        return set_id

    async def _insert_feature(
        self, session: AsyncSession, organization_id: UUID, case_id: UUID, set_id: UUID,
        code: str, body: str, spans: list[list[int]], origin: str, order: int,
    ) -> None:
        now = self._clock()
        await session.execute(
            text(
                """INSERT INTO product_features
                (id, organization_id, case_id, feature_set_id, feature_code, feature_text, spans, origin,
                 sort_order, created_at, updated_at)
                VALUES (:id, :org, :case, :set, :code, :text, CAST(:spans AS jsonb), :origin, :order, :now, :now)"""
            ),
            {
                "id": uuid4(), "org": organization_id, "case": case_id, "set": set_id, "code": code,
                "text": body, "spans": json.dumps(spans), "origin": origin, "order": order, "now": now,
            },
        )

    async def _update_feature(
        self, session: AsyncSession, organization_id: UUID, set_id: UUID, code: str, body: str, spans: list, origin: str
    ) -> None:
        await session.execute(
            text(
                """UPDATE product_features
                SET feature_text = :text, spans = CAST(:spans AS jsonb), origin = :origin, updated_at = :now
                WHERE feature_set_id = :set AND feature_code = :code AND organization_id = :org"""
            ),
            {"text": body, "spans": json.dumps(spans), "origin": origin, "now": self._clock(),
             "set": set_id, "code": code, "org": organization_id},
        )

    async def _shift_orders_after(self, session: AsyncSession, organization_id: UUID, set_id: UUID, order: int) -> None:
        await session.execute(
            text(
                """UPDATE product_features SET sort_order = sort_order + 1
                WHERE feature_set_id = :set AND organization_id = :org AND sort_order > :order"""
            ),
            {"set": set_id, "org": organization_id, "order": order},
        )

    async def _load_set(self, session: AsyncSession, organization_id: UUID, set_id: UUID) -> dict[str, Any]:
        row = (
            await session.execute(
                text(
                    """SELECT id, case_id, description_id, version_number, status, parent_set_id,
                              splitter_version, confirmed_at
                    FROM product_feature_sets WHERE id = :id AND organization_id = :org"""
                ),
                {"id": set_id, "org": organization_id},
            )
        ).mappings().one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="product_feature_set_not_found")
        features = (
            await session.execute(
                text(
                    """SELECT feature_code AS code, feature_text AS text, spans, origin, sort_order
                    FROM product_features WHERE feature_set_id = :id AND organization_id = :org
                    ORDER BY sort_order, feature_code"""
                ),
                {"id": set_id, "org": organization_id},
            )
        ).mappings().all()
        return {**dict(row), "features": [dict(f) for f in features]}

    async def _load_draft(self, session: AsyncSession, organization_id: UUID, set_id: UUID) -> dict[str, Any]:
        data = await self._load_set(session, organization_id, set_id)
        if data["status"] != "draft":
            raise HTTPException(status_code=409, detail="product_feature_set_confirmed")
        return data

    @staticmethod
    def _feature(data: dict[str, Any], code: str) -> dict[str, Any]:
        for feature in data["features"]:
            if feature["code"] == code:
                return feature
        raise HTTPException(status_code=404, detail="product_feature_not_found")

    @staticmethod
    def _next_code(data: dict[str, Any]) -> str:
        numbers = [int(m.group(1)) for f in data["features"] if (m := re.fullmatch(r"P(\d+)", f["code"]))]
        return f"P{max(numbers, default=0) + 1}"
