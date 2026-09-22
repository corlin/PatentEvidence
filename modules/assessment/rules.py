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
from datetime import date
from itertools import combinations
from typing import Any

ASSESSMENT_RULES_VERSION = "assessment-rules-v3"

COVERING_JUDGMENTS = {"identical", "equivalent"}
SINGLE_REFERENCE_JUDGMENTS = {"identical"}

JUDGMENT_PRECEDENCE = {"identical": 3, "equivalent": 2, "different": 1, "insufficient_evidence": 0}

# 优先权期限（月）：发明与实用新型 12 个月，外观设计 6 个月。
PRIORITY_TERM_MONTHS = {"invention": 12, "utility_model": 12, "design": 6}


def _judgment_precedence(judgment: str) -> int:
    return JUDGMENT_PRECEDENCE.get(judgment, -1)


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
    publication_date: date | None = None
    filing_date: date | None = None  # 对比文件的申请日
    priority_date: date | None = None  # 对比文件主张的优先权日
    filed_in_china: bool = True  # 抵触申请只认向中国提出的申请（含进入中国国家阶段的 PCT）

    def effective_filing_date(self) -> date | None:
        """对比文件的在先申请日：有优先权日的，指优先权日。"""
        candidates = [d for d in (self.priority_date, self.filing_date) if d is not None]
        return min(candidates) if candidates else None


@dataclass(frozen=True)
class PriorityClaim:
    """一项优先权主张。

    `covers` 用于部分优先权：只列出该在先申请确实记载的技术特征（或方案标识）。
    为空表示全部特征均享有该项优先权。未列入 `covers` 的特征回落到申请日。
    """

    claim_id: str
    priority_date: date
    country: str = ""
    first_application: bool = True  # 是否为同一主题的第一次申请
    same_subject: bool = True  # 在后申请与在先申请是否为相同主题
    proof_verified: bool = False  # 优先权证明文件/在先申请副本是否已核验
    covers: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PriorityVerification:
    """优先权核验结果：把「一个基准日」拆成「按特征的基准日」。

    代码只做可核验的部分（期限、首次申请、主题覆盖、证明是否核验）；
    相同主题的实质判断、优先权是否真正成立，必须由代理师确认。
    """

    default_reference_date: date
    per_feature_reference_dates: dict[str, date]
    valid_claims: tuple[str, ...]
    invalid_claims: tuple[dict[str, Any], ...]
    flags: tuple[str, ...]
    requires_human_confirmation: bool

    def reference_date_for(self, feature_code: str | None) -> date:
        if feature_code is None:
            return self.default_reference_date
        return self.per_feature_reference_dates.get(feature_code, self.default_reference_date)

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_reference_date": self.default_reference_date.isoformat(),
            "per_feature_reference_dates": {
                code: value.isoformat() for code, value in sorted(self.per_feature_reference_dates.items())
            },
            "valid_claims": list(self.valid_claims),
            "invalid_claims": [dict(item) for item in self.invalid_claims],
            "flags": list(self.flags),
            "requires_human_confirmation": self.requires_human_confirmation,
        }


def _add_months(start: date, months: int) -> date:
    """期限届满日：按月加，跨年进位；当月无对应日时回退到月末。"""
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    day = start.day
    while day > 1:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, 1)


