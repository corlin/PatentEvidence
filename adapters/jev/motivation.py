from __future__ import annotations

import os
from dataclasses import dataclass
from time import perf_counter
from typing import Any

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


class JevCombinationMotivationClient:
    """Narrow TypeSafe/Jev boundary for combination-motivation signals.

    One System One request per candidate combination; all questions ride on
    the same state. Returned probabilities are candidate screening signals
    for the patent agent — never a motivation-to-combine conclusion.
    """

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

    async def evaluate_combination(
        self,
        *,
        first_doc: dict[str, str],
        second_doc: dict[str, str],
        claimed_features: list[str],
        cell_judgments: list[dict[str, str]],
    ) -> JevMotivationEvaluation:
        if not self.api_key:
            raise RuntimeError("Jev API key is not configured")

        from typesafe_sdk import AsyncTypeSafeClient, Noul, Score

        questions = {
            "same_field": Noul(
                instructions=(
                    "Do both cited documents belong to the same or a closely "
                    "related technical field as the claimed invention? Judge "
                    "only from the supplied titles, fields, and judgments — "
                    "do not infer a field from generic keywords alone."
                ),
                criteria={
                    "true": "Both documents are in the same or a closely related technical field.",
                    "false": "At least one document is in a remote or unrelated field.",
                },
            ),
            "same_problem": Noul(
                instructions=(
                    "Do both documents address the same or a tightly related "
                    "technical problem? Do not treat a shared general purpose "
                    "(e.g. 'improving efficiency') as the same problem."
                ),
                criteria={
                    "true": "Both documents target the same or tightly related technical problem.",
                    "false": "The documents target clearly different technical problems.",
                },
            ),
            "motivation_grade": Score(
                instructions=(
                    "How strongly does the prior art as a whole suggest "
                    "combining these two documents to arrive at all claimed "
                    "features? Grade the written signal only; absence of an "
                    "explicit teaching lowers the grade."
                ),
                criteria=[
                    "No suggestion to combine; the documents are independent teachings.",
                    "Only a generic similarity; combining would require the applicant's own ideas.",
                    "Some concrete pointers toward combination, but the exact claimed assembly is not suggested.",
                    "Clear teaching or pointer in at least one document that would motivate the skilled person to combine them.",
                ],
            ),
            "technical_prejudice": Noul(
                instructions=(
                    "Does the supplied material contain signals of a technical "
                    "prejudice or discouragement that would steer the skilled "
                    "person AWAY from this combination?"
                ),
                criteria={
                    "true": "The material signals a prejudice or discouragement against the combination.",
                    "false": "No prejudice or discouragement signal is present.",
                },
            ),
        }
        state = {
            "claimed_features": claimed_features,
            "first_document": first_doc,
            "second_document": second_doc,
            "cell_judgments": cell_judgments,
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

        same_field = response.answers["same_field"]
        same_problem = response.answers["same_problem"]
        grade = response.answers["motivation_grade"]
        prejudice = response.answers["technical_prejudice"]
        usage = response.usage
        return JevMotivationEvaluation(
            same_field_probability=same_field.noul,
            same_problem_probability=same_problem.noul,
            motivation_score=grade.score,
            motivation_probabilities=dict(grade.probabilities),
            motivation_confidence=grade.confidence,
            prejudice_probability=prejudice.noul,
            model_id=response.model,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            latency_ms=latency_ms,
        )
