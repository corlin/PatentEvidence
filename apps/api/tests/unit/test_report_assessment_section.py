"""报告新增的预评估节：渲染封存时刻的最新版本，照实记录，不升级成结论。"""

from __future__ import annotations

from typing import Any

from modules.reports.generator import MarkdownReportGenerator
from modules.reports.sealer import EvidenceSealer

SEALED_AT = "2026-09-22T09:00:00+00:00"


def _assessment(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "has_version": True,
        "version_number": 3,
        "status": "approved",
        "blockers": ["引文未核验：D1/F2"],
        "flags": [],
        "payload_sha256": "deadbeef",
        "rules_version": "assessment-rules-v3",
        "prompt_versions": {"assessment/novelty": "novelty-v2"},
        "created_at": "2026-09-22T08:00:00+00:00",
        "payload": {
            "rules_version": "assessment-rules-v3",
            "prompt_versions": {"assessment/novelty": "novelty-v2"},
            "evidence": {
                "source_coverage": 0.8,
                "verified_citations": 4,
                "total_citations": 7,
                "missing_anchors": ["F2/D1"],
                "unverified_citations": ["c1", "c2", "c3"],
                "failed_sources": ["CNIPR"],
                "blocks_conclusion": True,
            },
            "three_step": {
                "closest_prior_art": "D1",
                "closest_prior_art_identical": 2,
                "distinguishing_features": ["F3", "F4"],
                "actual_technical_problem": "",
            },
            "findings": [
                {
                    "risk_kind": "novelty",
                    "level": "high_novelty_risk",
                    "basis": [{"doc": "D1", "feature": "F1"}],
                    "requires_human_confirmation": True,
                }
            ],
        },
    }
    base.update(overrides)
    return base


def _snapshot(assessment: dict[str, Any] | None) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "case": {"case_number": "C-1", "title": "t", "technical_field": "f"},
        "document": {"filename": "d.pdf", "version_number": 1, "file_sha256": "abc"},
        "features": {"items": []},
        "search": {"boolean_query_cnipr": "q"},
        "candidates": [],
        "comparison": {
            "risk_level": "clear_difference",
            "summary": "【候选提示·未发现全覆盖的对比文件】：存在差异。",
            "comparisons": [],
        },
        "sealed_at": SEALED_AT,
        "sealed_by": "agent@example.com",
    }
    if assessment is not None:
        snapshot["assessment"] = assessment
    return snapshot


def _render(assessment: dict[str, Any] | None) -> str:
    return MarkdownReportGenerator().generate(_snapshot(assessment), "ROOT")


def test_section_renders_version_status_and_hashes() -> None:
    content = _render(_assessment())
    assert "## 5. 预评估门禁与候选发现" in content
    assert "v3" in content
    assert "deadbeef" in content
    assert "assessment-rules-v3" in content
    assert "novelty-v2" in content
    assert "复核通过" in content


def test_candidate_findings_are_marked_as_requiring_confirmation() -> None:
    """候选发现被列进客户交付物，最容易被读成『系统已经认定』。"""
    content = _render(_assessment())
    assert "须人工确认" in content
    assert "候选发现（逐条须人工确认）" in content
    assert "不构成专利性结论或审查意见" in content
    # 层级本身也必须带候选字样
    assert "新颖性高风险（候选）" in content
    for phrase in ["认定存在", "结论为", "已经确定", "必然"]:
        assert phrase not in content


def test_version_freeze_notice_is_part_of_the_report() -> None:
    """报告不可变而评估版本可继续追加——这一条必须写在报告里，不能只写在文档里。"""
    content = _render(_assessment())
    assert "版本冻结声明" in content
    assert SEALED_AT in content
    assert "新的版本号" in content
    assert "本报告不随之更新" in content


def test_unapproved_version_is_reported_not_hidden() -> None:
    content = _render(_assessment(status="submitted"))
    assert "待复核" in content
    # 没通过复核就照实写，不省略整节
    assert "## 5. 预评估门禁与候选发现" in content
    assert "v3" in content


def test_no_blockers_state_does_not_read_as_clearance() -> None:
    assessment = _assessment(blockers=[])
    assessment["payload"]["evidence"]["blocks_conclusion"] = False
    content = _render(assessment)
    assert "未发现阻塞项" in content
    assert "不等于" in content
    assert "结论成立" in content
    assert "因此该版本不能给出结论" not in content


def test_missing_assessment_version_renders_no_findings() -> None:
    """没有评估版本就写没有，不编造发现列表。"""
    content = _render(None)
    assert "本案尚无预评估版本" in content
    assert "候选发现" in content  # 小标题仍在，但内容为无
    assert "无候选发现" not in content
    assert "引文未核验" not in content


def test_three_step_placeholder_is_left_blank() -> None:
    content = _render(_assessment())
    # 实际解决的技术问题由代理师填写，脚手架里是空的，报告不得替他编
    assert "N/A" in content
    assert "待代理师填写" in content or "N/A" in content


def test_section_numbering_stays_sequential() -> None:
    content = _render(_assessment())
    assert content.index("## 5. 预评估门禁与候选发现") < content.index(
        "## 6. 专利性与法律风险论证"
    )
    assert content.index("## 6. 专利性与法律风险论证") < content.index(
        "## 7. 证据链防伪验真与审计溯源声明"
    )


def test_blocked_version_makes_section_six_refuse_too() -> None:
    """同一份报告里两节必须口径一致：有阻塞项 ⇒ 第 6 节也不给倾向性判断。"""
    content = _render(_assessment())
    assert "未解决的阻塞项（因此该版本不能给出结论）" in content
    assert "本节不输出任何倾向性判断" in content


def test_sealed_payload_binds_the_rendered_content() -> None:
    """报告渲染的每个字段都必须被根哈希绑住，否则哈希证明不了报告里写的东西。"""
    common = {
        "case_data": {"id": "1", "case_number": "C", "title": "t", "technical_field": "f"},
        "doc_data": {"id": "2", "version_number": 1, "filename": "d", "file_sha256": "s"},
        "features_data": {"version_id": "3", "items": []},
        "search_data": {"strategy_id": "4"},
        "candidates_data": [],
        "comparison_data": {"matrix_id": "5"},
        "sealed_at_iso": SEALED_AT,
        "sealed_by_email": "a@b.c",
    }
    sealer = EvidenceSealer()
    _, sha_one = sealer.seal(assessment_data=_assessment(), **common)
    changed = _assessment(blockers=["完全不同的阻塞项"])
    _, sha_two = sealer.seal(assessment_data=changed, **common)

    assert sha_one != sha_two
    payload_one, _ = sealer.seal(assessment_data=_assessment(), **common)
    assert payload_one["assessment"]["payload"]["three_step"]["closest_prior_art"] == "D1"
    assert payload_one["assessment"]["version_number"] == 3