def verify_priority(
    subject: SubjectApplication,
    feature_codes: tuple[str, ...] = (),
) -> PriorityVerification:
    """核验多项 / 部分优先权，给出按特征的时间基准日。

    确定性可核验的只有四项：期限、首次申请、相同主题（按调用方标注）、
    证明是否核验。全部成立才算有效；无效的优先权使基准日回落到申请日。
    """
    filing_date = subject.filing_date
    term_months = PRIORITY_TERM_MONTHS.get(subject.application_type, PRIORITY_TERM_MONTHS["invention"])
    valid: list[str] = []
    invalid: list[dict[str, Any]] = []
    flags: list[str] = []

    covered: dict[str, date] = {}
    for claim in subject.claims():
        deadline = _add_months(claim.priority_date, term_months)
        if claim.priority_date > filing_date:
            invalid.append({"claim_id": claim.claim_id, "reason": "优先权日晚于本申请申请日"})
            continue
        if filing_date > deadline:
            invalid.append(
                {
                    "claim_id": claim.claim_id,
                    "reason": f"超出 {term_months} 个月优先权期限（届满日 {deadline.isoformat()}）",
                }
            )
            continue
        if not claim.first_application:
            invalid.append({"claim_id": claim.claim_id, "reason": "并非同一主题的第一次申请"})
            continue
        if not claim.same_subject:
            invalid.append({"claim_id": claim.claim_id, "reason": "在后申请与在先申请并非相同主题"})
            continue
        if not claim.proof_verified:
            flags.append(
                f"优先权 {claim.claim_id} 的证明文件/在先申请副本尚未核验，"
                "暂按成立计算，代理师须补核验。"
            )
        valid.append(claim.claim_id)

        if claim.covers:
            for code in claim.covers:
                previous = covered.get(code)
                if previous is None or claim.priority_date < previous:
                    covered[code] = claim.priority_date
        else:
            for code in feature_codes:
                previous = covered.get(code)
                if previous is None or claim.priority_date < previous:
                    covered[code] = claim.priority_date

    earliest_valid = None
    for claim in subject.claims():
        if claim.claim_id in valid:
            if earliest_valid is None or claim.priority_date < earliest_valid:
                earliest_valid = claim.priority_date

    default_reference_date = min([earliest_valid or filing_date, filing_date])
    per_feature: dict[str, date] = {}
    for code in feature_codes:
        per_feature[code] = min([covered.get(code, filing_date), filing_date])

    if valid and any(code for code in feature_codes if code not in covered):
        missing = sorted(code for code in feature_codes if code not in covered)
        flags.append(
            "存在部分优先权：以下特征不在任何有效在先申请的记载范围内，"
            f"其基准日回落到申请日 {filing_date.isoformat()}：{', '.join(missing)}。"
        )

    return PriorityVerification(
        default_reference_date=default_reference_date,
        per_feature_reference_dates=per_feature,
        valid_claims=tuple(valid),
        invalid_claims=tuple(invalid),
        flags=tuple(flags),
        requires_human_confirmation=bool(invalid) or bool(flags),
    )


def priority_verification_findings(
    subject: SubjectApplication,
    feature_codes: tuple[str, ...] = (),
) -> list[AssessmentFinding]:
    """把不成立或存疑的优先权暴露成必须人工处理的项。"""
    verification = verify_priority(subject, feature_codes)
    if not verification.invalid_claims and not verification.flags:
        return []
    return [
        AssessmentFinding(
            risk_kind="priority_verification",
            level="needs_confirmation",
            basis=[
                {"valid_claims": list(verification.valid_claims)},
                {"invalid_claims": [dict(item) for item in verification.invalid_claims]},
                {"default_reference_date": verification.default_reference_date.isoformat()},
            ],
            requires_human_confirmation=True,
            reasoning=(
                "优先权核验存在不成立或存疑项："
                + "；".join(item["reason"] for item in verification.invalid_claims)
                + ("；" if verification.invalid_claims and verification.flags else "")
                + "；".join(verification.flags)
                + "。权利要求层面的基准日必须由代理师确认。"
            ),
        )
    ]


@dataclass(frozen=True)
class SubjectApplication:
    """本申请的时间基准。判断现有技术以申请日为准；有优先权的，指优先权日。

    多项优先权 / 部分优先权会让同一件申请的不同技术方案拥有不同的基准日，
    因此 `priority_claims` 是权威来源；`priority_date` 只是单一优先权的简写，
    在 `priority_claims` 为空时生效。
    """

    filing_date: date
    priority_date: date | None = None
    priority_claims: tuple[PriorityClaim, ...] = ()
    application_type: str = "invention"  # invention | utility_model | design

    def claims(self) -> tuple[PriorityClaim, ...]:
        if self.priority_claims:
            return self.priority_claims
        if self.priority_date is None:
            return ()
        return (
            PriorityClaim(
                claim_id="P1",
                priority_date=self.priority_date,
                first_application=True,
                proof_verified=True,
            ),
        )

    def reference_date(self) -> date:
        """未做优先权核验时的兜底基准日（不区分部分优先权）。"""
        return min([self.priority_date or self.filing_date, self.filing_date])


class ReferenceKind:
    PRIOR_ART = "prior_art"  # 申请日（优先权日）前为公众所知：可用于新颖性与创造性
    CONFLICTING_APPLICATION = "conflicting_application"  # 抵触申请：只能用于评价新颖性
    NOT_USABLE = "not_usable"  # 公开晚于基准日且并非在先申请：不能用于评价
    UNKNOWN = "unknown"  # 日期缺失：证据不足，不得用于任何判断


# 文献日期分类的保守度：越高越不可用。部分优先权会让同一文献对不同特征得到
# 不同分类，文献级取最保守的那个。
REFERENCE_KIND_SEVERITY = {
    ReferenceKind.PRIOR_ART: 0,
    ReferenceKind.CONFLICTING_APPLICATION: 1,
    ReferenceKind.NOT_USABLE: 2,
    ReferenceKind.UNKNOWN: 3,
}


