from __future__ import annotations

from modules.search.strategy_planner import SearchStrategyPlanner
from modules.search.handoff import HandoffPackageGenerator


def test_search_strategy_planner_generates_queries() -> None:
    planner = SearchStrategyPlanner()
    features = [
        {
            "feature_code": "F1",
            "feature_type": "preamble",
            "feature_statement": "一种基于大模型混合精度量化的推理方法。",
        },
        {
            "feature_code": "F2",
            "feature_type": "characterizing",
            "feature_statement": "对预训练权重矩阵执行奇异值分解与稀疏量化查找表构建。",
        },
    ]

    plan = planner.plan_strategy(
        features=features,
        technical_field="人工智能 / 深度学习",
        title="大模型稀疏量化方法",
    )

    assert len(plan.keywords_matrix) >= 2
    assert "大模型" in plan.keywords_matrix or "量化" in plan.keywords_matrix
    assert len(plan.ipc_classes) >= 1
    assert any("G06N" in ipc["code"] or "G06F" in ipc["code"] for ipc in plan.ipc_classes)
    assert "AND" in plan.boolean_query_cnipr
    assert "IPC:" in plan.boolean_query_cnipr


def test_handoff_package_generator_markdown_and_json() -> None:
    gen = HandoffPackageGenerator()
    case_info = {
        "case_number": "2026-TEST-001",
        "title": "大模型量化系统",
        "technical_field": "AI",
    }
    strategy = {
        "boolean_query_cnipr": "(大模型 OR LLM) AND (量化 OR 稀疏)",
        "ipc_classes": [{"code": "G06N 3/08", "description": "神经网络计算"}],
    }
    features = [
        {"feature_code": "F1", "feature_type": "preamble", "feature_statement": "前序特征说明", "source_paragraph_id": "p1"}
    ]

    md = gen.generate_markdown(case_info, strategy, features)
    assert "CNIPR 官方专利检索人工交接规范包" in md
    assert "2026-TEST-001" in md
    assert "(大模型 OR LLM) AND (量化 OR 稀疏)" in md

    data = gen.generate_json(case_info, strategy, features)
    assert data["case"]["case_number"] == "2026-TEST-001"
    assert data["instructions"]["target_platform"] == "CNIPR (国家知识产权局专利检索及分析系统)"
