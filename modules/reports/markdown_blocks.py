"""Block-level parse of generator Markdown, shared by the DOCX and PDF exporters.

Scope matches what ``modules.reports.generator.MarkdownReportGenerator``
actually emits: ``#``/``##``/``###`` headings, pipe tables with ``:---``
separator rows, ``- `` bullets, ``> `` quotes, ``---`` rules, fenced ```
code blocks, and inline ``**bold**`` / `` `code` ``. Anything else is a plain
paragraph. Text is carried through verbatim — renderers add no wording, so no
conclusion language can enter an exported file that is not in the sealed
report itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_BULLET_RE = re.compile(r"^-\s+(.*)$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")
_RULE_RE = re.compile(r"^---+\s*$")
_FENCE_RE = re.compile(r"^```(\w*)\s*$")
_TABLE_SEPARATOR_RE = re.compile(r"^\|?(\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$")
_INLINE_TOKEN_RE = re.compile(r"(\*\*.+?\*\*|`.+?`)")

BlockKind = Literal["heading", "table", "rule", "code", "bullet", "quote", "paragraph"]
InlineKind = Literal["text", "bold", "code"]


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str = ""
    level: int = 0
    header: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    lines: tuple[str, ...] = ()


def _split_table_row(line: str) -> list[str]:
    """Split a pipe-table row into trimmed cell strings."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_table_start(lines: list[str], index: int) -> bool:
    """A table needs a header row followed by a separator row."""
    if index + 1 >= len(lines):
        return False
    header, separator = lines[index].strip(), lines[index + 1].strip()
    return "|" in header and bool(_TABLE_SEPARATOR_RE.match(separator))


def split_inline(text: str) -> list[tuple[InlineKind, str]]:
    """Split text into (kind, text) runs honoring **bold** and `code` tokens."""
    runs: list[tuple[InlineKind, str]] = []
    for token in _INLINE_TOKEN_RE.split(text):
        if not token:
            continue
        if token.startswith("**") and token.endswith("**") and len(token) > 4:
            runs.append(("bold", token[2:-2]))
        elif token.startswith("`") and token.endswith("`") and len(token) > 2:
            runs.append(("code", token[1:-1]))
        else:
            runs.append(("text", token))
    return runs


def parse_blocks(markdown: str) -> list[Block]:
    """把生成器产出的 Markdown 切分为块序列（纯函数）。"""
    blocks: list[Block] = []
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()

        if not line:
            index += 1
            continue

        if _is_table_start(lines, index):
            header = _split_table_row(lines[index])
            index += 2  # 跳过表头与分隔行
            rows: list[tuple[str, ...]] = []
            while index < len(lines) and "|" in lines[index].strip() and lines[index].strip():
                cells = _split_table_row(lines[index])
                rows.append(
                    tuple(cells[col] if col < len(cells) else "" for col in range(len(header)))
                )
                index += 1
            blocks.append(Block("table", header=tuple(header), rows=tuple(rows)))
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = min(len(heading.group(1)), 3)
            blocks.append(Block("heading", text=heading.group(2).strip(), level=level))
            index += 1
            continue

        if _RULE_RE.match(line):
            blocks.append(Block("rule"))
            index += 1
            continue

        if _FENCE_RE.match(line):
            # 围栏代码块：原样保留各行，直到闭合围栏（缺失则到文档尾）
            index += 1
            code_lines: list[str] = []
            while index < len(lines) and not _FENCE_RE.match(lines[index].strip()):
                code_lines.append(lines[index])
                index += 1
            index += 1  # 跳过闭合围栏
            blocks.append(Block("code", lines=tuple(code_lines)))
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            blocks.append(Block("bullet", text=bullet.group(1)))
            index += 1
            continue

        quote = _QUOTE_RE.match(line)
        if quote:
            blocks.append(Block("quote", text=quote.group(1)))
            index += 1
            continue

        blocks.append(Block("paragraph", text=line))
        index += 1
    return blocks