def classify_reference(
    document: CandidateDocument,
    subject: SubjectApplication,
    verification: PriorityVerification | None = None,
    feature_code: str | None = None,
) -> str:
    """Date gate: 现有技术 / 抵触申请 / 不可用 / 日期未知.

    抵触申请 = 由任何单位或个人在本申请申请日（优先权日）以前向中国提出，
    并记载在本申请日（含当日）以后公布的同样的发明或实用新型申请。

    传入 `verification` 与 `feature_code` 时按该特征自己的基准日判断——
    部分优先权下同一文献对不同特征的结论可能不同。
    """
    if verification is not None and feature_code is not None:
        reference_date = verification.reference_date_for(feature_code)
    elif verification is not None:
        reference_date = verification.default_reference_date
    else:
        reference_date = subject.reference_date()
    published = document.publication_date
    earlier_filing = document.effective_filing_date()
    if published is None or earlier_filing is None:
        return ReferenceKind.UNKNOWN
    if published < reference_date:
        return ReferenceKind.PRIOR_ART
    if earlier_filing < reference_date and document.filed_in_china:
        return ReferenceKind.CONFLICTING_APPLICATION
    return ReferenceKind.NOT_USABLE


def classify_all_references(
    documents: list[CandidateDocument],
    subject: SubjectApplication,
    verification: PriorityVerification | None = None,
    rows: list[FeatureComparisonRow] | None = None,
) -> dict[str, str]:
    """文献级分类。有部分优先权时，一篇文献对不同特征的结论可能不同，
    文献级一律取最保守（最不可用）的那个。"""
    features_by_doc = _rows_by_doc(rows) if rows else {}
    result: dict[str, str] = {}
    for doc in documents:
        codes = sorted({r.feature_code for r in features_by_doc.get(doc.doc_id, [])})
        if verification is not None and codes:
            kinds = [classify_reference(doc, subject, verification, code) for code in codes]
            result[doc.doc_id] = max(kinds, key=lambda kind: REFERENCE_KIND_SEVERITY[kind])
        else:
            result[doc.doc_id] = classify_reference(doc, subject, verification)
    return result


def classify_reference_for_features(
    document: CandidateDocument,
    subject: SubjectApplication,
    verification: PriorityVerification,
    feature_codes: list[str],
) -> dict[str, str]:
    """按特征给出日期分类，供人工逐项核对部分优先权的影响。"""
    return {
        code: classify_reference(document, subject, verification, code)
        for code in sorted(set(feature_codes))
    }


def reference_eligibility_findings(
    documents: list[CandidateDocument],
    subject: SubjectApplication,
    verification: PriorityVerification | None = None,
    kinds: dict[str, str] | None = None,
) -> list[AssessmentFinding]:
    """Date-gate findings: which references may be used, and for what."""
    findings: list[AssessmentFinding] = []
    resolved = kinds or classify_all_references(documents, subject, verification)
    for doc in documents:
        kind = resolved.get(doc.doc_id, ReferenceKind.UNKNOWN)
        if kind == ReferenceKind.PRIOR_ART:
            continue
        if kind == ReferenceKind.CONFLICTING_APPLICATION:
            findings.append(
                AssessmentFinding(
                    risk_kind="reference_eligibility",
                    level="needs_confirmation",
                    basis=[{"doc_id": doc.doc_id, "kind": kind}],
                    requires_human_confirmation=True,
                    reasoning=(
                        f"对比文件 {doc.doc_id} 为抵触申请：可用于评价新颖性，"
                        "不得用于评价创造性，也不得作为最接近的现有技术。"
                    ),
                )
            )
        elif kind == ReferenceKind.NOT_USABLE:
            findings.append(
                AssessmentFinding(
                    risk_kind="reference_eligibility",
                    level="needs_confirmation",
                    basis=[{"doc_id": doc.doc_id, "kind": kind}],
                    requires_human_confirmation=True,
                    reasoning=(
                        f"对比文件 {doc.doc_id} 公开日晚于本申请基准日 "
                        f"{verification.default_reference_date if verification else subject.reference_date()} "
                        "且并非在先申请，不能用于评价新颖性或创造性。"
                    ),
                )
            )
        else:
            findings.append(
                AssessmentFinding(
                    risk_kind="reference_eligibility",
                    level="needs_confirmation",
                    basis=[{"doc_id": doc.doc_id, "kind": kind}],
                    requires_human_confirmation=True,
                    reasoning=(
                        f"对比文件 {doc.doc_id} 缺少公开日或申请日/优先权日，"
                        "无法完成日期门禁，证据不足，不得用于任何评价。"
                    ),
                )
            )
    return findings


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
    reference_kinds: dict[str, str] | None = None,
) -> list[AssessmentFinding]:
    """Novelty gate: a single reference covering ALL features identically.

    Deterministic single-reference/all-elements gate. The application keeps
    this gate; any model may only supply the underlying cell judgments.

    Only 现有技术 and 抵触申请 can be used here (抵触申请仅评价新颖性).
    """
    if total_features <= 0:
        return []
    kinds = reference_kinds or {}
    findings: list[AssessmentFinding] = []
    for doc_id, doc_rows in sorted(_rows_by_doc(rows).items()):
        if kinds.get(doc_id) in {ReferenceKind.NOT_USABLE, ReferenceKind.UNKNOWN}:
            continue
        conflicting = kinds.get(doc_id) == ReferenceKind.CONFLICTING_APPLICATION
        scope_note = "（抵触申请，仅可用于评价新颖性，不得用于创造性）" if conflicting else ""
        identical = {r.feature_code for r in doc_rows if r.judgment in SINGLE_REFERENCE_JUDGMENTS}
        if len(identical) == total_features:
            findings.append(
                AssessmentFinding(
                    risk_kind="novelty",
                    level="high_novelty_risk",
                    basis=[r.to_dict() for r in sorted(doc_rows, key=lambda r: r.feature_code)],
                    requires_human_confirmation=False,
                    reasoning=(
                        f"单篇对比文件 {doc_id}{scope_note} 对全部 {total_features} 项必要技术特征均为相同公开，"
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
                        f"对比文件 {doc_id}{scope_note} 覆盖全部特征但含等同替代判断，不触发新颖性门禁；"
                        "等同认定必须人工复核。"
                    ),
                )
            )
    return findings


