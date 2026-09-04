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


def test_drawing_extractor_complex_marks_alphanumeric_and_context():
    extractor = DrawingExtractor()
    sample_text = """
    [0025] 图1是机器人臂组件的侧视图。
    [0026] 图2是图1的机器人臂组件的俯视图。
    
    [0035] 机器人臂组件10包含前臂12与手14。关节组件100允许手14围绕偏转轴线102和俯仰轴线104旋转。
    [0038] 关节组件100还包括第一致动器116a和第二致动器116b，以及第一连杆114a和第二连杆114b。
    [0041] 如图2所示，连杆114经由耦接万向节122围绕第一轴线106a和第一轴线106b与手结构120枢转耦接。
    耦接万向节122还限定第二轴线108a和第二轴线108b。沿中心线18，俯仰轴线104与偏转轴线102偏移距离136。
    在手结构120的第一侧140和第二侧142处设置控制线缆174。
    """

    drawings = [
        ExtractedDrawing(
            data=b"fake_image_2",
            filename="fig2.png",
            mime_type="image/png",
            sha256="hash2",
            figure_label="图 2",
            order_index=2,
        ),
    ]

    associated = extractor.associate_captions_and_marks(drawings, sample_text)
    assert len(associated) == 1
    d2 = associated[0]
    assert d2.figure_label == "图 2"
    
    mark_keys = [m["mark"] for m in d2.reference_marks]
    # Check that alphanumeric marks, short numbers, and all context marks are mapped
    assert "10" in mark_keys
    assert "12" in mark_keys
    assert "14" in mark_keys
    assert "18" in mark_keys
    assert "102" in mark_keys
    assert "104" in mark_keys
    assert "106a" in mark_keys
    assert "106b" in mark_keys
    assert "108a" in mark_keys
    assert "108b" in mark_keys
    assert "114a" in mark_keys
    assert "114b" in mark_keys
    assert "116a" in mark_keys
    assert "116b" in mark_keys
    assert "120" in mark_keys
    assert "122" in mark_keys
    assert "136" in mark_keys
    assert "140" in mark_keys
    assert "142" in mark_keys
    assert "174" in mark_keys
    
    # Check clean name formatting
    name_map = {m["mark"]: m["name"] for m in d2.reference_marks}
    assert name_map["106a"] == "第一轴线106a" or "第一轴线" in name_map["106a"]
    assert "偏转轴线" in name_map["102"]
    assert "俯仰轴线" in name_map["104"]


def test_drawing_extractor_fig4_exact_marks_and_uppercase():
    extractor = DrawingExtractor()
    sample_text = """
    [0028] 图4是控制线缆布置的透视图。
    [0056] 如图4所示，控制线缆174在第一侧186布置为第一构造182，并在第二侧194布置为第二构造190。
    在此示例中，机器人臂组件10的手14的手指16通过五组218连接。
    [0057] 如图4所示，控制线缆174限定过渡区198。五组218包括第一组218A、第二组218B、第三组218C、第四组218D和第五组218E。
    """

    drawings = [
        ExtractedDrawing(
            data=b"fake_image_4",
            filename="fig4.png",
            mime_type="image/png",
            sha256="hash4",
            figure_label="图 4",
            order_index=4,
        ),
    ]

    associated = extractor.associate_captions_and_marks(drawings, sample_text)
    assert len(associated) == 1
    d4 = associated[0]
    mark_keys = [m["mark"] for m in d4.reference_marks]
    
    # Must contain 218A-E, 174, 182, 186, 190, 194, 198
    assert "218A" in mark_keys
    assert "218B" in mark_keys
    assert "218C" in mark_keys
    assert "218D" in mark_keys
    assert "218E" in mark_keys
    assert "174" in mark_keys
    assert "182" in mark_keys
    assert "186" in mark_keys
    assert "190" in mark_keys
    assert "194" in mark_keys
    assert "198" in mark_keys
    
    # Macro parent words should be excluded from Figure 4
    assert "10" not in mark_keys
    assert "14" not in mark_keys
    assert "16" not in mark_keys
    assert "218" not in mark_keys  # parent prefix dropped when sub-marks exist


