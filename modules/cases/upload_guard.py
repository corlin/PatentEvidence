"""Server-side inspection of uploaded source documents (spec §6.2 step 2).

"服务端执行 MIME、扩展名、大小和恶意文件检查" — this module decides from the
bytes themselves, never from the client-supplied Content-Type:

- size: non-empty and within the limit;
- extension: ``.docx`` or ``.pdf`` only;
- type: the content must actually be that format (PDF header / OOXML word
  package), and the stored MIME type is the detected one;
- malicious content: structural checks for the active-content vectors that
  matter for these two formats.

Two tiers, because real disclosures routinely carry some active content
(MathType/Visio equations are OLE objects; CAD-exported PDFs and vendor
datasheets carry JavaScript):

- **rejected** — clearly weaponised or unsafe to process: DOCX macros and
  executable/macro-enabled embeddings, DDE fields, external templates/frames/
  OLE links pointing at network locations, zip bombs, malformed packages; PDF
  Launch/SubmitForm/ImportData actions, PDFs that need a real password, and
  unreadable PDFs. Raises :class:`UploadRejected` with a stable code.
- **recorded** — accepted, but returned as ``findings`` so they are stored on
  the document, written to the audit log and shown to the user: PDF
  JavaScript, embedded files, RichMedia, XFA forms; DOCX OLE embeddings and
  ActiveX controls. The parser only extracts text and never executes them.

PDFs encrypted only to restrict permissions (empty open password) are common
(datasheets, CNKI theses) and are accepted; pypdf opens them transparently.

These are deterministic structural checks, not a signature AV scan.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject

MAX_FILE_SIZE = 30 * 1024 * 1024  # 30 MB

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME = "application/pdf"

# DOCX（zip）解压防护：条目数、解压总量、单条目压缩比
_MAX_ZIP_ENTRIES = 5_000
_MAX_UNCOMPRESSED_TOTAL = 300 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 200
_RATIO_CHECK_MIN_SIZE = 1024 * 1024

_DOCX_MAIN_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
_MACRO_CONTENT_TYPE_MARKER = "macroEnabled"
# 外部关系中可被 Word 自动拉取/执行的类型（超链接等被动引用不在此列）
_DANGEROUS_EXTERNAL_RELATIONSHIPS = {
    "attachedTemplate",
    "oleObject",
    "frame",
    "subDocument",
    "externalLinkPath",
}
_URL_SCHEME_RE = re.compile(r"^([a-z][a-z0-9+.-]*):", re.IGNORECASE)
_DRIVE_RE = re.compile(r"^[a-z]:", re.IGNORECASE)
# 可执行或带宏的嵌入物 → 拒绝；其余 OLE 嵌入（.bin，如 MathType/Visio）→ 记录
_REJECTED_EMBEDDING_SUFFIXES = (".xlsm", ".docm", ".pptm", ".xlsb", ".exe", ".dll", ".js", ".vbs", ".scr", ".bat", ".cmd", ".ps1")
_DDE_RE = re.compile(rb"<w:instrText[^>]*>\s*DDE(AUTO)?\b|w:instr=\"\s*DDE(AUTO)?\b", re.IGNORECASE)
_RELS_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

# PDF：启动外部程序或向外提交/导入数据的动作 → 拒绝
_PDF_REJECTED_NAMES = {"Launch", "SubmitForm", "ImportData"}
# PDF：常见于正常文档的主动内容 → 接收并记录
_PDF_RECORDED_NAMES = {
    "JavaScript": "pdf_javascript",
    "JS": "pdf_javascript",
    "EmbeddedFile": "pdf_embedded_files",
    "EmbeddedFiles": "pdf_embedded_files",
    "RichMedia": "pdf_rich_media",
    "XFA": "pdf_xfa_form",
}
_PDF_NAME_RE = re.compile(rb"/([A-Za-z0-9#]+)")
# 流体是任意（通常已压缩的）二进制，偶然出现 "/JS" 等字节序列属常态，不参与原始扫描
_PDF_STREAM_BODY_RE = re.compile(rb"stream\r?\n.*?endstream", re.DOTALL)
_PDF_HEX_ESCAPE_RE = re.compile(r"#([0-9A-Fa-f]{2})")
_MAX_PDF_OBJECTS = 500_000


class UploadRejected(Exception):
    """上传文件未通过检查；``code`` 为稳定的机器可读原因。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class UploadVerdict:
    kind: str  # "docx" | "pdf"
    mime_type: str
    findings: tuple[str, ...] = ()  # 已接收但需记录的主动内容（排序、去重）


