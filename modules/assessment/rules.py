"""Deterministic assessment rules for the pre-assessment stage.

These rules are application-controlled: they never call a model, never emit a
final patentability conclusion, and only produce candidate findings that must
be confirmed by a patent agent and a reviewer. Judgment rows come from the
confirmed evidence matrix (source: analyst/review layers).

Gate vocabulary mirrors the comparison stage:
identical | equivalent | different | insufficient_evidence
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import combinations
from typing import Any

ASSESSMENT_RULES_VERSION = "assessment-rules-v1"

COVERING_JUDGMENTS = {"identical", "equivalent"}
SINGLE_REFERENCE_JUDGMENTS = {"identical"}


@dataclass(frozen=True)
class FeatureComparisonRow:
    """One confirmed matrix cell: feature F vs candidate document D."""

    feature_code: str
    doc_id: str
    judgment: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateDocument:
    doc_id: str
    publication_number: str
    title: str
    source_verified: bool = False


@dataclass
class AssessmentFinding:
    risk_kind: str  # novelty | inventive_combination | evidence_completeness
    level: str  # high_novelty_risk | high_inventive_risk | needs_confirmation | low
    basis: list[dict[str, str]] = field(default_factory=list)
    requires_human_confirmation: bool = True
    reasoning: str = ""
    rules_version: str = ASSESSMENT_RULES_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _rows_by_doc(rows: list[FeatureComparisonRow]) -> dict[str, list[FeatureComparisonRow]]:
    grouped: dict[str, list[FeatureComparisonRow]] = {}
    for row in rows:
        grouped.setdefault(row.doc_id, []).append(row)
    return grouped


def _feature_codes(rows: list[FeatureComparisonRow]) -> list[str]:
    seen: list[str] = []
    for row in rows:
        if row.feature_code not in seen:
            seen.append(row.feature_code)
    return seen


def novelty_findings(
    rows: list[FeatureComparisonRow],
    total_features: int,
) -> list[AssessmentFinding]:
    """Novelty gate: a single reference covering ALL features identically.

    Deterministic single-reference/all-elements gate. The application keeps
    this gate; any model may only supply the underlying cell judgments.
    """
    if total_features <= 0:
        return []
    findings: list[AssessmentFinding] = []
    for doc_id, doc_rows in sorted(_rows_by_doc(rows).items()):
        identical = {r.feature_code for r in doc_rows if r.judgment in SINGLE_REFERENCE_JUDGMENTS}
        if len(identical) == total_features:
            findings.append(
                AssessmentFinding(
                    risk_kind="novelty",
                    level="high_novelty_risk",
                    basis=[r.to_dict() for r in sorted(doc_rows, key=lambda r: r.feature_code)],
                    requires_human_confirmation=False,
                    reasoning=(
                        f"单篇对比文件 {doc_id} 对全部 {total_features} 项必要技术特征均为相同公开，"
                        "触发新颖性单篇全覆盖门禁；结论仍需代理师与复核人确认。"
                    ),
                )
            )
            continue
        covering = {r.feature_code for r in doc_rows if r.judgment in COVERING_JUDGMENTS}
        if len(covering) == total_features:
            findings.append(
                AssessmentFinding(
                    risk_kind="novelty",
                    level="needs_confirmation",
                    basis=[r.to_dict() for r in sorted(doc_rows, key=lambda r: r.feature_code)],
                    requires_human_confirmation=True,
                    reasoning=(
                        f"对比文件 {doc_id} 覆盖全部特征但含等同替代判断，不触发新颖性门禁；"
                        "等同认定必须人工复核。"
                    ),
                )
            )
    return findings


def combination_findings(
    rows: list[FeatureComparisonRow],
    total_features: int,
) -> list[AssessmentFinding]:
    """Coverage screening for document pairs (no motivation judgment here).

    Motivation-to-combine is NOT decided by code or by a model: a covering
    pair is only a *candidate combination* that a patent agent must confirm.
    """
    if total_features <= 0:
        return []
    grouped = _rows_by_doc(rows)
    doc_ids = sorted(grouped)
    if len(doc_ids) < 2:
        return []
    findings: list[AssessmentFinding] = []
    for first, second in combinations(doc_ids, 2):
        cells = {r.feature_code: r.judgment for r in grouped[first] + grouped[second]}
        covered = {code for code, judgment in cells.items() if judgment in COVERING_JUDGMENTS}
        if len(covered) == total_features:
            findings.append(
                AssessmentFinding(
                    risk_kind="inventive_combination",
                    level="needs_confirmation",
                    basis=[r.to_dict() for r in grouped[first] + grouped[second]],
                    requires_human_confirmation=True,
                    reasoning=(
                        f"文献组合 {first}+{second} 联合覆盖全部 {total_features} 项特征，"
                        "构成创造性组合风险候选；结合动机必须由代理师人工确认，系统不给结论。"
                    ),
                )
            )
    return findings


def evidence_completeness_finding(
    rows: list[FeatureComparisonRow],
    total_features: int,
    documents: list[CandidateDocument],
) -> AssessmentFinding:
    """Evidence completeness per spec 6.6: coverage, unverified, missing cells."""
    covered_features = {
        row.feature_code
        for row in rows
        if row.judgment in COVERING_JUDGMENTS or row.judgment == "different"
    }
    uncovered = [
        code
        for code in _feature_codes(rows)
        if code not in covered_features
    ]
    missing_cells = max(total_features - len({row.feature_code for row in rows}), 0)
    unverified = [doc.doc_id for doc in documents if not doc.source_verified]
    if uncovered or missing_cells or unverified:
        level = "needs_confirmation"
        reasoning = (
            f"证据完备度不足：未覆盖特征 {'、'.join(uncovered) or '无'}，缺失比对单元格 {missing_cells} 项，"
            f"未核验原文来源 {'、'.join(unverified) or '无'}。"
        )
    else:
        level = "low"
        reasoning = "来源覆盖率、核验状态与数据源时点均完备。"
    return AssessmentFinding(
        risk_kind="evidence_completeness",
        level=level,
        basis=[{"missing_cells": str(missing_cells), "unverified_sources": ",".join(unverified)}],
        requires_human_confirmation=True,
        reasoning=reasoning,
    )


@dataclass
class ThreeStepScaffold:
    """Deterministic three-step scaffolding; every field is a candidate."""

    closest_prior_art: str
    closest_prior_art_identical: int
    distinguishing_features: list[str]
    actual_technical_problem: str  # Always a placeholder: the agent must formulate it.
    rules_version: str = ASSESSMENT_RULES_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def three_step_scaffold(
    rows: list[FeatureComparisonRow],
) -> ThreeStepScaffold | None:
    """Step 1 + 2 of the inventive-step sequence, as candidate scaffolding.

    Step 1 (closest prior art) is scored deterministically as the document
    with the most identical judgments (ties broken by fewer
    insufficient_evidence cells, then doc_id). Step 3 (motivation to combine)
    is never computed here.
    """
    grouped = _rows_by_doc(rows)
    if not grouped:
        return None
    all_features = _feature_codes(rows)

    def score(doc_id: str) -> tuple[int, int, str]:
        doc_rows = grouped[doc_id]
        identical = sum(1 for r in doc_rows if r.judgment == "identical")
        insufficient = sum(1 for r in doc_rows if r.judgment == "insufficient_evidence")
        return (-identical, insufficient, doc_id)

    closest = min(grouped, key=score)
    identical_features = {
        r.feature_code for r in grouped[closest] if r.judgment == "identical"
    }
    return ThreeStepScaffold(
        closest_prior_art=closest,
        closest_prior_art_identical=len(identical_features),
        distinguishing_features=[code for code in all_features if code not in identical_features],
        actual_technical_problem="（占位）实际解决的技术问题必须由代理师基于区别特征与技术效果确定，不得直接写成区别特征本身。",
    )
