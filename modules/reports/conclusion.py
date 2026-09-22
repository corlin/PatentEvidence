"""Report-side gate over whether any forward-looking statement may be rendered.

The comparison matrix evaluator can always produce a *candidate* reading of the
chart — that is arithmetic over the cells and needs no gate. What needs a gate
is publishing that reading in a report that goes to a client, because there it
stops being an internal hint and starts being read as an opinion.

A candidate reading may be published only when a pre-assessment version exists,
has passed internal review, and carries no open blockers. Passing this gate does
**not** license a patentability conclusion: no blockers means nothing was found
to block, not that patentability was established. This module therefore never
returns a conclusion, only permission to publish a candidate reading.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CONCLUSION_GATE_VERSION = "report-conclusion-gate-v1"

APPROVED_STATUS = "approved"

# Shown verbatim whenever a candidate reading is published, so the qualifier
# travels with the statement instead of living in a separate disclaimer page.
PUBLICATION_DISCLAIMER = (
    "本节为基于当前比对矩阵的候选判断，不构成专利性结论或授权前景意见。"
    "其通过复核仅表示本候选评估包内部一致、未发现阻塞项，不代表该方案具备专利性或可授权。"
)


@dataclass(frozen=True)
class ConclusionEligibility:
    """Whether a candidate reading may be published, and why or why not."""

    eligible: bool
    reasons: tuple[str, ...] = ()
    version_number: int | None = None
    payload_sha256: str | None = None
    gate_version: str = CONCLUSION_GATE_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "version_number": self.version_number,
            "payload_sha256": self.payload_sha256,
            "gate_version": self.gate_version,
        }


@dataclass(frozen=True)
class AssessmentSummary:
    """The assessment facts a report needs. Absence of a version is first-class."""

    has_version: bool = False
    version_number: int | None = None
    status: str | None = None
    blockers: tuple[str, ...] = field(default_factory=tuple)
    payload_sha256: str | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, object] | None) -> "AssessmentSummary":
        if not data:
            return cls()
        blockers = data.get("blockers") or []
        if isinstance(blockers, (list, tuple)):
            blockers_tuple = tuple(str(item) for item in blockers)
        else:
            blockers_tuple = ()
        version_number = data.get("version_number")
        status = data.get("status")
        sha = data.get("payload_sha256")
        return cls(
            has_version=bool(data.get("has_version", version_number is not None)),
            version_number=int(version_number) if version_number is not None else None,
            status=str(status) if status is not None else None,
            blockers=blockers_tuple,
            payload_sha256=str(sha) if sha is not None else None,
        )


STATUS_LABELS = {
    "draft": "草稿",
    "submitted": "待复核",
    "approved": "复核通过",
    "rejected": "复核未通过",
    "changes_requested": "需修改",
}


def _status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def evaluate_conclusion_eligibility(
    assessment: AssessmentSummary | dict[str, object] | None,
) -> ConclusionEligibility:
    """Decide whether a report may publish a candidate reading.

    Deterministic and conservative: any missing fact resolves to "not eligible"
    with a reason, never to an optimistic default.
    """
    if isinstance(assessment, dict) or assessment is None:
        assessment = AssessmentSummary.from_mapping(assessment)  # type: ignore[arg-type]

    if not assessment.has_version:
        return ConclusionEligibility(
            eligible=False,
            reasons=("本案尚无预评估版本，未跑过日期门禁、新颖性与创造性覆盖及证据完备度检查。",),
        )

    if assessment.status != APPROVED_STATUS:
        return ConclusionEligibility(
            eligible=False,
            reasons=(
                f"预评估版本 v{assessment.version_number} 尚未通过内部复核"
                f"（当前状态：{_status_label(assessment.status or '未知')}）。",
            ),
            version_number=assessment.version_number,
            payload_sha256=assessment.payload_sha256,
        )

    if assessment.blockers:
        head = "；".join(list(assessment.blockers)[:5])
        more = (
            f"（另有 {len(assessment.blockers) - 5} 项未列出）" if len(assessment.blockers) > 5 else ""
        )
        return ConclusionEligibility(
            eligible=False,
            reasons=(
                f"预评估版本 v{assessment.version_number} 虽已通过复核，"
                f"但仍有 {len(assessment.blockers)} 项未解决的阻塞项：{head}{more}。",
                "阻塞项未解决意味着该版本本身不能给出结论，报告因此不得输出任何倾向性判断。",
            ),
            version_number=assessment.version_number,
            payload_sha256=assessment.payload_sha256,
        )

    return ConclusionEligibility(
        eligible=True,
        reasons=(
            f"预评估版本 v{assessment.version_number} 已通过内部复核且无未解决阻塞项，"
            "允许发布候选判断。",
            "允许发布候选判断不等于具备专利性：无阻塞项仅表示未发现阻塞，不代表结论成立。",
        ),
        version_number=assessment.version_number,
        payload_sha256=assessment.payload_sha256,
    )
