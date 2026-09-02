from __future__ import annotations

from typing import Any


class MatrixEvaluator:
    """Evaluates full matrix results and generates overall patentability risk conclusions."""

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
            }

        total_features = len(features)
        cand_map: dict[str, list[dict[str, Any]]] = {}
        for comp in comparisons:
            cid = str(comp.get("candidate_id"))
            cand_map.setdefault(cid, []).append(comp)

        high_risk_candidates: list[str] = []
        partial_risk_candidates: list[str] = []

        for cand in candidates:
            cid = str(cand.get("id"))
            pub = cand.get("publication_number", "未知文献")
            cand_comps = cand_map.get(cid, [])
            identical_count = sum(1 for c in cand_comps if c.get("judgment") == "identical")
            equiv_count = sum(1 for c in cand_comps if c.get("judgment") == "equivalent")

            if identical_count == total_features:
                high_risk_candidates.append(f"{pub} (全部特征完全公开)")
            elif (identical_count + equiv_count) == total_features:
                high_risk_candidates.append(f"{pub} (等同覆盖全部特征)")
            elif (identical_count + equiv_count) > 0:
                partial_risk_candidates.append(f"{pub} (公开 {identical_count + equiv_count}/{total_features} 项特征)")

        if high_risk_candidates:
            risk_level = "high_novelty_risk"
            summary = (
                f"【新颖性高风险预警】：对比文件 {', '.join(high_risk_candidates)} 已经全面公开/等同覆盖了本申请权利要求的全部技术特征。"
                f"建议代理师重点针对未被充分公开的细化实施步骤进行权利要求重构与特征补充。"
            )
        elif partial_risk_candidates:
            risk_level = "inventiveness_risk"
            summary = (
                f"【创造性审查重点关注】：现有技术对比文件 {', '.join(partial_risk_candidates[:3])} 分别公开了部分技术特征。"
                f"虽无单篇文献完全破坏新颖性，但需重点论证多篇对比文件结合时是否存在技术启示及是否产生预料不到的技术效果。"
            )
        else:
            risk_level = "clear_difference"
            summary = (
                f"【良好授权前景】：检索到的现有技术对比文件与本申请全部核心特征均存在实质性显著差异，"
                f"独立权利要求具备清晰的技术创新高度与良好的新颖性/创造性授权前景。"
            )

        return {
            "risk_level": risk_level,
            "summary": summary,
            "high_risk_candidates": high_risk_candidates,
            "partial_risk_candidates": partial_risk_candidates,
            "total_features_count": total_features,
            "total_candidates_count": len(candidates),
        }
