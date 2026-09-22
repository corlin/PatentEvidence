"""Printable HTML rendering for the standalone pre-assessment deliverable.

Renders the structured deliverable dict (see ``modules.assessment.deliverable``)
into a self-contained, print-friendly HTML document a patent agency can save or
send to a client. Pure and deterministic: no model calls, no network, no I/O.

Discipline (same as the JSON deliverable):
- every dynamic value is HTML-escaped;
- the candidate notice, human-confirmation flag, publication disclaimer and the
  version-freeze declaration are always rendered;
- the document never states a patentability conclusion — it only carries the
  conclusion-eligibility gate result ("是否允许发布候选判断").
"""

from __future__ import annotations

from html import escape
from typing import Any

RISK_KIND_LABELS = {
    "novelty": "新颖性",
    "inventiveness": "创造性",
    "priority": "优先权",
    "evidence": "证据",
    "formality": "形式",
}

LEVEL_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "info": "提示",
}


def _e(value: Any) -> str:
    """Escape any dynamic value for HTML; None becomes an em dash."""
    if value is None:
        return "—"
    return escape(str(value))


def _label(mapping: dict[str, str], key: Any) -> str:
    if key is None:
        return "—"
    return escape(mapping.get(str(key), str(key)))


def _bool_label(value: Any) -> str:
    return "是" if value else "否"


