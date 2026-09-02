from __future__ import annotations

from typing import Any


class MarkdownReportGenerator:
    """Generates a structured, client-ready Markdown patent evidence analysis report."""

    def generate(self, snapshot_payload: dict[str, Any], root_sha256: str) -> str:
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

        risk_str = comparison.get("risk_level", "unknown")
        risk_badge = "⚠️ 新颖性高风险预警" if risk_str == "high_novelty_risk" else ("⚡ 创造性审查关注" if risk_str == "inventiveness_risk" else "✓ 良好授权前景")

        lines.extend(
            [
                f"",
                f"---",
                f"",
                f"## 5. 专利性与法律风险综合论证",
                f"",
                f"> **全案风险评级**：**{risk_badge}**",
                f"",
                f"{comparison.get('summary', '暂无全案综合评述。')}",
                f"",
                f"---",
                f"",
                f"## 6. 证据链防伪验真与审计溯源声明",
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