def combination_findings(
    rows: list[FeatureComparisonRow],
    total_features: int,
    reference_kinds: dict[str, str] | None = None,
) -> list[AssessmentFinding]:
    """Coverage screening for document pairs (no motivation judgment here).

    Motivation-to-combine is NOT decided by code or by a model: a covering
    pair is only a *candidate combination* that a patent agent must confirm.

    抵触申请不得用于评价创造性，因此只有现有技术进入组合筛查。
    """
    if total_features <= 0:
        return []
    kinds = reference_kinds or {}
    grouped = _rows_by_doc(rows)
    doc_ids = sorted(doc_id for doc_id in grouped if kinds.get(doc_id, ReferenceKind.PRIOR_ART) == ReferenceKind.PRIOR_ART)
    if len(doc_ids) < 2:
        return []
    findings: list[AssessmentFinding] = []
    for first, second in combinations(doc_ids, 2):
        # 组合覆盖 = 任一篇披露即覆盖，因此同名特征取"最优"判定，不能被后一篇覆盖掉。
        cells: dict[str, str] = {}
        for row in grouped[first] + grouped[second]:
            if row.feature_code not in cells or _judgment_precedence(row.judgment) > _judgment_precedence(
                cells[row.feature_code]
            ):
                cells[row.feature_code] = row.judgment
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


ABSTRACT_ONLY_LOCATIONS = {"摘要", "abstract", "abstract_only", "书目信息"}


