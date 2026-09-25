"""Deterministic Markdown → DOCX export for analysis reports.

The report pipeline stores reports as Markdown produced by
``modules.reports.generator.MarkdownReportGenerator``. This module converts that
Markdown into a Word document so agencies can deliver an editable file, as the
MVP spec requires ("PDF/DOCX 报告").

Block parsing lives in ``modules.reports.markdown_blocks`` (shared with the
PDF exporter); this module only renders blocks. Content is carried through
verbatim — the converter adds no wording of its own (no conclusion language can
sneak in here, and the report's own disclaimers/gates travel with the content).

python-docx is an existing project dependency; nothing new is introduced.

Byte-level determinism: python-docx stamps every zip entry with the wall-clock
time, so two exports of the same report would hash differently. When
provenance is supplied, the package timestamps and core properties are pinned
to the snapshot's ``sealed_at`` so the same sealed snapshot always yields the
same bytes — and therefore the same file SHA-256 (spec §4.1 "对最终文件计算
SHA-256"). The file hash itself cannot live inside the file; callers publish it
alongside (response header, audit record).
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone

from docx import Document
from docx.shared import Pt

from modules.reports.markdown_blocks import Block, parse_blocks, split_inline

# zip 格式可表示的最早时间；无溯源信息时作为固定时间戳
_ZIP_EPOCH = datetime(1980, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class ReportProvenance:
    """报告所属封存快照的溯源信息，写入页脚并用于固定文件时间戳。"""

    snapshot_number: int
    root_sha256: str
    sealed_at: datetime


def format_sealed_at(sealed_at: datetime) -> str:
    """封存时间统一以 UTC、秒级 ISO 8601 呈现。"""
    return sealed_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def provenance_footer_text(provenance: ReportProvenance) -> str:
    """页脚文本：版本号 + 快照根校验值 + 封存时间（spec：版本号和校验值）。"""
    sealed = format_sealed_at(provenance.sealed_at)
    return (
        f"证据快照版本 #{provenance.snapshot_number} · "
        f"快照根校验值 SHA-256: {provenance.root_sha256} · 封存时间 {sealed}"
    )


def _pin_zip_timestamps(data: bytes, moment: datetime) -> bytes:
    """以固定时间戳重写 zip 条目，使同一输入产出逐字节相同的文件。"""
    stamp = moment.astimezone(timezone.utc)
    if stamp < _ZIP_EPOCH:
        stamp = _ZIP_EPOCH
    date_time = stamp.timetuple()[:6]
    source = zipfile.ZipFile(io.BytesIO(data))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            pinned = zipfile.ZipInfo(info.filename, date_time=date_time)
            pinned.compress_type = zipfile.ZIP_DEFLATED
            pinned.external_attr = info.external_attr
            target.writestr(pinned, source.read(info.filename))
    return output.getvalue()


def _add_inline_runs(paragraph, text: str) -> None:
    """Add runs to a paragraph, honoring **bold** and `code` inline tokens."""
    for kind, token in split_inline(text):
        run = paragraph.add_run(token)
        if kind == "bold":
            run.bold = True
        elif kind == "code":
            run.font.name = "Courier New"


def _render_block(document, block: Block) -> None:
    if block.kind == "table":
        table = document.add_table(rows=1, cols=len(block.header))
        table.style = "Table Grid"
        for col, cell_text in enumerate(block.header):
            cell_paragraph = table.rows[0].cells[col].paragraphs[0]
            _add_inline_runs(cell_paragraph, cell_text)
            for run in cell_paragraph.runs:
                run.bold = True
        for row in block.rows:
            cells = table.add_row().cells
            for col, cell_text in enumerate(row):
                _add_inline_runs(cells[col].paragraphs[0], cell_text)
    elif block.kind == "heading":
        document.add_heading(block.text, level=block.level)
    elif block.kind == "rule":
        # Word 没有水平线元素，用一个空段落隔开即可
        document.add_paragraph("")
    elif block.kind == "code":
        for code_line in block.lines:
            code_run = document.add_paragraph().add_run(code_line)
            code_run.font.name = "Courier New"
    elif block.kind == "bullet":
        _add_inline_runs(document.add_paragraph(style="List Bullet"), block.text)
    elif block.kind == "quote":
        _add_inline_runs(document.add_paragraph(style="Intense Quote"), block.text)
    else:
        _add_inline_runs(document.add_paragraph(), block.text)


def markdown_to_docx_bytes(
    markdown: str,
    *,
    title: str = "专利证据分析报告",
    provenance: ReportProvenance | None = None,
) -> bytes:
    """把生成器产出的 Markdown 报告转换为 DOCX 字节流（纯函数、逐字节确定性）。"""
    document = Document()
    fixed_moment = provenance.sealed_at if provenance else _ZIP_EPOCH
    core = document.core_properties
    core.title = title
    core.author = "PatentEvidence"
    core.comments = ""
    core.created = fixed_moment.astimezone(timezone.utc).replace(tzinfo=None)
    core.modified = core.created
    core.last_modified_by = ""
    if provenance is not None:
        footer = document.sections[0].footer.paragraphs[0]
        footer.text = provenance_footer_text(provenance)
        for run in footer.runs:
            run.font.size = Pt(8)
    # 默认正文字号偏小，便于打印阅读
    normal = document.styles["Normal"]
    normal.font.size = Pt(10.5)

    document.add_heading(title, level=0)

    for block in parse_blocks(markdown):
        _render_block(document, block)

    buffer = io.BytesIO()
    document.save(buffer)
    return _pin_zip_timestamps(buffer.getvalue(), fixed_moment)
