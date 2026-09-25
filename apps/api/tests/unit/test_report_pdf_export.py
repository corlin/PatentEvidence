"""Unit tests for the deterministic Markdown → PDF report exporter."""

from __future__ import annotations

import io
import itertools
from datetime import datetime, timezone

from pypdf import PdfReader

from modules.reports.docx_export import ReportProvenance, provenance_footer_text
from modules.reports.pdf_export import markdown_to_html, markdown_to_pdf_bytes

PROVENANCE = ReportProvenance(
    snapshot_number=7,
    root_sha256="ab" * 32,
    sealed_at=datetime(2026, 9, 1, 8, 30, tzinfo=timezone.utc),
)

REPORT = "\n".join(
    [
        "# 专利证据分析与法律评估报告",
        "> **案件编号**：`2026-CASE-001`",
        "## 1. 技术特征分解",
        "| 特征编号 | 特征内容 |",
        "| :--- | :--- |",
        "| `F1` | 一种量化方法 |",
        "- 交底文档：交底书.docx",
        "- 版本 v1",
        "---",
        "```text",
        "TIAB=(量化 AND 模型)",
        "```",
        "本报告不构成专利性结论。",
    ]
)


def _text(data: bytes) -> str:
    return "".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)


def test_html_renders_every_block_kind() -> None:
    html = markdown_to_html(REPORT)
    assert "<h1>专利证据分析与法律评估报告</h1>" in html
    assert "<blockquote><strong>案件编号</strong>：<code>2026-CASE-001</code></blockquote>" in html
    assert "<th>特征编号</th>" in html and "<td><code>F1</code></td>" in html
    assert "<ul>\n<li>交底文档：交底书.docx</li>\n<li>版本 v1</li>\n</ul>" in html
    assert "<hr>" in html
    assert "<pre>TIAB=(量化 AND 模型)</pre>" in html


def test_html_escapes_report_content() -> None:
    html = markdown_to_html('正文 <script>alert(1)</script> & "引号"', title="<b>标题</b>")
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp;" in html
    assert "<title>&lt;b&gt;标题&lt;/b&gt;</title>" in html


def test_footer_value_cannot_break_out_of_css() -> None:
    hostile = ReportProvenance(1, 'x"; } body { display:none } /*', PROVENANCE.sealed_at)
    html = markdown_to_html("正文", provenance=hostile)
    assert '--footer: "' in html
    assert 'x\\"; }' in html


def test_pdf_carries_content_and_provenance_footer() -> None:
    data = markdown_to_pdf_bytes(REPORT, title="大模型量化 分析报告", provenance=PROVENANCE)
    assert data.startswith(b"%PDF-")
    text = _text(data)
    assert "大模型量化 分析报告" in text
    assert "一种量化方法" in text
    assert "不构成专利性结论" in text
    assert provenance_footer_text(PROVENANCE) in text
    meta = PdfReader(io.BytesIO(data)).metadata
    assert meta["/CreationDate"] == "D:20260901083000Z"
    assert meta["/Author"] == "PatentEvidence"


def test_same_input_yields_identical_bytes() -> None:
    first = markdown_to_pdf_bytes(REPORT, provenance=PROVENANCE)
    second = markdown_to_pdf_bytes(REPORT, provenance=PROVENANCE)
    assert first == second


def test_bytes_do_not_depend_on_the_wall_clock(monkeypatch) -> None:
    """字体子集时间戳不得随墙钟变化（API 镜像内 Noto CJK 曾因此逐次不同）。

    WeasyPrint 有 hb-subset 时走 HarfBuzz 子集化（开发机 Homebrew），否则回退到
    fontTools（API 镜像）；后者会写入当前时间。这里强制走 fontTools 路径复现镜像行为。
    """
    import fontTools.misc.timeTools as time_tools
    import weasyprint.pdf.fonts as weasy_fonts

    monkeypatch.setattr(weasy_fonts, "harfbuzz_subset", None)
    # 每次读取墙钟都前进约 17 分钟，确保任何写入当前时间的地方都会产生差异
    clock = itertools.count(1_900_000_000, 997)
    monkeypatch.setattr(time_tools.time, "time", lambda: float(next(clock)))
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    first = markdown_to_pdf_bytes(REPORT, provenance=PROVENANCE)
    second = markdown_to_pdf_bytes(REPORT, provenance=PROVENANCE)
    assert first == second


def test_different_snapshot_changes_the_file_bytes() -> None:
    other = ReportProvenance(8, "cd" * 32, PROVENANCE.sealed_at)
    assert markdown_to_pdf_bytes(REPORT, provenance=PROVENANCE) != markdown_to_pdf_bytes(
        REPORT, provenance=other
    )


def test_export_adds_no_conclusion_wording() -> None:
    text = _text(markdown_to_pdf_bytes(REPORT, provenance=PROVENANCE))
    for banned in ("良好授权前景", "创新高度", "全案风险评级", "具备新颖性", "具备创造性"):
        assert banned not in text
