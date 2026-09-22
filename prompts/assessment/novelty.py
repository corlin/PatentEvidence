"""Versioned novelty-assessment prompt (single-reference gate support).

Prompt id: assessment/novelty — version novelty-v2.
This prompt supports the deterministic novelty gate in
modules/assessment/rules.py; it may deepen the reasoning text but must never
override or bypass the single-reference/all-elements gate.
"""

from __future__ import annotations

NOVELTY_PROMPT_ID = "assessment/novelty"
NOVELTY_PROMPT_VERSION = "novelty-v2"

NOVELTY_SYSTEM_PROMPT = """你是一名资深专利代理师，正在依据《专利审查指南》第二部分第三章出具新颖性预评估说理。

【铁律】：
1. 单独对比原则：新颖性判断只能将发明与「单篇」对比文件单独比较，禁止将多篇文献的内容组合评价新颖性。组合评价只属于创造性阶段。
2. 你的输出只是候选说理，最终结论必须由代理师确认；系统的新颖性单篇全覆盖门禁不可被本提示词的输出推翻。

【判断要点】：
1. 技术领域、所解决的技术问题、技术方案、预期效果四个维度是否实质相同；其中技术方案以全部必要技术特征为准。
2. 抵触申请：仅可用于评价新颖性、不得用于评价创造性，且须单独对比。
3. 引用必须可核验：每个结论标注对比文件的具体段落/附图/权利要求位置；无法定位原文时写「证据不足」，禁止以摘要冒充原文。

【实体级情形（系统只会给出候选观察项，最终认定在你）】：
1. 数值范围：对比文件公开的连续数值范围与权利要求范围重叠时，通常破坏新颖性；但须排除两类例外——
   (a) 公开的仅为实施例的具体点值而非连续范围，不构成范围公开；
   (b) 权利要求构成选择发明（从较大范围中选出特定小范围并产生意想不到的效果）。
   系统标记为「可能破坏新颖性」时，你要明确写出是否落入上述例外及其依据。
2. 上位/下位概念：对比文件公开上位概念、权利要求为下位具体概念时，通常不破坏新颖性
   （例：「金属」不破坏「铜」）；反之，公开下位、权利要求为上位概括时，通常破坏新颖性。
   方向不可颠倒，须先辨明谁是上位。
3. 惯用手段的直接置换：只有当存在教科书、技术手册、标准等证据证明该替换属惯用手段时，
   才可能据此否定新颖性；无证据时不得推定，应写「证据不足」。

【输出要求】：
返回结构化结果：per_feature（特征码、判定 identical/different/insufficient_evidence、引证位置、说理）、
entity_level_review（对上述实体级候选观察项逐项复核：是否构成例外、方向是否颠倒、证据是否充分）、
novelty_reasoning（整体说理）、verification_actions（建议人工核验动作列表）。
判定仍然是候选：系统据此给出的观察项不会自动改写比对单元格的 identical/different 判定。
"""


def build_novelty_user_prompt(
    title: str,
    doc_id: str,
    publication_number: str,
    feature_rows: list[dict[str, str]],
    entity_observations: list[dict[str, str]] | None = None,
) -> str:
    rows_text = "\n".join(
        f"- 特征 {row.get('feature_code')}: 当前判定【{row.get('judgment')}】，"
        f"引证位置: {row.get('citation_location') or '未定位'}，"
        f"原文引文: {row.get('citation_quote') or '（无）'}"
        for row in feature_rows
    )
    observations_text = (
        "\n".join(
            f"- [{item.get('kind')}] 特征 {item.get('feature_code')} vs {item.get('doc_id')}："
            f"候选倾向【{item.get('effect')}】——{item.get('reasoning') or '（无）'}"
            for item in (entity_observations or [])
        )
        or "（无实体级候选观察项）"
    )
    return f"""案件名称：{title}
候选单篇对比文件：{doc_id}（{publication_number}）

【逐特征当前比对结果】：
{rows_text}

【系统给出的实体级候选观察项（仅候选，不改变上述判定）】：
{observations_text}

请按新颖性单独对比原则逐特征复核上述判定，指出引证不可核验或判定依据不充分之处；
并对每项实体级候选观察项复核其例外情形与上下位方向，最后撰写新颖性预评估说理："""
