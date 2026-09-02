from __future__ import annotations

import hashlib
import io
import mimetypes
import re
from dataclasses import dataclass, field
from typing import Any

from docx import Document
from pypdf import PdfReader


@dataclass
class ExtractedDrawing:
    data: bytes
    filename: str
    mime_type: str
    sha256: str
    page_number: int | None = None
    figure_label: str = "附图"
    figure_title: str = ""
    reference_marks: list[dict[str, str]] = field(default_factory=list)
    order_index: int = 1


class DrawingExtractor:
    """Extracts patent drawings and figures from DOCX and PDF documents with smart caption & mark association."""

    @staticmethod
    def compute_sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def extract_drawings(
        self,
        data: bytes,
        filename: str,
        mime_type: str | None = None,
        document_text: str = "",
    ) -> list[ExtractedDrawing]:
        lower_name = filename.lower()
        drawings: list[ExtractedDrawing] = []

        # Auto-extract text if none provided
        if not document_text:
            if lower_name.endswith(".pdf") or mime_type == "application/pdf":
                try:
                    reader = PdfReader(io.BytesIO(data))
                    document_text = "\n".join([p.extract_text() or "" for p in reader.pages])
                except Exception:
                    document_text = ""
            elif lower_name.endswith(".docx") or mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                try:
                    doc = Document(io.BytesIO(data))
                    document_text = "\n".join([p.text for p in doc.paragraphs if p.text])
                except Exception:
                    document_text = ""

        if lower_name.endswith(".docx") or mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            drawings = self._extract_from_docx(data)
        elif lower_name.endswith(".pdf") or mime_type == "application/pdf":
            drawings = self._extract_from_pdf(data)
        else:
            drawings = []

        # Associate captions and reference marks from document text
        if document_text and drawings:
            drawings = self.associate_captions_and_marks(drawings, document_text)

        return drawings

    def _extract_from_docx(self, data: bytes) -> list[ExtractedDrawing]:
        doc = Document(io.BytesIO(data))
        drawings: list[ExtractedDrawing] = []
        seen_hashes: set[str] = set()
        order = 1

        for rel_id, part in doc.part.related_parts.items():
            content_type = getattr(part, "content_type", "")
            if content_type.startswith("image/"):
                blob = getattr(part, "blob", None)
                if not blob or len(blob) < 500:
                    continue

                sha256 = self.compute_sha256(blob)
                if sha256 in seen_hashes:
                    continue
                seen_hashes.add(sha256)

                part_name = getattr(part, "partname", "")
                base_name = part_name.split("/")[-1] if part_name else f"image_{order}.png"
                guessed_mime = content_type or mimetypes.guess_type(base_name)[0] or "image/png"

                drawings.append(
                    ExtractedDrawing(
                        data=blob,
                        filename=base_name,
                        mime_type=guessed_mime,
                        sha256=sha256,
                        page_number=None,
                        figure_label=f"图 {order}",
                        figure_title=f"说明书附图 {order}",
                        reference_marks=[],
                        order_index=order,
                    )
                )
                order += 1

        return drawings

    def _extract_from_pdf(self, data: bytes) -> list[ExtractedDrawing]:
        try:
            reader = PdfReader(io.BytesIO(data))
        except Exception:
            return []

        drawings: list[ExtractedDrawing] = []
        seen_hashes: set[str] = set()
        order = 1

        try:
            pages = reader.pages
        except Exception:
            return []

        for page_num, page in enumerate(pages, start=1):
            try:
                page_text = page.extract_text() or ""
                # Check for explicit figure label in page text (e.g., "图 1", "图1", "说明书附图 1/8 页")
                page_fig_match = re.search(r"图\s*([0-9]+)", page_text)
                page_fig_num = int(page_fig_match.group(1)) if page_fig_match else None

                images = getattr(page, "images", [])
                for img in images:
                    blob = getattr(img, "data", None)
                    # Filter out logos, header/footer icons and small artifacts (< 4000 bytes)
                    if not blob or len(blob) < 4000:
                        continue

                    sha256 = self.compute_sha256(blob)
                    if sha256 in seen_hashes:
                        continue
                    seen_hashes.add(sha256)

                    img_name = getattr(img, "name", f"image_{page_num}_{order}.png")
                    guessed_mime = mimetypes.guess_type(img_name)[0] or "image/jpeg"

                    fig_label = f"图 {page_fig_num}" if page_fig_num else f"图 {order}"
                    fig_title = f"说明书附图 {page_fig_num or order}"

                    if page_num == 1 and ("摘要" in page_text or "摘要附图" in page_text):
                        fig_label = "摘要附图"
                        fig_title = "发明专利摘要附图"

                    drawings.append(
                        ExtractedDrawing(
                            data=blob,
                            filename=img_name,
                            mime_type=guessed_mime,
                            sha256=sha256,
                            page_number=page_num,
                            figure_label=fig_label,
                            figure_title=fig_title,
                            reference_marks=[],
                            order_index=order,
                        )
                    )
                    order += 1
            except Exception:
                pass

        return drawings

    def associate_captions_and_marks(
        self, drawings: list[ExtractedDrawing], document_text: str
    ) -> list[ExtractedDrawing]:
        """Scan document text for '附图说明' and '附图标记' to enrich figure metadata."""
        if not document_text:
            return drawings

        # 1. Extract figure titles: e.g. "图 1 为本发明实施例提供的系统架构图。"
        # or "[0025] 图1是根据一个实施例的机器人臂组件的侧视图。"
        fig_captions: dict[int, tuple[str, str]] = {}
        
        # Prioritize 附图说明 section if present
        drawings_section = ""
        sec_match = re.search(
            r"(?:【?(?:说明书)?附图说明】?|附图简要说明)(.*?)(?:【?具体实施方式】?|【?详细说明】?|【?附图标记说明】?|$)",
            document_text,
            re.DOTALL,
        )
        if sec_match and len(sec_match.group(1).strip()) > 10:
            drawings_section = sec_match.group(1)

        search_targets = [drawings_section, document_text] if drawings_section else [document_text]

        caption_patterns = [
            r"(?:\[[0-9]{4}\]\s*)?图\s*([0-9一二三四五六七八九十]+)\s*(?:是|为|：|:)?\s*(.*?)(?=[;；。\n]|$)",
            r"(?:\[[0-9]{4}\]\s*)?Figure\s*([0-9]+)\s*(?:is|:)?\s*(.*?)(?=[;；。\n]|$)",
        ]
        chinese_num_map = {
            "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        }

        for text_target in search_targets:
            for pat in caption_patterns:
                for match in re.finditer(pat, text_target, re.IGNORECASE):
                    raw_num = match.group(1).strip()
                    title_text = match.group(2).strip()
                    if not title_text or len(title_text) < 2:
                        continue
                    if re.match(r"^(页|所示|中|内|上|下|限定|包括|限定了)", title_text):
                        continue
                    # Remove common boilerplate prefixes
                    title_text = re.sub(
                        r"^(?:是|为|示出了|展示了|用于说明)?\s*(?:根据|按照)?\s*(?:本发明|本实用新型|本申请)?\s*(?:一个|某些|各个|一)?\s*(?:示例性)?\s*(?:实施例|实施方式)?\s*(?:提供)?\s*(?:的)?\s*",
                        "",
                        title_text,
                    ).strip()
                    title_text = title_text.rstrip("。;；,，")
                    if len(title_text) > 80:
                        title_text = title_text[:80]

                    idx = None
                    if raw_num.isdigit():
                        idx = int(raw_num)
                    elif raw_num in chinese_num_map:
                        idx = chinese_num_map[raw_num]

                    if idx is not None and (idx not in fig_captions or text_target == drawings_section):
                        fig_captions[idx] = (f"图 {idx}", title_text)

        # 2. Extract reference marks dictionary: e.g. "偏转轴线102", "支架112", "101：输入模块"
        stopwords = {
            "权利要求", "说明书", "优先权", "申请号", "公布号", "实施例", "附图", "国家",
            "知识产权", "公司", "根据", "参见", "本公开", "技术领域", "背景技术", "页",
            "第", "至", "和", "中", "与", "该", "所述", "包括", "一种"
        }
        seen_marks: dict[str, str] = {}

        # Pattern A: 偏转轴线102 / 支架112
        for m in re.finditer(r"([\u4e00-\u9fa5]{2,12})\s*([0-9]{2,4})", document_text):
            name = m.group(1).strip()
            mark = m.group(2).strip()
            if mark.startswith("19") or mark.startswith("20") and len(mark) == 4:
                continue
            if any(sw in name for sw in stopwords):
                continue
            if mark not in seen_marks:
                seen_marks[mark] = name

        # Pattern B: 101：输入模块 / 102-量化单元
        for m in re.finditer(r"(?:^|[\s,，;；。、\(（])([0-9]{2,4})\s*[、:：—\-]\s*([\u4e00-\u9fa5]{2,12})", document_text):
            mark = m.group(1).strip()
            name = m.group(2).strip()
            if mark.startswith("19") or mark.startswith("20") and len(mark) == 4:
                continue
            if any(sw in name for sw in stopwords):
                continue
            if mark not in seen_marks:
                seen_marks[mark] = name

        all_extracted_marks = [{"mark": k, "name": v} for k, v in seen_marks.items()]

        # 3. Associate with drawings
        for idx, d in enumerate(drawings, start=1):
            if d.figure_label == "摘要附图":
                d.reference_marks = all_extracted_marks[:4]
                continue

            fig_match = re.search(r"图\s*([0-9]+)", d.figure_label)
            fig_idx = int(fig_match.group(1)) if fig_match else (d.order_index or idx)

            if fig_idx in fig_captions:
                d.figure_label, d.figure_title = fig_captions[fig_idx]
            else:
                d.figure_label = f"图 {fig_idx}"
                if not d.figure_title:
                    d.figure_title = f"说明书附图 {fig_idx}"

            # Filter marks related to this figure (e.g. marks starting with fig_idx or fig_idx*100)
            related_marks = [
                m for m in all_extracted_marks
                if m["mark"].startswith(str(fig_idx)) or (fig_idx == 1 and int(m["mark"]) < 200)
            ]
            d.reference_marks = related_marks[:8] if related_marks else all_extracted_marks[:4]

        return drawings
