"""Deterministic Markdown → PDF export for analysis reports.

The MVP spec requires the server to produce both DOCX and PDF reports and to
compute SHA-256 over the final file (spec §4.1). This module renders the same
block structure as the DOCX exporter (``modules.reports.markdown_blocks``) to
escaped HTML and prints it with WeasyPrint. Content is carried through
verbatim; the renderer adds no wording beyond the provenance footer.

Byte-level determinism: the PDF creation/modification dates come from the
snapshot's ``sealed_at`` and the document identifier is fixed, so the same
sealed snapshot always yields the same bytes and the same file SHA-256.
Embedded font subsets are written by fontTools, which stamps each subset's
``head.modified`` with the wall clock unless ``SOURCE_DATE_EPOCH`` is set
(reproducible-builds convention); the renderer pins it. This only bites with
OpenType/CFF fonts such as Noto Sans CJK in the API image, so it is easy to
miss on a development host.

Fonts: Chinese text needs a CJK font on the host. The API image installs
``fonts-noto-cjk``; development hosts fall back to the platform CJK fonts.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from html import escape

from modules.reports.docx_export import ReportProvenance, format_sealed_at
from modules.reports.markdown_blocks import Block, parse_blocks, split_inline

_EPOCH = datetime(1980, 1, 1, tzinfo=timezone.utc)
# 字体子集 head.modified 的固定时间戳（1980-01-01，秒）；运维方已设置时尊重其值
_SOURCE_DATE_EPOCH = str(int(_EPOCH.timestamp()))

_FONT_STACK = (
    '"Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", '
    '"PingFang SC", "Heiti SC", "Microsoft YaHei", sans-serif'
)
_MONO_STACK = '"Noto Sans Mono CJK SC", "DejaVu Sans Mono", Menlo, monospace'

_BASE_CSS = f"""
@page {{
  size: A4;
  margin: 20mm 18mm 22mm 18mm;
  @bottom-left {{
    content: var(--footer, "");
    width: 86%;
    white-space: pre;
    font-family: {_FONT_STACK};
    font-size: 7pt;
    line-height: 1.5;
    color: #555;
  }}
  @bottom-right {{
    content: counter(page) " / " counter(pages);
    width: 14%;
    white-space: nowrap;
    text-align: right;
    font-family: {_FONT_STACK};
    font-size: 7pt;
    color: #555;
  }}
}}
body {{ font-family: {_FONT_STACK}; font-size: 10.5pt; line-height: 1.55; color: #111; }}
h1.title {{ font-size: 18pt; margin: 0 0 12pt; }}
h1 {{ font-size: 15pt; }}
h2 {{ font-size: 13pt; margin-top: 16pt; }}
h3 {{ font-size: 11.5pt; }}
table {{ border-collapse: collapse; width: 100%; margin: 6pt 0; font-size: 9.5pt; }}
th, td {{ border: 0.6pt solid #888; padding: 3pt 5pt; text-align: left; vertical-align: top; }}
th {{ background: #f0f0f0; }}
blockquote {{ margin: 6pt 0; padding: 4pt 10pt; border-left: 2pt solid #999; color: #333; }}
code, pre {{ font-family: {_MONO_STACK}; font-size: 9pt; }}
pre {{ white-space: pre-wrap; background: #f6f6f6; padding: 6pt; }}
hr {{ border: none; border-top: 0.6pt solid #bbb; margin: 10pt 0; }}
ul {{ margin: 4pt 0; padding-left: 16pt; }}
"""


def _css_string(value: str) -> str:
    """Quote a value for use as a CSS string literal (newlines become CSS ``\\A``)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped.replace("\n", "\\A ") + '"'


def pdf_footer_lines(provenance: ReportProvenance) -> tuple[str, str]:
    """PDF 页脚两行：版本号与封存时间一行，64 位根校验值独占一行。

    Noto Sans CJK（API 镜像字体）比开发机字体宽，单行页脚会被自动折行并挤压
    页码；按固定两行排版可避免。分隔符用 ASCII "|"：中点 "·" 在 Noto 中提取
    文本时会变成 "•"。DOCX 页脚保持单行原文不变，以免改变既有快照的导出字节。
    """
    return (
        f"证据快照版本 #{provenance.snapshot_number} | "
        f"封存时间 {format_sealed_at(provenance.sealed_at)}",
        f"快照根校验值 SHA-256: {provenance.root_sha256}",
    )


def _inline_html(text: str) -> str:
    parts: list[str] = []
    for kind, token in split_inline(text):
        escaped = escape(token)
        if kind == "bold":
            parts.append(f"<strong>{escaped}</strong>")
        elif kind == "code":
            parts.append(f"<code>{escaped}</code>")
        else:
            parts.append(escaped)
    return "".join(parts)


def _render_blocks(blocks: list[Block]) -> str:
    html: list[str] = []
    in_list = False
    for block in blocks:
        if block.kind != "bullet" and in_list:
            html.append("</ul>")
            in_list = False
        if block.kind == "table":
            head = "".join(f"<th>{_inline_html(cell)}</th>" for cell in block.header)
            body = "".join(
                "<tr>" + "".join(f"<td>{_inline_html(cell)}</td>" for cell in row) + "</tr>"
                for row in block.rows
            )
            html.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
        elif block.kind == "heading":
            html.append(f"<h{block.level}>{_inline_html(block.text)}</h{block.level}>")
        elif block.kind == "rule":
            html.append("<hr>")
        elif block.kind == "code":
            html.append(f"<pre>{escape(chr(10).join(block.lines))}</pre>")
        elif block.kind == "bullet":
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{_inline_html(block.text)}</li>")
        elif block.kind == "quote":
            html.append(f"<blockquote>{_inline_html(block.text)}</blockquote>")
        else:
            html.append(f"<p>{_inline_html(block.text)}</p>")
    if in_list:
        html.append("</ul>")
    return "\n".join(html)


def markdown_to_html(
    markdown: str,
    *,
    title: str = "专利证据分析报告",
    provenance: ReportProvenance | None = None,
) -> str:
    """生成供 PDF 打印的完整 HTML 文档（所有文本均已转义）。"""
    moment = (provenance.sealed_at if provenance else _EPOCH).astimezone(timezone.utc)
    stamp = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    footer = "\n".join(pdf_footer_lines(provenance)) if provenance else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>
<meta name="author" content="PatentEvidence">
<meta name="generator" content="PatentEvidence">
<meta name="dcterms.created" content="{stamp}">
<meta name="dcterms.modified" content="{stamp}">
<style>{_BASE_CSS}
:root {{ --footer: {_css_string(footer)}; }}
</style>
</head>
<body>
<h1 class="title">{escape(title)}</h1>
{_render_blocks(parse_blocks(markdown))}
</body>
</html>
"""


def markdown_to_pdf_bytes(
    markdown: str,
    *,
    title: str = "专利证据分析报告",
    provenance: ReportProvenance | None = None,
) -> bytes:
    """把生成器产出的 Markdown 报告渲染为 PDF 字节流（逐字节确定性）。"""
    from weasyprint import HTML  # 延迟导入：仅导出时需要系统 pango 库

    # fontTools 写字体子集时用 SOURCE_DATE_EPOCH 代替当前时间，否则同一输入字节不同
    os.environ.setdefault("SOURCE_DATE_EPOCH", _SOURCE_DATE_EPOCH)
    document_html = markdown_to_html(markdown, title=title, provenance=provenance)
    # 固定文档标识：由内容派生，而非随机值，保证同一输入产出同一文件
    identifier = hashlib.sha256(document_html.encode("utf-8")).hexdigest()[:32].encode()
    return HTML(string=document_html).write_pdf(pdf_identifier=identifier)