def inspect_upload(filename: str, data: bytes, *, max_size: int = MAX_FILE_SIZE) -> UploadVerdict:
    """检查上传文件；通过则返回按内容判定的类型，否则抛出 UploadRejected。"""
    if not data:
        raise UploadRejected("empty_file")
    if len(data) > max_size:
        raise UploadRejected("file_size_exceeds_30mb_limit")

    dot_idx = filename.rfind(".")
    ext = filename[dot_idx:].lower() if dot_idx != -1 else ""
    if ext == ".docx":
        return UploadVerdict("docx", DOCX_MIME, _inspect_docx(data))
    if ext == ".pdf":
        return UploadVerdict("pdf", PDF_MIME, _inspect_pdf(data))
    raise UploadRejected("unsupported_file_format_only_docx_and_pdf")


def _inspect_docx(data: bytes) -> tuple[str, ...]:
    if not data.startswith(b"PK\x03\x04"):
        raise UploadRejected("file_content_does_not_match_extension")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()
    except (zipfile.BadZipFile, ValueError) as exc:
        raise UploadRejected("file_content_does_not_match_extension") from exc

    if len(infos) > _MAX_ZIP_ENTRIES:
        raise UploadRejected("suspicious_archive_structure")
    total = 0
    names: set[str] = set()
    for info in infos:
        name = info.filename
        if name.startswith("/") or "\\" in name or ".." in name.split("/"):
            raise UploadRejected("suspicious_archive_structure")
        total += info.file_size
        if total > _MAX_UNCOMPRESSED_TOTAL:
            raise UploadRejected("suspicious_archive_structure")
        if (
            info.file_size >= _RATIO_CHECK_MIN_SIZE
            and info.file_size > _MAX_COMPRESSION_RATIO * max(info.compress_size, 1)
        ):
            raise UploadRejected("suspicious_archive_structure")
        names.add(name)

    if "[Content_Types].xml" not in names or "word/document.xml" not in names:
        raise UploadRejected("file_content_does_not_match_extension")

    content_types = _read_member(archive, "[Content_Types].xml")
    if _MACRO_CONTENT_TYPE_MARKER.encode() in content_types:
        raise UploadRejected("macros_not_allowed")
    if _DOCX_MAIN_CONTENT_TYPE.encode() not in content_types:
        raise UploadRejected("file_content_does_not_match_extension")

    findings: set[str] = set()
    for name in names:
        lower = name.lower()
        if lower.endswith("vbaproject.bin") or lower.startswith("word/vba"):
            raise UploadRejected("macros_not_allowed")
        if lower.startswith("word/embeddings/"):
            if lower.endswith(_REJECTED_EMBEDDING_SUFFIXES):
                raise UploadRejected("embedded_active_content_not_allowed")
            if lower.endswith(".bin"):
                findings.add("docx_ole_embedding")
        if lower.startswith("word/activex/"):
            findings.add("docx_activex_control")

    for name in names:
        if name.endswith(".rels"):
            _check_relationships(_read_member(archive, name))

    for name in names:
        if name.startswith("word/") and name.endswith(".xml") and _DDE_RE.search(
            _read_member(archive, name)
        ):
            raise UploadRejected("dde_field_not_allowed")
    return tuple(sorted(findings))


