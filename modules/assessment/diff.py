"""两个已冻结评估版本之间的确定性差异对比。

只对比 payload。原因不是省事，而是可信性：两个版本的 payload 都是冻结且带
SHA-256 的字节，可以忠实对比；而生成它们所用的输入档案（本案申请信息、
对比文件日期与来源核验）是**可变且未版本化**的，系统无法重建「生成版本 N
时档案是什么样」。拿今天的档案值去解释昨天的版本差异，就是编造因果。所以
这里不产出任何「输入变化 → 结论变化」的推断，也不声称阻塞项消失的原因。

另一条纪律：差异只陈述事实，不下结论。「某个阻塞项不再出现」不等于「该问题
已解决」——它可能因为数据变化而不再被触发，也可能换了个说法仍在。两条都
留给人工判断，diff 只负责把它指出来。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DIFF_RULES_VERSION = "assessment-diff-v1"


def _finding_key(finding: dict[str, Any]) -> str:
    """候选发现没有稳定 id，用内容本身做键。

    只取判定相关的字段：risk_kind / level / basis / reasoning。
    rules_version 不进键——版本升级时同一条发现仍应算同一条。
    """
    basis = tuple(
        sorted(
            (str(item.get("doc_id", "")), str(item.get("feature_code", "")))
            for item in (finding.get("basis") or [])
        )
    )
    return f"{finding.get('risk_kind', '')}|{finding.get('level', '')}|{basis}|{finding.get('reasoning', '')}"


def _observation_key(observation: dict[str, Any]) -> str:
    return (
        f"{observation.get('feature_code', '')}|"
        f"{observation.get('doc_id', '')}|"
        f"{observation.get('effect', '')}"
    )


def _split_lists(older: list[str], newer: list[str]) -> dict[str, list[str]]:
    old_set = set(older)
    new_set = set(newer)
    return {
        "added": [item for item in newer if item not in old_set],
        "removed": [item for item in older if item not in new_set],
        "retained": [item for item in newer if item in old_set],
    }


def _split_by_key(
    older: list[dict[str, Any]], newer: list[dict[str, Any]], key: Any
) -> dict[str, list[dict[str, Any]]]:
    old_map = {key(item): item for item in older}
    new_map = {key(item): item for item in newer}
    return {
        "added": [item for k, item in new_map.items() if k not in old_map],
        "removed": [item for k, item in old_map.items() if k not in new_map],
        "retained": [item for k, item in new_map.items() if k in old_map],
    }


def _prompt_changes(older: dict[str, Any], newer: dict[str, Any]) -> list[dict[str, str]]:
    keys = sorted(set(older) | set(newer))
    return [
        {"name": key, "from": str(older.get(key, "")), "to": str(newer.get(key, ""))}
        for key in keys
        if str(older.get(key, "")) != str(newer.get(key, ""))
    ]


def _evidence_delta(older: dict[str, Any], newer: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "source_coverage",
        "verified_citations",
        "total_citations",
        "level",
        "blocks_conclusion",
    )
    changes = {
        key: {"from": older.get(key), "to": newer.get(key)}
        for key in keys
        if older.get(key) != newer.get(key)
    }
    lists = (
        "missing_anchors",
        "unverified_citations",
        "abstract_only_citations",
        "failed_sources",
        "partial_sources",
        "blocking_gaps",
    )
    list_changes = {
        key: _split_lists(list(older.get(key) or []), list(newer.get(key) or []))
        for key in lists
        if set(older.get(key) or []) != set(newer.get(key) or [])
    }
    return {"scalars": changes, "lists": list_changes}


def _three_step_delta(older: dict[str, Any] | None, newer: dict[str, Any] | None) -> dict[str, Any]:
    old = older or {}
    new = newer or {}
    return {
        "closest_prior_art": {
            "from": old.get("closest_prior_art"),
            "to": new.get("closest_prior_art"),
        }
        if old.get("closest_prior_art") != new.get("closest_prior_art")
        else None,
        "actual_technical_problem": {
            "from": old.get("actual_technical_problem"),
            "to": new.get("actual_technical_problem"),
        }
        if old.get("actual_technical_problem") != new.get("actual_technical_problem")
        else None,
        "distinguishing_features": _split_lists(
            list(old.get("distinguishing_features") or []),
            list(new.get("distinguishing_features") or []),
        ),
        "present_in_both": bool(older) and bool(newer),
    }


@dataclass(frozen=True)
class AssessmentVersionDiff:
    """两版之间的差异。纯事实，不含因果推断，也不含结论。"""

    from_version: int
    to_version: int
    from_payload_sha256: str
    to_payload_sha256: str
    rules_version: dict[str, str]
    rules_version_changed: bool
    prompt_changes: list[dict[str, str]]
    blockers: dict[str, list[str]]
    flags: dict[str, list[str]]
    findings: dict[str, list[dict[str, Any]]]
    evidence: dict[str, Any]
    three_step: dict[str, Any]
    entity_observations: dict[str, list[dict[str, Any]]]
    priority_changed: bool
    requires_human_confirmation: bool
    diff_rules_version: str = DIFF_RULES_VERSION
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_version": self.from_version,
            "to_version": self.to_version,
            "from_payload_sha256": self.from_payload_sha256,
            "to_payload_sha256": self.to_payload_sha256,
            "rules_version": self.rules_version,
            "rules_version_changed": self.rules_version_changed,
            "prompt_changes": self.prompt_changes,
            "blockers": self.blockers,
            "flags": self.flags,
            "findings": self.findings,
            "evidence": self.evidence,
            "three_step": self.three_step,
            "entity_observations": self.entity_observations,
            "priority_changed": self.priority_changed,
            "requires_human_confirmation": self.requires_human_confirmation,
            "diff_rules_version": self.diff_rules_version,
            "notes": list(self.notes),
        }


def diff_payloads(
    older: dict[str, Any],
    newer: dict[str, Any],
    *,
    from_version: int,
    to_version: int,
    from_payload_sha256: str = "",
    to_payload_sha256: str = "",
) -> AssessmentVersionDiff:
    """对比两个版本的 payload 字典，版本号小的作为基准。

    调用方不需要关心方向：差异始终按版本号由小到大描述。
    """
    if from_version > to_version:
        older, newer = newer, older
        from_version, to_version = to_version, from_version
        from_payload_sha256, to_payload_sha256 = to_payload_sha256, from_payload_sha256

    rules_from = str(older.get("rules_version", ""))
    rules_to = str(newer.get("rules_version", ""))
    rules_changed = rules_from != rules_to

    notes: list[str] = []
    if rules_changed:
        # 差异可能来自规则本身而非数据，必须说清，否则会被当成证据变化
        notes.append(
            f"两版规则版本不同（{rules_from or '—'} → {rules_to or '—'}），"
            "差异可能来自规则本身，而非案件数据变化"
        )
    notes.append(
        "本对比只涉及两个已冻结版本的内容，不推断输入档案的变化："
        "档案可变且未版本化，无法忠实重建生成各版本时的输入"
    )

    blockers = _split_lists(list(older.get("blockers") or []), list(newer.get("blockers") or []))
    if blockers["removed"]:
        notes.append(
            "「不再出现」不等于「已解决」：该阻塞项可能因数据变化而不再被触发，"
            "也可能换了表述仍然存在，须人工核对"
        )

    findings = _split_by_key(
        list(older.get("findings") or []), list(newer.get("findings") or []), _finding_key
    )
    observations = _split_by_key(
        list(older.get("entity_observations") or []),
        list(newer.get("entity_observations") or []),
        _observation_key,
    )

    return AssessmentVersionDiff(
        from_version=from_version,
        to_version=to_version,
        from_payload_sha256=from_payload_sha256,
        to_payload_sha256=to_payload_sha256,
        rules_version={"from": rules_from, "to": rules_to},
        rules_version_changed=rules_changed,
        prompt_changes=_prompt_changes(
            dict(older.get("prompt_versions") or {}), dict(newer.get("prompt_versions") or {})
        ),
        blockers=blockers,
        flags=_split_lists(list(older.get("flags") or []), list(newer.get("flags") or [])),
        findings=findings,
        evidence=_evidence_delta(
            dict(older.get("evidence") or {}), dict(newer.get("evidence") or {})
        ),
        three_step=_three_step_delta(older.get("three_step"), newer.get("three_step")),
        entity_observations=observations,
        priority_changed=(older.get("priority") or None) != (newer.get("priority") or None),
        requires_human_confirmation=bool(
            older.get("requires_human_confirmation", True)
            or newer.get("requires_human_confirmation", True)
        ),
        notes=notes,
    )


def diff_packages(
    older: Any,
    newer: Any,
    *,
    from_version: int,
    to_version: int,
    from_payload_sha256: str = "",
    to_payload_sha256: str = "",
) -> AssessmentVersionDiff:
    """`AssessmentPackage` 便捷入口。"""
    return diff_payloads(
        older.to_dict() if hasattr(older, "to_dict") else dict(older),
        newer.to_dict() if hasattr(newer, "to_dict") else dict(newer),
        from_version=from_version,
        to_version=to_version,
        from_payload_sha256=from_payload_sha256,
        to_payload_sha256=to_payload_sha256,
    )
