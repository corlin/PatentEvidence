"""报告侧结论门禁：未通过门禁时，报告不得输出任何倾向性判断。"""

from __future__ import annotations

from typing import Any

from modules.reports.conclusion import (
    CONCLUSION_GATE_VERSION,
    AssessmentSummary,
    evaluate_conclusion_eligibility,
)
from modules.reports.generator import MarkdownReportGenerator


def _snapshot(comparison: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "case": {"case_number": "C-1", "title": "t", "technical_field": "f"},
        "document": {"filename": "d.pdf", "version_number": 1, "file_sha256": "abc"},
        "features": {"items": []},
        "search": {"boolean_query_cnipr": "q"},
        "candidates": [],
        "comparison": comparison
        or {
            "risk_level": "clear_difference",
            "summary": "【候选提示·未发现全覆盖的对比文件】：按当前矩阵计数，存在差异。",
            "comparisons": [],
        },
        "sealed_at": "2026-09-22T00:00:00+00:00",
        "sealed_by": "agent@example.com",
    }


def _approved_no_blockers() -> dict[str, Any]:
    return {
        "has_version": True,
        "version_number": 3,
        "status": "approved",
        "blockers": [],
        "payload_sha256": "deadbeef",
    }


# 只禁肯定式措辞。"不构成…授权前景意见" 这类否定式声明是必需的，不能被禁词误伤。
BANNED_PHRASES = ["良好授权前景", "创新高度", "全案风险评级"]


def test_no_assessment_version_refuses_to_publish() -> None:
    result = evaluate_conclusion_eligibility(None)
    assert result.eligible is False
    assert any("尚无预评估版本" in r for r in result.reasons)


def test_unapproved_version_refuses_to_publish() -> None:
    for status in ("draft", "submitted", "rejected", "changes_requested"):
        result = evaluate_conclusion_eligibility(
            {"has_version": True, "version_number": 1, "status": status, "blockers": []}
        )
        assert result.eligible is False, status
        assert any("复核" in r for r in result.reasons)


def test_approved_version_with_blockers_refuses_to_publish() -> None:
    result = evaluate_conclusion_eligibility(
        {
            "has_version": True,
            "version_number": 2,
            "status": "approved",
            "blockers": ["引文未核验", "对比文件缺申请日"],
        }
    )
    assert result.eligible is False
    assert any("2 项未解决的阻塞项" in r for r in result.reasons)
    # 必须说清「有阻塞项 ⇒ 该版本不能给出结论」
    assert any("不能给出结论" in r for r in result.reasons)


def test_approved_version_without_blockers_publishes_candidate_only() -> None:
    result = evaluate_conclusion_eligibility(_approved_no_blockers())
    assert result.eligible is True
    assert result.version_number == 3
    assert result.gate_version == CONCLUSION_GATE_VERSION
    # 允许发布候选判断 ≠ 具备专利性，这句话必须在理由里
    assert any("不等于具备专利性" in r for r in result.reasons)


def test_missing_facts_resolve_to_refusal_not_permission() -> None:
    """任何缺失事实都必须落到拒绝，而不是乐观默认值。"""
    for payload in ({}, {"has_version": True}, {"has_version": True, "version_number": 1}):
        assert evaluate_conclusion_eligibility(payload).eligible is False


def test_summary_from_mapping_normalises_blockers() -> None:
    summary = AssessmentSummary.from_mapping(
        {"version_number": 5, "status": "approved", "blockers": ["a", "b"]}
    )
    assert summary.has_version is True
    assert summary.blockers == ("a", "b")
    assert AssessmentSummary.from_mapping(None).has_version is False


def test_report_without_assessment_renders_no_tendency() -> None:
    """旧快照没有 assessment 段 —— 门禁必须拒绝，而不是按老样子输出结论。"""
    content = MarkdownReportGenerator().generate(_snapshot(), "sha")
    assert "本节不输出任何倾向性判断" in content
    assert "尚无预评估版本" in content
    for phrase in BANNED_PHRASES:
        assert phrase not in content


def test_report_refuses_when_version_not_approved() -> None:
    snapshot = _snapshot()
    snapshot["assessment"] = {
        "has_version": True,
        "version_number": 1,
        "status": "submitted",
        "blockers": [],
    }
    content = MarkdownReportGenerator().generate(snapshot, "sha")
    assert "本节不输出任何倾向性判断" in content
    assert "尚未通过内部复核" in content
    assert "候选提示" not in content


def test_report_refuses_when_approved_version_has_blockers() -> None:
    snapshot = _snapshot()
    snapshot["assessment"] = {
        "has_version": True,
        "version_number": 2,
        "status": "approved",
        "blockers": ["引文未核验：D1/F2"],
    }
    content = MarkdownReportGenerator().generate(snapshot, "sha")
    assert "本节不输出任何倾向性判断" in content
    assert "引文未核验：D1/F2" in content
    assert "未发现全覆盖的对比文件" not in content


def test_report_publishes_candidate_with_qualifier_when_gate_passes() -> None:
    snapshot = _snapshot()
    snapshot["assessment"] = _approved_no_blockers()
    content = MarkdownReportGenerator().generate(snapshot, "sha")

    assert "候选判断" in content
    assert "未发现全覆盖的对比文件" in content
    # 即便门禁通过，限定语与版本号也必须同行出现
    assert "不构成专利性结论或授权前景意见" in content
    assert "v3" in content
    assert CONCLUSION_GATE_VERSION in content
    for phrase in BANNED_PHRASES:
        assert phrase not in content


def test_report_never_uses_the_checkmark_badge() -> None:
    """✓ 在报告里等于「没问题」，会盖过候选性质。三档都必须给出候选措辞。"""
    for level in ("high_novelty_risk", "inventiveness_risk", "clear_difference"):
        snapshot = _snapshot(
            {"risk_level": level, "summary": "计数结果", "comparisons": []}
        )
        snapshot["assessment"] = _approved_no_blockers()
        content = MarkdownReportGenerator().generate(snapshot, "sha")
        assert "✓" not in content
        assert "候选提示" in content