@dataclass(frozen=True)
class EvidenceCitation:
    """One matrix cell's source layer: 原文引文 + 可定位位置 + 逐字核验状态."""

    doc_id: str
    feature_code: str
    location: str = ""  # 页码 / 段落 / 权利要求定位 / URL
    quote: str = ""  # 原文引文
    verified: bool = False  # 引文能在输入原文块中逐字定位

    def anchor(self) -> str:
        return f"{self.doc_id}/{self.feature_code}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DataSourceRun:
    """One search adapter run: EPO / USPTO / CNIPR 等。"""

    name: str
    status: str  # ok | partial | failed
    as_of: date | None = None  # 数据快照时点

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceCompleteness:
    """Spec 6.6 证据完备度：来源覆盖率、未核验引用、数据源失败、法律状态时点。"""

    source_coverage: float
    verified_citations: int
    total_citations: int
    missing_anchors: list[str]
    unverified_citations: list[str]
    abstract_only_citations: list[str]
    failed_sources: list[str]
    partial_sources: list[str]
    documents_without_legal_status_timepoint: list[str]
    blocking_gaps: list[str]
    flags: list[str]
    blocks_conclusion: bool
    level: str
    rules_version: str = ASSESSMENT_RULES_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_evidence_completeness(
    rows: list[FeatureComparisonRow],
    total_features: int,
    documents: list[CandidateDocument],
    citations: list[EvidenceCitation] | None = None,
    source_runs: list[DataSourceRun] | None = None,
    legal_status_as_of: dict[str, date] | None = None,
) -> EvidenceCompleteness:
    """Fine-grained evidence completeness with hard blocking gaps.

    Blocking (禁止输出结论): 引证未定位、引用未逐字核验、数据源失败。
    法律状态时点缺失只标记不阻塞——它影响权利行使与有效性，而非可专利性
    判断本身，且公开出版物类对比文件本无法律状态概念；是否影响本案由
    代理师判断。摘要不能替代说明书原文，同样只标记不阻塞。
    """
    provided = list(citations or [])
    verified_citations = [c for c in provided if c.verified and c.location.strip() and c.quote.strip()]
    missing_anchors = [c.anchor() for c in provided if not c.location.strip() or not c.quote.strip()]
    # 有判定但完全没有引证的单元格同样是证据缺口：没有可验证原文时必须显示证据不足。
    cited_cells = {c.anchor() for c in provided}
    missing_anchors.extend(
        sorted(
            f"{row.doc_id}/{row.feature_code}"
            for row in rows
            if f"{row.doc_id}/{row.feature_code}" not in cited_cells
        )
    )
    unverified_citations = [
        c.anchor() for c in provided if not c.verified and c.location.strip() and c.quote.strip()
    ]
    abstract_only_citations = [
        c.anchor() for c in provided if c.location.strip().lower() in {a.lower() for a in ABSTRACT_ONLY_LOCATIONS}
    ]

    declared_cells = len({(row.doc_id, row.feature_code) for row in rows})
    denominator = declared_cells or len(provided) or max(total_features * len(documents), 1)
    source_coverage = round(len(verified_citations) / denominator, 4) if denominator else 0.0

    runs = list(source_runs or [])
    failed_sources = [run.name for run in runs if run.status == "failed"]
    partial_sources = [run.name for run in runs if run.status == "partial"]

    status_as_of = legal_status_as_of or {}
    documents_without_legal_status_timepoint = [
        doc.doc_id for doc in documents if doc.doc_id not in status_as_of
    ]

    blocking_gaps: list[str] = []
    flags: list[str] = []
    if missing_anchors:
        blocking_gaps.append(f"引证未定位（缺页码/段落/权利要求位置或原文引文）{len(missing_anchors)} 处")
    if unverified_citations:
        blocking_gaps.append(f"引用未逐字核验 {len(unverified_citations)} 处")
    if failed_sources:
        blocking_gaps.append(f"数据源失败 {'、'.join(failed_sources)}（任务为 partial_success，不得丢弃成功结果）")
    if partial_sources:
        flags.append(f"数据源部分成功 {'、'.join(partial_sources)}")
    if abstract_only_citations:
        flags.append(f"仅摘要级引用 {len(abstract_only_citations)} 处，摘要不能替代说明书原文")
    if documents_without_legal_status_timepoint:
        flags.append(
            f"缺失法律状态时点 {'、'.join(documents_without_legal_status_timepoint)}"
        )
    missing_cells = max(total_features - len({row.feature_code for row in rows}), 0)
    if missing_cells:
        blocking_gaps.append(f"缺失比对单元格 {missing_cells} 项")
    unverified_documents = [doc.doc_id for doc in documents if not doc.source_verified]
    if unverified_documents:
        flags.append(f"来源未核验 {'、'.join(unverified_documents)}")

    level = "needs_confirmation" if (blocking_gaps or flags) else "low"
    return EvidenceCompleteness(
        source_coverage=source_coverage,
        verified_citations=len(verified_citations),
        total_citations=len(provided),
        missing_anchors=missing_anchors,
        unverified_citations=unverified_citations,
        abstract_only_citations=abstract_only_citations,
        failed_sources=failed_sources,
        partial_sources=partial_sources,
        documents_without_legal_status_timepoint=documents_without_legal_status_timepoint,
        blocking_gaps=blocking_gaps,
        flags=flags,
        blocks_conclusion=bool(blocking_gaps),
        level=level,
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
    reference_kinds: dict[str, str] | None = None,
) -> ThreeStepScaffold | None:
    """Step 1 + 2 of the inventive-step sequence, as candidate scaffolding.

    Step 1 (closest prior art) is scored deterministically as the document
    with the most identical judgments (ties broken by fewer
    insufficient_evidence cells, then doc_id). 抵触申请不得作为最接近的现有
    技术（它只能评价新颖性），因此不参与打分。 Step 3 (motivation to
    combine) is never computed here — it is a human-filled checklist.
    """
    kinds = reference_kinds or {}
    grouped = {
        doc_id: rows_for_doc
        for doc_id, rows_for_doc in _rows_by_doc(rows).items()
        if kinds.get(doc_id, ReferenceKind.PRIOR_ART) == ReferenceKind.PRIOR_ART
    }
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


