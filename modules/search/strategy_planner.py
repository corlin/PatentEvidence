from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class PlannedStrategy:
    keywords_matrix: dict[str, list[str]]
    ipc_classes: list[dict[str, str]]
    boolean_query_cnipr: str
    boolean_query_standard: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Common Patent IPC domain mapping
IPC_DOMAIN_MAPPINGS: list[dict[str, Any]] = [
    {
        "keywords": ["模型", "神经网络", "深度学习", "人工智能", "训练", "推理", "注意力", "transformer", "llm"],
        "ipc": "G06N 3/08",
        "description": "基于神经网络或特定计算模型的学习方法",
    },
    {
        "keywords": ["量化", "稀疏", "矩阵", "计算", "低延迟", "加速", "算法", "精度"],
        "ipc": "G06F 17/16",
        "description": "矩阵或矢量计算",
    },
    {
        "keywords": ["数据处理", "数据库", "检索", "结构化", "向量", "存储", "索引"],
        "ipc": "G06F 16/24",
        "description": "信息检索与数据库查询处理",
    },
    {
        "keywords": ["加密", "安全", "鉴权", "签名", "隐私", "隔离"],
        "ipc": "H04L 9/08",
        "description": "密码协议与密钥管理",
    },
    {
        "keywords": ["图像", "视觉", "卷积", "目标检测", "分割"],
        "ipc": "G06T 7/00",
        "description": "图像分析与处理",
    },
]

# Common Patent Synonym Dictionary
SYNONYMS_DICT: dict[str, list[str]] = {
    "大模型": ["大语言模型", "LLM", "大型语言模型", "预训练模型"],
    "量化": ["混合精度", "低位宽", "模型压缩", "权重量化", "定点化"],
    "稀疏": ["剪枝", "低秩分解", "稀疏化", "SVD分解"],
    "推理": ["预测", "前向计算", "解码", "Inference"],
    "神经网络": ["深度学习", "注意力机制", "Transformer", "多层感知机"],
    "检索": ["搜索", "查找", "匹配", "Query"],
    "加密": ["密码学", "密文", "多租户隔离", "脱敏"],
    "向量": ["Embedding", "特征向量", "表征", "隐空间"],
}


class SearchStrategyPlanner:
    """Generates structured search strategies, IPC suggestions, and CNIPR Boolean queries."""

    def plan_strategy(
        self,
        features: list[dict[str, Any]],
        technical_field: str = "",
        title: str = "",
    ) -> PlannedStrategy:
        # 1. Extract core terms across features, title and field
        all_text = f"{title} {technical_field} " + " ".join(
            f.get("feature_statement", "") for f in features
        )

        extracted_keywords: dict[str, list[str]] = {}
        for root_term, syns in SYNONYMS_DICT.items():
            if root_term in all_text or any(s.lower() in all_text.lower() for s in syns):
                extracted_keywords[root_term] = [root_term] + [s for s in syns if s != root_term]

        # Fallback if no dictionary match
        if not extracted_keywords:
            words = [w for w in re.findall(r"[\w\u4e00-\u9fa5]{2,6}", all_text) if len(w) >= 2][:4]
            for w in words:
                extracted_keywords[w] = [w]

        # 2. Recommend IPC Classifications
        recommended_ipcs: list[dict[str, str]] = []
        for mapping in IPC_DOMAIN_MAPPINGS:
            if any(k in all_text.lower() for k in mapping["keywords"]):
                recommended_ipcs.append(
                    {"code": mapping["ipc"], "description": mapping["description"]}
                )

        if not recommended_ipcs:
            recommended_ipcs.append(
                {"code": "G06F 18/00", "description": "一般数据处理与模式识别"}
            )

        # 3. Build CNIPR Boolean query:
        # Syntax: (term1 OR term2) AND (term3 OR term4) AND (IPC:(G06N+ OR G06F+))
        kw_groups: list[str] = []
        for term, syns in list(extracted_keywords.items())[:3]:
            or_group = " OR ".join(f'"{s}"' if " " in s else s for s in syns[:3])
            kw_groups.append(f"({or_group})")

        ipc_codes = [ipc["code"].split()[0] + "+" for ipc in recommended_ipcs[:2]]
        ipc_group = " OR ".join(f"IPC:{c}" for c in ipc_codes)

        if kw_groups:
            boolean_cnipr = " AND ".join(kw_groups)
            if ipc_group:
                boolean_cnipr += f" AND ({ipc_group})"
        else:
            boolean_cnipr = f'"{title}"'

        # 4. Build Standard Boolean query (for Google Patents / OpenAlex / EPO)
        boolean_standard = " AND ".join(kw_groups) if kw_groups else f'"{title}"'

        return PlannedStrategy(
            keywords_matrix=extracted_keywords,
            ipc_classes=recommended_ipcs,
            boolean_query_cnipr=boolean_cnipr,
            boolean_query_standard=boolean_standard,
        )
