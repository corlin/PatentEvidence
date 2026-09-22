"""Jev screening of combination motivation: candidate signals only.

The application keeps the deterministic sequence: coverage of a document pair
is computed in modules/assessment/rules.py; whether the combination is
obvious is decided by the patent agent, never by code or by a model. Jev only
contributes typed signal probabilities (same field, same problem, motivation
grade, technical prejudice) that are attached as evaluation metadata and must
be confirmed by a human.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from modules.assessment.rules import (
    ASSESSMENT_RULES_VERSION,
    CandidateDocument,
    FeatureComparisonRow,
    _feature_codes,
    _rows_by_doc,
)

QUESTION_SET_VERSION = "patent-combination-motivation-v1"


@dataclass(frozen=True)
class JevMotivationEvaluation:
    same_field_probability: float
    same_problem_probability: float
    motivation_score: float
    motivation_probabilities: dict[int, float]
    motivation_confidence: float
    prejudice_probability: float
    model_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    question_set_version: str = QUESTION_SET_VERSION


class MotivationJevClient(Protocol):
    def is_configured(self) -> bool: ...

    async def evaluate_combination(self, **kwargs: Any) -> JevMotivationEvaluation: ...


@dataclass
class MotivationFinding:
    doc_ids: list[str]
    motivation_signals: dict[str, float]
    motivation_grade: int
    requires_human_confirmation: bool = True
    evaluation_source: str = "deterministic_coverage_only"  # | jev_live | jev_error | jev_not_run
    reasoning: str = ""
    rules_version: str = ASSESSMENT_RULES_VERSION
    evaluation_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def assess_combination_motivation(
    rows: list[FeatureComparisonRow],
    total_features: int,
    documents: dict[str, CandidateDocument],
    jev_client: MotivationJevClient | None = None,
) -> MotivationFinding | None:
    """Screen one covering document pair; Jev signals stay non-authoritative.

    Returns None when no pair jointly covers all features (no risk candidate,
    no Jev call). The requires_human_confirmation flag is always True: a
    system-suggested combination can never self-confirm.
    """
    from modules.assessment.rules import combination_findings

    if not combination_findings(rows, total_features):
        return None
    grouped = _rows_by_doc(rows)
    pair_ids = sorted(grouped)
    combined_text = [
        {
            "doc_id": doc_id,
            "publication_number": documents[doc_id].publication_number if doc_id in documents else doc_id,
            "title": documents[doc_id].title if doc_id in documents else "",
        }
        for doc_id in pair_ids
    ]
    state = {
        "claimed_features": _feature_codes(rows),
        "candidate_combination": combined_text,
        "cell_judgments": [r.to_dict() for r in rows if r.doc_id in pair_ids],
    }

    client = jev_client
    if client is None or not client.is_configured():
        return MotivationFinding(
            doc_ids=pair_ids,
            motivation_signals={},
            motivation_grade=-1,
            requires_human_confirmation=True,
            evaluation_source="deterministic_coverage_only",
            reasoning="组合联合覆盖全部特征，构成候选组合；未调用 Jev，结合动机等待代理师人工确认。",
        )

    try:
        evaluation = await client.evaluate_combination(
            first_doc=state["candidate_combination"][0],
            second_doc=state["candidate_combination"][1],
            claimed_features=state["claimed_features"],
            cell_judgments=state["cell_judgments"],
        )
    except Exception as exc:
        return MotivationFinding(
            doc_ids=pair_ids,
            motivation_signals={},
            motivation_grade=-1,
            requires_human_confirmation=True,
            evaluation_source="jev_error",
            reasoning="Jev 动机信号未完成，保留失败状态并转人工复核；未使用规则结果冒充在线判断。",
            evaluation_metadata={"error_type": type(exc).__name__},
        )

    return MotivationFinding(
        doc_ids=pair_ids,
        motivation_signals={
            "same_field": evaluation.same_field_probability,
            "same_problem": evaluation.same_problem_probability,
            "technical_prejudice": evaluation.prejudice_probability,
        },
        motivation_grade=int(evaluation.motivation_score),
        requires_human_confirmation=True,
        evaluation_source="jev_live",
        reasoning=(
            f"Jev 动机信号：同领域 {evaluation.same_field_probability:.2f}、"
            f"同问题 {evaluation.same_problem_probability:.2f}、"
            f"技术偏见 {evaluation.prejudice_probability:.2f}、动机档位 {evaluation.motivation_score}。"
            "信号仅为候选输入，结合动机仍需人工确认。"
        ),
        evaluation_metadata={
            "question_set_version": evaluation.question_set_version,
            "model_id": evaluation.model_id,
            "latency_ms": evaluation.latency_ms,
            "usage": {
                "input_tokens": evaluation.input_tokens,
                "output_tokens": evaluation.output_tokens,
            },
            "motivation_probabilities": evaluation.motivation_probabilities,
            "motivation_confidence": evaluation.motivation_confidence,
        },
    )
