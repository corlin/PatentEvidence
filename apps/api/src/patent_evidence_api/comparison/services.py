from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.comparison.engine import RuleComparisonEngine, compare_feature_with_ai
from modules.comparison.evaluator import MatrixEvaluator

Clock = Callable[[], datetime]


def default_clock() -> datetime:
    return datetime.now(timezone.utc)


class ComparisonMatrixService:
    def __init__(self, clock: Clock = default_clock) -> None:
        self.clock = clock
        self.engine = RuleComparisonEngine()
        self.evaluator = MatrixEvaluator()

    async def generate_or_rebuild_matrix(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
        actor_identity_id: UUID,
    ) -> dict[str, Any]:
        # 1. Fetch active feature set version
        res_version = await session.execute(
            text(
                """SELECT id, version_number, status FROM feature_set_versions
                WHERE case_id = :case_id AND organization_id = :org_id
                ORDER BY CASE WHEN status = 'confirmed' THEN 1 WHEN status = 'draft' THEN 2 ELSE 3 END, version_number DESC
                LIMIT 1"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        v_row = res_version.fetchone()
        if not v_row:
            raise HTTPException(status_code=400, detail="no_feature_version_available")

        version_id = v_row.id

        # 2. Fetch features
        res_feats = await session.execute(
            text(
                """SELECT id, feature_code, feature_type, feature_statement, source_paragraph_id, sort_order
                FROM claim_features
                WHERE feature_set_version_id = :v_id AND organization_id = :org_id
                ORDER BY sort_order ASC"""
            ),
            {"v_id": version_id, "org_id": organization_id},
        )
        features = [dict(r._mapping) for r in res_feats.fetchall()]
        if not features:
            raise HTTPException(status_code=400, detail="no_claim_features_found")

        # 3. Fetch candidates (prefer 'included' triaged candidates; fallback to top candidates)
        res_cands = await session.execute(
            text(
                """SELECT c.id, c.publication_number, c.title, c.abstract, c.publication_date, c.applicant,
                          c.ipc_classification, c.relevance_score, COALESCE(t.triage_status, 'pending') as triage_status
                FROM search_candidates c
                LEFT JOIN candidate_triage_records t ON c.id = t.candidate_id
                WHERE c.case_id = :case_id AND c.organization_id = :org_id
                ORDER BY CASE WHEN COALESCE(t.triage_status, 'pending') = 'included' THEN 1 ELSE 2 END,
                         c.relevance_score DESC
                LIMIT 10"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        candidates = [dict(r._mapping) for r in res_cands.fetchall()]
        if not candidates:
            raise HTTPException(status_code=400, detail="no_search_candidates_available_execute_search_first")

        # Filter candidates: prioritize included ones if any exist
        included_cands = [c for c in candidates if c["triage_status"] == "included"]
        active_candidates = included_cands if included_cands else candidates[:4]

        now = self.clock()
        matrix_id = uuid4()

        # 4. Upsert comparison matrix header
        res_matrix = await session.execute(
            text(
                """INSERT INTO comparison_matrices
                (id, organization_id, case_id, feature_set_version_id, name, status, created_at, updated_at)
                VALUES
                (:id, :org_id, :case_id, :v_id, '权利要求特征比对表', 'draft', :now, :now)
                ON CONFLICT (case_id, feature_set_version_id)
                DO UPDATE SET status = 'draft', updated_at = EXCLUDED.updated_at
                RETURNING id"""
            ),
            {
                "id": matrix_id,
                "org_id": organization_id,
                "case_id": case_id,
                "v_id": version_id,
                "now": now,
            },
        )
        actual_matrix_id = res_matrix.scalar_one()

        # 5. Generate feature-candidate comparisons
        comparison_records: list[dict[str, Any]] = []
        for feat in features:
            for cand in active_candidates:
                comp_res = await compare_feature_with_ai(
                    feature_code=feat["feature_code"],
                    feature_statement=feat["feature_statement"],
                    candidate_pub_no=cand["publication_number"],
                    candidate_title=cand["title"],
                    candidate_abstract=cand["abstract"],
                )
                comp_id = uuid4()
                await session.execute(
                    text(
                        """INSERT INTO claim_feature_comparisons
                        (id, organization_id, case_id, matrix_id, claim_feature_id, candidate_id,
                         judgment, confidence_score, citation_location, citation_quote, reasoning_analysis, is_manually_edited, created_at, updated_at)
                        VALUES
                        (:id, :org_id, :case_id, :matrix_id, :feat_id, :cand_id,
                         :judgment, :score, :loc, :quote, :reasoning, false, :now, :now)
                        ON CONFLICT (matrix_id, claim_feature_id, candidate_id)
                        DO UPDATE SET judgment = EXCLUDED.judgment,
                                      confidence_score = EXCLUDED.confidence_score,
                                      citation_location = EXCLUDED.citation_location,
                                      citation_quote = EXCLUDED.citation_quote,
                                      reasoning_analysis = EXCLUDED.reasoning_analysis,
                                      updated_at = EXCLUDED.updated_at
                        WHERE claim_feature_comparisons.is_manually_edited = false"""
                    ),
                    {
                        "id": comp_id,
                        "org_id": organization_id,
                        "case_id": case_id,
                        "matrix_id": actual_matrix_id,
                        "feat_id": feat["id"],
                        "cand_id": cand["id"],
                        "judgment": comp_res.judgment,
                        "score": comp_res.confidence_score,
                        "loc": comp_res.citation_location,
                        "quote": comp_res.citation_quote,
                        "reasoning": comp_res.reasoning_analysis,
                        "now": now,
                    },
                )
                comparison_records.append(
                    {
                        "matrix_id": str(actual_matrix_id),
                        "claim_feature_id": str(feat["id"]),
                        "candidate_id": str(cand["id"]),
                        "judgment": comp_res.judgment,
                    }
                )

        # 6. Evaluate full matrix summary
        eval_result = self.evaluator.evaluate_matrix(features, active_candidates, comparison_records)
        await session.execute(
            text(
                "UPDATE comparison_matrices SET summary = :summary, updated_at = :now WHERE id = :id"
            ),
            {"id": actual_matrix_id, "summary": eval_result["summary"], "now": now},
        )

        return await self.get_active_matrix(session, organization_id, case_id)  # type: ignore

    async def get_active_matrix(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
    ) -> dict[str, Any] | None:
        res_matrix = await session.execute(
            text(
                """SELECT id, organization_id, case_id, feature_set_version_id, name, status, summary,
                          confirmed_at, confirmed_by_identity_id, created_at, updated_at
                FROM comparison_matrices
                WHERE case_id = :case_id AND organization_id = :org_id
                ORDER BY created_at DESC
                LIMIT 1"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        m_row = res_matrix.fetchone()
        if not m_row:
            return None

        matrix_id = m_row.id
        v_id = m_row.feature_set_version_id

        # Fetch features
        res_feats = await session.execute(
            text(
                """SELECT id, feature_code, feature_type, feature_statement, source_paragraph_id, sort_order
                FROM claim_features
                WHERE feature_set_version_id = :v_id AND organization_id = :org_id
                ORDER BY sort_order ASC"""
            ),
            {"v_id": v_id, "org_id": organization_id},
        )
        features = [
            {
                "id": str(r.id),
                "feature_code": r.feature_code,
                "feature_type": r.feature_type,
                "feature_statement": r.feature_statement,
                "source_paragraph_id": r.source_paragraph_id,
                "sort_order": r.sort_order,
            }
            for r in res_feats.fetchall()
        ]

        # Fetch comparison items with joined candidates
        res_items = await session.execute(
            text(
                """SELECT comp.id, comp.matrix_id, comp.claim_feature_id, comp.candidate_id,
                          comp.judgment, comp.confidence_score, comp.citation_location, comp.citation_quote,
                          comp.reasoning_analysis, comp.is_manually_edited, comp.created_at, comp.updated_at,
                          cand.publication_number, cand.title, cand.applicant, cand.publication_date
                FROM claim_feature_comparisons comp
                JOIN search_candidates cand ON comp.candidate_id = cand.id
                WHERE comp.matrix_id = :m_id AND comp.organization_id = :org_id
                ORDER BY comp.created_at ASC"""
            ),
            {"m_id": matrix_id, "org_id": organization_id},
        )
        rows = res_items.fetchall()

        comparisons: list[dict[str, Any]] = []
        cands_dict: dict[str, dict[str, Any]] = {}
        for r in rows:
            c_id = str(r.candidate_id)
            if c_id not in cands_dict:
                cands_dict[c_id] = {
                    "id": c_id,
                    "publication_number": r.publication_number,
                    "title": r.title,
                    "applicant": r.applicant,
                    "publication_date": r.publication_date,
                }
            comparisons.append(
                {
                    "id": str(r.id),
                    "matrix_id": str(r.matrix_id),
                    "claim_feature_id": str(r.claim_feature_id),
                    "candidate_id": c_id,
                    "judgment": r.judgment,
                    "confidence_score": r.confidence_score,
                    "citation_location": r.citation_location,
                    "citation_quote": r.citation_quote,
                    "reasoning_analysis": r.reasoning_analysis,
                    "is_manually_edited": r.is_manually_edited,
                    "created_at": r.created_at.isoformat(),
                    "updated_at": r.updated_at.isoformat(),
                }
            )

        candidates = list(cands_dict.values())
        eval_result = self.evaluator.evaluate_matrix(features, candidates, comparisons)

        return {
            "matrix": {
                "id": str(m_row.id),
                "organization_id": str(m_row.organization_id),
                "case_id": str(m_row.case_id),
                "feature_set_version_id": str(m_row.feature_set_version_id),
                "name": m_row.name,
                "status": m_row.status,
                "summary": m_row.summary,
                "confirmed_at": m_row.confirmed_at.isoformat() if m_row.confirmed_at else None,
                "confirmed_by_identity_id": str(m_row.confirmed_by_identity_id) if m_row.confirmed_by_identity_id else None,
                "created_at": m_row.created_at.isoformat(),
                "updated_at": m_row.updated_at.isoformat(),
            },
            "evaluation": eval_result,
            "features": features,
            "candidates": candidates,
            "comparisons": comparisons,
        }

    async def update_comparison_item(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
        comparison_id: UUID,
        judgment: str | None = None,
        citation_location: str | None = None,
        citation_quote: str | None = None,
        reasoning_analysis: str | None = None,
    ) -> dict[str, Any]:
        res = await session.execute(
            text(
                """SELECT c.id, c.matrix_id, m.status as matrix_status
                FROM claim_feature_comparisons c
                JOIN comparison_matrices m ON c.matrix_id = m.id
                WHERE c.id = :c_id AND c.organization_id = :org_id AND c.case_id = :case_id"""
            ),
            {"c_id": comparison_id, "org_id": organization_id, "case_id": case_id},
        )
        row = res.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="comparison_item_not_found")
        if row.matrix_status == "confirmed":
            raise HTTPException(status_code=400, detail="matrix_is_confirmed_and_locked")

        now = self.clock()
        updates: list[str] = ["is_manually_edited = true", "updated_at = :now"]
        params: dict[str, Any] = {"id": comparison_id, "org_id": organization_id, "now": now}

        if judgment is not None:
            if judgment not in ("identical", "equivalent", "different"):
                raise HTTPException(status_code=422, detail="invalid_judgment_value")
            updates.append("judgment = :judgment")
            params["judgment"] = judgment
        if citation_location is not None:
            updates.append("citation_location = :loc")
            params["loc"] = citation_location
        if citation_quote is not None:
            updates.append("citation_quote = :quote")
            params["quote"] = citation_quote
        if reasoning_analysis is not None:
            updates.append("reasoning_analysis = :reasoning")
            params["reasoning"] = reasoning_analysis

        await session.execute(
            text(f"UPDATE claim_feature_comparisons SET {', '.join(updates)} WHERE id = :id AND organization_id = :org_id"),
            params,
        )

        return await self.get_active_matrix(session, organization_id, case_id)  # type: ignore

    async def confirm_matrix(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
        matrix_id: UUID,
        actor_identity_id: UUID,
    ) -> dict[str, Any]:
        now = self.clock()
        await session.execute(
            text(
                """UPDATE comparison_matrices
                SET status = 'confirmed', confirmed_at = :now, confirmed_by_identity_id = :actor_id, updated_at = :now
                WHERE id = :id AND organization_id = :org_id AND case_id = :case_id"""
            ),
            {"id": matrix_id, "org_id": organization_id, "case_id": case_id, "actor_id": actor_identity_id, "now": now},
        )
        # Advance Case status
        await session.execute(
            text(
                "UPDATE cases SET status = 'comparisons_confirmed', updated_at = :now WHERE id = :case_id AND organization_id = :org_id"
            ),
            {"case_id": case_id, "org_id": organization_id, "now": now},
        )
        return await self.get_active_matrix(session, organization_id, case_id)  # type: ignore
