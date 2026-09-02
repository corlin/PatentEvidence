from __future__ import annotations

import re
from typing import Any


class RelevanceScorer:
    """Calculates heuristic and keyword-coverage relevance score (0~100) for candidates."""

    def compute_score(
        self,
        candidate_title: str,
        candidate_abstract: str,
        candidate_ipc: str | None,
        keywords_matrix: dict[str, list[str]],
        target_ipc_classes: list[dict[str, str]],
    ) -> float:
        score = 10.0  # Base prior

        title_lower = (candidate_title or "").lower()
        abstract_lower = (candidate_abstract or "").lower()
        ipc_lower = (candidate_ipc or "").lower()

        # 1. Title Keyword Matching (up to 45 pts)
        title_matches = 0
        for root_term, syns in keywords_matrix.items():
            if any(s.lower() in title_lower for s in syns):
                title_matches += 1
        score += min(title_matches * 15.0, 45.0)

        # 2. Abstract Keyword Matching (up to 30 pts)
        abs_matches = 0
        for root_term, syns in keywords_matrix.items():
            if any(s.lower() in abstract_lower for s in syns):
                abs_matches += 1
        score += min(abs_matches * 8.0, 30.0)

        # 3. IPC Classification Match (up to 15 pts)
        if ipc_lower:
            for target_ipc in target_ipc_classes:
                code_prefix = target_ipc.get("code", "").split()[0].lower()
                if code_prefix and code_prefix in ipc_lower:
                    score += 15.0
                    break

        return min(round(score, 1), 100.0)
