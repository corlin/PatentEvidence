"""Immutable pre-assessment version records.

`assess_case` produces a candidate package; this module freezes one into an
append-only version record. The record carries the rules version, the prompt
versions and a SHA-256 over the normalised payload, so a later approval or
report binding can point at a byte-stable snapshot rather than at whatever the
rules happen to produce today.

Immutability is deliberate: there is no update path. A revised assessment is a
new version number, never a rewrite of an existing row.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from modules.assessment.package import AssessmentPackage


def _canonical(value: Any) -> Any:
    """递归规范化，保证同一内容得到同一字节序列。"""
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def canonical_payload_json(payload: dict[str, Any]) -> str:
    return json.dumps(_canonical(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def assessment_payload_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_payload_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AssessmentVersionRecord:
    """一行 assessment_versions 的不可变内容。"""

    id: UUID
    organization_id: UUID
    case_id: UUID
    version_number: int
    rules_version: str
    prompt_versions: dict[str, str]
    payload: dict[str, Any]
    payload_sha256: str
    blockers: list[str]
    flags: list[str]
    requires_human_confirmation: bool
    created_by_identity_id: UUID | None
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["id"] = str(self.id)
        data["organization_id"] = str(self.organization_id)
        data["case_id"] = str(self.case_id)
        data["created_by_identity_id"] = (
            str(self.created_by_identity_id) if self.created_by_identity_id else None
        )
        data["created_at"] = self.created_at.isoformat()
        return data


def build_assessment_version_record(
    package: AssessmentPackage,
    *,
    record_id: UUID,
    organization_id: UUID,
    case_id: UUID,
    version_number: int,
    created_by_identity_id: UUID | None = None,
    created_at: datetime | None = None,
) -> AssessmentVersionRecord:
    """把评估包冻结成版本记录。

    记录里不带任何专利性结论——只有候选 findings、阻塞项与提示项。
    """
    payload = package.to_dict()
    return AssessmentVersionRecord(
        id=record_id,
        organization_id=organization_id,
        case_id=case_id,
        version_number=version_number,
        rules_version=package.rules_version,
        prompt_versions=dict(package.prompt_versions),
        payload=payload,
        payload_sha256=assessment_payload_sha256(payload),
        blockers=list(package.blockers),
        flags=list(package.flags),
        requires_human_confirmation=package.requires_human_confirmation,
        created_by_identity_id=created_by_identity_id,
        created_at=created_at or datetime.now(timezone.utc),
    )
