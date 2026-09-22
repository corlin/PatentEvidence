"""HTTP contract for the pre-assessment stage.

The domain layer is vendor free and works on dataclasses. This module is the
only place that knows how to turn request JSON into those dataclasses, and how
to render a frozen version record back into an HTTP payload.

Rendering rule that must not be weakened: an assessment version carries
candidate findings and blocking gaps, never a patentability conclusion. Every
response therefore repeats the disclaimer and the human-confirmation flag, so
a caller cannot read a package as a legal opinion by accident.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from modules.assessment.package import AssessmentInput
from modules.assessment.records import AssessmentVersionRecord
from modules.assessment.rules import (
    AuxiliaryFactor,
    CandidateDocument,
    ConceptRelation,
    DataSourceRun,
    EvidenceCitation,
    FeatureComparisonRow,
    KnownSubstitute,
    MotivationChecklist,
    NumericRange,
    PriorityClaim,
    SubjectApplication,
)

DISCLAIMER = (
    "本评估仅输出候选发现与阻塞项，不构成专利性结论或法律意见；"
    "任何结论须经人工复核确认后方可对外使用。"
)


class PriorityClaimIn(BaseModel):
    claim_id: str
    priority_date: date
    country: str = ""
    first_application: bool = True
    same_subject: bool = True
    proof_verified: bool = False
    covers: list[str] = Field(default_factory=list)

    def to_domain(self) -> PriorityClaim:
        return PriorityClaim(
            claim_id=self.claim_id,
            priority_date=self.priority_date,
            country=self.country,
            first_application=self.first_application,
            same_subject=self.same_subject,
            proof_verified=self.proof_verified,
            covers=frozenset(self.covers),
        )


class SubjectIn(BaseModel):
    filing_date: date
    priority_date: date | None = None
    priority_claims: list[PriorityClaimIn] = Field(default_factory=list)
    application_type: str = "invention"

    def to_domain(self) -> SubjectApplication:
        return SubjectApplication(
            filing_date=self.filing_date,
            priority_date=self.priority_date,
            priority_claims=tuple(claim.to_domain() for claim in self.priority_claims),
            application_type=self.application_type,
        )


class CandidateDocumentIn(BaseModel):
    doc_id: str
    publication_number: str
    title: str
    source_verified: bool = False
    publication_date: date | None = None
    filing_date: date | None = None
    priority_date: date | None = None
    filed_in_china: bool = True

    def to_domain(self) -> CandidateDocument:
        return CandidateDocument(
            doc_id=self.doc_id,
            publication_number=self.publication_number,
            title=self.title,
            source_verified=self.source_verified,
            publication_date=self.publication_date,
            filing_date=self.filing_date,
            priority_date=self.priority_date,
            filed_in_china=self.filed_in_china,
        )


class FeatureComparisonRowIn(BaseModel):
    feature_code: str
    doc_id: str
    judgment: str

    def to_domain(self) -> FeatureComparisonRow:
        return FeatureComparisonRow(
            feature_code=self.feature_code,
            doc_id=self.doc_id,
            judgment=self.judgment,
        )


class EvidenceCitationIn(BaseModel):
    doc_id: str
    feature_code: str
    location: str = ""
    quote: str = ""
    verified: bool = False

    def to_domain(self) -> EvidenceCitation:
        return EvidenceCitation(
            doc_id=self.doc_id,
            feature_code=self.feature_code,
            location=self.location,
            quote=self.quote,
            verified=self.verified,
        )


class DataSourceRunIn(BaseModel):
    name: str
    status: str
    as_of: date | None = None

    def to_domain(self) -> DataSourceRun:
        return DataSourceRun(name=self.name, status=self.status, as_of=self.as_of)


class MotivationChecklistIn(BaseModel):
    common_knowledge: str | None = None
    explicit_teaching: str | None = None
    prejudice_or_teaching_away: str | None = None
    combination_obstacle: str | None = None
    effect_predictability: str | None = None

    def to_domain(self) -> MotivationChecklist:
        return MotivationChecklist(
            common_knowledge=self.common_knowledge,
            explicit_teaching=self.explicit_teaching,
            prejudice_or_teaching_away=self.prejudice_or_teaching_away,
            combination_obstacle=self.combination_obstacle,
            effect_predictability=self.effect_predictability,
        )


class AuxiliaryFactorIn(BaseModel):
    kind: str
    claimed: bool = False
    evidence_cited: bool = False
    causal_link_to_features: bool = False

    def to_domain(self) -> AuxiliaryFactor:
        return AuxiliaryFactor(
            kind=self.kind,
            claimed=self.claimed,
            evidence_cited=self.evidence_cited,
            causal_link_to_features=self.causal_link_to_features,
        )


class NumericRangeIn(BaseModel):
    feature_code: str
    doc_id: str
    claimed_lower: float | None = None
    claimed_upper: float | None = None
    disclosed_lower: float | None = None
    disclosed_upper: float | None = None
    disclosed_is_example: bool = False

    def to_domain(self) -> NumericRange:
        return NumericRange(
            feature_code=self.feature_code,
            doc_id=self.doc_id,
            claimed_lower=self.claimed_lower,
            claimed_upper=self.claimed_upper,
            disclosed_lower=self.disclosed_lower,
            disclosed_upper=self.disclosed_upper,
            disclosed_is_example=self.disclosed_is_example,
        )


class ConceptRelationIn(BaseModel):
    feature_code: str
    doc_id: str
    claimed_concept: str = ""
    disclosed_concept: str = ""
    relation: str = "unknown"

    def to_domain(self) -> ConceptRelation:
        return ConceptRelation(
            feature_code=self.feature_code,
            doc_id=self.doc_id,
            claimed_concept=self.claimed_concept,
            disclosed_concept=self.disclosed_concept,
            relation=self.relation,
        )


class KnownSubstituteIn(BaseModel):
    feature_code: str
    doc_id: str
    claimed_means: str = ""
    disclosed_means: str = ""
    substitutability_documented: bool = False

    def to_domain(self) -> KnownSubstitute:
        return KnownSubstitute(
            feature_code=self.feature_code,
            doc_id=self.doc_id,
            claimed_means=self.claimed_means,
            disclosed_means=self.disclosed_means,
            substitutability_documented=self.substitutability_documented,
        )


class AssessmentCreateBody(BaseModel):
    subject: SubjectIn
    documents: list[CandidateDocumentIn]
    rows: list[FeatureComparisonRowIn]
    citations: list[EvidenceCitationIn] = Field(default_factory=list)
    source_runs: list[DataSourceRunIn] = Field(default_factory=list)
    legal_status_as_of: dict[str, date] = Field(default_factory=dict)
    total_features: int | None = None
    motivation_checklist: MotivationChecklistIn | None = None
    auxiliary_factors: list[AuxiliaryFactorIn] = Field(default_factory=list)
    actual_technical_problem: str = ""
    distinguishing_feature_statements: list[str] = Field(default_factory=list)
    numeric_ranges: list[NumericRangeIn] = Field(default_factory=list)
    concept_relations: list[ConceptRelationIn] = Field(default_factory=list)
    known_substitutes: list[KnownSubstituteIn] = Field(default_factory=list)

    def to_assessment_input(self) -> AssessmentInput:
        return AssessmentInput(
            subject=self.subject.to_domain(),
            documents=[item.to_domain() for item in self.documents],
            rows=[item.to_domain() for item in self.rows],
            citations=[item.to_domain() for item in self.citations],
            source_runs=[item.to_domain() for item in self.source_runs],
            legal_status_as_of=dict(self.legal_status_as_of),
            total_features=self.total_features,
            motivation_checklist=(
                self.motivation_checklist.to_domain() if self.motivation_checklist else None
            ),
            auxiliary_factors=[item.to_domain() for item in self.auxiliary_factors],
            actual_technical_problem=self.actual_technical_problem,
            distinguishing_feature_statements=list(self.distinguishing_feature_statements),
            numeric_ranges=[item.to_domain() for item in self.numeric_ranges],
            concept_relations=[item.to_domain() for item in self.concept_relations],
            known_substitutes=[item.to_domain() for item in self.known_substitutes],
        )


class AssessmentDecideBody(BaseModel):
    decision: str  # approved | rejected | changes_requested
    comments: str = ""
    # 审批人明知仍存在未解决的阻塞项而坚持批准时，必须显式声明并写明理由，
    # 否则状态机会拒绝批准。
    accepts_insufficient_evidence: bool = False


def render_version(record: AssessmentVersionRecord, *, status: str | None = None) -> dict[str, Any]:
    """渲染单个评估版本。

    始终带上 requires_human_confirmation 与免责声明，避免调用方把候选发现
    当成已确认的专利性结论。
    """
    rendered = record.to_dict()
    rendered["status"] = status
    rendered["requires_human_confirmation"] = bool(record.requires_human_confirmation)
    rendered["disclaimer"] = DISCLAIMER
    return rendered


def render_version_summary(record: AssessmentVersionRecord) -> dict[str, Any]:
    """列表视图只给摘要，不回传完整 payload。"""
    return {
        "id": str(record.id),
        "version_number": record.version_number,
        "rules_version": record.rules_version,
        "prompt_versions": dict(record.prompt_versions),
        "payload_sha256": record.payload_sha256,
        "blockers": list(record.blockers),
        "flags": list(record.flags),
        "requires_human_confirmation": bool(record.requires_human_confirmation),
        "created_at": record.created_at.isoformat(),
        "disclaimer": DISCLAIMER,
    }


def render_decision(record: Any) -> dict[str, Any]:
    """审批决定记录。只读追加产物，不含任何改写能力。"""
    return {
        "version_id": record.version_id,
        "version_number": record.version_number,
        "payload_sha256": record.payload_sha256,
        "decision": record.decision,
        "reviewer_identity_id": record.reviewer_identity_id,
        "comments": record.comments,
        "open_blockers": list(record.open_blockers),
        "accepts_insufficient_evidence": record.accepts_insufficient_evidence,
        "decision_signature": record.decision_signature,
        "decided_at": record.decided_at,
        "disclaimer": DISCLAIMER,
    }
