from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from modules.cases.parser import split_sentences


@dataclass
class DraftFeature:
    feature_code: str
    feature_type: str  # 'preamble' | 'characterizing' | 'dependent'
    feature_statement: str
    source_paragraph_id: str | None
    citation_quote: str | None
    sort_order: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuleFeatureExtractor:
    """Extracts structured technical features and binds paragraph citations deterministically."""

    def extract(self, paragraphs: list[dict[str, Any]]) -> list[DraftFeature]:
        if not paragraphs:
            return []

        features: list[DraftFeature] = []
        code_idx = 1

        # 1. Preamble feature detection (from title, technical field or opening paragraph)
        preamble_found = False
        for p in paragraphs:
            sec = p.get("section", "")
            text = p.get("text", "").strip()
            p_id = p.get("id")

            if ("技术领域" in sec or "发明名称" in sec or "正文" in sec) and not preamble_found:
                # Look for "一种...方法/系统/装置"
                match = re.search(r"(一种.+?(?:方法|系统|装置|设备|介质|构件))", text)
                if match:
                    statement = match.group(1)
                    features.append(
                        DraftFeature(
                            feature_code=f"F{code_idx}",
                            feature_type="preamble",
                            feature_statement=f"一种技术方案，其特征在于包括：{statement}",
                            source_paragraph_id=p_id,
                            citation_quote=statement,
                            sort_order=code_idx,
                        )
                    )
                    code_idx += 1
                    preamble_found = True
                    break

        if not preamble_found and paragraphs:
            p0 = paragraphs[0]
            first_sent = p0.get("text", "").split("。")[0]
            if first_sent:
                features.append(
                    DraftFeature(
                        feature_code=f"F{code_idx}",
                        feature_type="preamble",
                        feature_statement=first_sent,
                        source_paragraph_id=p0.get("id"),
                        citation_quote=first_sent,
                        sort_order=code_idx,
                    )
                )
                code_idx += 1

        # 2. Characterizing features detection (from "发明内容", "技术方案", "实施例" or steps)
        for p in paragraphs:
            sec = p.get("section", "")
            text = p.get("text", "").strip()
            p_id = p.get("id")

            if "技术领域" in sec or "背景技术" in sec:
                continue

            # Split paragraph into clean sentences
            sentences = split_sentences(text, min_length=8)
            for s in sentences:
                # Look for technical action keywords
                if any(kw in s for kw in ("通过", "基于", "获取", "计算", "处理", "优化", "执行", "配置", "包括", "构建", "步骤")):
                    features.append(
                        DraftFeature(
                            feature_code=f"F{code_idx}",
                            feature_type="characterizing",
                            feature_statement=s,
                            source_paragraph_id=p_id,
                            citation_quote=s,
                            sort_order=code_idx,
                        )
                    )
                    code_idx += 1
                    if code_idx > 6:  # Reasonable initial draft count
                        break
            if code_idx > 6:
                break

        # 3. Fallback if fewer than 2 features extracted
        if len(features) < 2 and len(paragraphs) > 1:
            for p in paragraphs[1:]:
                text = p.get("text", "").strip()
                if len(text) > 10:
                    features.append(
                        DraftFeature(
                            feature_code=f"F{code_idx}",
                            feature_type="dependent",
                            feature_statement=text[:120],
                            source_paragraph_id=p.get("id"),
                            citation_quote=text[:80],
                            sort_order=code_idx,
                        )
                    )
                    code_idx += 1
                    if len(features) >= 3:
                        break

        return features


async def extract_features_with_ai(
    title: str,
    paragraphs: list[dict[str, Any]],
    llm_client: Any | None = None,
) -> list[DraftFeature]:
    """Extract features via LLM using CNIPA examination prompts, falling back to rule extractor."""
    from adapters.llm.client import LlmClient
    from adapters.llm.schemas import FeatureExtractionResultSchema
    from prompts.feature_modeling import FEATURE_MODELING_SYSTEM_PROMPT, build_feature_modeling_user_prompt

    client = llm_client or LlmClient()
    if client.is_configured():
        try:
            messages = [
                {"role": "system", "content": FEATURE_MODELING_SYSTEM_PROMPT},
                {"role": "user", "content": build_feature_modeling_user_prompt(title, paragraphs)},
            ]
            result = await client.generate_structured(
                messages=messages,
                response_model=FeatureExtractionResultSchema,
            )
            drafts: list[DraftFeature] = []
            for idx, f in enumerate(result.features, start=1):
                drafts.append(
                    DraftFeature(
                        feature_code=f.feature_code or f"F{idx}",
                        feature_type=f.feature_type,
                        feature_statement=f.feature_statement,
                        source_paragraph_id=f.source_paragraph_id,
                        citation_quote=f.citation_quote,
                        sort_order=idx,
                    )
                )
            if drafts:
                return drafts
        except Exception:
            pass

    return RuleFeatureExtractor().extract(paragraphs)