MOTIVATION_CHECKLIST_ITEMS: tuple[str, ...] = (
    "common_knowledge",  # 区别特征是否为公知常识或本领域的惯用手段
    "explicit_teaching",  # 是否存在另一篇文献给出将该特征应用到最接近现有技术的明确教导
    "prejudice_or_teaching_away",  # 现有技术是否存在技术偏见或相反教导
    "combination_obstacle",  # 是否存在结合的技术障碍（无法工作/需改造）
    "effect_predictability",  # 结合后的技术效果是否可预期
)


@dataclass
class MotivationChecklist:
    """Step 3: structured, human-filled motivation-to-combine checklist.

    Code never decides whether a motivation exists; it only verifies that
    every item has been answered and flags items that favor inventiveness.
    """

    common_knowledge: str | None = None
    explicit_teaching: str | None = None
    prejudice_or_teaching_away: str | None = None
    combination_obstacle: str | None = None
    effect_predictability: str | None = None

    def answers(self) -> dict[str, str | None]:
        return {item: getattr(self, item) for item in MOTIVATION_CHECKLIST_ITEMS}

    def to_dict(self) -> dict[str, Any]:
        return self.answers()


def motivation_checklist_state(checklist: MotivationChecklist) -> dict[str, Any]:
    """Validate completeness; return blockers and inventiveness-favouring flags."""
    answers = checklist.answers()
    unanswered = [item for item, value in answers.items() if not value or value.strip() == ""]
    favouring = [
        item
        for item in ("prejudice_or_teaching_away", "combination_obstacle")
        if str(answers.get(item) or "").strip().lower() == "yes"
    ]
    return {
        "complete": not unanswered,
        "unanswered": unanswered,
        "favouring_inventiveness": favouring,
        "blocks_conclusion": bool(unanswered),
        "rules_version": ASSESSMENT_RULES_VERSION,
    }


AUXILIARY_FACTOR_KINDS: tuple[str, ...] = (
    "long_unsolved_problem",
    "overcoming_prejudice",
    "unexpected_effect",
    "commercial_success",
)


@dataclass
class AuxiliaryFactor:
    """辅助性审查基准。主张必须有证据支撑；商业成功还须由技术特征直接导致。"""

    kind: str
    claimed: bool = False
    evidence_cited: bool = False
    causal_link_to_features: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_auxiliary_factors(factors: list[AuxiliaryFactor]) -> dict[str, Any]:
    """辅助因素只作参考：未举证的主张不计入，不得单独支撑创造性结论。"""
    counted: list[dict[str, Any]] = []
    unsubstantiated: list[str] = []
    for factor in factors:
        entry = factor.to_dict()
        if not factor.claimed:
            continue
        if factor.kind == "commercial_success" and not (factor.evidence_cited and factor.causal_link_to_features):
            entry["status"] = "unsubstantiated"
            unsubstantiated.append(factor.kind)
        elif not factor.evidence_cited:
            entry["status"] = "unsubstantiated"
            unsubstantiated.append(factor.kind)
        else:
            entry["status"] = "counted"
        counted.append(entry)
    return {
        "counted": counted,
        "unsubstantiated": unsubstantiated,
        "note": "辅助性审查基准仅为参考，不得单独作为具备创造性的依据。",
        "rules_version": ASSESSMENT_RULES_VERSION,
    }


def hindsight_risk(
    actual_technical_problem: str,
    distinguishing_feature_statements: list[str],
) -> dict[str, Any]:
    """Flag 事后诸葛亮 risk when the 'problem' simply restates the features.

    Deterministic smell check only: it does not decide the problem, it only
    warns when the stated problem embeds the distinguishing feature itself.
    """
    problem = (actual_technical_problem or "").strip()
    hits = [stmt for stmt in distinguishing_feature_statements if stmt and stmt.strip() and stmt.strip() in problem]
    return {
        "hindsight_risk": bool(hits),
        "matched_statements": hits,
        "guidance": (
            "实际解决的技术问题必须基于区别特征所达到的技术效果重新确定，"
            "不得把区别特征本身或本申请方案直接写成技术问题。"
        ),
        "rules_version": ASSESSMENT_RULES_VERSION,
    }


