from __future__ import annotations

from typing import Any


# Appended to every summary. The evaluation is arithmetic over the chart cells;
# it is not a patentability opinion and must not read like one.
CANDIDATE_DISCLAIMER = (
    "本判断仅基于当前比对矩阵的公开/等同计数，未经过日期门禁、优先权核验与引文核验，"
    "不构成专利性结论或授权前景意见。"
)


class MatrixEvaluator:
    """Evaluates full matrix results and produces a **candidate** reading only.

    The counting below is deterministic and stays in code, but it is arithmetic
    over chart cells: it does not know whether a document is prior art, whether
    a priority claim holds, or whether a citation was verified. Every output is
    therefore phrased as a candidate hint and carries CANDIDATE_DISCLAIMER.
    """

    def evaluate_matrix(
        self,
        features: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        comparisons: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not features or not candidates or not comparisons:
            return {
                "risk_level": "unknown",
                "summary": "尚未生成完整的对比数据，无法给出任何候选判断。",
                "candidate_nature": True,
                "disclaimer": CANDIDATE_DISCLAIMER,
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
                f"【候选提示·新颖性需重点核查】：按当前矩阵计数，对比文件 {', '.join(high_risk_candidates)}"
                f"覆盖了本申请权利要求的全部技术特征。是否真正破坏新颖性，取决于这些文件是否构成现有技术"
                f"（日期门禁）及其引文是否经核验——本环节尚未判定，不得据此认定新颖性丧失。"
            )
        elif partial_risk_candidates:
            risk_level = "inventiveness_risk"
            summary = (
                f"【候选提示·创造性需重点论证】：按当前矩阵计数，对比文件 {', '.join(partial_risk_candidates[:3])}"
                f"分别公开了部分技术特征。多篇结合是否存在技术启示、是否产生预料不到的技术效果，"
                f"须按三步法另行论证；本环节仅完成计数，不构成创造性判断。"
            )
        else:
            risk_level = "clear_difference"
            summary = (
                f"【候选提示·未发现全覆盖的对比文件】：按当前矩阵计数，检索到的对比文件与本申请各项特征均存在差异。"
                f"这**不表示**具备专利性或授权前景——检索范围、日期门禁与优先权核验均可能改变这一计数结果。"
            )

        return {
            "risk_level": risk_level,
            "summary": summary,
            "candidate_nature": True,
            "disclaimer": CANDIDATE_DISCLAIMER,
            "high_risk_candidates": high_risk_candidates,
            "partial_risk_candidates": partial_risk_candidates,
            "total_features_count": total_features,
            "total_candidates_count": len(candidates),
        }
