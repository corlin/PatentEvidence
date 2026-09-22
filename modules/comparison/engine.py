from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from adapters.jev.client import JevEvaluation, JevInventivenessClient
from modules.cases.parser import split_sentences


@dataclass
class ComparisonResult:
    judgment: str
    confidence_score: float
    citation_location: str
    citation_quote: str
    reasoning_analysis: str
    evidence_status: str = "insufficient"
    evaluation_source: str = "deterministic_baseline"
    evaluation_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JevClient(Protocol):
    def is_configured(self) -> bool: ...

    async def evaluate_feature(self, **kwargs: Any) -> JevEvaluation: ...


EQUIVALENCE_SYNONYMS: dict[str, list[str]] = {
    "大模型": ["大语言模型", "LLM", "预训练模型", "深度神经网络"],
    "量化": ["混合精度", "低位宽", "模型压缩", "定点化", "权重量化"],
    "奇异值分解": ["SVD", "低秩分解", "矩阵分解", "特征值分解"],
    "稀疏": ["稀疏化", "剪枝", "非零元素优化", "查找表"],
    "推理": ["预测", "前向计算", "解码", "Inference"],
    "向量": ["Embedding", "特征向量", "表征", "隐空间"],
}


class RuleComparisonEngine:
    """Recall-oriented baseline; it never emits a patentability conclusion."""

    def compare_feature_with_candidate(
        self,
        feature_code: str,
        feature_statement: str,
        candidate_pub_no: str,
        candidate_title: str,
        candidate_abstract: str,
    ) -> ComparisonResult:
        source_text = candidate_abstract.strip()
        if not source_text:
            return ComparisonResult(
                judgment="insufficient_evidence",
                confidence_score=0.0,
                citation_location="",
                citation_quote="",
                evidence_status="missing_source_text",
                reasoning_analysis=f"对比文献 {candidate_pub_no} 只有书目信息，没有可逐字核验的公开文本，必须补充原文后人工复核。",
            )

        feature_words = [w for w in re.findall(r"[\w\u4e00-\u9fa5]{2,6}", feature_statement) if len(w) >= 2]
        sentences = split_sentences(source_text, min_length=6) or [source_text]
        best_sentence = max(sentences, key=lambda sentence: sum(word in sentence for word in feature_words))
        citation_quote = source_text if len(sentences) == 1 else best_sentence
        overlap = sum(word in best_sentence for word in feature_words) / max(len(feature_words), 1)
        return ComparisonResult(
            judgment="insufficient_evidence",
            confidence_score=0.0,
            citation_location="摘要",
            citation_quote=citation_quote,
            evidence_status="abstract_only",
            reasoning_analysis=(
                f"对比文献 {candidate_pub_no} 的摘要与特征 {feature_code} 存在词项重合（检索提示分 {overlap:.2f}），"
                "但摘要不能替代权利要求书或说明书原文，当前不形成相同、等同或不同的法律判断。"
            ),
            evaluation_metadata={"retrieval_hint_score": round(overlap, 4)},
        )


def _metadata(evaluation: JevEvaluation) -> dict[str, Any]:
    return {
        "question_set_version": evaluation.question_set_version,
        "model_id": evaluation.model_id,
        "latency_ms": evaluation.latency_ms,
        "usage": {
            "input_tokens": evaluation.input_tokens,
            "output_tokens": evaluation.output_tokens,
        },
        "answers": {
            "relation": {
                "choice": evaluation.relation,
                "probabilities": evaluation.relation_probabilities,
                "confidence": evaluation.relation_confidence,
            },
            "direct_disclosure": {"noul": evaluation.direct_disclosure_probability},
            "enabling_disclosure": {"noul": evaluation.enabling_disclosure_probability},
            "evidence_strength": {
                "score": evaluation.evidence_strength_score,
                "probabilities": evaluation.evidence_strength_probabilities,
                "confidence": evaluation.evidence_strength_confidence,
            },
            "evidence_chunk": {
                "choice": evaluation.evidence_chunk_id,
                "probabilities": evaluation.evidence_chunk_probabilities,
                "confidence": evaluation.evidence_chunk_confidence,
            },
        },
    }


