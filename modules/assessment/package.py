"""Single orchestration entry for the pre-assessment stage.

`assess_case` runs every deterministic gate once and returns an
`AssessmentPackage` that a future API layer can persist and a reviewer can
approve. It never emits a patentability conclusion: the package only carries
candidate findings, the three-step scaffolding, the step-3 checklist state,
and the blocking gaps that must be resolved before any conclusion exists.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from modules.assessment.rules import (
    ASSESSMENT_RULES_VERSION,
    AssessmentFinding,
    AuxiliaryFactor,
    CandidateDocument,
    DataSourceRun,
    EvidenceCitation,
    EvidenceCompleteness,
    FeatureComparisonRow,
    MotivationChecklist,
    PriorityVerification,
    SubjectApplication,
    ThreeStepScaffold,
    assess_evidence_completeness,
    classify_all_references,
    combination_findings,
    evaluate_auxiliary_factors,
    hindsight_risk,
    motivation_checklist_state,
    novelty_findings,
    priority_verification_findings,
    reference_eligibility_findings,
    three_step_scaffold,
    verify_priority,
)


@dataclass
class AssessmentInput:
    subject: SubjectApplication
    documents: list[CandidateDocument]
    rows: list[FeatureComparisonRow]
    citations: list[EvidenceCitation] = field(default_factory=list)
    source_runs: list[DataSourceRun] = field(default_factory=list)
    legal_status_as_of: dict[str, date] = field(default_factory=dict)
    total_features: int | None = None
    motivation_checklist: MotivationChecklist | None = None
    auxiliary_factors: list[AuxiliaryFactor] = field(default_factory=list)
    actual_technical_problem: str = ""
    distinguishing_feature_statements: list[str] = field(default_factory=list)


@dataclass
class AssessmentPackage:
    rules_version: str
    reference_kinds: dict[str, str]
    priority: PriorityVerification | None
    findings: list[AssessmentFinding]
    three_step: ThreeStepScaffold | None
    motivation: dict[str, Any] | None
    auxiliary: dict[str, Any]
    hindsight: dict[str, Any] | None
    evidence: EvidenceCompleteness
    blockers: list[str]
    flags: list[str]
    requires_human_confirmation: bool
    prompt_versions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rules_version": self.rules_version,
            "reference_kinds": self.reference_kinds,
            "priority": self.priority.to_dict() if self.priority else None,
            "findings": [finding.to_dict() for finding in self.findings],
            "three_step": self.three_step.to_dict() if self.three_step else None,
            "motivation": self.motivation,
            "auxiliary": self.auxiliary,
            "hindsight": self.hindsight,
            "evidence": self.evidence.to_dict(),
            "blockers": self.blockers,
            "flags": self.flags,
            "requires_human_confirmation": self.requires_human_confirmation,
            "prompt_versions": self.prompt_versions,
        }


def _prompt_versions() -> dict[str, str]:
    try:  # prompts is a sibling top-level package; keep the import optional.
        from prompts.assessment import PROMPT_REGISTRY
    except ImportError:
        return {}
    return {key: str(value["version"]) for key, value in PROMPT_REGISTRY.items()}


def assess_case(payload: AssessmentInput) -> AssessmentPackage:
    """Run all deterministic gates and return the candidate assessment package."""
    total_features = payload.total_features
    if total_features is None:
        total_features = len({row.feature_code for row in payload.rows})

    feature_codes = tuple(sorted({row.feature_code for row in payload.rows}))
    priority = verify_priority(payload.subject, feature_codes)

    reference_kinds = classify_all_references(
        payload.documents, payload.subject, priority, payload.rows
    )

    findings: list[AssessmentFinding] = []
    findings.extend(priority_verification_findings(payload.subject, feature_codes))
    findings.extend(
        reference_eligibility_findings(payload.documents, payload.subject, priority, reference_kinds)
    )
    findings.extend(novelty_findings(payload.rows, total_features, reference_kinds))
    findings.extend(combination_findings(payload.rows, total_features, reference_kinds))

    scaffold = three_step_scaffold(payload.rows, reference_kinds)

    motivation: dict[str, Any] | None = None
    if payload.motivation_checklist is not None:
        motivation = motivation_checklist_state(payload.motivation_checklist)

    auxiliary = evaluate_auxiliary_factors(payload.auxiliary_factors)

    hindsight: dict[str, Any] | None = None
    if payload.actual_technical_problem.strip():
        statements = payload.distinguishing_feature_statements or (
            scaffold.distinguishing_features if scaffold else []
        )
        hindsight = hindsight_risk(payload.actual_technical_problem, statements)

    evidence = assess_evidence_completeness(
        payload.rows,
        total_features,
        payload.documents,
        citations=payload.citations,
        source_runs=payload.source_runs,
        legal_status_as_of=payload.legal_status_as_of,
    )

    blockers: list[str] = list(evidence.blocking_gaps)
    flags: list[str] = list(evidence.flags)
    flags.extend(priority.flags)
    if priority.invalid_claims:
        flags.append(
            "存在不成立的优先权主张，相关特征的基准日已回落到申请日"
            f" {payload.subject.filing_date.isoformat()}"
        )
    if priority.per_feature_reference_dates and len(
        set(priority.per_feature_reference_dates.values())
    ) > 1:
        flags.append("部分优先权导致不同技术特征的时间基准日不同，日期门禁按特征逐项判断")
    if motivation is None:
        blockers.append("三步法第 3 步结合启示清单未填写，缺 5 项必答项")
    elif motivation["blocks_conclusion"]:
        blockers.append(f"结合启示清单存在未回答项：{'、'.join(motivation['unanswered'])}")
    if scaffold is None:
        blockers.append("无可用现有技术（文献均为抵触申请/不可用/日期未知），无法确定最接近的现有技术")
    if hindsight and hindsight["hindsight_risk"]:
        flags.append("实际解决的技术问题疑似复述区别特征，存在事后诸葛亮风险")
    if any(finding.risk_kind == "inventive_combination" for finding in findings):
        flags.append("存在系统建议的文献组合，结合动机必须由代理师人工确认")

    requires_human_confirmation = (
        any(finding.requires_human_confirmation for finding in findings) or bool(blockers) or bool(flags)
    )

    return AssessmentPackage(
        rules_version=ASSESSMENT_RULES_VERSION,
        reference_kinds=reference_kinds,
        priority=priority,
        findings=findings,
        three_step=scaffold,
        motivation=motivation,
        auxiliary=auxiliary,
        hindsight=hindsight,
        evidence=evidence,
        blockers=blockers,
        flags=flags,
        requires_human_confirmation=requires_human_confirmation,
        prompt_versions=_prompt_versions(),
    )
