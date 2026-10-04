"""FTO claim charts: snapshot claims, confirm claim features, record manual findings (ADR 0011).

Conclusions are derived on read with the exact all-elements algorithm from
ADR 0008 (modules.fto.chart); they are risk indications, not legal opinions.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.fto import ep_claims, us_claims
from modules.fto.chart import claim_conclusion, conclude_claim
from modules.fto.model import Claim, ClaimChart, ClaimFeature, ClaimSet, FeatureAssessment

FINDINGS = ("literally_present", "present_by_equivalent", "absent", "undetermined")
NEEDS_PRODUCT_FEATURE = {"literally_present", "present_by_equivalent"}
NEEDS_RATIONALE = {"present_by_equivalent", "absent"}

CAVEAT_AS_GRANTED = (
    "US claims are as granted: later reexamination, IPR or correction certificates may have amended "
    "or cancelled claims, and are not reflected here."
)
CAVEAT_TRANSLATION = (
    "EP claims may be a translation; the language of the proceedings (authentic text, EPC Art. 70(1)) "
    "is not stated by the source."
)
CAVEAT_NOT_LEGAL_ADVICE = "Conclusions are risk indications derived from recorded findings, not a legal opinion."


def _parse(source: str, claims_text: str, publication_number: str) -> tuple[ClaimSet, str]:
    if source == "uspto_grant_xml":
        return us_claims.parse_us_claims(claims_text, publication_number=publication_number), us_claims.PARSER_ID
    if source == "epo_ops_claims":
        return ep_claims.parse_ep_claims(json.loads(claims_text), publication_number=publication_number), ep_claims.PARSER_ID
    raise HTTPException(status_code=409, detail="unsupported_claim_source")


class FtoChartService:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    async def create_chart(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        case_id: UUID,
        publication_number: str,
        product_feature_set_id: UUID,
        actor_id: UUID,
    ) -> dict[str, Any]:
        product_set = (
            await session.execute(
                text("SELECT case_id, status FROM product_feature_sets WHERE id = :id AND organization_id = :org"),
                {"id": product_feature_set_id, "org": organization_id},
            )
        ).one_or_none()
        if product_set is None or product_set.case_id != case_id:
            raise HTTPException(status_code=404, detail="product_feature_set_not_found")
        if product_set.status != "confirmed":
            raise HTTPException(status_code=409, detail="product_feature_set_not_confirmed")

        document = (
            await session.execute(
                text(
                    """SELECT id, source, claims_text, text_represents FROM patent_claim_documents
                    WHERE publication_number = :pub AND outcome = 'found'
                    ORDER BY retrieved_at DESC LIMIT 1"""
                ),
                {"pub": publication_number},
            )
        ).one_or_none()
        if document is None:
            raise HTTPException(status_code=409, detail="claims_not_fetched")

        claim_set, parser = _parse(document.source, document.claims_text, publication_number)
        snapshot = {
            "language": claim_set.language,
            "proceedings_language": claim_set.proceedings_language,
            "warnings": list(claim_set.warnings),
            "claims": [
                {
                    "number": c.number,
                    "depends_on": list(c.depends_on),
                    "structure_source": c.structure_source,
                    "warnings": list(c.parse_warnings),
                }
                for c in claim_set.claims
            ],
        }
        chart_id = uuid4()
        await session.execute(
            text(
                """INSERT INTO fto_charts
                (id, organization_id, case_id, publication_number, claim_document_id, claims_text_sha256,
                 parser, text_represents, claims_snapshot, product_feature_set_id, created_by_identity_id, created_at)
                VALUES (:id, :org, :case, :pub, :doc, :sha, :parser, :represents, CAST(:snapshot AS jsonb),
                        :product, :actor, :now)"""
            ),
            {
                "id": chart_id, "org": organization_id, "case": case_id, "pub": publication_number,
                "doc": document.id, "sha": hashlib.sha256(document.claims_text.encode("utf-8")).hexdigest(),
                "parser": parser, "represents": document.text_represents, "snapshot": json.dumps(snapshot),
                "product": product_feature_set_id, "actor": actor_id, "now": self._clock(),
            },
        )
        order = 0
        for claim in claim_set.claims:
            for feature in claim.features:
                await session.execute(
                    text(
                        """INSERT INTO fto_chart_claim_features
                        (organization_id, chart_id, feature_id, claim_number, feature_text, spans, sort_order)
                        VALUES (:org, :chart, :fid, :claim, :text, CAST(:spans AS jsonb), :order)"""
                    ),
                    {
                        "org": organization_id, "chart": chart_id, "fid": feature.feature_id,
                        "claim": claim.number, "text": feature.text,
                        "spans": json.dumps([list(s) for s in feature.spans]), "order": order,
                    },
                )
                order += 1
        return await self.get_chart(session, organization_id=organization_id, chart_id=chart_id)

    async def confirm_claim_features(
        self, session: AsyncSession, *, organization_id: UUID, chart_id: UUID, claim_number: int, actor_id: UUID
    ) -> dict[str, Any]:
        chart = await self.get_chart(session, organization_id=organization_id, chart_id=chart_id)
        if not any(c["number"] == claim_number for c in chart["claims"]):
            raise HTTPException(status_code=404, detail="claim_not_found")
        await session.execute(
            text(
                """UPDATE fto_chart_claim_features
                SET confirmed_by_identity_id = :actor, confirmed_at = :now
                WHERE chart_id = :chart AND organization_id = :org AND claim_number = :claim
                  AND confirmed_at IS NULL"""
            ),
            {"actor": actor_id, "now": self._clock(), "chart": chart_id, "org": organization_id, "claim": claim_number},
        )
        return await self.get_chart(session, organization_id=organization_id, chart_id=chart_id)

    async def record_finding(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        chart_id: UUID,
        feature_id: str,
        finding: str,
        product_feature_codes: list[str],
        rationale: str,
        actor_id: UUID,
    ) -> dict[str, Any]:
        if finding not in FINDINGS:
            raise HTTPException(status_code=422, detail="invalid_finding")
        codes = sorted(set(product_feature_codes))
        if finding in NEEDS_PRODUCT_FEATURE and not codes:
            raise HTTPException(status_code=422, detail="finding_needs_product_feature")
        if finding in NEEDS_RATIONALE and not rationale.strip():
            raise HTTPException(status_code=422, detail="finding_needs_rationale")
        chart = await self._chart_row(session, organization_id, chart_id)
        known_feature = (
            await session.execute(
                text("SELECT 1 FROM fto_chart_claim_features WHERE chart_id = :chart AND feature_id = :fid"),
                {"chart": chart_id, "fid": feature_id},
            )
        ).one_or_none()
        if known_feature is None:
            raise HTTPException(status_code=404, detail="claim_feature_not_found")
        if codes:
            product_codes = {
                r[0]
                for r in (
                    await session.execute(
                        text("SELECT feature_code FROM product_features WHERE feature_set_id = :set AND organization_id = :org"),
                        {"set": chart["product_feature_set_id"], "org": organization_id},
                    )
                ).all()
            }
            unknown = [c for c in codes if c not in product_codes]
            if unknown:
                raise HTTPException(status_code=422, detail=f"unknown_product_features:{','.join(unknown)}")
        await session.execute(
            text(
                """INSERT INTO fto_feature_findings
                (id, organization_id, chart_id, feature_id, finding, product_feature_codes, rationale,
                 assessed_by_identity_id, assessed_at)
                VALUES (:id, :org, :chart, :fid, :finding, :codes, :rationale, :actor, :now)"""
            ),
            {
                "id": uuid4(), "org": organization_id, "chart": chart_id, "fid": feature_id, "finding": finding,
                "codes": codes, "rationale": rationale.strip(), "actor": actor_id, "now": self._clock(),
            },
        )
        return await self.get_chart(session, organization_id=organization_id, chart_id=chart_id)

    async def list_charts(self, session: AsyncSession, *, organization_id: UUID, case_id: UUID) -> list[dict[str, Any]]:
        rows = (
            await session.execute(
                text(
                    """SELECT id, publication_number, product_feature_set_id, text_represents, created_at
                    FROM fto_charts WHERE case_id = :case AND organization_id = :org ORDER BY created_at DESC"""
                ),
                {"case": case_id, "org": organization_id},
            )
        ).mappings().all()
        return [
            {"id": str(r["id"]), "publication_number": r["publication_number"],
             "product_feature_set_id": str(r["product_feature_set_id"]),
             "text_represents": r["text_represents"], "created_at": r["created_at"].isoformat()}
            for r in rows
        ]

    async def get_chart(self, session: AsyncSession, *, organization_id: UUID, chart_id: UUID) -> dict[str, Any]:
        chart = await self._chart_row(session, organization_id, chart_id)
        features = (
            await session.execute(
                text(
                    """SELECT feature_id, claim_number, feature_text, spans, confirmed_at
                    FROM fto_chart_claim_features WHERE chart_id = :chart ORDER BY sort_order"""
                ),
                {"chart": chart_id},
            )
        ).mappings().all()
        latest = {
            r["feature_id"]: r
            for r in (
                await session.execute(
                    text(
                        """SELECT DISTINCT ON (feature_id) feature_id, finding, product_feature_codes, rationale, assessed_at
                        FROM fto_feature_findings WHERE chart_id = :chart
                        ORDER BY feature_id, assessed_at DESC, id"""
                    ),
                    {"chart": chart_id},
                )
            ).mappings().all()
        }
        snapshot = chart["claims_snapshot"]
        by_claim: dict[int, list[ClaimFeature]] = {}
        for f in features:
            by_claim.setdefault(f["claim_number"], []).append(
                ClaimFeature(
                    feature_id=f["feature_id"], claim_number=f["claim_number"], text=f["feature_text"],
                    spans=tuple(tuple(s) for s in f["spans"]),
                    status="confirmed" if f["confirmed_at"] else "proposed",
                )
            )
        claim_set = ClaimSet(
            publication_number=chart["publication_number"],
            claims=tuple(
                Claim(
                    number=c["number"], text="", depends_on=tuple(c["depends_on"]),
                    structure_source=c["structure_source"], features=tuple(by_claim.get(c["number"], [])),
                )
                for c in snapshot["claims"]
            ),
            language=snapshot.get("language"),
            proceedings_language=snapshot.get("proceedings_language"),
        )
        claim_chart = ClaimChart(claim_set)
        for fid, row in latest.items():
            claim_chart.assessments[fid] = FeatureAssessment(fid, row["finding"], rationale=row["rationale"])
        caveats = [CAVEAT_NOT_LEGAL_ADVICE]
        if chart["text_represents"] == "as_granted":
            caveats.insert(0, CAVEAT_AS_GRANTED)
        ep_text = any(c["structure_source"] == "ops_text_parsed" for c in snapshot["claims"])
        if ep_text and claim_set.is_translation is not False:  # unknown or known translation
            caveats.insert(0, CAVEAT_TRANSLATION)
        claims_out = []
        for c in snapshot["claims"]:
            result = conclude_claim(claim_chart, c["number"])
            claims_out.append(
                {
                    "number": c["number"],
                    "depends_on": c["depends_on"],
                    "warnings": c["warnings"],
                    "conclusion": claim_conclusion(claim_chart, c["number"]),
                    "absent_features": sorted({fid for p in result.paths for fid in p.absent}),
                    "features": [
                        {
                            "feature_id": f.feature_id,
                            "text": f.text,
                            "confirmed": f.status == "confirmed",
                            "finding": latest[f.feature_id]["finding"] if f.feature_id in latest else None,
                            "product_feature_codes": list(latest[f.feature_id]["product_feature_codes"]) if f.feature_id in latest else [],
                            "rationale": latest[f.feature_id]["rationale"] if f.feature_id in latest else "",
                        }
                        for f in by_claim.get(c["number"], [])
                    ],
                }
            )
        return {
            "id": str(chart["id"]),
            "case_id": str(chart["case_id"]),
            "publication_number": chart["publication_number"],
            "product_feature_set_id": str(chart["product_feature_set_id"]),
            "text_represents": chart["text_represents"],
            "parser": chart["parser"],
            "claims_text_sha256": chart["claims_text_sha256"],
            "warnings": snapshot.get("warnings", []),
            "caveats": caveats,
            "claims": claims_out,
        }

    async def finding_history(
        self, session: AsyncSession, *, organization_id: UUID, chart_id: UUID, feature_id: str
    ) -> list[dict[str, Any]]:
        await self._chart_row(session, organization_id, chart_id)
        rows = (
            await session.execute(
                text(
                    """SELECT finding, product_feature_codes, rationale, assessed_by_identity_id, assessed_at
                    FROM fto_feature_findings WHERE chart_id = :chart AND feature_id = :fid
                    ORDER BY assessed_at DESC, id"""
                ),
                {"chart": chart_id, "fid": feature_id},
            )
        ).mappings().all()
        return [
            {"finding": r["finding"], "product_feature_codes": list(r["product_feature_codes"]),
             "rationale": r["rationale"], "assessed_by": str(r["assessed_by_identity_id"]),
             "assessed_at": r["assessed_at"].isoformat()}
            for r in rows
        ]

    async def _chart_row(self, session: AsyncSession, organization_id: UUID, chart_id: UUID) -> dict[str, Any]:
        row = (
            await session.execute(
                text(
                    """SELECT id, case_id, publication_number, product_feature_set_id, text_represents, parser,
                              claims_text_sha256, claims_snapshot
                    FROM fto_charts WHERE id = :id AND organization_id = :org"""
                ),
                {"id": chart_id, "org": organization_id},
            )
        ).mappings().one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="fto_chart_not_found")
        return dict(row)