def test_drawing_extractor_claim_marks_and_authority():
    extractor = DrawingExtractor()
    sample_text = """
    1.一种机器人下臂组件，包括：
    前臂构件（12）；
    手构件（14）；
    腕关节（100）；以及
    多个控制线缆（174），其中控制线缆在腕关节处布置为第一构造（182）和第二构造（190），并且限定过渡区（198）。
    
    [0001] 技术领域
    [0028] 图4是控制线缆布置的透视图。
    [0056] 如图4所示，控制线缆174在第一侧186布置为第一构造182，并在第二侧194布置为第二构造190。
    [0057] 如图4所示，控制线缆174限定过渡区198。控制线缆分为五组，包括第一组218A、第二组218B。
    """

    drawings = [
        ExtractedDrawing(
            data=b"fake_image_4",
            filename="fig4.png",
            mime_type="image/png",
            sha256="hash4",
            figure_label="图 4",
            order_index=4,
        ),
    ]

    associated = extractor.associate_captions_and_marks(drawings, sample_text)
    assert len(associated) == 1
    d4 = associated[0]
    marks_by_key = {m["mark"]: m for m in d4.reference_marks}

    # Core claim features should be recognized and tagged with is_claim_feature=True
    assert marks_by_key["174"]["is_claim_feature"] is True
    assert marks_by_key["182"]["is_claim_feature"] is True
    assert marks_by_key["190"]["is_claim_feature"] is True
    assert marks_by_key["198"]["is_claim_feature"] is True
    assert "控制线缆" in marks_by_key["174"]["name"]
    assert "第一构造" in marks_by_key["182"]["name"]


def test_drawing_extractor_claim_numbers_and_hierarchy():
    extractor = DrawingExtractor()
    sample_text = """
    【权利要求书】
    1. 一种机器人组件，包括主干框架（10）和驱动电机（20）。
    2. 根据权利要求1所述的机器人组件，其特征在于，还包括传感模块（30）。
    3. 根据权利要求1或2所述的机器人组件，其特征在于，还包括万向节（40）。

    【说明书附图说明】
    图1是机器人组件的整体结构图。

    【具体实施方式】
    如图1所示，机器人组件包括主干框架10、驱动电机20、传感模块30和万向节40。
    """
    drawings = [
        ExtractedDrawing(
            data=b"fake_image_1",
            filename="fig1.png",
            mime_type="image/png",
            sha256="hash1",
            figure_label="图 1",
            order_index=1,
        )
    ]
    res = extractor.associate_captions_and_marks(drawings, sample_text)
    marks_by_key = {m["mark"]: m for m in res[0].reference_marks}

    # Mark 10 is in independent claim 1
    assert marks_by_key["10"]["is_claim_feature"] is True
    assert 1 in marks_by_key["10"]["claim_numbers"]
    assert marks_by_key["10"]["is_independent"] is True

    # Mark 30 is in dependent claim 2
    assert marks_by_key["30"]["is_claim_feature"] is True
    assert 2 in marks_by_key["30"]["claim_numbers"]
    assert marks_by_key["30"]["is_independent"] is False


def test_drawing_extractor_patent_linter():
    extractor = DrawingExtractor()
    sample_text = """
    【权利要求书】
    1. 一种结构，包括框架（10）和未绘出构件（99）。

    【说明书附图说明】
    图1是框架立体图。
    图2是框架剖面图。
    """
    drawings = [
        ExtractedDrawing(
            data=b"img1",
            filename="fig1.png",
            mime_type="image/png",
            sha256="h1",
            figure_label="图 1",
            reference_marks=[
                {"mark": "10", "name": "支撑框架"},
                {"mark": "20", "name": "连杆"},
            ],
        ),
        ExtractedDrawing(
            data=b"img2",
            filename="fig2.png",
            mime_type="image/png",
            sha256="h2",
            figure_label="图 2",
            reference_marks=[
                {"mark": "10", "name": "主壳体框架"},  # naming drift from 支撑框架
                {"mark": "30", "name": ""},         # undefined mark
            ],
        ),
    ]

    report = extractor.lint_drawing_marks(drawings, sample_text)
    assert report["has_issues"] is True
    issue_types = [i["type"] for i in report["issues"]]
    # Should catch naming drift (10), dangling claim mark (99), and undefined mark (30)
    assert "naming_drift" in issue_types
    assert "dangling_claim_mark" in issue_types
    assert "undefined_mark" in issue_types




