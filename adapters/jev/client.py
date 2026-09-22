from __future__ import annotations

import os
from dataclasses import dataclass
from time import perf_counter
from typing import Any

QUESTION_SET_VERSION = "patent-feature-disclosure-v1"


@dataclass(frozen=True)
class JevEvaluation:
    relation: str
    relation_probabilities: dict[str, float]
    relation_confidence: float
    direct_disclosure_probability: float
    enabling_disclosure_probability: float
    evidence_strength_score: float
    evidence_strength_probabilities: dict[int, float]
    evidence_strength_confidence: float
    evidence_chunk_id: str
    evidence_chunk_probabilities: dict[str, float]
    evidence_chunk_confidence: float
    model_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    question_set_version: str = QUESTION_SET_VERSION


class JevInventivenessClient:
    """Narrow TypeSafe/Jev boundary for atomic patent-disclosure judgments."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("PATENT_EVIDENCE_JEV_API_KEY") or os.environ.get("TYPESAFE_API_KEY")
        self.base_url = base_url or os.environ.get("PATENT_EVIDENCE_JEV_BASE_URL") or os.environ.get("TYPESAFE_ENDPOINT")
        self.model = model or os.environ.get("PATENT_EVIDENCE_JEV_MODEL") or "jev-latest"
        self.timeout_seconds = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def evaluate_feature(
        self,
        *,
        feature_code: str,
        feature_statement: str,
        candidate_pub_no: str,
        candidate_title: str,
        candidate_chunks: list[dict[str, str]],
    ) -> JevEvaluation:
        if not self.api_key:
            raise RuntimeError("Jev API key is not configured")

        from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score

        chunk_criteria = {
            str(chunk["id"]): f"This exact source chunk contains the strongest disclosure: {chunk['text']}"
            for chunk in candidate_chunks
        }
        chunk_criteria["none"] = "None of the supplied source chunks provides support."
        questions = {
            "relation": Choice(
                instructions="How does the cited prior-art text disclose the claimed technical feature?",
                criteria={
                    "identical": "Direct and unambiguous disclosure of the same technical feature.",
                    "equivalent": "A technically equivalent means, function, and effect, but not identical wording or structure.",
                    "different": "The supplied text affirmatively describes a materially different technical feature.",
                    "insufficient_evidence": "The supplied text is missing, ambiguous, or does not support a reliable comparison.",
                },
            ),
            "direct_disclosure": Noul(
                instructions="Does the supplied prior-art text directly and unambiguously disclose every limitation in this single claimed feature?",
                criteria={
                    "true": "Every limitation is supported by the supplied source text without adding unstated facts.",
                    "false": "At least one limitation is absent, merely inferred, or ambiguous.",
                },
            ),
            "enabling_disclosure": Noul(
                instructions="Would the supplied disclosure enable a skilled person to implement this claimed feature without inventive work?"
            ),
            "evidence_strength": Score(
                instructions="How strong is the supplied text as evidence for the feature comparison?",
                criteria=[
                    "No relevant source text.",
                    "Weak contextual resemblance only.",
                    "Relevant disclosure with some ambiguity or missing limitation.",
                    "Explicit, specific, and self-contained disclosure of the feature.",
                ],
            ),
            "evidence_chunk": Choice(
                instructions="Which exact source chunk is the strongest evidence for this comparison?",
                criteria=chunk_criteria,
            ),
        }
        state = {
            "claimed_feature": {"code": feature_code, "text": feature_statement},
            "prior_art": {
                "publication_number": candidate_pub_no,
                "title": candidate_title,
                "source_chunks": candidate_chunks,
            },
        }

        started = perf_counter()
        kwargs: dict[str, Any] = {
            "api_key": self.api_key,
            "timeout": self.timeout_seconds,
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        async with AsyncTypeSafeClient(**kwargs) as client:
            response = await client.system_one(state=state, questions=questions, model=self.model)
        latency_ms = round((perf_counter() - started) * 1000)

        relation = response.answers["relation"]
        direct = response.answers["direct_disclosure"]
        enabling = response.answers["enabling_disclosure"]
        strength = response.answers["evidence_strength"]
        chunk = response.answers["evidence_chunk"]
        usage = response.usage
        return JevEvaluation(
            relation=relation.choice,
            relation_probabilities=dict(relation.probabilities),
            relation_confidence=relation.confidence,
            direct_disclosure_probability=direct.noul,
            enabling_disclosure_probability=enabling.noul,
            evidence_strength_score=strength.score,
            evidence_strength_probabilities=dict(strength.probabilities),
            evidence_strength_confidence=strength.confidence,
            evidence_chunk_id=chunk.choice,
            evidence_chunk_probabilities=dict(chunk.probabilities),
            evidence_chunk_confidence=chunk.confidence,
            model_id=response.model,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            latency_ms=latency_ms,
        )
