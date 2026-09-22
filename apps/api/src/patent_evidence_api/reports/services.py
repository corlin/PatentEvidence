from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.assessment.approval import derive_status
from modules.reports.generator import MarkdownReportGenerator
from modules.reports.sealer import EvidenceSealer

Clock = Callable[[], datetime]


def default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _as_list(value: Any) -> list[str]:
    """blockers/flags 存成 JSONB，驱动层可能回传字符串。"""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, (str, bytes, bytearray)):
        import json

        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
    return []


class EvidenceReportService:
    def __init__(self, clock: Clock = default_clock) -> None:
        self.clock = clock
        self.sealer = EvidenceSealer()
        self.generator = MarkdownReportGenerator()

    async def seal_evidence_snapshot(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
        actor_identity_id: UUID,
        actor_email: str,
    ) -> dict[str, Any]:
        now = self.clock()

        # 1. Fetch Case
        res_case = await session.execute(
            text(
                "SELECT id, case_number, title, technical_field, status FROM cases WHERE id = :id AND organization_id = :org_id"
            ),
            {"id": case_id, "org_id": organization_id},
        )
        case_row = res_case.fetchone()
        if not case_row:
            raise HTTPException(status_code=404, detail="case_not_found")

        case_data = {
            "id": str(case_row.id),
            "case_number": case_row.case_number,
            "title": case_row.title,
            "technical_field": case_row.technical_field,
        }

        # 2. Fetch Document
        res_doc = await session.execute(
            text(
                """SELECT dv.id, dv.version_number, dv.sha256 as file_sha256, sd.filename
                FROM document_versions dv
                JOIN source_documents sd ON dv.source_document_id = sd.id
                WHERE dv.case_id = :case_id AND dv.organization_id = :org_id
                ORDER BY dv.is_confirmed DESC, dv.version_number DESC LIMIT 1"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        doc_row = res_doc.fetchone()
        doc_data = (
            {
                "id": str(doc_row.id),
                "version_number": doc_row.version_number,
                "file_sha256": doc_row.file_sha256,
                "filename": doc_row.filename,
            }
            if doc_row
            else {}
        )

        # 3. Fetch Features
        res_fsv = await session.execute(
            text(
                """SELECT id, version_number FROM feature_set_versions
                WHERE case_id = :case_id AND organization_id = :org_id AND status = 'confirmed'
                ORDER BY version_number DESC LIMIT 1"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        fsv_row = res_fsv.fetchone()
        if not fsv_row:
            raise HTTPException(status_code=400, detail="no_confirmed_feature_version")

        res_cf = await session.execute(
            text(
                """SELECT feature_code, feature_type, feature_statement, source_paragraph_id, sort_order
                FROM claim_features
                WHERE feature_set_version_id = :v_id AND organization_id = :org_id
                ORDER BY sort_order ASC"""
            ),
            {"v_id": fsv_row.id, "org_id": organization_id},
        )
        features_items = [
            {
                "feature_code": r.feature_code,
                "feature_type": r.feature_type,
                "feature_statement": r.feature_statement,
                "source_paragraph_id": r.source_paragraph_id,
                "sort_order": r.sort_order,
            }
            for r in res_cf.fetchall()
        ]
        features_data = {
            "version_id": str(fsv_row.id),
            "items": features_items,
        }

        # 4. Fetch Search Strategy
        res_strat = await session.execute(
            text(
                """SELECT id, keywords_matrix, ipc_classes, boolean_query_cnipr
                FROM search_strategies
                WHERE case_id = :case_id AND organization_id = :org_id
                ORDER BY created_at DESC LIMIT 1"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        strat_row = res_strat.fetchone()
        search_data = (
            {
                "strategy_id": str(strat_row.id),
                "keywords_matrix": strat_row.keywords_matrix,
                "ipc_classes": strat_row.ipc_classes,
                "boolean_query_cnipr": strat_row.boolean_query_cnipr,
            }
            if strat_row
            else {}
        )

        # 5. Fetch Candidates and Triage Records
        res_cands = await session.execute(
            text(
                """SELECT c.publication_number, c.title, COALESCE(t.triage_status, 'pending') as triage_status,
                          t.exclusion_reason, t.notes
                FROM search_candidates c
                LEFT JOIN candidate_triage_records t ON c.id = t.candidate_id
                WHERE c.case_id = :case_id AND c.organization_id = :org_id
                ORDER BY c.created_at ASC"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        candidates_data = [
            {
                "publication_number": r.publication_number,
                "title": r.title,
                "triage_status": r.triage_status,
                "exclusion_reason": r.exclusion_reason,
                "notes": r.notes,
            }
            for r in res_cands.fetchall()
        ]

        # 6. Fetch Comparison Matrix
        res_matrix = await session.execute(
            text(
                """SELECT id, status, summary
                FROM comparison_matrices
                WHERE case_id = :case_id AND organization_id = :org_id
                ORDER BY CASE WHEN status = 'confirmed' THEN 1 ELSE 2 END, created_at DESC LIMIT 1"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        m_row = res_matrix.fetchone()
        if not m_row:
            raise HTTPException(status_code=400, detail="no_comparison_matrix_available_generate_first")

        res_comps = await session.execute(
            text(
                """SELECT cf.feature_code, sc.publication_number as candidate_pub_number,
                          comp.judgment, comp.confidence_score, comp.citation_location,
                          comp.citation_quote, comp.reasoning_analysis, comp.is_manually_edited
                FROM claim_feature_comparisons comp
                JOIN claim_features cf ON comp.claim_feature_id = cf.id
                JOIN search_candidates sc ON comp.candidate_id = sc.id
                WHERE comp.matrix_id = :m_id AND comp.organization_id = :org_id
                ORDER BY cf.sort_order ASC, sc.publication_number ASC"""
            ),
            {"m_id": m_row.id, "org_id": organization_id},
        )
        comps_list = [
            {
                "feature_code": r.feature_code,
                "candidate_pub_number": r.candidate_pub_number,
                "judgment": r.judgment,
                "confidence_score": r.confidence_score,
                "citation_location": r.citation_location,
                "citation_quote": r.citation_quote,
                "reasoning_analysis": r.reasoning_analysis,
                "is_manually_edited": r.is_manually_edited,
            }
            for r in res_comps.fetchall()
        ]
        comparison_data = {
            "matrix_id": str(m_row.id),
            "summary": m_row.summary or "",
            "comparisons": comps_list,
        }

        # 6.5 Latest pre-assessment facts — what gates section 5 of the report.
        assessment_data = await self._latest_assessment_facts(
            session, organization_id, case_id
        )

        # 7. Seal Payload and compute Root SHA-256
        dict_payload, root_sha256 = self.sealer.seal(
            case_data=case_data,
            doc_data=doc_data,
            features_data=features_data,
            search_data=search_data,
            candidates_data=candidates_data,
            comparison_data=comparison_data,
            sealed_at_iso=now.isoformat(),
            sealed_by_email=actor_email,
            assessment_data=assessment_data,
        )

        # Count existing snapshots for this case
        res_count = await session.execute(
            text("SELECT COUNT(*) FROM evidence_snapshots WHERE case_id = :case_id AND organization_id = :org_id"),
            {"case_id": case_id, "org_id": organization_id},
        )
        seq = (res_count.scalar() or 0) + 1
        snapshot_num = f"SNAP-{now.year}-{str(case_id)[:8].upper()}-{seq:02d}"

        snapshot_id = uuid4()
        await session.execute(
            text(
                """INSERT INTO evidence_snapshots
                (id, organization_id, case_id, snapshot_number, status, root_sha256, snapshot_payload, sealed_by_identity_id, sealed_at, created_at)
                VALUES
                (:id, :org_id, :case_id, :num, 'sealed', :root_sha, CAST(:payload AS jsonb), :actor_id, :now, :now)"""
            ),
            {
                "id": snapshot_id,
                "org_id": organization_id,
                "case_id": case_id,
                "num": snapshot_num,
                "root_sha": root_sha256,
                "payload": json.dumps(dict_payload),
                "actor_id": actor_identity_id,
                "now": now,
            },
        )

        # Advance case status to completed
        await session.execute(
            text("UPDATE cases SET status = 'completed', updated_at = :now WHERE id = :case_id AND organization_id = :org_id"),
            {"case_id": case_id, "org_id": organization_id, "now": now},
        )

        # Generate default Markdown Report
        report_content = self.generator.generate(dict_payload, root_sha256)
        rep_id = uuid4()
        await session.execute(
            text(
                """INSERT INTO analysis_reports
                (id, organization_id, case_id, snapshot_id, report_title, format, content, generated_by_identity_id, created_at)
                VALUES
                (:id, :org_id, :case_id, :snap_id, :title, 'markdown', :content, :actor_id, :now)"""
            ),
            {
                "id": rep_id,
                "org_id": organization_id,
                "case_id": case_id,
                "snap_id": snapshot_id,
                "title": f"专利证据分析与法律评估报告 ({case_data['case_number']})",
                "content": report_content,
                "actor_id": actor_identity_id,
                "now": now,
            },
        )

        return await self.get_active_snapshot(session, organization_id, case_id)  # type: ignore

    async def _latest_assessment_facts(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
    ) -> dict[str, Any]:
        """最新预评估版本的事实——报告第 5 节的门禁依据。

        返回的是事实而非判定：门禁在渲染时复算，封存时只固化事实，
        这样一份旧快照也能被今天的规则重新判一遍。
        """
        row = (
            await session.execute(
                text(
                    """SELECT id, version_number, payload_sha256, blockers
                    FROM assessment_versions
                    WHERE organization_id = :org_id AND case_id = :case_id
                    ORDER BY version_number DESC
                    LIMIT 1"""
                ),
                {"org_id": organization_id, "case_id": case_id},
            )
        ).fetchone()

        if row is None:
            return {"has_version": False}

        decisions = (
            await session.execute(
                text(
                    """SELECT decision FROM assessment_version_reviews
                    WHERE organization_id = :org_id AND version_id = :version_id
                    ORDER BY decided_at, id"""
                ),
                {"org_id": organization_id, "version_id": row.id},
            )
        ).fetchall()

        return {
            "has_version": True,
            "version_number": int(row.version_number),
            "status": derive_status([str(d.decision) for d in decisions]),
            "blockers": _as_list(row.blockers),
            "payload_sha256": row.payload_sha256,
        }

    async def get_active_snapshot(
        self,
        session: AsyncSession,
        organization_id: UUID,
        case_id: UUID,
    ) -> dict[str, Any] | None:
        res = await session.execute(
            text(
                """SELECT s.id, s.organization_id, s.case_id, s.snapshot_number, s.status, s.root_sha256,
                          s.snapshot_payload, s.sealed_by_identity_id, s.sealed_at, s.created_at,
                          r.id as report_id, r.report_title, r.content as report_content
                FROM evidence_snapshots s
                LEFT JOIN analysis_reports r ON s.id = r.snapshot_id
                WHERE s.case_id = :case_id AND s.organization_id = :org_id
                ORDER BY s.sealed_at DESC LIMIT 1"""
            ),
            {"case_id": case_id, "org_id": organization_id},
        )
        row = res.fetchone()
        if not row:
            return None

        payload = row.snapshot_payload if isinstance(row.snapshot_payload, dict) else json.loads(row.snapshot_payload)

        return {
            "snapshot": {
                "id": str(row.id),
                "organization_id": str(row.organization_id),
                "case_id": str(row.case_id),
                "snapshot_number": row.snapshot_number,
                "status": row.status,
                "root_sha256": row.root_sha256,
                "sealed_by_identity_id": str(row.sealed_by_identity_id),
                "sealed_at": row.sealed_at.isoformat(),
                "created_at": row.created_at.isoformat(),
            },
            "report": {
                "id": str(row.report_id) if row.report_id else None,
                "title": row.report_title,
                "content": row.report_content,
            }
            if row.report_id
            else None,
            "payload": payload,
        }
