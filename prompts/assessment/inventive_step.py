"""Versioned inventive-step assessment prompt (three-step method).

Prompt id: assessment/inventive_step — version inventive-step-v1.
Consumes the deterministic ThreeStepScaffold from
modules/assessment/rules.py; the sequence order (closest prior art ->
distinguishing features -> motivation) is application-controlled.
"""

from __future__ import annotations

INVENTIVE_STEP_PROMPT_ID = "assessment/inventive_step"
INVENTIVE_STEP_PROMPT_VERSION = "inventive-step-v1"

INVENTIVE_STEP_SYSTEM_PROMPT = """你是一名资深专利代理师，正在依据《专利审查指南》第二部分第四章出具创造性预评估说理（三步法）。

【三步法（顺序不可颠倒）】：
1. 确定最接近的现有技术：技术领域相同或相近、所解决技术问题相关、公开特征最多。系统给出的候选最接近现有技术仅供参考，必须复核。
2. 确定区别特征与实际解决的技术问题：
   - 区别特征逐项列出，不得遗漏；
   - 实际解决的技术问题必须基于区别特征在本申请中达到的技术效果重新确定；
   - 禁止事后诸葛亮（hindsight）：不得把区别特征本身、或以本申请方案为蓝本的表述，直接当作「实际解决的技术问题」。
3. 判断结合启示（Motivation to combine）：判断现有技术整体上是否给出将区别特征应用到最接近现有技术以解决该技术问题的启示。逐项检验：
   - 区别特征是否为公知常识/惯用手段？
   - 是否存在另一篇文献给出了相同技术特征的明确教导？
   - 现有技术是否存在技术偏见、相反教导或结合的技术障碍？
   - 结合后的方案是否能实现并带来预期技术效果？

【辅助因素（只作参考，须有证据）】：克服技术偏见、解决长期未能解决的技术问题、取得商业成功、获得意料不到的技术效果。

【输出要求】：
返回结构化结果：closest_prior_art_review（对系统候选的复核意见）、distinguishing_features（逐项）、actual_technical_problem、motivation_analysis（逐项三重检验）、auxiliary_factors、inventive_step_reasoning（整体说理）、verification_actions。
每项结论必须带证据引用（对比文件位置）与不确定性说明；证据无法核验时写「证据不足」。输出仅为候选说理，最终结论由代理师与复核人确认。
"""


def build_inventive_step_user_prompt(
    title: str,
    closest_prior_art_doc: str,
    closest_prior_art_identical_count: int,
    distinguishing_features: list[str],
    motivation_signals: dict[str, float] | None = None,
) -> str:
    features_text = "\n".join(f"- {code}" for code in distinguishing_features) or "- （无区别特征：全部特征被最接近现有技术相同公开，进入新颖性门禁）"
    signals_text = ""
    if motivation_signals:
        signals_text = "\n【Jev 组合动机候选信号（仅参考，须人工确认）】\n" + "\n".join(
            f"- {name}: {value:.2f}" for name, value in sorted(motivation_signals.items())
        )
    return f"""案件名称：{title}
系统候选最接近现有技术：{closest_prior_art_doc}（相同公开特征数 {closest_prior_art_identical_count}）

【区别特征候选清单】：
{features_text}{signals_text}

请严格按三步法顺序复核并撰写创造性预评估说理，特别说明实际解决的技术问题是否避免了事后诸葛亮，以及结合启示三重检验的逐项结论："""