async def compare_feature_with_ai(
    feature_code: str,
    feature_statement: str,
    candidate_pub_no: str,
    candidate_title: str,
    candidate_abstract: str,
    candidate_chunks: list[dict[str, str]] | None = None,
    jev_client: JevClient | None = None,
    llm_client: Any | None = None,
) -> ComparisonResult:
    """Evaluate one feature with Jev, then enforce deterministic evidence gates."""
    del llm_client  # Kept for call compatibility; free-form LLM output is no longer authoritative here.
    chunks = [
        {"id": str(chunk.get("id", "")), "text": str(chunk.get("text", "")).strip()}
        for chunk in (candidate_chunks or [])
        if str(chunk.get("id", "")).strip() and str(chunk.get("text", "")).strip()
    ]
    client = jev_client or JevInventivenessClient()
    if not client.is_configured():
        return RuleComparisonEngine().compare_feature_with_candidate(
            feature_code, feature_statement, candidate_pub_no, candidate_title, candidate_abstract
        )
    if not chunks:
        return ComparisonResult(
            judgment="insufficient_evidence",
            confidence_score=0.0,
            citation_location="",
            citation_quote="",
            reasoning_analysis="没有可定位的对比文件原文块，未调用 Jev，转人工补充证据。",
            evidence_status="missing_source_text",
            evaluation_source="jev_not_run",
        )

    try:
        evaluation = await client.evaluate_feature(
            feature_code=feature_code,
            feature_statement=feature_statement,
            candidate_pub_no=candidate_pub_no,
            candidate_title=candidate_title,
            candidate_chunks=chunks,
        )
    except Exception as exc:
        return ComparisonResult(
            judgment="insufficient_evidence",
            confidence_score=0.0,
            citation_location="",
            citation_quote="",
            reasoning_analysis="Jev 判断未完成，已保留失败状态并转人工复核；未使用规则结果冒充在线判断。",
            evidence_status="evaluation_failed",
            evaluation_source="jev_error",
            evaluation_metadata={"error_type": type(exc).__name__},
        )

    metadata = _metadata(evaluation)
    selected = next((chunk for chunk in chunks if chunk["id"] == evaluation.evidence_chunk_id), None)
    if selected is None or evaluation.evidence_chunk_id == "none":
        return ComparisonResult(
            judgment="insufficient_evidence",
            confidence_score=evaluation.relation_confidence * 100,
            citation_location="",
            citation_quote="",
            reasoning_analysis="Jev 返回的证据锚点无法在输入原文块中逐字定位，禁止形成自动判断。",
            evidence_status="unverified_anchor",
            evaluation_source="jev_live",
            evaluation_metadata=metadata,
        )

    evidence_status = "abstract_only" if selected["id"] == "abstract" else "verified"
    high_enough = (
        evaluation.relation_confidence >= 0.80
        and evaluation.evidence_chunk_confidence >= 0.80
        and evaluation.evidence_strength_score >= 2.0
    )
    if evaluation.relation == "identical":
        high_enough = high_enough and evaluation.direct_disclosure_probability >= 0.80 and evaluation.enabling_disclosure_probability >= 0.75
    judgment = evaluation.relation if high_enough and evidence_status == "verified" else "insufficient_evidence"
    if judgment not in {"identical", "equivalent", "different"}:
        judgment = "insufficient_evidence"

    return ComparisonResult(
        judgment=judgment,
        confidence_score=evaluation.relation_confidence * 100,
        citation_location=selected["id"],
        citation_quote=selected["text"],
        reasoning_analysis=(
            f"Jev 对特征 {feature_code} 的类型化判断为 {evaluation.relation}；"
            f"直接公开概率 {evaluation.direct_disclosure_probability:.2f}，"
            f"充分公开概率 {evaluation.enabling_disclosure_probability:.2f}。"
            + ("证据门禁通过。" if judgment != "insufficient_evidence" else "因置信度或证据完整性不足，转人工复核。")
        ),
        evidence_status=evidence_status,
        evaluation_source="jev_live",
        evaluation_metadata=metadata,
    )