# ---------------------------------------------------------------------------
# 实体级新颖性细化（只出候选标记，绝不自动升级为 identical）
# ---------------------------------------------------------------------------


class EntityObservationEffect:
    MAY_DEFEAT = "may_defeat_novelty"  # 候选：可能破坏新颖性，须人工确认
    DOES_NOT_DEFEAT = "does_not_defeat_novelty"  # 候选：通常不破坏新颖性
    UNDETERMINED = "undetermined"  # 证据不足，无法给出倾向


@dataclass(frozen=True)
class NumericRange:
    """权利要求的数值范围 vs 对比文件公开的数值范围。

    `disclosed_is_example` 表示对比文件公开的是实施例的具体点值而非连续范围，
    此时即便落入权利要求范围，也不当然破坏新颖性（须人工判断是否构成选择发明）。
    """

    feature_code: str
    doc_id: str
    claimed_lower: float | None = None
    claimed_upper: float | None = None
    disclosed_lower: float | None = None
    disclosed_upper: float | None = None
    disclosed_is_example: bool = False


@dataclass(frozen=True)
class ConceptRelation:
    """权利要求概念与对比文件公开概念的上下位关系。"""

    feature_code: str
    doc_id: str
    claimed_concept: str = ""
    disclosed_concept: str = ""
    # generic_disclosed: 对比文件公开上位、权利要求为下位
    # specific_disclosed: 对比文件公开下位、权利要求为上位
    # synonym: 同义/惯用称谓替换
    # unknown: 关系未定
    relation: str = "unknown"


@dataclass(frozen=True)
class KnownSubstitute:
    """惯用手段的直接置换。

    `substitutability_documented` 表示是否有教科书、手册或标准等证据证明该置换
    属于惯用手段。没有证据时不得推定为惯用手段。
    """

    feature_code: str
    doc_id: str
    claimed_means: str = ""
    disclosed_means: str = ""
    substitutability_documented: bool = False


@dataclass(frozen=True)
class EntityLevelObservation:
    """一条实体级候选观察。

    观察项永远不改变比对单元格的判定（identical/equivalent/different），
    也永远不触发单篇全覆盖门禁——它只是交给代理师的候选信号。
    """

    kind: str
    feature_code: str
    doc_id: str
    effect: str
    reasoning: str
    requires_human_confirmation: bool = True
    rules_version: str = ASSESSMENT_RULES_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _overlaps(
    claimed_lower: float | None,
    claimed_upper: float | None,
    disclosed_lower: float | None,
    disclosed_upper: float | None,
) -> bool | None:
    """两区间是否重叠。任一端缺失即返回 None（信息不足）。"""
    if None in (claimed_lower, claimed_upper, disclosed_lower, disclosed_upper):
        return None
    return claimed_lower <= disclosed_upper and disclosed_lower <= claimed_upper


def observe_numeric_ranges(ranges: list[NumericRange]) -> list[EntityLevelObservation]:
    """数值范围重叠：只标「可能破坏新颖性」的候选，绝不下结论。

    数值范围重叠在新颖性判断中通常破坏新颖性，但存在选择发明、实施例点值等
    例外，因此代码只给出候选方向，例外与否由代理师确认。
    """
    observations: list[EntityLevelObservation] = []
    for item in ranges:
        overlap = _overlaps(
            item.claimed_lower, item.claimed_upper, item.disclosed_lower, item.disclosed_upper
        )
        if overlap is None:
            observations.append(
                EntityLevelObservation(
                    kind="numeric_range",
                    feature_code=item.feature_code,
                    doc_id=item.doc_id,
                    effect=EntityObservationEffect.UNDETERMINED,
                    reasoning=(
                        f"特征 {item.feature_code} 的权利要求数值范围或对比文件 {item.doc_id} "
                        "的公开范围不完整，无法判断区间关系，证据不足。"
                    ),
                )
            )
            continue
        if not overlap:
            observations.append(
                EntityLevelObservation(
                    kind="numeric_range",
                    feature_code=item.feature_code,
                    doc_id=item.doc_id,
                    effect=EntityObservationEffect.DOES_NOT_DEFEAT,
                    reasoning=(
                        f"对比文件 {item.doc_id} 公开的数值范围与特征 {item.feature_code} "
                        "的权利要求范围不相交，通常不破坏新颖性；"
                        "是否构成选择发明须人工确认。"
                    ),
                )
            )
            continue
        example_note = (
            "对比文件公开的为实施例点值而非连续范围，可能不构成范围公开；"
            if item.disclosed_is_example
            else ""
        )
        observations.append(
            EntityLevelObservation(
                kind="numeric_range",
                feature_code=item.feature_code,
                doc_id=item.doc_id,
                effect=EntityObservationEffect.MAY_DEFEAT,
                reasoning=(
                    f"对比文件 {item.doc_id} 公开的数值范围与特征 {item.feature_code} "
                    f"的权利要求范围重叠，存在破坏新颖性的候选风险；{example_note}"
                    "是否属于选择发明或端点例外须人工确认，系统不作认定。"
                ),
            )
        )
    return observations


