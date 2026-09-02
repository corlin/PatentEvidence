import io
import pytest
from docx import Document
from pypdf import PdfWriter

from modules.cases.drawing_extractor import DrawingExtractor, ExtractedDrawing


def test_drawing_extractor_caption_association():
    extractor = DrawingExtractor()
    sample_text = """
    【说明书附图说明】
    图 1 为本发明实施例一提供的大模型稀疏矩阵量化系统的结构示意图；
    图 2 为量化计算单元的内部拓扑图；
    图 3 为量化加速流程图。

    【附图标记说明】
    101：输入模块，102：量化单元，103：累加器，201：乘加阵列。
    """

    drawings = [
        ExtractedDrawing(
            data=b"fake_image_1",
            filename="img1.png",
            mime_type="image/png",
            sha256="hash1",
            order_index=1,
        ),
        ExtractedDrawing(
            data=b"fake_image_2",
            filename="img2.png",
            mime_type="image/png",
            sha256="hash2",
            order_index=2,
        ),
    ]

    associated = extractor.associate_captions_and_marks(drawings, sample_text)
    assert len(associated) == 2
    assert associated[0].figure_label == "图 1"
    assert "大模型稀疏矩阵量化系统" in associated[0].figure_title
    assert any(m["mark"] == "101" for m in associated[0].reference_marks)

    assert associated[1].figure_label == "图 2"
    assert "内部拓扑图" in associated[1].figure_title
    assert any(m["mark"] == "201" for m in associated[1].reference_marks)


def test_drawing_extractor_pdf_empty_graceful():
    extractor = DrawingExtractor()
    # Test on valid blank pdf
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = io.BytesIO()
    writer.write(stream)
    pdf_bytes = stream.getvalue()

    drawings = extractor.extract_drawings(pdf_bytes, "test.pdf")
    assert isinstance(drawings, list)
    assert len(drawings) == 0


def test_drawing_extractor_corrupt_bytes_graceful():
    extractor = DrawingExtractor()
    corrupt_bytes = b"not a valid pdf or docx"
    drawings = extractor.extract_drawings(corrupt_bytes, "corrupt.pdf")
    assert drawings == []
