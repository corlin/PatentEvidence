from __future__ import annotations

from modules.comparison.engine import RuleComparisonEngine
from modules.comparison.evaluator import MatrixEvaluator


def test_comparison_engine_identifies_identical_features() -> None:
    engine = RuleComparisonEngine()
    feat_code = "F1"
    feat_stmt = "一种面向低位宽的大语言模型混合精度量化推理加速方法。"
    cand_title = "一种基于大模型混合精度量化的推理方法及系统"
    cand_abs = "本发明公开了一种面向大语言模型的低位宽混合精度量化加速架构，通过奇异值分解优化权重分布。"

    res = engine.compare_feature_with_candidate(
        feature_code=feat_code,
        feature_statement=feat_stmt,
        candidate_pub_no="CN117283912A",
        candidate_title=cand_title,
        candidate_abstract=cand_abs,
    )

    assert res.judgment in ("identical", "equivalent")
    assert res.confidence_score >= 75.0
    assert "说明书第" in res.citation_location
    assert len(res.citation_quote) > 0
    assert "CN117283912A" in res.reasoning_analysis


def test_comparison_engine_identifies_different_features() -> None:
    engine = RuleComparisonEngine()
    feat_code = "F3"
    feat_stmt = "根据权利要求 1 所述的方法，基于反向传播梯度方差自适应设置量化位宽阈值。"
    cand_title = "一种机械传动减速齿轮箱"
    cand_abs = "本发明公开了一种高耐磨圆柱齿轮结构与润滑回路。"

    res = engine.compare_feature_with_candidate(
        feature_code=feat_code,
        feature_statement=feat_stmt,
        candidate_pub_no="CN209999123U",
        candidate_title=cand_title,
        candidate_abstract=cand_abs,
    )

    assert res.judgment == "different"
    assert "显著区别技术特征" in res.reasoning_analysis


def test_matrix_evaluator_risk_levels() -> None:
    evaluator = MatrixEvaluator()
    features = [{"id": "f1"}, {"id": "f2"}]
    candidates = [{"id": "c1", "publication_number": "D1"}]

    # All identical -> high novelty risk
    comparisons_high = [
        {"claim_feature_id": "f1", "candidate_id": "c1", "judgment": "identical"},
        {"claim_feature_id": "f2", "candidate_id": "c1", "judgment": "identical"},
    ]
    res_high = evaluator.evaluate_matrix(features, candidates, comparisons_high)
    assert res_high["risk_level"] == "high_novelty_risk"
    assert "候选提示" in res_high["summary"]
    assert res_high["candidate_nature"] is True

    # Partial -> inventiveness risk
    comparisons_part = [
        {"claim_feature_id": "f1", "candidate_id": "c1", "judgment": "identical"},
        {"claim_feature_id": "f2", "candidate_id": "c1", "judgment": "different"},
    ]
    res_part = evaluator.evaluate_matrix(features, candidates, comparisons_part)
    assert res_part["risk_level"] == "inventiveness_risk"
    assert "候选提示" in res_part["summary"]

    # 全覆盖也不得倒向结论：计数不知道对比文件是否构成现有技术
    assert res_high["summary"].startswith("【候选提示")
    assert "不构成专利性结论" in res_high["disclaimer"]


def test_matrix_evaluator_never_claims_patentability() -> None:
    """计数结果不得出现授权前景类措辞——它没跑日期门禁、优先权核验与引文核验。"""
    evaluator = MatrixEvaluator()
    features = [{"id": "f1"}, {"id": "f2"}]
    candidates = [{"id": "c1", "publication_number": "D1"}]

    # 无任何 identical / equivalent —— 正是旧文案会输出「良好授权前景」的分支
    comparisons_clear = [
        {"claim_feature_id": "f1", "candidate_id": "c1", "judgment": "different"},
        {"claim_feature_id": "f2", "candidate_id": "c1", "judgment": "different"},
    ]
    res = evaluator.evaluate_matrix(features, candidates, comparisons_clear)
    assert res["risk_level"] == "clear_difference"

    # 只禁肯定式表述；否定式声明（「不构成…授权前景意见」）是必需的，不该被误伤
    banned = ["良好授权前景", "具备清晰的技术创新高度", "具备良好的", "✓"]
    text = res["summary"] + res["disclaimer"]
    for phrase in banned:
        assert phrase not in text
    assert res["summary"].startswith("【候选提示")

    # 空数据分支同样不许给倾向性判断
    empty = evaluator.evaluate_matrix([], [], [])
    assert empty["risk_level"] == "unknown"
    assert empty["candidate_nature"] is True
    assert "无法评估全案风险" not in empty["summary"]
