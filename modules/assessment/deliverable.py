"""Standalone, exportable pre-assessment deliverable.

A deliverable is a self-contained, client-facing *candidate* reading built from a
single frozen assessment version. It never becomes a conclusion: it carries the
human-confirmation flag, the publication disclaimer, the version-freeze
declaration and the same conclusion-eligibility gate used by the report's
section 5.

Whether the candidate reading may be published is decided by
``evaluate_conclusion_eligibility`` — reused from the report gate — and surfaced
explicitly, so the caller cannot quietly treat the deliverable as an opinion. The
deliverable is deterministic; it performs no model calls and invents no causal
link between inputs and conclusions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from modules.assessment.records import AssessmentVersionRecord
from modules.reports.conclusion import (
    PUBLICATION_DISCLAIMER,
    STATUS_LABELS,
    ConclusionEligibility,
    evaluate_conclusion_eligibility,
)

DELIVERABLE_VERSION = "assessment-deliverable-v1"

CANDIDATE_NOTICE = (
    "本预评估意见全部内容为候选信号，须人工确认，不构成专利性结论或审查/授权前景意见。"
)

STATUS_CAVEAT = (
    "复核状态仅表示本候选评估包是否通过内部复核，不代表该方案具备专利性或可授权。"
)

VERSION_FREEZE_TEMPLATE = (
    "本意见基于冻结的预评估版本 v{version}（内容摘要 {sha256}）生成于 {generated_at}。"
    "该版本此后若发生修订将产生新的版本号，本意见不随之更新；"
    "如需引用最新版本，须重新生成本意见。"
)


def _status_label(status: str | None) -> str:
    return STATUS_LABELS.get(status or "", status or "未知")


def build_assessment_deliverable(
    record: AssessmentVersionRecord,
    status: str,
    eligibility: ConclusionEligibility | None = None,
) -> dict[str, Any]:
    """从单个冻结版本构建自包含、可导出的候选意见交付物。

    永远不产出结论：携带 requires_human_confirmation、发布免责声明、版本冻结声明，
    以及复用 report 结论门禁的 eligibility（明确「是否允许发布候选判断」）。
    """
    payload = record.payload or {}
    evidence = payload.get("evidence") or {}
    scaffold = payload.get("three_step") or {}
    findings = payload.get("findings") or []
    entity_observations = payload.get("entity_observations") or []

    if eligibility is None:
        eligibility = evaluate_conclusion_eligibility(
            {
                "has_version": True,
                "version_number": record.version_number,
                "status": status,
                "blockers": list(record.blockers),
                "payload_sha256": record.payload_sha256,
            }
        )

    generated_at = datetime.now(timezone.utc).isoformat()

    return {
        "deliverable_version": DELIVERABLE_VERSION,
        "version_number": record.version_number,
        "rules_version": record.rules_version,
        "prompt_versions": dict(record.prompt_versions),
        "payload_sha256": record.payload_sha256,
        "status": status,
        "status_label": _status_label(status),
        "status_caveat": STATUS_CAVEAT,
        "requires_human_confirmation": bool(record.requires_human_confirmation),
        "candidate_notice": CANDIDATE_NOTICE,
        "blockers": list(record.blockers),
        "flags": list(record.flags),
        "evidence": {
            "source_coverage": evidence.get("source_coverage", "N/A"),
            "verified_citations": evidence.get("verified_citations", 0),
            "total_citations": evidence.get("total_citations", 0),
            "missing_anchors": len(evidence.get("missing_anchors") or []),
            "unverified_citations": len(evidence.get("unverified_citations") or []),
            "failed_sources": len(evidence.get("failed_sources") or []),
            "blocks_conclusion": bool(evidence.get("blocks_conclusion")),
        },
        "three_step": {
            "closest_prior_art": scaffold.get("closest_prior_art"),
            "closest_prior_art_identical": scaffold.get("closest_prior_art_identical", 0),
            "distinguishing_features": scaffold.get("distinguishing_features") or [],
            "actual_technical_problem": scaffold.get("actual_technical_problem"),
            "note": "三步法脚手架为待代理师填写的部分，照实留空，非结论。",
        },
        "findings": [
            {
                "risk_kind": finding.get("risk_kind"),
                "level": finding.get("level"),
                "basis": finding.get("basis") or [],
                "requires_human_confirmation": bool(
                    finding.get("requires_human_confirmation", True)
                ),
            }
            for finding in findings
        ],
        "entity_observations": [
            {
                "kind": obs.get("kind"),
                "feature_code": obs.get("feature_code"),
                "doc_id": obs.get("doc_id"),
                "effect": obs.get("effect"),
                "reasoning": obs.get("reasoning"),
                "requires_human_confirmation": True,
            }
            for obs in entity_observations
        ],
        "eligibility": eligibility.to_dict(),
        "publication_disclaimer": PUBLICATION_DISCLAIMER,
        "version_freeze_declaration": VERSION_FREEZE_TEMPLATE.format(
            version=record.version_number,
            sha256=record.payload_sha256,
            generated_at=generated_at,
        ),
        "generated_at": generated_at,
    }
