"""Versioned originality (copyright) assessment prompt.

Prompt id: assessment/originality — version originality-v1.
Covers 独创性 assessment for evidence cases involving works (text, drawings,
software, datasets): independent creation + minimal creative choice, the
idea/expression dichotomy, and merger / scanned-in limitations. Output is
candidate reasoning only; conclusions require patent/legal-agent and reviewer
confirmation.
"""

from __future__ import annotations

ORIGINALITY_PROMPT_ID = "assessment/originality"
ORIGINALITY_PROMPT_VERSION = "originality-v1"

ORIGINALITY_SYSTEM_PROMPT = """你是一名资深知识产权律师，正在对涉案作品出具独创性预评估说理（著作权法语境）。

【独创性两要件】：
1. 独立完成：作品由作者独立创作完成，非抄袭、非机械复制。存在接触+实质性相似证据时必须逐项指出。
2. 最低限度的创造性：体现了作者个性化的选择、取舍、安排或表达。判断对象是表达而非价值高低；不以艺术质量优劣为标准（避免「美感标准」误用）。

【思想/表达二分法】：
- 受保护的是表达，不是思想、程序、工艺、操作方法、概念、原理、事实或数据本身。
- 数据汇编受保护的是内容的选择或编排上的独创性，而非数据本身。

【独创性受限的情形】（逐项排查）：
1. 思想与表达混同（merger）：某思想只有唯一或极有限表达方式时，表达不受保护。
2. 有限表达/标准化表达：通用表格、公式、常用参数、行业标准的照抄部分。
3. 事实性内容与客观限制决定的表达（扫描件、照片对客观物体的忠实记录中不受保护的部分）。
4. 过滤后仍具备独创性的部分需逐项指明（类似「抽象-过滤-比较」路径），不得笼统认定整体独创。

【比对要求】：
- 逐要素比对：将原告主张作品与被诉作品按表达要素拆分，标注相同、实质相似、不同；
- 每项结论必须引用双方作品的具体位置（页/段/行/图）；无法定位原文时写「证据不足」，禁止以描述性摘要冒充原文；
- 给出接触可能性证据清单与缺口。

【输出要求】：
返回结构化结果：work_elements（逐表达要素、独创性判定 protectable/unprotectable/insufficient_evidence、依据与引证）、access_evidence、substantial_similarity、originality_reasoning、verification_actions。
输出仅为候选说理，最终结论由代理师与复核人确认。
"""


def build_originality_user_prompt(
    case_title: str,
    claimed_work: dict[str, str],
    accused_work: dict[str, str],
    expression_elements: list[dict[str, str]] | None = None,
) -> str:
    elements_text = ""
    if expression_elements:
        elements_text = "\n【已拆分表达要素】\n" + "\n".join(
            f"- {item.get('element')}: 原告作品位置 {item.get('claimed_location') or '未定位'}，"
            f"被诉作品位置 {item.get('accused_location') or '未定位'}，"
            f"初步比对 {item.get('preliminary') or '未比对'}"
            for item in expression_elements
        )
    return f"""案件名称：{case_title}

【主张作品】：
- 名称/类型：{claimed_work.get('name', '未提供')} / {claimed_work.get('kind', '未提供')}
- 创作完成时间：{claimed_work.get('created_at', '未提供')}
- 首次发表/使用：{claimed_work.get('published_at', '未提供')}
- 权利凭证：{claimed_work.get('title_evidence', '未提供')}

【被诉作品】：
- 名称/类型：{accused_work.get('name', '未提供')} / {accused_work.get('kind', '未提供')}
- 公开时间：{accused_work.get('published_at', '未提供')}
- 来源线索：{accused_work.get('source_clue', '未提供')}
{elements_text}

请按独创性两要件与思想/表达二分法逐要素出具独创性预评估说理，明确过滤不受保护部分，并给出接触+实质性相似证据缺口清单："""
