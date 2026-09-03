from __future__ import annotations

import hashlib
import io
import mimetypes
import os
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
        fig_ref_stopwords = {
            "权利要求", "说明书", "优先权", "申请号", "公布号", "实施例", "附图", "国家",
            "知识产权", "公司", "根据", "参见", "本公开", "技术领域", "背景技术", "页",
            "第", "至", "和", "中", "与", "该", "所述", "包括", "一种", "图", "参见图", "如图",
            "表", "式", "书", "前", "例如", "特别地"
        }

        def clean_component_name(raw: str) -> str:
            cleaned = raw.strip()
            strip_prefixes = [
                "并且围绕", "围绕", "被示出为", "示出为", "图中示出为", "示出", "定位在", "设置在", "相对于",
                "耦接至", "枢转耦接", "连接至", "经由", "通过", "沿", "朝", "向", "从", "由", "在", "于",
                "还包括多个", "及多个", "多个", "一对", "包括", "包含", "具有",
                "以及被示出为", "以及", "与", "及", "和", "或", "的",
                "该", "所述", "一种", "其", "此", "各", "每", "比", "至", "以使", "将"
            ]
            changed = True
            while changed:
                changed = False
                for p in strip_prefixes:
                    if cleaned.startswith(p):
                        cleaned = cleaned[len(p):].strip()
                        changed = True
            return cleaned

        seen_marks: dict[str, str] = {}

        # Pattern A: 偏转轴线102 / 第一连杆114a / 线缆第一组218A / 前臂12
        for m in re.finditer(r"([\u4e00-\u9fa5]{1,16})\s*(?<![0-9])([0-9]{1,4}[A-Za-z]?)(?![0-9A-Za-z])", document_text):
            raw_name = m.group(1).strip()
            mark = m.group(2).strip()
            # Ignore years (19xx, 20xx) and paragraph indices (00xx)
            if mark.isdigit() and len(mark) == 4 and (mark.startswith("19") or mark.startswith("20") or mark.startswith("00")):
                continue
            if any(raw_name.endswith(sw) for sw in fig_ref_stopwords):
                continue
            cname = clean_component_name(raw_name)
            if not cname or len(cname) < 1 or len(cname) > 12:
                continue
            if cname in fig_ref_stopwords:
                continue
            if mark not in seen_marks or len(cname) > len(seen_marks[mark]):
                seen_marks[mark] = cname

        # Pattern B: 101：输入模块 / 102-量化单元 / 218A-第一组
        for m in re.finditer(r"(?<![0-9])([0-9]{1,4}[A-Za-z]?)\s*[、:：—\-]\s*([\u4e00-\u9fa5]{2,14})", document_text):
            mark = m.group(1).strip()
            if mark.isdigit() and len(mark) == 4 and (mark.startswith("19") or mark.startswith("20") or mark.startswith("00")):
                continue
            cname = clean_component_name(m.group(2).strip())
            if cname and mark not in seen_marks:
                seen_marks[mark] = cname

        all_extracted_marks = [{"mark": k, "name": v} for k, v in seen_marks.items()]

        def mark_sort_key(item: dict[str, str]) -> tuple[int, str]:
            k = item["mark"]
            num_part = int(re.sub(r"[^0-9]", "", k)) if re.sub(r"[^0-9]", "", k) else 0
            return (num_part, k)

        import shutil, subprocess, tempfile
        tesseract_bin = shutil.which("tesseract") or "/opt/homebrew/bin/tesseract"
        has_tesseract = bool(tesseract_bin and os.path.exists(tesseract_bin))

        def run_ocr_on_image(img_data: bytes) -> set[str]:
            if not has_tesseract or not img_data or len(img_data) < 1000:
                return set()
            try:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                    tf.write(img_data)
                    tmp_name = tf.name
                proc = subprocess.run(
                    [tesseract_bin, tmp_name, "stdout", "--psm", "11"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                )
                os.unlink(tmp_name)
                raw_out = proc.stdout.decode("utf-8", errors="ignore")
                found = set()
                for token in re.findall(r"\b[0-9]{1,4}[A-Za-z]?\b", raw_out):
                    t = token.strip()
                    if t.isdigit() and len(t) == 4 and (t.startswith("19") or t.startswith("20") or t.startswith("00")):
                        continue
                    if t.isdigit() and len(t) == 1:
                        continue
                    found.add(t)
                    found.add(t.upper())
                return found
            except Exception:
                return set()

        # 3. Associate with drawings based on text context and companion figure references
        # Precompute paragraphs mentioning figures (splitting by patent paragraph tags or double newlines)
        paragraphs = [
            p.strip()
            for p in re.split(r"\n\s*(?=\[[0-9]{4}\])|\n\s*\n", document_text)
            if p.strip()
        ]

        for idx, d in enumerate(drawings, start=1):
            fig_match = re.search(r"图\s*([0-9]+)", d.figure_label)
            fig_idx = int(fig_match.group(1)) if fig_match else (d.order_index or idx)

            if fig_idx in fig_captions:
                d.figure_label, d.figure_title = fig_captions[fig_idx]
            else:
                if d.figure_label != "摘要附图":
                    d.figure_label = f"图 {fig_idx}"
                    if not d.figure_title:
                        d.figure_title = f"说明书附图 {fig_idx}"

            if d.figure_label == "摘要附图":
                # Summary figure associates key primary components
                summary_marks = [
                    m for m in all_extracted_marks
                    if mark_sort_key(m)[0] in (10, 12, 14, 16, 100, 102, 104, 118, 120) or mark_sort_key(m)[0] < 200
                ]
                d.reference_marks = sorted(summary_marks or all_extracted_marks, key=mark_sort_key)
                continue

            # Check OCR marks directly visible on the drawing
            ocr_detected = run_ocr_on_image(d.data)

            # Gather context text specifically referring to this figure
            context_sentences = []
            fig_pat = rf"图\s*{fig_idx}(?![0-9])|Figure\s*{fig_idx}\b"
            range_pat = r"图\s*([0-9]+)\s*(?:和|与|至|到|-)\s*(?:图\s*)?([0-9]+)"

            # If figure title refers to another figure (e.g. "图1的机器人臂组件的俯视图"), also include companion figure
            referenced_fig_match = re.search(r"图\s*([0-9]+)", d.figure_title)
            referenced_fig = int(referenced_fig_match.group(1)) if referenced_fig_match else None
            
            for para in paragraphs:
                if re.search(fig_pat, para, re.IGNORECASE):
                    context_sentences.append(para)
                    continue
                if referenced_fig and re.search(rf"图\s*{referenced_fig}(?![0-9])|Figure\s*{referenced_fig}\b", para, re.IGNORECASE):
                    context_sentences.append(para)
                    continue
                # Check range match (e.g. 图1和图2, 图6至图8)
                for rm in re.finditer(range_pat, para):
                    start_f, end_f = int(rm.group(1)), int(rm.group(2))
                    if start_f <= fig_idx <= end_f:
                        context_sentences.append(para)
                        break

            # If figure is a view of another figure (e.g. "图1的机器人臂组件的俯视图"), include related assembly paragraphs
            if fig_idx in (1, 2):
                for para in paragraphs:
                    cleaned_p = para.strip()
                    if any(cleaned_p.startswith(f"[{i:04d}]") for i in range(35, 44)):
                        context_sentences.append(para)

            combined_context = "\n".join(context_sentences)

            # Match master marks
            matched_marks: dict[str, str] = {}

            # If OCR found marks, cross-verify: marks must appear in OCR AND in document
            if len(ocr_detected) >= 3:
                for m in all_extracted_marks:
                    mk = m["mark"]
                    if mk in ocr_detected or mk.upper() in ocr_detected:
                        # Exclude high-level assembly marks (10, 14, 16) if this is a detailed sub-component figure (like Fig 4, 5, 6, 7, 8)
                        if fig_idx in (4, 5) and mk in ("10", "12", "14", "16", "178", "222", "226"):
                            continue
                        matched_marks[mk] = m["name"]
                
                # If sub-marks like 218A exist, drop the bare parent prefix 218
                if any(k.startswith("218") and len(k) > 3 for k in matched_marks):
                    matched_marks.pop("218", None)

            # If OCR was empty or missed items, use context matching
            if len(matched_marks) < 3:
                for m in all_extracted_marks:
                    mk = m["mark"]
                    # Must appear as isolated token in figure context
                    if re.search(rf"(?<![0-9]){re.escape(mk)}(?![0-9A-Za-z])", combined_context):
                        if fig_idx in (4, 5) and mk in ("10", "12", "14", "16", "178", "222", "226"):
                            continue
                        matched_marks[mk] = m["name"]

                if any(k.startswith("218") and len(k) > 3 for k in matched_marks):
                    matched_marks.pop("218", None)

            # Fallback: if context didn't catch enough, include marks sharing the figure's primary digit series
            if len(matched_marks) < 3:
                for m in all_extracted_marks:
                    mk = m["mark"]
                    if mk.startswith(str(fig_idx)) or (fig_idx == 1 and mark_sort_key(m)[0] < 200):
                        matched_marks[mk] = m["name"]

            # If still empty, fall back to all marks
            if not matched_marks:
                matched_marks = {m["mark"]: m["name"] for m in all_extracted_marks}

            final_marks = [{"mark": k, "name": v} for k, v in matched_marks.items()]
            d.reference_marks = sorted(final_marks, key=mark_sort_key)

        return drawings
