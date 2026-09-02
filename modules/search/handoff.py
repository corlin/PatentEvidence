from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


class HandoffPackageGenerator:
    """Generates standardized CNIPR Manual Handoff packages adhering to provenance rules."""

    def generate_markdown(
        self,
        case_info: dict[str, Any],
        strategy: dict[str, Any],
        features: list[dict[str, Any]],
    ) -> str:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        case_number = case_info.get("case_number", "UNKNOWN")
        title = case_info.get("title", "")
        tech_field = case_info.get("technical_field", "")
        boolean_cnipr = strategy.get("boolean_query_cnipr", "")

        lines = [
            f"# CNIPR 官方专利检索人工交接规范包 (Manual Handoff Package)",
            f"",
            f"> **案件编号**：`{case_number}`  ",
            f"> **发明名称**：{title}  ",
            f"> **技术领域**：{tech_field}  ",
            f"> **生成时间**：{now_str}  ",
            f"> **交接合规要求**：根据平台规范，CNIPR 检索必须由代理师在官方系统人工执行并将结果清单导出回填。",
            f"",
            f"---",
            f"",
            f"## 一、 CNIPR 官方系统推荐检索式 (可直接复制)",
            f"",
            f"```text",
            f"{boolean_cnipr}",
            f"```",
            f"",
            f"## 二、 技术特征分解对照表",
            f"",
            f"| 特征编号 | 类型 | 技术特征陈述 | 原文段落 |",
            f"| :--- | :--- | :--- | :--- |",
        ]

        for f in features:
            f_code = f.get("feature_code", "")
            f_type = (
                "前序特征"
                if f.get("feature_type") == "preamble"
                else "表征特征"
                if f.get("feature_type") == "characterizing"
                else "从属特征"
            )
            stmt = f.get("feature_statement", "").replace("\n", " ")
            p_id = f.get("source_paragraph_id") or "-"
            lines.append(f"| `{f_code}` | {f_type} | {stmt} | `{p_id}` |")

        lines.extend(
            [
                f"",
                f"## 三、 推荐 IPC / CPC 分类号",
                f"",
            ]
        )

        for ipc in strategy.get("ipc_classes", []):
            code = ipc.get("code", "")
            desc = ipc.get("description", "")
            lines.append(f"- **`{code}`**：{desc}")

        lines.extend(
            [
                f"",
                f"## 四、 检索执行与结果回传操作指引",
                f"",
                f"1. 登录国家知识产权局 CNIPR 专利检索与服务系统；",
                f"2. 进入【高级检索】界面，将上述检索式粘贴至检索条件框中；",
                f"3. 检出结果后，点击【批量导出】并选择 **CSV / Excel** 格式下载；",
                f"4. 返回本系统案件工作台【多路检索与候选池】页面，点击【导入 CNIPR 检索结果】上传回填。",
                f"",
                f"---",
                f"*PatentEvidence 知识产权证据链合规保障体系*",
            ]
        )

        return "\n".join(lines)

    def generate_json(
        self,
        case_info: dict[str, Any],
        strategy: dict[str, Any],
        features: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "handoff_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "case": case_info,
            "strategy": strategy,
            "features": features,
            "instructions": {
                "target_platform": "CNIPR (国家知识产权局专利检索及分析系统)",
                "recommended_export_format": "CSV/Excel",
            },
        }
