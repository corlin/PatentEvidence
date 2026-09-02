from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.search.base import BaseSearchAdapter
from modules.search.handoff import HandoffPackageGenerator
from modules.search.importer import CniprResultsImporter, normalize_pub_number
from modules.search.scorer import RelevanceScorer
from modules.search.strategy_planner import SearchStrategyPlanner

Clock = Callable[[], datetime]


def default_clock() -> datetime:
    return datetime.now(timezone.utc)


class SearchStrategyService:
    def __init__(self, clock: Clock = default_clock) -> None:
        self.clock = clock
        self.planner = SearchStrategyPlanner()
        self.handoff_gen = HandoffPackageGenerator()

    async def generate_strategy(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
        actor_identity_id: UUID,
    ) -> dict[str, Any]:
        # 1. Fetch case info
        res_case = await session.execute(
            text(
                "SELECT id, case_number, title, technical_field FROM cases WHERE id = :case_id AND organization_id = :org_id"
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        case_row = res_case.fetchone()
        if not case_row:
            raise HTTPException(status_code=404, detail="case_not_found")

        # 2. Fetch active feature set version (prefer confirmed, otherwise latest)
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
            raise HTTPException(status_code=400, detail="no_features_available_extract_features_first")

        version_id = v_row.id

        # 3. Fetch features
        res_feats = await session.execute(
            text(
                """SELECT feature_code, feature_type, feature_statement, source_paragraph_id, citation_quote, sort_order
                FROM claim_features
                WHERE feature_set_version_id = :v_id AND organization_id = :org_id
                ORDER BY sort_order ASC"""
            ),
            {"v_id": version_id, "org_id": organization_id},
        )
        features = [dict(r._mapping) for r in res_feats.fetchall()]

        # 4. Plan strategy (AI-powered with rule fallback)
        from modules.search.strategy_planner import plan_strategy_with_ai
        plan = await plan_strategy_with_ai(
            features=features,
            technical_field=case_row.technical_field,
            title=case_row.title,
        )

        now = self.clock()
        strat_id = uuid4()
        await session.execute(
            text(
                """INSERT INTO search_strategies
                (id, organization_id, case_id, feature_set_version_id, keywords_matrix, ipc_classes, boolean_query_cnipr, boolean_query_standard, status, created_at, updated_at)
                VALUES
                (:id, :org_id, :case_id, :v_id, :kw, :ipc, :cnipr, :std, 'confirmed', :now, :now)"""
            ),
            {
                "id": strat_id,
                "org_id": organization_id,
                "case_id": case_id,
                "v_id": version_id,
                "kw": json.dumps(plan.keywords_matrix),
                "ipc": json.dumps(plan.ipc_classes),
                "cnipr": plan.boolean_query_cnipr,
                "std": plan.boolean_query_standard,
                "now": now,
            },
        )

        return {
            "id": str(strat_id),
            "organization_id": str(organization_id),
            "case_id": str(case_id),
            "feature_set_version_id": str(version_id),
            "keywords_matrix": plan.keywords_matrix,
            "ipc_classes": plan.ipc_classes,
            "boolean_query_cnipr": plan.boolean_query_cnipr,
            "boolean_query_standard": plan.boolean_query_standard,
            "status": "confirmed",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

    async def get_active_strategy(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
    ) -> dict[str, Any] | None:
        res = await session.execute(
            text(
                """SELECT id, organization_id, case_id, feature_set_version_id, keywords_matrix, ipc_classes,
                          boolean_query_cnipr, boolean_query_standard, status, created_at, updated_at
                FROM search_strategies
                WHERE case_id = :case_id AND organization_id = :org_id
                ORDER BY created_at DESC
                LIMIT 1"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        row = res.fetchone()
        if not row:
            return None
        return {
            "id": str(row.id),
            "organization_id": str(row.organization_id),
            "case_id": str(row.case_id),
            "feature_set_version_id": str(row.feature_set_version_id),
            "keywords_matrix": row.keywords_matrix if isinstance(row.keywords_matrix, dict) else json.loads(row.keywords_matrix),
            "ipc_classes": row.ipc_classes if isinstance(row.ipc_classes, list) else json.loads(row.ipc_classes),
            "boolean_query_cnipr": row.boolean_query_cnipr,
            "boolean_query_standard": row.boolean_query_standard,
            "status": row.status,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }

    async def update_strategy(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
        strategy_id: UUID,
        keywords_matrix: dict[str, list[str]] | None = None,
        ipc_classes: list[dict[str, str]] | None = None,
        boolean_query_cnipr: str | None = None,
        boolean_query_standard: str | None = None,
    ) -> dict[str, Any]:
        existing = await self.get_active_strategy(session, organization_id, case_id)
        if not existing or existing["id"] != str(strategy_id):
            raise HTTPException(status_code=404, detail="strategy_not_found")

        new_kw = keywords_matrix if keywords_matrix is not None else existing["keywords_matrix"]
        new_ipc = ipc_classes if ipc_classes is not None else existing["ipc_classes"]
        new_cnipr = boolean_query_cnipr if boolean_query_cnipr is not None else existing["boolean_query_cnipr"]
        new_std = boolean_query_standard if boolean_query_standard is not None else existing["boolean_query_standard"]
        now = self.clock()

        await session.execute(
            text(
                """UPDATE search_strategies
                SET keywords_matrix = :kw, ipc_classes = :ipc, boolean_query_cnipr = :cnipr,
                    boolean_query_standard = :std, updated_at = :now
                WHERE id = :id AND organization_id = :org_id AND case_id = :case_id"""
            ),
            {
                "id": strategy_id,
                "org_id": organization_id,
                "case_id": case_id,
                "kw": json.dumps(new_kw),
                "ipc": json.dumps(new_ipc),
                "cnipr": new_cnipr,
                "std": new_std,
                "now": now,
            },
        )
        return await self.get_active_strategy(session, organization_id, case_id)  # type: ignore

    async def get_handoff_package(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
        strategy_id: UUID,
    ) -> dict[str, Any]:
        strat = await self.get_active_strategy(session, organization_id, case_id)
        if not strat or strat["id"] != str(strategy_id):
            raise HTTPException(status_code=404, detail="strategy_not_found")

        res_case = await session.execute(
            text(
                "SELECT case_number, title, technical_field FROM cases WHERE id = :case_id AND organization_id = :org_id"
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        case_row = res_case.fetchone()
        case_info = dict(case_row._mapping) if case_row else {}

        res_feats = await session.execute(
            text(
                """SELECT feature_code, feature_type, feature_statement, source_paragraph_id
                FROM claim_features
                WHERE feature_set_version_id = :v_id AND organization_id = :org_id
                ORDER BY sort_order ASC"""
            ),
            {"v_id": UUID(strat["feature_set_version_id"]), "org_id": organization_id},
        )
        features = [dict(r._mapping) for r in res_feats.fetchall()]

        markdown_pkg = self.handoff_gen.generate_markdown(case_info, strat, features)
        json_pkg = self.handoff_gen.generate_json(case_info, strat, features)

        return {
            "markdown": markdown_pkg,
            "json": json_pkg,
            "raw_cnipr_query": strat["boolean_query_cnipr"],
        }


class SearchExecutionService:
    def __init__(self, clock: Clock = default_clock) -> None:
        self.clock = clock
        self.scorer = RelevanceScorer()

    async def execute_public_search(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
        strategy: dict[str, Any],
        adapter: BaseSearchAdapter,
        actor_identity_id: UUID,
        source_type: str = "google_patents",
    ) -> dict[str, Any]:
        now = self.clock()
        job_id = uuid4()
        strat_id = UUID(strategy["id"]) if strategy.get("id") else None
        query = strategy.get("boolean_query_standard", "")

        # 1. Create search job
        await session.execute(
            text(
                """INSERT INTO search_jobs
                (id, organization_id, case_id, strategy_id, source_type, query_text, status, results_count, created_at)
                VALUES
                (:id, :org_id, :case_id, :strat_id, :source, :query, 'running', 0, :now)"""
            ),
            {
                "id": job_id,
                "org_id": organization_id,
                "case_id": case_id,
                "strat_id": strat_id,
                "source": source_type,
                "query": query,
                "now": now,
            },
        )

        # 2. Query adapter
        try:
            items = await adapter.search(query)
        except Exception as exc:
            await session.execute(
                text(
                    "UPDATE search_jobs SET status = 'failed', error_message = :err WHERE id = :id"
                ),
                {"id": job_id, "err": str(exc)},
            )
            raise HTTPException(status_code=502, detail=f"search_adapter_failed: {exc}") from exc

        kw_matrix = strategy.get("keywords_matrix", {})
        ipc_classes = strategy.get("ipc_classes", [])

        # 3. Upsert candidates and initialize triage records
        imported_count = 0
        for item in items:
            norm_pub = normalize_pub_number(item.publication_number)
            score = self.scorer.compute_score(
                candidate_title=item.title,
                candidate_abstract=item.abstract,
                candidate_ipc=item.ipc_classification,
                keywords_matrix=kw_matrix,
                target_ipc_classes=ipc_classes,
            )
            cand_id = uuid4()

            res_cand = await session.execute(
                text(
                    """INSERT INTO search_candidates
                    (id, organization_id, case_id, publication_number, publication_number_normalized, title, abstract,
                     publication_date, applicant, ipc_classification, source_type, raw_metadata, relevance_score, created_at)
                    VALUES
                    (:id, :org_id, :case_id, :pub, :pub_norm, :title, :abstract, :date, :app, :ipc, :src, :meta, :score, :now)
                    ON CONFLICT (organization_id, case_id, publication_number_normalized)
                    DO UPDATE SET relevance_score = EXCLUDED.relevance_score, raw_metadata = EXCLUDED.raw_metadata
                    RETURNING id"""
                ),
                {
                    "id": cand_id,
                    "org_id": organization_id,
                    "case_id": case_id,
                    "pub": item.publication_number,
                    "pub_norm": norm_pub,
                    "title": item.title,
                    "abstract": item.abstract,
                    "date": item.publication_date,
                    "app": item.applicant,
                    "ipc": item.ipc_classification,
                    "src": item.source_type,
                    "meta": json.dumps(item.raw_metadata or {}),
                    "score": score,
                    "now": now,
                },
            )
            actual_cand_id = res_cand.scalar_one()

            # Initialize triage record if none exists
            await session.execute(
                text(
                    """INSERT INTO candidate_triage_records
                    (id, organization_id, case_id, candidate_id, triage_status, triaged_by_identity_id, triaged_at)
                    VALUES
                    (:id, :org_id, :case_id, :cand_id, 'pending', :actor_id, :now)
                    ON CONFLICT (candidate_id) DO NOTHING"""
                ),
                {
                    "id": uuid4(),
                    "org_id": organization_id,
                    "case_id": case_id,
                    "cand_id": actual_cand_id,
                    "actor_id": actor_identity_id,
                    "now": now,
                },
            )
            imported_count += 1

        # 4. Finish job
        await session.execute(
            text(
                "UPDATE search_jobs SET status = 'completed', results_count = :cnt, finished_at = :now WHERE id = :id"
            ),
            {"id": job_id, "cnt": imported_count, "now": now},
        )

        return {
            "job_id": str(job_id),
            "status": "completed",
            "source_type": source_type,
            "results_count": imported_count,
        }


class CandidateTriageService:
    def __init__(self, clock: Clock = default_clock) -> None:
        self.clock = clock
        self.importer = CniprResultsImporter()
        self.scorer = RelevanceScorer()

    async def import_cnipr_candidates(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
        raw_content: str,
        actor_identity_id: UUID,
        strategy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        candidates = self.importer.import_from_csv(raw_content)
        if not candidates:
            candidates = self.importer.import_from_text(raw_content)

        if not candidates:
            raise HTTPException(status_code=422, detail="no_valid_patents_found_in_upload")

        kw_matrix = strategy.get("keywords_matrix", {}) if strategy else {}
        ipc_classes = strategy.get("ipc_classes", []) if strategy else []
        now = self.clock()

        imported_count = 0
        for item in candidates:
            score = self.scorer.compute_score(
                candidate_title=item.title,
                candidate_abstract=item.abstract,
                candidate_ipc=item.ipc_classification,
                keywords_matrix=kw_matrix,
                target_ipc_classes=ipc_classes,
            )
            cand_id = uuid4()
            res = await session.execute(
                text(
                    """INSERT INTO search_candidates
                    (id, organization_id, case_id, publication_number, publication_number_normalized, title, abstract,
                     publication_date, applicant, ipc_classification, source_type, raw_metadata, relevance_score, created_at)
                    VALUES
                    (:id, :org_id, :case_id, :pub, :pub_norm, :title, :abstract, :date, :app, :ipc, :src, :meta, :score, :now)
                    ON CONFLICT (organization_id, case_id, publication_number_normalized)
                    DO UPDATE SET relevance_score = EXCLUDED.relevance_score, title = EXCLUDED.title, abstract = EXCLUDED.abstract
                    RETURNING id"""
                ),
                {
                    "id": cand_id,
                    "org_id": organization_id,
                    "case_id": case_id,
                    "pub": item.publication_number,
                    "pub_norm": item.publication_number_normalized,
                    "title": item.title,
                    "abstract": item.abstract,
                    "date": item.publication_date,
                    "app": item.applicant,
                    "ipc": item.ipc_classification,
                    "src": item.source_type,
                    "meta": json.dumps(item.raw_metadata or {}),
                    "score": score,
                    "now": now,
                },
            )
            actual_cand_id = res.scalar_one()

            # Initialize triage record
            await session.execute(
                text(
                    """INSERT INTO candidate_triage_records
                    (id, organization_id, case_id, candidate_id, triage_status, triaged_by_identity_id, triaged_at)
                    VALUES
                    (:id, :org_id, :case_id, :cand_id, 'pending', :actor_id, :now)
                    ON CONFLICT (candidate_id) DO NOTHING"""
                ),
                {
                    "id": uuid4(),
                    "org_id": organization_id,
                    "case_id": case_id,
                    "cand_id": actual_cand_id,
                    "actor_id": actor_identity_id,
                    "now": now,
                },
            )
            imported_count += 1

        return {"imported_count": imported_count}

    async def list_candidates(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
        triage_status: str | None = None,
    ) -> list[dict[str, Any]]:
        query_sql = """
            SELECT c.id, c.publication_number, c.publication_number_normalized, c.title, c.abstract,
                   c.publication_date, c.applicant, c.ipc_classification, c.source_type, c.relevance_score,
                   c.created_at,
                   COALESCE(t.triage_status, 'pending') AS triage_status,
                   t.exclusion_reason, t.notes, t.triaged_at
            FROM search_candidates c
            LEFT JOIN candidate_triage_records t ON c.id = t.candidate_id
            WHERE c.case_id = :case_id AND c.organization_id = :org_id
        """
        params: dict[str, Any] = {"case_id": case_id, "org_id": organization_id}

        if triage_status and triage_status != "all":
            query_sql += " AND COALESCE(t.triage_status, 'pending') = :t_status"
            params["t_status"] = triage_status

        query_sql += " ORDER BY c.relevance_score DESC, c.created_at DESC"

        res = await session.execute(text(query_sql), params)
        rows = res.fetchall()

        results: list[dict[str, Any]] = []
        for r in rows:
            results.append(
                {
                    "id": str(r.id),
                    "publication_number": r.publication_number,
                    "publication_number_normalized": r.publication_number_normalized,
                    "title": r.title,
                    "abstract": r.abstract,
                    "publication_date": r.publication_date,
                    "applicant": r.applicant,
                    "ipc_classification": r.ipc_classification,
                    "source_type": r.source_type,
                    "relevance_score": r.relevance_score,
                    "created_at": r.created_at.isoformat(),
                    "triage_status": r.triage_status,
                    "exclusion_reason": r.exclusion_reason,
                    "notes": r.notes,
                    "triaged_at": r.triaged_at.isoformat() if r.triaged_at else None,
                }
            )
        return results

    async def update_triage(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
        candidate_id: UUID,
        triage_status: str,
        exclusion_reason: str | None,
        notes: str | None,
        actor_identity_id: UUID,
    ) -> dict[str, Any]:
        if triage_status not in ("pending", "included", "excluded"):
            raise HTTPException(status_code=422, detail="invalid_triage_status")

        now = self.clock()
        await session.execute(
            text(
                """INSERT INTO candidate_triage_records
                (id, organization_id, case_id, candidate_id, triage_status, exclusion_reason, notes, triaged_by_identity_id, triaged_at)
                VALUES
                (:id, :org_id, :case_id, :cand_id, :status, :reason, :notes, :actor_id, :now)
                ON CONFLICT (candidate_id)
                DO UPDATE SET triage_status = EXCLUDED.triage_status,
                              exclusion_reason = EXCLUDED.exclusion_reason,
                              notes = EXCLUDED.notes,
                              triaged_by_identity_id = EXCLUDED.triaged_by_identity_id,
                              triaged_at = EXCLUDED.triaged_at"""
            ),
            {
                "id": uuid4(),
                "org_id": organization_id,
                "case_id": case_id,
                "cand_id": candidate_id,
                "status": triage_status,
                "reason": exclusion_reason,
                "notes": notes,
                "actor_id": actor_identity_id,
                "now": now,
            },
        )

        candidates = await self.list_candidates(session, organization_id, case_id)
        for c in candidates:
            if c["id"] == str(candidate_id):
                return c
        raise HTTPException(status_code=404, detail="candidate_not_found")