def observe_concept_relations(relations: list[ConceptRelation]) -> list[EntityLevelObservation]:
    """上位/下位概念：方向敏感。上位公开不破坏下位，下位公开破坏上位。"""
    observations: list[EntityLevelObservation] = []
    for item in relations:
        if item.relation == "generic_disclosed":
            observations.append(
                EntityLevelObservation(
                    kind="concept_generality",
                    feature_code=item.feature_code,
                    doc_id=item.doc_id,
                    effect=EntityObservationEffect.DOES_NOT_DEFEAT,
                    reasoning=(
                        f"对比文件 {item.doc_id} 公开的是上位概念「{item.disclosed_concept}」，"
                        f"权利要求为下位概念「{item.claimed_concept}」；"
                        "上位概念的公开通常不破坏下位概念特征的新颖性（须人工确认）。"
                    ),
                )
            )
        elif item.relation == "specific_disclosed":
            observations.append(
                EntityLevelObservation(
                    kind="concept_generality",
                    feature_code=item.feature_code,
                    doc_id=item.doc_id,
                    effect=EntityObservationEffect.MAY_DEFEAT,
                    reasoning=(
                        f"对比文件 {item.doc_id} 公开的是下位概念「{item.disclosed_concept}」，"
                        f"权利要求为上位概括「{item.claimed_concept}」；"
                        "下位公开通常破坏上位概括的新颖性，但须人工确认该下位是否确实落入上位范围。"
                    ),
                )
            )
        else:
            observations.append(
                EntityLevelObservation(
                    kind="concept_generality",
                    feature_code=item.feature_code,
                    doc_id=item.doc_id,
                    effect=EntityObservationEffect.UNDETERMINED,
                    reasoning=(
                        f"特征 {item.feature_code} 与对比文件 {item.doc_id} 的概念关系未定"
                        f"「{item.claimed_concept}」vs「{item.disclosed_concept}」，"
                        "无法判断上下位，须人工确认。"
                    ),
                )
            )
    return observations


def observe_known_substitutes(substitutes: list[KnownSubstitute]) -> list[EntityLevelObservation]:
    """惯用手段的直接置换：只有在有文献证据证明属惯用手段时才给候选倾向。"""
    observations: list[EntityLevelObservation] = []
    for item in substitutes:
        if item.substitutability_documented:
            observations.append(
                EntityLevelObservation(
                    kind="known_substitute",
                    feature_code=item.feature_code,
                    doc_id=item.doc_id,
                    effect=EntityObservationEffect.MAY_DEFEAT,
                    reasoning=(
                        f"对比文件 {item.doc_id} 公开「{item.disclosed_means}」，"
                        f"权利要求为「{item.claimed_means}」，已有证据证明属惯用手段的直接置换；"
                        "依审查指南该类替换可能破坏新颖性，但须人工确认证据是否充分。"
                    ),
                )
            )
        else:
            observations.append(
                EntityLevelObservation(
                    kind="known_substitute",
                    feature_code=item.feature_code,
                    doc_id=item.doc_id,
                    effect=EntityObservationEffect.UNDETERMINED,
                    reasoning=(
                        f"对比文件 {item.doc_id} 公开「{item.disclosed_means}」，"
                        f"权利要求为「{item.claimed_means}」，但无教科书/手册/标准等证据证明"
                        "二者属惯用手段的直接置换；不得推定为惯用手段，须人工补充证据。"
                    ),
                )
            )
    return observations


def entity_level_observations(
    ranges: list[NumericRange] | None = None,
    relations: list[ConceptRelation] | None = None,
    substitutes: list[KnownSubstitute] | None = None,
) -> list[EntityLevelObservation]:
    """汇总三类实体级候选观察项。

    这些观察项不改变任何比对单元格的判定，也不触发单篇全覆盖门禁。
    """
    observations: list[EntityLevelObservation] = []
    observations.extend(observe_numeric_ranges(ranges or []))
    observations.extend(observe_concept_relations(relations or []))
    observations.extend(observe_known_substitutes(substitutes or []))
    return observations