def _read_member(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        return archive.read(name)
    except (zipfile.BadZipFile, KeyError, RuntimeError, ValueError, OSError) as exc:
        raise UploadRejected("suspicious_archive_structure") from exc


def _check_relationships(xml_bytes: bytes) -> None:
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as exc:
        raise UploadRejected("suspicious_archive_structure") from exc
    for rel in root.iter(f"{_RELS_NS}Relationship"):
        if rel.get("TargetMode") != "External":
            continue
        rel_type = (rel.get("Type") or "").rsplit("/", 1)[-1]
        if rel_type in _DANGEROUS_EXTERNAL_RELATIONSHIPS and _is_network_target(
            rel.get("Target") or ""
        ):
            raise UploadRejected("external_resource_reference_not_allowed")


def _is_network_target(target: str) -> bool:
    """外部目标是否指向网络位置（可被远程拉取，如远程模板注入）。

    本地路径（``file:///C:\\...``、``C:\\...``、``file:///Users/...``、相对路径）
    是 Word 文档常见的模板残留，无法远程拉取，放行；其余一律视为网络位置：
    非 file 的 URL 方案、``file://host/``、UNC（``\\\\server``、``//server``、
    ``file:////server``、``file:///\\\\server``）。
    """
    value = target.strip()
    scheme = _URL_SCHEME_RE.match(value)
    if scheme and not _DRIVE_RE.match(value):
        if scheme.group(1).lower() != "file":
            return True
        path = value[len(scheme.group(0)):]
        slashes = len(path) - len(path.lstrip("/\\"))
        # 2 个分隔符 = file://host/；≥4 个 = UNC（file:////server、file:///\\server）
        return slashes == 2 or slashes >= 4
    return value.startswith(("\\\\", "//"))


def _normalize_pdf_name(raw: str) -> str:
    """还原 #xx 转义（如 /J#61vaScript），防止名字混淆绕过检查。"""
    return _PDF_HEX_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), raw)


def _pdf_name_verdict(name: str, findings: set[str]) -> None:
    if name in _PDF_REJECTED_NAMES:
        raise UploadRejected("pdf_active_content_not_allowed")
    if name in _PDF_RECORDED_NAMES:
        findings.add(_PDF_RECORDED_NAMES[name])


def _inspect_pdf(data: bytes) -> tuple[str, ...]:
    if not data.startswith(b"%PDF-"):
        raise UploadRejected("file_content_does_not_match_extension")

    # 1) 原始字节扫描（跳过流体）：覆盖未压缩对象及 xref 之外的残留对象
    findings: set[str] = set()
    for match in _PDF_NAME_RE.finditer(_PDF_STREAM_BODY_RE.sub(b"stream endstream", data)):
        _pdf_name_verdict(_normalize_pdf_name(match.group(1).decode("latin-1")), findings)

    # 2) 解析扫描：覆盖对象流（ObjStm）中压缩存放的对象
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        # pypdf 会自动以空密码打开仅限制权限的 PDF；空密码打不开的才需要真实密码
        if reader.is_encrypted and not reader.decrypt(""):
            raise UploadRejected("password_protected_pdf_not_supported")
        object_ids: list[tuple[int, int]] = [
            (num, gen) for gen, entries in reader.xref.items() for num in entries
        ]
        object_ids.extend((num, 0) for num in reader.xref_objStm)
        if len(object_ids) > _MAX_PDF_OBJECTS:
            raise UploadRejected("suspicious_pdf_structure")
        for num, gen in object_ids:
            for name in _object_names(reader.get_object(IndirectObject(num, gen, reader))):
                _pdf_name_verdict(name, findings)
    except UploadRejected:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
        raise UploadRejected("unreadable_pdf") from exc
    return tuple(sorted(findings))


def _object_names(obj: object) -> set[str]:
    """单个对象中出现的全部名字（字典键与名字值；不跟随间接引用，每个对象单独检查）。"""
    names: set[str] = set()
    stack = [obj]
    while stack:
        current = stack.pop()
        if isinstance(current, DictionaryObject):
            for key, value in current.items():
                names.add(str(key).lstrip("/"))
                stack.append(value)
        elif isinstance(current, ArrayObject):
            stack.extend(current)
        elif isinstance(current, NameObject):
            names.add(str(current).lstrip("/"))
    return names
