import pytest
from prompts.feature_modeling import build_feature_modeling_user_prompt, FEATURE_MODELING_SYSTEM_PROMPT
from prompts.search_planning import build_search_planning_user_prompt, SEARCH_PLANNING_SYSTEM_PROMPT
from prompts.claim_comparison import build_claim_comparison_user_prompt, CLAIM_COMPARISON_SYSTEM_PROMPT
from prompts.risk_assessment import build_risk_assessment_user_prompt, RISK_ASSESSMENT_SYSTEM_PROMPT
from adapters.llm.schemas import (
    FeatureExtractionResultSchema,
    SearchStrategyResultSchema,
    ComparisonMatrixResultSchema,
    ClaimComparisonItemSchema,
)


def test_feature_modeling_prompt_generation():
    assert "专利审查指南" in FEATURE_MODELING_SYSTEM_PROMPT
    user_prompt = build_feature_modeling_user_prompt(
        "测试神经网络加速器",
        [{"id": "0001", "text": "一种加速矩阵计算的硬件系统。"}]
    )
    assert "测试神经网络加速器" in user_prompt
    assert "[0001]" in user_prompt


def test_search_planning_prompt_generation():
    assert "EPO" in SEARCH_PLANNING_SYSTEM_PROMPT
    assert "USPTO" in SEARCH_PLANNING_SYSTEM_PROMPT
    assert "CNIPR" in SEARCH_PLANNING_SYSTEM_PROMPT
    user_prompt = build_search_planning_user_prompt(
        "测试专利",
        "人工智能",
        [{"feature_code": "F1", "feature_type": "characterizing", "feature_statement": "量化稀疏矩阵"}]
    )
    assert "量化稀疏矩阵" in user_prompt


def test_claim_comparison_prompt_generation():
    assert "全面覆盖原则" in CLAIM_COMPARISON_SYSTEM_PROMPT
    user_prompt = build_claim_comparison_user_prompt(
        {"feature_code": "F1", "feature_statement": "位图索引稀疏跳过"},
        {"publication_number": "EP3989123A1", "title": "稀疏网络"},
        [{"id": "0035", "text": "通过位图跳过全零数据权重。"}]
    )
    assert "位图索引稀疏跳过" in user_prompt
    assert "EP3989123A1" in user_prompt
    assert "【段落标号 0035】" in user_prompt


def test_risk_assessment_prompt_generation():
    assert "创造性三步法" in RISK_ASSESSMENT_SYSTEM_PROMPT
    user_prompt = build_risk_assessment_user_prompt(
        "测试专利",
        feature_count=3,
        identical_count=2,
        equivalent_count=1,
        different_count=0,
        itemized_summary=[{"feature_code": "F1", "judgment": "identical", "citation_location": "[0012]", "reasoning": "全公开"}]
    )
    assert "相同公开=2" in user_prompt


def test_risk_assessment_prompt_produces_candidates_not_conclusions():
    """提示词不得让模型出具结论——授权与否由人判断。"""
    assert "出具全案可专利性预评估结论" not in RISK_ASSESSMENT_SYSTEM_PROMPT
    assert "具备充分可专利性前景" not in RISK_ASSESSMENT_SYSTEM_PROMPT
    assert "候选" in RISK_ASSESSMENT_SYSTEM_PROMPT
    # 模型没有申请日与优先权日，不得自行判定现有技术资格
    assert "待日期门禁核验" in RISK_ASSESSMENT_SYSTEM_PROMPT
    assert "不得给出授权结论" in build_risk_assessment_user_prompt(
        "测试专利",
        feature_count=1,
        identical_count=0,
        equivalent_count=0,
        different_count=1,
        itemized_summary=[],
    )
