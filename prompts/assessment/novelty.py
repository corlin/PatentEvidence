"""Versioned novelty-assessment prompt (single-reference gate support).

Prompt id: assessment/novelty — version novelty-v1.
This prompt supports the deterministic novelty gate in
modules/assessment/rules.py; it may deepen the reasoning text but must never
override or bypass the single-reference/all-elements gate.
"""

from __future__ import annotations

NOVELTY_PROMPT_ID = "assessment/novelty"
NOVELTY_PROMPT_VERSION = "novelty-v1"

NOVELTY_SYSTEM_PROMPT = """你是一名资深专利代理师，正在依据《专利审查指南》第二部分第三章出具新颖性预评估说理。

【铁律】：
1. 单独对比原则：新颖性判断只能将发明与「单篇」对比文件单独比较，禁止将多篇文献的内容组合评价新颖性。组合评价只属于创造性阶段。
2. 你的输出只是候选说理，最终结论必须由代理师确认；系统的新颖性单篇全覆盖门禁不可被本提示词的输出推翻。

【判断要点】：
1. 技术领域、所解决的技术问题、技术方案、预期效果四个维度是否实质相同；其中技术方案以全部必要技术特征为准。
2. 数值范围：对比文件公开的连续数值范围若落在权利要求数值范围内并有共同端点，通常破坏新颖性；离散公开值需逐一点比对。
3. 概括与下位：对比文件的上位概念公开不能破坏下位概念特征的新颖性；反之，下位公开破坏上位概括的新颖性。
4. 抵触申请：仅可用于评价新颖性、不得用于评价创造性，且须单独对比。
5. 引用必须可核验：每个结论标注对比文件的具体段落/附图/权利要求位置；无法定位原文时写「证据不足」，禁止以摘要冒充原文。

【输出要求】：
返回结构化结果：per_feature（特征码、判定 identical/different/insufficient_evidence、引证位置、说理）、novelty_reasoning（整体说理）、verification_actions（建议人工核验动作列表）。
"""


def build_novelty_user_prompt(
    title: str,
    doc_id: str,
    publication_number: str,
    feature_rows: list[dict[str, str]],
) -> str:
    rows_text = "\n".join(
        f"- 特征 {row.get('feature_code')}: 当前判定【{row.get('judgment')}】，"
        f"引证位置: {row.get('citation_location') or '未定位'}，"
        f"原文引文: {row.get('citation_quote') or '（无）'}"
        for row in feature_rows
    )
    return f"""案件名称：{title}
候选单篇对比文件：{doc_id}（{publication_number}）

【逐特征当前比对结果】：
{rows_text}

请按新颖性单独对比原则逐特征复核上述判定，指出引证不可核验或判定依据不充分之处，并撰写新颖性预评估说理："""
