from __future__ import annotations

from typing import Any

from modules.assessment.diff import diff_payloads, diff_packages


def _payload(
    *,
    rules_version: str = "assessment-rules-v3",
    blockers: list[str] | None = None,
    flags: list[str] | None = None,
    findings: list[dict[str, Any]] | None = None,
    evidence: dict[str, Any] | None = None,
    three_step: dict[str, Any] | None = None,
    entity_observations: list[dict[str, Any]] | None = None,
    priority: Any = None,
    prompt_versions: dict[str, str] | None = None,
    requires_human_confirmation: bool = True,
) -> dict[str, Any]:
    return {
        "rules_version": rules_version,
        "reference_kinds": {},
        "priority": priority,
        "entity_observations": entity_observations or [],
        "findings": findings or [],
        "three_step": three_step,
        "motivation": None,
        "auxiliary": {"counted": [], "unsubstantiated": []},
        "hindsight": None,
        "evidence": evidence
        or {
            "source_coverage": 1.0,
            "verified_citations": 2,
            "total_citations": 2,
            "missing_anchors": [],
            "unverified_citations": [],
            "abstract_only_citations": [],
            "failed_sources": [],
            "partial_sources": [],
            "documents_without_legal_status_timepoint": [],
            "blocking_gaps": [],
            "flags": [],
            "blocks_conclusion": False,
            "level": "sufficient",
            "rules_version": rules_version,
        },
        "blockers": blockers or [],
        "flags": flags or [],
        "requires_human_confirmation": requires_human_confirmation,
        "prompt_versions": prompt_versions or {"novelty": "novelty-v2"},
    }


def _finding(reasoning: str, level: str = "high_novelty_risk") -> dict[str, Any]:
    return {
        "risk_kind": "novelty",
        "level": level,
        "basis": [{"doc_id": "D1", "feature_code": "F1"}],
        "requires_human_confirmation": True,
        "reasoning": reasoning,
        "rules_version": "assessment-rules-v3",
    }


def test_identical_payloads_produce_an_empty_diff() -> None:
    payload = _payload(blockers=["引证未定位：D1/F2"], findings=[_finding("D1 单独公开")])
    diff = diff_payloads(payload, dict(payload), from_version=1, to_version=2)

    assert diff.blockers == {"added": [], "removed": [], "retained": ["引证未定位：D1/F2"]}
    assert diff.findings["added"] == []
    assert diff.findings["removed"] == []
    assert diff.findings["retained"]
    assert diff.rules_version_changed is False
    assert diff.evidence["scalars"] == {}
    assert diff.evidence["lists"] == {}


def test_blockers_are_split_into_added_removed_and_retained() -> None:
    older = _payload(blockers=["A", "B"])
    newer = _payload(blockers=["B", "C"])
    diff = diff_payloads(older, newer, from_version=1, to_version=2)

    assert diff.blockers["added"] == ["C"]
    assert diff.blockers["removed"] == ["A"]
    assert diff.blockers["retained"] == ["B"]


def test_removed_blockers_carry_a_note_that_they_are_not_necessarily_resolved() -> None:
    older = _payload(blockers=["引证未定位：D1/F2"])
    newer = _payload(blockers=[])
    diff = diff_payloads(older, newer, from_version=1, to_version=2)

    assert any("不等于「已解决」" in note for note in diff.notes)


def test_diff_never_infers_what_the_input_was() -> None:
    """档案可变且未版本化，diff 必须声明自己不涉及输入变化。"""
    diff = diff_payloads(_payload(), _payload(), from_version=1, to_version=2)
    assert any("不推断输入档案的变化" in note for note in diff.notes)


def test_rules_version_change_is_reported_as_a_caveat_not_a_data_change() -> None:
    older = _payload(rules_version="assessment-rules-v2")
    newer = _payload(rules_version="assessment-rules-v3")
    diff = diff_payloads(older, newer, from_version=1, to_version=2)

    assert diff.rules_version_changed is True
    assert diff.rules_version == {"from": "assessment-rules-v2", "to": "assessment-rules-v3"}
    assert any("差异可能来自规则本身" in note for note in diff.notes)


def test_findings_are_keyed_by_content_not_by_rules_version() -> None:
    older = _payload(findings=[_finding("D1 单独公开")])
    bumped = _finding("D1 单独公开")
    bumped["rules_version"] = "assessment-rules-v4"
    newer = _payload(findings=[bumped], rules_version="assessment-rules-v4")

    diff = diff_payloads(older, newer, from_version=1, to_version=2)
    assert diff.findings["retained"]
    assert diff.findings["added"] == []
    assert diff.findings["removed"] == []


def test_findings_added_and_removed_are_separated() -> None:
    older = _payload(findings=[_finding("D1 单独公开")])
    newer = _payload(
        findings=[
            _finding("D1 单独公开"),
            _finding("D2 与 D3 组合覆盖 F2", level="high_inventive_risk"),
        ]
    )
    diff = diff_payloads(older, newer, from_version=1, to_version=2)

    assert len(diff.findings["added"]) == 1
    assert diff.findings["added"][0]["reasoning"] == "D2 与 D3 组合覆盖 F2"
    assert diff.findings["removed"] == []