def render_deliverable_html(deliverable: dict[str, Any]) -> str:
    """把交付物 dict 渲染成自包含的可打印 HTML（候选措辞，非结论）。"""
    eligibility = deliverable.get("eligibility") or {}
    evidence = deliverable.get("evidence") or {}
    three_step = deliverable.get("three_step") or {}
    blockers = deliverable.get("blockers") or []
    flags = deliverable.get("flags") or []
    findings = deliverable.get("findings") or []
    entity_observations = deliverable.get("entity_observations") or []
    eligible = bool(eligibility.get("eligible"))

    blocker_items = "".join(f"<li>{_e(item)}</li>" for item in blockers)
    flag_items = "".join(f"<li>{_e(item)}</li>" for item in flags)
    reason_items = "".join(
        f"<li>{_e(reason)}</li>" for reason in (eligibility.get("reasons") or [])
    )

    finding_rows = "".join(
        "<tr>"
        f"<td>{_label(RISK_KIND_LABELS, f.get('risk_kind'))}</td>"
        f"<td>{_label(LEVEL_LABELS, f.get('level'))}</td>"
        f"<td>{_e('；'.join(str(b) for b in (f.get('basis') or [])) or None)}</td>"
        f"<td>{_bool_label(f.get('requires_human_confirmation', True))}</td>"
        "</tr>"
        for f in findings
    )

    observation_rows = "".join(
        "<tr>"
        f"<td>{_e(o.get('feature_code'))}</td>"
        f"<td>{_e(o.get('doc_id'))}</td>"
        f"<td>{_e(o.get('effect'))}</td>"
        f"<td>{_e(o.get('reasoning'))}</td>"
        "</tr>"
        for o in entity_observations
    )

    distinguishing = "".join(
        f"<li>{_e(item)}</li>" for item in (three_step.get("distinguishing_features") or [])
    )

    blockers_section = (
        f"""
    <section>
      <h2>尚未解决的阻塞项（因此不能给出结论）</h2>
      <ul class="blockers">{blocker_items}</ul>
    </section>"""
        if blockers
        else ""
    )

    flags_section = (
        f"""
    <section>
      <h2>提示标记</h2>
      <ul>{flag_items}</ul>
    </section>"""
        if flags
        else ""
    )

    findings_section = (
        f"""
    <section>
      <h2>候选发现（须人工确认）</h2>
      <table>
        <thead><tr><th>类别</th><th>等级</th><th>依据</th><th>须人工确认</th></tr></thead>
        <tbody>{finding_rows}</tbody>
      </table>
    </section>"""
        if findings
        else ""
    )

    observations_section = (
        f"""
    <section>
      <h2>实体级候选观察项</h2>
      <table>
        <thead><tr><th>特征</th><th>对比文件</th><th>效果</th><th>候选说理</th></tr></thead>
        <tbody>{observation_rows}</tbody>
      </table>
    </section>"""
        if entity_observations
        else ""
    )

    distinguishing_section = (
        f"<p><strong>区别特征（候选）：</strong></p><ul>{distinguishing}</ul>"
        if distinguishing
        else "<p>区别特征：照实留空，待代理师填写。</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>预评估意见（候选） v{_e(deliverable.get('version_number'))}</title>
<style>
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         color: #1a1a1a; background: #fff; max-width: 800px; margin: 2em auto;
         padding: 0 1.5em; line-height: 1.6; }}
  h1 {{ font-size: 1.4em; border-bottom: 2px solid #333; padding-bottom: .3em; }}
  h2 {{ font-size: 1.05em; margin-top: 1.6em; color: #333; }}
  .notice {{ background: #fff8e6; border: 1px solid #e6c34a; padding: .8em 1em;
            border-radius: 6px; font-weight: 600; }}
  .gate-ok {{ background: #eef7ee; border: 1px solid #7ab87a; }}
  .gate-no {{ background: #fdeeee; border: 1px solid #d98a8a; }}
  .meta dt {{ font-weight: 600; float: left; clear: left; width: 9em; }}
  .meta dd {{ margin-left: 9.5em; }}
  .mono {{ font-family: ui-monospace, monospace; font-size: .85em; word-break: break-all; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .92em; }}
  th, td {{ border: 1px solid #ccc; padding: .4em .6em; text-align: left;
           vertical-align: top; }}
  th {{ background: #f2f2f2; }}
  ul.blockers li {{ color: #a33; }}
  .footer {{ margin-top: 2em; padding-top: 1em; border-top: 1px solid #ccc;
            font-size: .88em; color: #444; }}
  @media print {{ body {{ margin: 0; }} .notice {{ -webkit-print-color-adjust: exact; }} }}
</style>
</head>
<body>
  <h1>预评估意见（候选 · 非结论）—— 版本 v{_e(deliverable.get('version_number'))}</h1>

  <p class="notice">{_e(deliverable.get('candidate_notice'))}</p>

  <section>
    <h2>版本与复核信息</h2>
    <dl class="meta">
      <dt>评估版本</dt><dd>v{_e(deliverable.get('version_number'))}</dd>
      <dt>复核状态</dt><dd>{_e(deliverable.get('status_label'))}（{_e(deliverable.get('status_caveat'))}）</dd>
      <dt>须人工确认</dt><dd>{_bool_label(deliverable.get('requires_human_confirmation', True))}</dd>
      <dt>规则版本</dt><dd>{_e(deliverable.get('rules_version'))}</dd>
      <dt>内容摘要</dt><dd class="mono">{_e(deliverable.get('payload_sha256'))}</dd>
      <dt>生成时间</dt><dd>{_e(deliverable.get('generated_at'))}</dd>
    </dl>
  </section>

  <section>
    <h2>是否允许发布候选判断（结论门禁）</h2>
    <p class="notice {'gate-ok' if eligible else 'gate-no'}">
      {'允许发布候选判断' if eligible else '不允许发布候选判断'}
    </p>
    <ul>{reason_items}</ul>
  </section>
  {blockers_section}
  {flags_section}

  <section>
    <h2>证据覆盖摘要</h2>
    <dl class="meta">
      <dt>来源覆盖</dt><dd>{_e(evidence.get('source_coverage'))}</dd>
      <dt>已核验引证</dt><dd>{_e(evidence.get('verified_citations'))} / {_e(evidence.get('total_citations'))}</dd>
      <dt>缺失锚点</dt><dd>{_e(evidence.get('missing_anchors'))}</dd>
      <dt>未核验引证</dt><dd>{_e(evidence.get('unverified_citations'))}</dd>
      <dt>失败来源</dt><dd>{_e(evidence.get('failed_sources'))}</dd>
      <dt>阻塞结论</dt><dd>{_bool_label(evidence.get('blocks_conclusion'))}</dd>
    </dl>
  </section>

  <section>
    <h2>三步法脚手架（待填写，非结论）</h2>
    <dl class="meta">
      <dt>最接近现有技术</dt><dd>{_e(three_step.get('closest_prior_art'))}</dd>
      <dt>相同特征数</dt><dd>{_e(three_step.get('closest_prior_art_identical'))}</dd>
      <dt>实际技术问题</dt><dd>{_e(three_step.get('actual_technical_problem'))}</dd>
    </dl>
    {distinguishing_section}
    <p><em>{_e(three_step.get('note'))}</em></p>
  </section>
  {findings_section}
  {observations_section}

  <div class="footer">
    <p>{_e(deliverable.get('publication_disclaimer'))}</p>
    <p>{_e(deliverable.get('version_freeze_declaration'))}</p>
  </div>
</body>
</html>
"""
