from __future__ import annotations

import pytest

from adapters.jev.client import JevEvaluation
from modules.comparison.engine import RuleComparisonEngine, compare_feature_with_ai
from modules.comparison.evaluator import MatrixEvaluator


class StubJevClient:
    def __init__(self, evaluation: JevEvaluation | None = None, error: Exception | None = None) -> None:
        self.evaluation = evaluation
        self.error = error

    def is_configured(self) -> bool:
        return True

    async def evaluate_feature(self, **_: object) -> JevEvaluation:
        if self.error is not None:
            raise self.error
        assert self.evaluation is not None
        return self.evaluation


def test_abstract_only_baseline_never_invents_a_paragraph_or_legal_conclusion() -> None:
    result = RuleComparisonEngine().compare_feature_with_candidate(
        feature_code="F1",
        feature_statement="一种面向低位宽的大语言模型混合精度量化推理加速方法。",
        candidate_pub_no="CN117283912A",
        candidate_title="一种基于大模型混合精度量化的推理方法及系统",
        candidate_abstract="本发明公开了一种面向大语言模型的低位宽混合精度量化加速架构。",
    )

    assert result.judgment == "insufficient_evidence"
    assert result.citation_location == "摘要"
    assert result.citation_quote == "本发明公开了一种面向大语言模型的低位宽混合精度量化加速架构。"
    assert result.evidence_status == "abstract_only"
    assert result.evaluation_source == "deterministic_baseline"
    assert "说明书第" not in result.reasoning_analysis


@pytest.mark.asyncio
async def test_live_jev_judgment_keeps_probabilities_model_usage_and_exact_anchor() -> None:
    exact_text = "该系统在解码阶段采用低位宽映射实现加速。"
    jev = StubJevClient(JevEvaluation(
        relation="identical",
        relation_probabilities={"identical": 0.91, "equivalent": 0.04, "different": 0.03, "insufficient_evidence": 0.02},
        relation_confidence=0.88,
        direct_disclosure_probability=0.93,
        enabling_disclosure_probability=0.86,
        evidence_strength_score=2.8,
        evidence_strength_probabilities={0: 0.0, 1: 0.02, 2: 0.16, 3: 0.82},
        evidence_strength_confidence=0.82,
        evidence_chunk_id="p32",
        evidence_chunk_probabilities={"p32": 0.96, "none": 0.04},
        evidence_chunk_confidence=0.92,
        model_id="jev-1.13.0",
        input_tokens=321,
        output_tokens=42,
        latency_ms=137,
    ))

    result = await compare_feature_with_ai(
        feature_code="F1",
        feature_statement="在解码阶段采用低位宽映射",
        candidate_pub_no="CN117283912A",
        candidate_title="低位宽推理系统",
        candidate_abstract="摘要文本",
        candidate_chunks=[{"id": "p32", "text": exact_text}],
        jev_client=jev,
    )

    assert result.judgment == "identical"
    assert result.evidence_status == "verified"
    assert result.evaluation_source == "jev_live"
    assert result.citation_location == "p32"
    assert result.citation_quote == exact_text
    assert result.confidence_score == pytest.approx(88.0)
    assert result.evaluation_metadata["model_id"] == "jev-1.13.0"
    assert result.evaluation_metadata["usage"] == {"input_tokens": 321, "output_tokens": 42}
    assert result.evaluation_metadata["answers"]["relation"]["probabilities"]["identical"] == 0.91


@pytest.mark.asyncio
async def test_jev_cannot_promote_an_unverifiable_quote() -> None:
    jev = StubJevClient(JevEvaluation(
        relation="identical",
        relation_probabilities={"identical": 0.99, "insufficient_evidence": 0.01},
        relation_confidence=0.98,
        direct_disclosure_probability=0.99,
        enabling_disclosure_probability=0.95,
        evidence_strength_score=3.0,
        evidence_strength_probabilities={3: 1.0},
        evidence_strength_confidence=1.0,
        evidence_chunk_id="hallucinated-p99",
        evidence_chunk_probabilities={"hallucinated-p99": 1.0},
        evidence_chunk_confidence=1.0,
        model_id="jev-1.13.0",
        input_tokens=10,
        output_tokens=5,
        latency_ms=20,
    ))

    result = await compare_feature_with_ai(
        feature_code="F1",
        feature_statement="低位宽映射",
        candidate_pub_no="CN1",
        candidate_title="测试文献",
        candidate_abstract="",
        candidate_chunks=[{"id": "p32", "text": "真实原文"}],
        jev_client=jev,
    )

    assert result.judgment == "insufficient_evidence"
    assert result.evidence_status == "unverified_anchor"
    assert result.citation_quote == ""


@pytest.mark.asyncio
async def test_jev_failure_routes_to_review_instead_of_silent_heuristic_fallback() -> None:
    result = await compare_feature_with_ai(
        feature_code="F1",
        feature_statement="低位宽映射",
        candidate_pub_no="CN1",
        candidate_title="低位宽系统",
        candidate_abstract="低位宽映射",
        candidate_chunks=[{"id": "abstract", "text": "低位宽映射"}],
        jev_client=StubJevClient(error=TimeoutError("provider timed out")),
    )

    assert result.judgment == "insufficient_evidence"
    assert result.evidence_status == "evaluation_failed"
    assert result.evaluation_source == "jev_error"
    assert result.evaluation_metadata["error_type"] == "TimeoutError"


def test_matrix_evaluator_requires_verified_evidence_before_novelty_conclusion() -> None:
    result = MatrixEvaluator().evaluate_matrix(
        [{"id": "f1"}, {"id": "f2"}],
        [{"id": "c1", "publication_number": "D1"}],
        [
            {"claim_feature_id": "f1", "candidate_id": "c1", "judgment": "identical", "evidence_status": "verified"},
            {"claim_feature_id": "f2", "candidate_id": "c1", "judgment": "insufficient_evidence", "evidence_status": "abstract_only"},
        ],
    )

    assert result["risk_level"] == "human_review_required"
    assert result["three_step_analysis"]["step_1_closest_prior_art"]["candidate_id"] == "c1"
    assert result["three_step_analysis"]["step_2_distinguishing_features"] == ["f2"]
    assert result["three_step_analysis"]["step_3_motivation_and_effect"] == "not_assessed"
    assert "证据不足" in result["summary"]


def test_matrix_evaluator_allows_novelty_risk_only_for_one_fully_verified_reference() -> None:
    result = MatrixEvaluator().evaluate_matrix(
        [{"id": "f1"}, {"id": "f2"}],
        [{"id": "c1", "publication_number": "D1"}],
        [
            {"claim_feature_id": "f1", "candidate_id": "c1", "judgment": "identical", "evidence_status": "verified"},
            {"claim_feature_id": "f2", "candidate_id": "c1", "judgment": "identical", "evidence_status": "verified"},
        ],
    )

    assert result["risk_level"] == "high_novelty_risk"
    assert "D1" in result["summary"]