def test_evidence_deltas_cover_scalars_and_lists() -> None:
    older = _payload(
        evidence={
            "source_coverage": 0.5,
            "verified_citations": 1,
            "total_citations": 3,
            "missing_anchors": ["D1/F1", "D1/F2"],
            "unverified_citations": [],
            "abstract_only_citations": [],
            "failed_sources": ["CNIPR"],
            "partial_sources": [],
            "documents_without_legal_status_timepoint": [],
            "blocking_gaps": ["引证未定位：D1/F1"],
            "flags": [],
            "blocks_conclusion": True,
            "level": "insufficient",
            "rules_version": "assessment-rules-v3",
        }
    )
    newer = _payload(
        evidence={
            "source_coverage": 1.0,
            "verified_citations": 3,
            "total_citations": 3,
            "missing_anchors": ["D1/F1"],
            "unverified_citations": [],
            "abstract_only_citations": [],
            "failed_sources": [],
            "partial_sources": [],
            "documents_without_legal_status_timepoint": [],
            "blocking_gaps": [],
            "flags": [],
            "blocks_conclusion": False,
            "level": "sufficient",
            "rules_version": "assessment-rules-v3",
        }
    )
    diff = diff_payloads(older, newer, from_version=1, to_version=2)

    assert diff.evidence["scalars"]["source_coverage"] == {"from": 0.5, "to": 1.0}
    assert diff.evidence["scalars"]["blocks_conclusion"] == {"from": True, "to": False}
    assert diff.evidence["scalars"]["level"] == {"from": "insufficient", "to": "sufficient"}
    assert diff.evidence["lists"]["missing_anchors"]["removed"] == ["D1/F2"]
    assert diff.evidence["lists"]["failed_sources"]["removed"] == ["CNIPR"]


def test_three_step_and_entity_observations_are_compared() -> None:
    older = _payload(
        three_step={
            "closest_prior_art": "D1",
            "closest_prior_art_identical": 1,
            "distinguishing_features": ["F2"],
            "actual_technical_problem": "待代理师归纳",
            "rules_version": "assessment-rules-v3",
        },
        entity_observations=[
            {"feature_code": "F1", "doc_id": "D1", "effect": "may_defeat_novelty"}
        ],
    )
    newer = _payload(
        three_step={
            "closest_prior_art": "D2",
            "closest_prior_art_identical": 0,
            "distinguishing_features": ["F2", "F3"],
            "actual_technical_problem": "降低量化误差",
            "rules_version": "assessment-rules-v3",
        },
        entity_observations=[
            {"feature_code": "F1", "doc_id": "D1", "effect": "may_defeat_novelty"},
            {"feature_code": "F3", "doc_id": "D2", "effect": "undetermined"},
        ],
    )
    diff = diff_payloads(older, newer, from_version=1, to_version=2)

    assert diff.three_step["closest_prior_art"] == {"from": "D1", "to": "D2"}
    assert diff.three_step["distinguishing_features"]["added"] == ["F3"]
    assert diff.three_step["actual_technical_problem"]["to"] == "降低量化误差"
    assert len(diff.entity_observations["added"]) == 1
    assert diff.entity_observations["removed"] == []


def test_direction_is_normalised_by_version_number() -> None:
    """调用方不必关心先后：始终按版本号由小到大描述。"""
    older = _payload(blockers=["A"])
    newer = _payload(blockers=["B"])

    forward = diff_payloads(newer, older, from_version=2, to_version=1)
    assert forward.from_version == 1
    assert forward.to_version == 2
    assert forward.blockers["added"] == ["B"]
    assert forward.blockers["removed"] == ["A"]


def test_diff_is_serialisable_and_keeps_its_rules_version() -> None:
    diff = diff_payloads(_payload(), _payload(), from_version=1, to_version=2)
    rendered = diff.to_dict()

    assert rendered["diff_rules_version"] == diff.diff_rules_version
    assert rendered["from_version"] == 1
    assert rendered["to_version"] == 2
    assert rendered["requires_human_confirmation"] is True


def test_diff_packages_accepts_objects_with_to_dict() -> None:
    class Package:
        def to_dict(self) -> dict[str, Any]:
            return _payload(blockers=["A"])

    class Other:
        def to_dict(self) -> dict[str, Any]:
            return _payload(blockers=["B"])

    diff = diff_packages(Package(), Other(), from_version=1, to_version=2)
    assert diff.blockers["added"] == ["B"]
    assert diff.blockers["removed"] == ["A"]


def test_missing_sections_do_not_crash_the_diff() -> None:
    diff = diff_payloads({}, {}, from_version=1, to_version=2)

    assert diff.blockers == {"added": [], "removed": [], "retained": []}
    assert diff.findings["retained"] == []
    assert diff.three_step["present_in_both"] is False
    assert diff.priority_changed is False
