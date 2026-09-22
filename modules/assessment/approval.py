"""Approval state machine for pre-assessment versions.

Cases are reviewed as a whole by `modules/review/workflow.py`; this engine is
scoped to a single assessment version, because a case may run through several
assessment versions and a report may only bind to one that was approved.

The rules that matter:

- a version is 草稿 until submitted, then 待复核;
- approving is impossible while blockers remain, unless the reviewer
  explicitly accepts an 证据不足 conclusion (see `accepts_insufficient_evidence`)
  — "证据不足" is itself a legitimate pre-assessment outcome, so the gate must
  be explicit rather than silently passable;
- approved versions are frozen: any further decision is rejected, revision
  means a new version;
- every decision carries a signature over the payload digest, so an approval
  cannot later be replayed against a different package.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


class AssessmentVersionStatus:
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"


class AssessmentDecision:
    APPROVE = "approved"
    REQUEST_CHANGES = "changes_requested"
    REJECT = "rejected"


TERMINAL_STATUSES = (AssessmentVersionStatus.APPROVED, AssessmentVersionStatus.REJECTED)

# 允许从「待复核」走到各决策；草稿必须先提交。打回修改回到草稿——修订意味着
# 生成新版本，而不是改写旧版本，所以这里回到的是「可再次提交」的状态。
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    AssessmentVersionStatus.DRAFT: (AssessmentVersionStatus.SUBMITTED,),
    AssessmentVersionStatus.SUBMITTED: (
        AssessmentVersionStatus.APPROVED,
        AssessmentVersionStatus.REJECTED,
        AssessmentVersionStatus.DRAFT,
    ),
}


def derive_status(decisions: list[str]) -> str:
    """由追加的决策事件流推导版本当前状态。

    版本表本身不允许 UPDATE，所以状态不是存出来的，而是从最后一次决策推导的：
    没有决策即草稿。
    """
    if not decisions:
        return AssessmentVersionStatus.DRAFT
    last = decisions[-1]
    if last == AssessmentDecision.REQUEST_CHANGES:
        return AssessmentVersionStatus.DRAFT
    if last == AssessmentDecision.APPROVE:
        return AssessmentVersionStatus.APPROVED
    if last == AssessmentDecision.REJECT:
        return AssessmentVersionStatus.REJECTED
    return AssessmentVersionStatus.SUBMITTED


class AssessmentApprovalError(Exception):
    """状态机拒绝的一次非法流转。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AssessmentDecisionRecord:
    version_id: str
    version_number: int
    payload_sha256: str
    decision: str
    reviewer_identity_id: str | None
    comments: str
    open_blockers: tuple[str, ...]
    accepts_insufficient_evidence: bool
    decision_signature: str
    decided_at: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["open_blockers"] = list(self.open_blockers)
        return data


