from __future__ import annotations

from prompts.assessment import PROMPT_REGISTRY
from prompts.assessment.inventive_step import (
    INVENTIVE_STEP_SYSTEM_PROMPT,
    build_inventive_step_user_prompt,
)
from prompts.assessment.novelty import NOVELTY_SYSTEM_PROMPT, build_novelty_user_prompt
from prompts.originality.originality import ORIGINALITY_SYSTEM_PROMPT, build_originality_user_prompt


def test_assessment_prompts_are_version_registered() -> None:
    assert PROMPT_REGISTRY["assessment/novelty"]["version"] == "novelty-v1"
    assert PROMPT_REGISTRY["assessment/inventive_step"]["version"] == "inventive-step-v1"
    assert "assessment/originality" not in PROMPT_REGISTRY  # 独创性不在专利评估边界内


def test_novelty_prompt_enforces_single_reference_principle() -> None:
    assert "单独对比原则" in NOVELTY_SYSTEM_PROMPT
    assert "禁止将多篇文献的内容组合评价新颖性" in NOVELTY_SYSTEM_PROMPT
    assert "抵触申请" in NOVELTY_SYSTEM_PROMPT

    user_prompt = build_novelty_user_prompt(
        "测试量化专利",
        doc_id="D1",
        publication_number="CN117283912A",
        feature_rows=[
            {"feature_code": "F1", "judgment": "identical", "citation_location": "[0012]", "citation_quote": "低位宽映射"}
        ],
    )
    assert "CN117283912A" in user_prompt
    assert "低位宽映射" in user_prompt
    assert "【0012】" not in user_prompt  # raw location text passes through unchanged


def test_inventive_step_prompt_keeps_three_step_order_and_hindsight_ban() -> None:
    assert "三步法" in INVENTIVE_STEP_SYSTEM_PROMPT
    assert "事后诸葛亮" in INVENTIVE_STEP_SYSTEM_PROMPT
    assert "结合启示" in INVENTIVE_STEP_SYSTEM_PROMPT

    user_prompt = build_inventive_step_user_prompt(
        "测试量化专利",
        closest_prior_art_doc="D1 (CN117283912A)",
        closest_prior_art_identical_count=2,
        distinguishing_features=["F3"],
        motivation_signals={"same_field": 0.91, "same_problem": 0.84},
    )
    assert "D1 (CN117283912A)" in user_prompt
    assert "- F3" in user_prompt
    assert "0.91" in user_prompt
    assert "须人工确认" in user_prompt


def test_inventive_step_prompt_without_signals_has_no_signal_block() -> None:
    user_prompt = build_inventive_step_user_prompt(
        "测试", closest_prior_art_doc="D1", closest_prior_art_identical_count=3, distinguishing_features=[]
    )
    assert "组合动机候选信号" not in user_prompt
    assert "新颖性门禁" in user_prompt


def test_originality_prompt_covers_two_elements_and_idea_expression_dichotomy() -> None:
    assert "独立完成" in ORIGINALITY_SYSTEM_PROMPT
    assert "最低限度的创造性" in ORIGINALITY_SYSTEM_PROMPT
    assert "思想/表达二分法" in ORIGINALITY_SYSTEM_PROMPT
    assert "混同" in ORIGINALITY_SYSTEM_PROMPT

    user_prompt = build_originality_user_prompt(
        "软件著作权侵权案",
        claimed_work={"name": "原告作品", "kind": "文字作品", "created_at": "2025-01"},
        accused_work={"name": "被诉作品", "kind": "文字作品"},
        expression_elements=[
            {"element": "章节编排", "claimed_location": "P3", "accused_location": "P5", "preliminary": "实质相似"}
        ],
    )
    assert "原告作品" in user_prompt
    assert "章节编排" in user_prompt
