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


def _pc_key(claim: dict[str, Any]) -> str:
    return f"{claim.get('claim_id')}|{claim.get('priority_date')}|{claim.get('country')}"


def _diff_inputs(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """对比两份输入快照，只陈述事实，不做输入→结论的因果推断。"""
    appl_a = a.get("application_profile") or {}
    appl_b = b.get("application_profile") or {}

    appl_fields = ("filing_date", "application_type")
    changed_fields = [
        {"field": f, "from": appl_a.get(f), "to": appl_b.get(f)}
        for f in appl_fields
        if appl_a.get(f) != appl_b.get(f)
    ]
    priority_a = [_pc_key(c) for c in (appl_a.get("priority_claims") or [])]
    priority_b = [_pc_key(c) for c in (appl_b.get("priority_claims") or [])]
    priority_claims = _split_lists(priority_a, priority_b)

    cand_a = {c.get("publication_number"): c for c in (a.get("candidate_profiles") or [])}
    cand_b = {c.get("publication_number"): c for c in (b.get("candidate_profiles") or [])}

    added = [cn for cn in cand_b if cn not in cand_a]
    removed = [cn for cn in cand_a if cn not in cand_b]
    changed = []
    for cn in cand_b:
        if cn in cand_a:
            field_deltas = []
            for f in ("filing_date", "priority_date", "filed_in_china", "source_verified"):
                if cand_a[cn].get(f) != cand_b[cn].get(f):
                    field_deltas.append({"field": f, "from": cand_a[cn].get(f), "to": cand_b[cn].get(f)})
            if field_deltas:
                changed.append({"publication_number": cn, "changed_fields": field_deltas})

    return {
        "application_profile": {
            "changed_fields": changed_fields,
            "priority_claims": priority_claims,
        },
        "candidate_profiles": {
            "added": added,
            "removed": removed,
            "changed": changed,
        },
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
    inputs: dict[str, Any] | None = None
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
            "inputs": self.inputs,
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
    input_a: dict[str, Any] | None = None,
    input_b: dict[str, Any] | None = None,
) -> AssessmentVersionDiff:
    """对比两个版本的 payload 字典，版本号小的作为基准。

    调用方不需要关心方向：差异始终按版本号由小到大描述。可选的 input_a/input_b
    是两个版本冻结时的输入档案快照；两者都提供时，diff 会展示「输入改了什么」，
    但**不做输入→结论的因果推断**；任一缺失时 inputs 为 None 并明确说明无法归因。
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

    if input_a is not None and input_b is not None:
        inputs = _diff_inputs(input_a, input_b)
        # 只陈述「输入改了什么」，绝不声称「因此结论改了」：是否相关须人工核对。
        notes.append(
            "两版均已保存输入快照，下列「输入变化」可能与结论变化相关，"
            "但本工具不做自动因果判断，是否由输入变化导致须人工核对"
        )
    else:
        inputs = None
        notes.append(
            "输入快照未参与本次对比，不对照、不推断输入档案的变化"
            "（无法做输入→结论的归因）"
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
        inputs=inputs,
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
    input_a: dict[str, Any] | None = None,
    input_b: dict[str, Any] | None = None,
) -> AssessmentVersionDiff:
    """`AssessmentPackage` 便捷入口。"""
    return diff_payloads(
        older.to_dict() if hasattr(older, "to_dict") else dict(older),
        newer.to_dict() if hasattr(newer, "to_dict") else dict(newer),
        from_version=from_version,
        to_version=to_version,
        from_payload_sha256=from_payload_sha256,
        to_payload_sha256=to_payload_sha256,
        input_a=input_a,
        input_b=input_b,
    )
