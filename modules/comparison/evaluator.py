from __future__ import annotations

from typing import Any


class MatrixEvaluator:
    """Deterministic novelty gate and three-step inventiveness scaffold."""

    def evaluate_matrix(
        self,
        features: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        comparisons: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not features or not candidates or not comparisons:
            return {
                "risk_level": "unknown",
                "summary": "尚未生成完整的对比数据，无法评估全案风险。",
                "covered_features_count": 0,
                "total_features_count": len(features),
                "three_step_analysis": None,
                "high_risk_candidates": [],
                "partial_risk_candidates": [],
                "total_candidates_count": len(candidates),
            }

        feature_ids = [str(feature.get("id")) for feature in features]
        cand_map: dict[str, list[dict[str, Any]]] = {}
        for comparison in comparisons:
            cand_map.setdefault(str(comparison.get("candidate_id")), []).append(comparison)

        def verified_disclosures(candidate_id: str) -> list[dict[str, Any]]:
            return [
                item
                for item in cand_map.get(candidate_id, [])
                if item.get("evidence_status") == "verified"
                and item.get("judgment") in {"identical", "equivalent"}
            ]

        ranked = sorted(
            candidates,
            key=lambda candidate: len(verified_disclosures(str(candidate.get("id")))),
            reverse=True,
        )
        closest = ranked[0]
        closest_id = str(closest.get("id"))
        closest_items = cand_map.get(closest_id, [])
        directly_disclosed = {
            str(item.get("claim_feature_id"))
            for item in closest_items
            if item.get("judgment") == "identical" and item.get("evidence_status") == "verified"
        }
        covered = {
            str(item.get("claim_feature_id"))
            for item in verified_disclosures(closest_id)
        }
        distinguishing = [feature_id for feature_id in feature_ids if feature_id not in covered]
        three_step = {
            "step_1_closest_prior_art": {
                "candidate_id": closest_id,
                "publication_number": closest.get("publication_number", "未知文献"),
                "verified_covered_features": len(covered),
            },
            "step_2_distinguishing_features": distinguishing,
            "step_3_motivation_and_effect": "not_assessed",
        }

        high_risk_candidates: list[str] = []
        partial_risk_candidates: list[str] = []
        for candidate in candidates:
            candidate_id = str(candidate.get("id"))
            publication_number = candidate.get("publication_number", "未知文献")
            items = cand_map.get(candidate_id, [])
            identical = {
                str(item.get("claim_feature_id"))
                for item in items
                if item.get("judgment") == "identical" and item.get("evidence_status") == "verified"
            }
            verified = verified_disclosures(candidate_id)
            if set(feature_ids) == identical:
                high_risk_candidates.append(f"{publication_number} (单篇文献逐项原文核验后完全公开)")
            elif verified:
                partial_risk_candidates.append(f"{publication_number} (已核验公开 {len(verified)}/{len(feature_ids)} 项特征)")

        if high_risk_candidates:
            risk_level = "high_novelty_risk"
            summary = (
                f"【新颖性高风险预警】：{', '.join(high_risk_candidates)}。"
                "该结论仅基于同一篇文献中逐项通过原文锚定的相同公开。"
            )
        else:
            risk_level = "human_review_required"
            if distinguishing:
                summary = (
                    f"【证据不足，需人工复核】：已按三步法选出最接近现有技术并识别 {len(distinguishing)} 项区别特征；"
                    "尚未完成客观技术问题、组合动机与预料不到技术效果判断，不自动给出创造性结论。"
                )
            else:
                summary = "【需人工复核】：存在等同覆盖或不完整证据，但不满足单篇文献逐项相同公开的新颖性门禁。"

        return {
            "risk_level": risk_level,
            "summary": summary,
            "high_risk_candidates": high_risk_candidates,
            "partial_risk_candidates": partial_risk_candidates,
            "total_features_count": len(features),
            "total_candidates_count": len(candidates),
            "covered_features_count": len(directly_disclosed),
            "three_step_analysis": three_step,
        }
