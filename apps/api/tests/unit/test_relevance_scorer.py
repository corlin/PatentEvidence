from __future__ import annotations

from modules.search.scorer import RelevanceScorer


def test_relevance_scorer_computation() -> None:
    scorer = RelevanceScorer()
    kw_matrix = {
        "大模型": ["大模型", "大语言模型", "LLM"],
        "量化": ["量化", "混合精度", "低位宽"],
    }
    target_ipcs = [{"code": "G06N 3/08", "description": "计算模型"}]

    # High match candidate
    score_high = scorer.compute_score(
        candidate_title="基于大模型与低位宽量化的推理加速方法",
        candidate_abstract="本发明公开了一种大语言模型权重矩阵混合精度压缩方案。",
        candidate_ipc="G06N 3/08",
        keywords_matrix=kw_matrix,
        target_ipc_classes=target_ipcs,
    )

    # Low match candidate
    score_low = scorer.compute_score(
        candidate_title="一种水利大坝渗漏监测装置",
        candidate_abstract="通过压力传感器测量水体压力并传输预警信号。",
        candidate_ipc="E02B 7/00",
        keywords_matrix=kw_matrix,
        target_ipc_classes=target_ipcs,
    )

    assert score_high >= 60.0
    assert score_low <= 20.0
    assert score_high > score_low
