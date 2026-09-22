"""Unit tests for the printable HTML deliverable renderer."""

from __future__ import annotations

from modules.assessment.deliverable import build_assessment_deliverable
from modules.assessment.deliverable_html import render_deliverable_html
from modules.reports.conclusion import ConclusionEligibility

# 只禁肯定式措辞；「不构成…授权前景意见」这类否定式声明是必需的，不能被误伤。
BANNED_PHRASES = ["良好授权前景", "创新高度", "全案风险评级"]


def _deliverable(**overrides):
    base = {
        "deliverable_version": "assessment-deliverable-v1",
        "version_number": 3,
        "rules_version": "rules-2026-09",
        "prompt_versions": {"assessment": "v1"},
        "payload_sha256": "ab" * 32,
        "status": "submitted",
        "status_label": "已提交复核",
        "status_caveat": "复核状态仅表示本候选评估包是否通过内部复核。",
        "requires_human_confirmation": True,
        "candidate_notice": "本预评估意见全部内容为候选信号，须人工确认，不构成专利性结论。",
        "blockers": ["引证未定位：D1/F2"],
        "flags": ["priority_unverified"],
        "evidence": {
            "source_coverage": "partial",
            "verified_citations": 1,
            "total_citations": 3,
            "missing_anchors": 2,
            "unverified_citations": 1,
            "failed_sources": 0,
            "blocks_conclusion": True,
        },
        "three_step": {
            "closest_prior_art": "D1",
            "closest_prior_art_identical": 2,
            "distinguishing_features": ["F3"],
            "actual_technical_problem": None,
            "note": "三步法脚手架为待代理师填写的部分，照实留空，非结论。",
        },
        "findings": [
            {
                "risk_kind": "novelty",
                "level": "high",
                "basis": ["D1 公开了 F1"],
                "requires_human_confirmation": True,
            }
        ],
        "entity_observations": [
            {
                "kind": "novelty",
                "feature_code": "F1",
                "doc_id": "D1",
                "effect": "identical",
                "reasoning": "D1 第[0009]段逐字公开",
                "requires_human_confirmation": True,
            }
        ],
        "eligibility": ConclusionEligibility(
            eligible=False,
            reasons=("存在未解决阻塞项",),
            version_number=3,
            payload_sha256="ab" * 32,
        ).to_dict(),
        "publication_disclaimer": "本文件不构成专利性结论或授权前景意见。",
        "version_freeze_declaration": "本意见基于冻结的预评估版本 v3 生成。",
        "generated_at": "2026-09-22T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_html_always_carries_candidate_wording_and_disclaimers() -> None:
    html = render_deliverable_html(_deliverable())

    assert "候选" in html
    assert "不构成专利性结论" in html
    assert "须人工确认" in html
    assert "冻结" in html
    assert "不允许发布候选判断" in html
    # 交付物绝不携带肯定式结论措辞
    for phrase in BANNED_PHRASES:
        assert phrase not in html


def test_html_escapes_all_dynamic_content() -> None:
    payload = _deliverable(
        blockers=['<script>alert("x")</script>'],
        findings=[
            {
                "risk_kind": "<img src=x onerror=alert(1)>",
                "level": "high",
                "basis": ["<b>bold</b>"],
                "requires_human_confirmation": True,
            }
        ],
        entity_observations=[
            {
                "kind": "novelty",
                "feature_code": "F1",
                "doc_id": "D1",
                "effect": '"><script>alert(2)</script>',
                "reasoning": None,
                "requires_human_confirmation": True,
            }
        ],
    )
    html = render_deliverable_html(payload)

    assert "<script>" not in html
    assert "<img" not in html
    assert "<b>bold</b>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img" in html


def test_html_renders_gate_allowed_when_eligible() -> None:
    eligible = ConclusionEligibility(
        eligible=True,
        reasons=("已批准且无阻塞项",),
        version_number=3,
        payload_sha256="ab" * 32,
    ).to_dict()
    html = render_deliverable_html(_deliverable(eligibility=eligible, blockers=[]))

    assert "允许发布候选判断" in html
    # 即使门禁通过，候选与人工确认措辞仍必须在场
    assert "候选" in html
    assert "须人工确认" in html
    for phrase in BANNED_PHRASES:
        assert phrase not in html


def test_html_renders_empty_sections_honestly() -> None:
    html = render_deliverable_html(
        _deliverable(blockers=[], flags=[], findings=[], entity_observations=[])
    )

    # 无内容时不渲染对应表格/列表，但脚手架与免责声明仍在
    assert "候选发现（须人工确认）" not in html
    assert "尚未解决的阻塞项" not in html
    assert "三步法脚手架" in html
    assert "不构成专利性结论" in html


def test_html_builds_from_real_build_assessment_deliverable() -> None:
    """与真实 deliverable dict 的端到端契合：build → render 不抛错且关键措辞在场。"""
    from datetime import datetime, timezone
    from uuid import uuid4

    from modules.assessment.records import AssessmentVersionRecord

    record = AssessmentVersionRecord(
        id=uuid4(),
        organization_id=uuid4(),
        case_id=uuid4(),
        version_number=1,
        payload={
            "evidence": {"source_coverage": "full", "verified_citations": 2, "total_citations": 2},
            "three_step": {"closest_prior_art": "D1"},
            "findings": [],
            "entity_observations": [],
        },
        payload_sha256="cd" * 32,
        rules_version="rules-2026-09",
        prompt_versions={"assessment": "v1"},
        blockers=[],
        flags=[],
        requires_human_confirmation=True,
        created_by_identity_id=None,
        created_at=datetime.now(timezone.utc),
    )
    deliverable = build_assessment_deliverable(record, "approved")
    html = render_deliverable_html(deliverable)

    assert "v1" in html
    assert "候选" in html
    for phrase in BANNED_PHRASES:
        assert phrase not in html
