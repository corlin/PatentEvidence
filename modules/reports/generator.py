from __future__ import annotations

from typing import Any

from modules.reports.conclusion import (
    PUBLICATION_DISCLAIMER,
    STATUS_LABELS,
    evaluate_conclusion_eligibility,
)

FINDING_KIND = {
    "novelty": "新颖性",
    "inventive_combination": "创造性组合",
    "evidence_completeness": "证据完备度",
}

FINDING_LEVEL = {
    "high_novelty_risk": "新颖性高风险（候选）",
    "high_inventive_risk": "创造性高风险（候选）",
    "needs_confirmation": "需人工确认",
    "low": "低",
}

ASSESSMENT_CANDIDATE_NOTICE = (
    "本节全部内容为候选信号，**须人工确认**，不构成专利性结论或审查意见。"
)

# Candidate readings only. Deliberately no "授权前景" / "good prospects" wording:
# the underlying count does not know whether a document is prior art.
RISK_BADGE = {
    "high_novelty_risk": "⚠️ 候选提示：新颖性需重点核查",
    "inventiveness_risk": "⚡ 候选提示：创造性需重点论证",
    "clear_difference": "○ 候选提示：未发现全覆盖的对比文件",
    "unknown": "— 无可用计数",
}


def _basis_text(basis: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in basis:
        if isinstance(item, dict):
            parts.append("；".join(f"{k}={v}" for k, v in item.items()))
        else:
            parts.append(str(item))
    return " / ".join(parts) or "—"


def render_assessment_section(
    assessment: dict[str, Any] | None, sealed_at: str
) -> list[str]:
    """预评估门禁与候选发现摘要。

    渲染封存时刻的最新版本，并照实写明其复核状态——不因为没通过就省略，
    也不因为通过了就升级成结论。
    """
    lines: list[str] = [
        f"## 5. 预评估门禁与候选发现（须人工确认）",
        f"",
        f"> {ASSESSMENT_CANDIDATE_NOTICE}",
        f"",
    ]

    if not assessment or not assessment.get("has_version"):
        lines.extend(
            [
                f"**本案尚无预评估版本。** 日期门禁、新颖性与创造性覆盖检查、证据完备度检查"
                f"均未在本案上运行过，因此本报告不含任何评估结论或候选发现。",
                f"",
                f"如需评估，须先登记本案申请日与对比文件日期后组装预评估版本。",
                f"",
            ]
        )
        return lines

    version = assessment.get("version_number")
    status = str(assessment.get("status") or "")
    payload = assessment.get("payload") or {}
    blockers = list(assessment.get("blockers") or [])
    flags = list(assessment.get("flags") or [])
    evidence = payload.get("evidence") or {}
    scaffold = payload.get("three_step") or {}
    findings = payload.get("findings") or []

    prompt_versions = payload.get("prompt_versions") or assessment.get("prompt_versions") or {}
    prompt_text = (
        "、".join(f"{k} {v}" for k, v in sorted(prompt_versions.items()))
        if isinstance(prompt_versions, dict)
        else ""
    )

    lines.extend(
        [
            f"- **预评估版本**：v{version}"
            + (
                f"（内容摘要 `{assessment.get('payload_sha256')}`）"
                if assessment.get("payload_sha256")
                else ""
            ),
            f"- **规则版本**：`{payload.get('rules_version') or assessment.get('rules_version') or 'N/A'}`"
            + (f" ｜ **提示词版本**：{prompt_text}" if prompt_text else ""),
            f"- **复核状态**：{STATUS_LABELS.get(status, status or '未知')}"
            f"（仅表示本候选评估包是否通过内部复核，不代表该方案具备专利性）",
            f"",
        ]
    )

    if blockers:
        lines.extend([f"### 未解决的阻塞项（因此该版本不能给出结论）", f""])
        for item in blockers:
            lines.append(f"- {item}")
        lines.append(f"")
    else:
        lines.extend(
            [
                f"### 未解决的阻塞项",
                f"",
                f"- 无。未发现阻塞项**不等于**结论成立，仅表示当前材料未触发阻塞条件。",
                f"",
            ]
        )

    if flags:
        lines.extend([f"### 提示性标记", f""])
        for item in flags:
            lines.append(f"- {item}")
        lines.append(f"")

    lines.extend(
        [
            f"### 证据完备度",
            f"",
            f"| 来源覆盖率 | 已核验引文 | 缺锚点 | 未核验引文 | 失败数据源 | 阻断结论 |",
            f"| :--- | :--- | :--- | :--- | :--- | :--- |",
            f"| {evidence.get('source_coverage', 'N/A')} "
            f"| {evidence.get('verified_citations', 0)}/{evidence.get('total_citations', 0)} "
            f"| {len(evidence.get('missing_anchors') or [])} "
            f"| {len(evidence.get('unverified_citations') or [])} "
            f"| {len(evidence.get('failed_sources') or [])} "
            f"| {'是' if evidence.get('blocks_conclusion') else '否'} |",
            f"",
        ]
    )

    if scaffold:
        distinguishing = scaffold.get("distinguishing_features") or []
        lines.extend(
            [
                f"### 创造性三步法脚手架（待代理师填写的部分照实留空）",
                f"",
                f"- **最接近的现有技术（候选）**：`{scaffold.get('closest_prior_art') or 'N/A'}`"
                f"（相同特征 {scaffold.get('closest_prior_art_identical', 0)} 项）",
                f"- **区别特征**：{('、'.join(str(x) for x in distinguishing)) if distinguishing else 'N/A'}",
                f"- **实际解决的技术问题**：{scaffold.get('actual_technical_problem') or 'N/A'}",
                f"",
            ]
        )

    lines.extend([f"### 候选发现（逐条须人工确认）", f""])
    if not findings:
        lines.extend([f"- 无候选发现。", f""])
    else:
        lines.extend(
            [
                f"| 类别 | 候选层级 | 依据 | 人工确认 |",
                f"| :--- | :--- | :--- | :--- |",
            ]
        )
        for finding in findings:
            kind = FINDING_KIND.get(str(finding.get("risk_kind")), str(finding.get("risk_kind")))
            level = FINDING_LEVEL.get(str(finding.get("level")), str(finding.get("level")))
            lines.append(
                f"| {kind} | {level} | {_basis_text(finding.get('basis') or [])} | "
                f"{'须确认' if finding.get('requires_human_confirmation', True) else '—'} |"
            )
        lines.append(f"")

    # 报告不可变而评估版本可继续追加，这一条必须写进报告本身
    lines.extend(
        [
            f"> **版本冻结声明**：本报告封存于 `{sealed_at}`，引用的是封存时刻最新的预评估版本"
            f" v{version}。此后若发生修订将产生**新的版本号**，本报告不随之更新；"
            f"如需引用最新版本，须重新封存并重新出具报告。",
            f"",
        ]
    )
    return lines


class MarkdownReportGenerator:
    """Generates a structured, client-ready Markdown patent evidence analysis report."""

    def generate(self, snapshot_payload: dict[str, Any], root_sha256: str) -> str:
        assessment = snapshot_payload.get("assessment")
        eligibility = evaluate_conclusion_eligibility(assessment)
        case = snapshot_payload.get("case", {})
        doc = snapshot_payload.get("document", {})
        features = snapshot_payload.get("features", {}).get("items", [])
        search = snapshot_payload.get("search", {})
        candidates = snapshot_payload.get("candidates", [])
        comparison = snapshot_payload.get("comparison", {})
        sealed_at = snapshot_payload.get("sealed_at", "")
        sealed_by = snapshot_payload.get("sealed_by", "")

        lines: list[str] = [
            f"# 专利证据分析与法律评估报告",
            f"",
            f"> **案件编号**：`{case.get('case_number', 'N/A')}`  ",
            f"> **案件名称**：{case.get('title', 'N/A')}  ",
            f"> **技术领域**：{case.get('technical_field', 'N/A')}  ",
            f"> **封存时间**：{sealed_at}  ",
            f"> **责任代理师**：{sealed_by}  ",
            f"> **防篡改根哈希**：`{root_sha256}`  ",
            f"",
            f"---",
            f"",
            f"## 1. 技术交底文档与权利要求特征分解",
            f"",
            f"- **交底文档**：`{doc.get('filename', 'N/A')}` (版本 v{doc.get('version_number', 1)})",
            f"- **原始文件 SHA-256**：`{doc.get('file_sha256', 'N/A')}`",
            f"",
            f"### 权利要求技术特征明细表",
            f"",
            f"| 特征编号 | 特征类型 | 所在段落 | 特征具体技术内容 |",
            f"| :--- | :--- | :--- | :--- |",
        ]

        for f in features:
            f_type_str = "前序特征" if f.get("feature_type") == "preamble" else "表征特征"
            lines.append(
                f"| `{f.get('feature_code')}` | {f_type_str} | `{f.get('source_paragraph_id') or '全文'}` | {f.get('feature_statement')} |"
            )

        lines.extend(
            [
                f"",
                f"---",
                f"",
                f"## 2. 专利检索策略与 CNIPR 人工交接留痕",
                f"",
                f"### 官方 CNIPR 检索表达式",
                f"```text",
                f"{search.get('boolean_query_cnipr', 'N/A')}",
                f"```",
                f"",
                f"---",
                f"",
                f"## 3. 候选文献初筛与排除理由审计",
                f"",
                f"| 公开号 | 发明名称 | 初筛结论 | 排除原因与代理师批注 |",
                f"| :--- | :--- | :--- | :--- |",
            ]
        )

        for c in candidates:
            status_str = "✓ 纳入比对" if c.get("triage_status") == "included" else "✕ 排除"
            reason_str = c.get("exclusion_reason") or c.get("notes") or "符合对比条件"
            lines.append(
                f"| `{c.get('publication_number')}` | {c.get('title')} | {status_str} | {reason_str} |"
            )

        lines.extend(
            [
                f"",
                f"---",
                f"",
                f"## 4. 权利要求特征深度比对表 (Claim Chart Matrix)",
                f"",
                f"| 特征项 | 对比文献 | 判定结论 | 引文位置与原文摘录 | 技术论证分析 |",
                f"| :--- | :--- | :--- | :--- | :--- |",
            ]
        )

        comp_items = comparison.get("comparisons", [])
        for item in comp_items:
            j_raw = item.get("judgment")
            j_str = "🔴 相同公开" if j_raw == "identical" else ("🟡 等同替代" if j_raw == "equivalent" else "🟢 存在差异")
            loc = item.get("citation_location") or "全文"
            quote = f"“{item.get('citation_quote')}”" if item.get("citation_quote") else "无明确公开"
            lines.append(
                f"| `{item.get('feature_code')}` | `{item.get('candidate_pub_number')}` | {j_str} | {loc}<br>{quote} | {item.get('reasoning_analysis')} |"
            )

        # 5. 先讲评估事实与门禁，再讲候选判断——顺序本身就是论证的一部分
        lines.extend([f"", f"---", f""])
        lines.extend(render_assessment_section(assessment, sealed_at))

        risk_str = comparison.get("risk_level", "unknown")
        risk_badge = RISK_BADGE.get(risk_str, RISK_BADGE["unknown"])

        lines.extend([f"", f"---", f"", f"## 6. 专利性与法律风险论证（候选判断）", f""])

        if not eligibility.eligible:
            lines.extend(
                [
                    f"> **本节不输出任何倾向性判断。**",
                    f"",
                    f"比对矩阵本身可用于核对事实，但将其计数结果作为专利性判断发布，"
                    f"需要先通过预评估门禁。当前未通过，原因：",
                    f"",
                ]
            )
            for reason in eligibility.reasons:
                lines.append(f"- {reason}")
            lines.extend(
                [
                    f"",
                    f"因此本节仅陈述：该计数尚未与日期门禁、优先权核验、引文核验及三步法论证的结果对齐，"
                    f"不能作为新颖性或创造性的结论使用。",
                    f"",
                ]
            )
        else:
            lines.extend(
                [
                    f"> **全案候选评级**：**{risk_badge}**",
                    f"",
                    f"{comparison.get('summary', '暂无全案综合评述。')}",
                    f"",
                    f"> {PUBLICATION_DISCLAIMER}",
                    f"",
                    f"对应预评估版本：v{eligibility.version_number}"
                    + (
                        f"（内容摘要 `{eligibility.payload_sha256}`）"
                        if eligibility.payload_sha256
                        else ""
                    )
                    + f"，门禁版本 `{eligibility.gate_version}`。",
                    f"",
                ]
            )

        lines.extend(
            [
                f"",
                f"---",
                f"",
                f"## 7. 证据链防伪验真与审计溯源声明",
                f"",
                f"1. **证据不可篡改证明**：本报告基于 PatentEvidence 不可变证据存证系统自动生成，全案证据已固化，Merkle 根哈希为：",
                f"   ```text",
                f"   {root_sha256}",
                f"   ```",
                f"2. **验真说明**：任何第三方均可通过比对原始证据快照哈希与本报告防伪区块，验证证据链自交底解析至比对确认全流程的真实性与完整性。",
                f"3. **出具机构**：PatentEvidence 智能专利证据存证平台",
                f"4. **签署人**：`{sealed_by}` 于 `{sealed_at}` 电子签署确认",
                f"",
            ]
        )

        return "\n".join(lines)