class AssessmentApprovalEngine:
    """评估版本级复核：状态流转、阻塞门禁与决策签名。"""

    @staticmethod
    def can_transit(current: str, target: str) -> bool:
        return target in ALLOWED_TRANSITIONS.get(current, ())

    @staticmethod
    def assert_transition(current: str, target: str) -> None:
        if current in TERMINAL_STATUSES:
            raise AssessmentApprovalError(
                "version_frozen",
                f"评估版本已处于终态 {current}，不可再变更；修订请生成新版本。",
            )
        if not AssessmentApprovalEngine.can_transit(current, target):
            raise AssessmentApprovalError(
                "invalid_transition",
                f"不允许的状态流转：{current} -> {target}",
            )

    @staticmethod
    def generate_decision_signature(
        *,
        version_id: str,
        version_number: int,
        payload_sha256: str,
        decision: str,
        reviewer_identity_id: str | None,
        decided_at: str,
    ) -> str:
        """把复核人、决策与评估包摘要绑在一起。

        摘要取自落库快照的 payload_sha256，因此即便评估包内容日后被重新计算，
        也无法拿同一签名套到不同内容上。
        """
        payload = (
            f"assessment_version:{version_id}|version:{version_number}|"
            f"payload_sha256:{payload_sha256}|decision:{decision}|"
            f"reviewer:{reviewer_identity_id}|timestamp:{decided_at}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def generate_submission_record(
        cls,
        *,
        version_id: str,
        version_number: int,
        payload_sha256: str,
        submitter_identity_id: str | None,
        submitted_at: datetime,
    ) -> AssessmentDecisionRecord:
        """提交动作本身也是一条追加记录，状态由事件流推导。"""
        timestamp = submitted_at.isoformat()
        return AssessmentDecisionRecord(
            version_id=version_id,
            version_number=version_number,
            payload_sha256=payload_sha256,
            decision="submitted",
            reviewer_identity_id=submitter_identity_id,
            comments="",
            open_blockers=(),
            accepts_insufficient_evidence=False,
            decision_signature=cls.generate_decision_signature(
                version_id=version_id,
                version_number=version_number,
                payload_sha256=payload_sha256,
                decision="submitted",
                reviewer_identity_id=submitter_identity_id,
                decided_at=timestamp,
            ),
            decided_at=timestamp,
        )

    @classmethod
    def approve(
        cls,
        *,
        version_id: str,
        version_number: int,
        current_status: str,
        payload_sha256: str,
        blockers: list[str],
        reviewer_identity_id: str | None,
        comments: str = "",
        accepts_insufficient_evidence: bool = False,
        decided_at: datetime | None = None,
    ) -> AssessmentDecisionRecord:
        """批准一个评估版本。

        存在未解决阻塞项时默认拒绝批准——批准一个「禁止输出结论」的版本是自相
        矛盾的。但「证据不足」本身是合法的预评估结论，因此复核人可以显式接受
        （`accepts_insufficient_evidence`），此时必须写明理由，且该接受会被
        记录在决策里。
        """
        cls.assert_transition(current_status, AssessmentVersionStatus.APPROVED)

        open_blockers = [item for item in (blockers or []) if item.strip()]
        if open_blockers and not accepts_insufficient_evidence:
            raise AssessmentApprovalError(
                "blockers_open",
                "该评估版本存在未解决的阻塞项，不得批准："
                + "；".join(open_blockers)
                + "。如确需以「证据不足」作为结论，须显式确认并写明理由。",
            )
        if open_blockers and accepts_insufficient_evidence and not comments.strip():
            raise AssessmentApprovalError(
                "acceptance_reason_required",
                "以「证据不足」结论批准时必须写明理由。",
            )

        timestamp = (decided_at or datetime.now()).isoformat()
        return AssessmentDecisionRecord(
            version_id=version_id,
            version_number=version_number,
            payload_sha256=payload_sha256,
            decision=AssessmentDecision.APPROVE,
            reviewer_identity_id=reviewer_identity_id,
            comments=comments,
            open_blockers=tuple(open_blockers),
            accepts_insufficient_evidence=accepts_insufficient_evidence,
            decision_signature=cls.generate_decision_signature(
                version_id=version_id,
                version_number=version_number,
                payload_sha256=payload_sha256,
                decision=AssessmentDecision.APPROVE,
                reviewer_identity_id=reviewer_identity_id,
                decided_at=timestamp,
            ),
            decided_at=timestamp,
        )

    @classmethod
    def reject(
        cls,
        *,
        version_id: str,
        version_number: int,
        current_status: str,
        payload_sha256: str,
        reviewer_identity_id: str | None,
        comments: str = "",
        decided_at: datetime | None = None,
    ) -> AssessmentDecisionRecord:
        cls.assert_transition(current_status, AssessmentVersionStatus.REJECTED)
        timestamp = (decided_at or datetime.now()).isoformat()
        return AssessmentDecisionRecord(
            version_id=version_id,
            version_number=version_number,
            payload_sha256=payload_sha256,
            decision=AssessmentDecision.REJECT,
            reviewer_identity_id=reviewer_identity_id,
            comments=comments,
            open_blockers=(),
            accepts_insufficient_evidence=False,
            decision_signature=cls.generate_decision_signature(
                version_id=version_id,
                version_number=version_number,
                payload_sha256=payload_sha256,
                decision=AssessmentDecision.REJECT,
                reviewer_identity_id=reviewer_identity_id,
                decided_at=timestamp,
            ),
            decided_at=timestamp,
        )

    @classmethod
    def request_changes(
        cls,
        *,
        version_id: str,
        version_number: int,
        current_status: str,
        payload_sha256: str,
        reviewer_identity_id: str | None,
        comments: str = "",
        decided_at: datetime | None = None,
    ) -> AssessmentDecisionRecord:
        """打回修改：版本回到草稿状态，修订通过生成新版本完成。"""
        cls.assert_transition(current_status, AssessmentVersionStatus.DRAFT)
        timestamp = (decided_at or datetime.now()).isoformat()
        return AssessmentDecisionRecord(
            version_id=version_id,
            version_number=version_number,
            payload_sha256=payload_sha256,
            decision=AssessmentDecision.REQUEST_CHANGES,
            reviewer_identity_id=reviewer_identity_id,
            comments=comments,
            open_blockers=(),
            accepts_insufficient_evidence=False,
            decision_signature=cls.generate_decision_signature(
                version_id=version_id,
                version_number=version_number,
                payload_sha256=payload_sha256,
                decision=AssessmentDecision.REQUEST_CHANGES,
                reviewer_identity_id=reviewer_identity_id,
                decided_at=timestamp,
            ),
            decided_at=timestamp,
        )
