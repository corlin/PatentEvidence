"""从 AssessmentInput 派生可冻结的输入档案快照。

版本在创建时就把输入档案（本案申请信息 + 各对比文件日期与来源核验）冻结进
`assessment_input_snapshots`，使版本 diff 能对照输入变化做归因，而不必回读可变且
会随时间改变的实时档案表。

注意范围：这里只派生「驱动评估的两类输入档案」——本案申请信息与对比文件档案。
比对单元格、引文、检索运行不在这里复制：前者属于比对矩阵（自身有确认/冻结语义），
后两者属于检索作业，各有自己的不可变边界。

快照必须只依赖 `AssessmentInput` 本身，不能回查数据库：两条创建路径（直接提交与
从案件组装）最终都汇聚到 `create_version(payload)`，从 payload 派生能保证快照与
「真正被用来跑评估的输入」逐字一致，不会和档案表在某个时点的取值产生偏差。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from modules.assessment.package import AssessmentInput
from modules.assessment.rules import PriorityClaim


def _iso(value: Any) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    return None


def _priority_claim_to_dict(claim: PriorityClaim) -> dict[str, Any]:
    return {
        "claim_id": claim.claim_id,
        "priority_date": _iso(claim.priority_date),
        "country": claim.country,
        "first_application": bool(claim.first_application),
        "same_subject": bool(claim.same_subject),
        "proof_verified": bool(claim.proof_verified),
        "covers": sorted(claim.covers),
    }


def input_profile_snapshot(input: AssessmentInput) -> dict[str, Any]:
    """派生一份与版本绑定的输入档案快照（JSON 友好字典）。"""
    subject = input.subject
    application_profile = {
        "filing_date": _iso(subject.filing_date),
        "application_type": subject.application_type,
        "priority_claims": [
            _priority_claim_to_dict(claim) for claim in (subject.priority_claims or ())
        ],
    }
    candidate_profiles = [
        {
            "publication_number": doc.publication_number,
            "filing_date": _iso(doc.filing_date),
            "priority_date": _iso(doc.priority_date),
            "filed_in_china": bool(doc.filed_in_china),
            "source_verified": bool(doc.source_verified),
        }
        for doc in input.documents
    ]
    return {
        "application_profile": application_profile,
        "candidate_profiles": candidate_profiles,
    }
