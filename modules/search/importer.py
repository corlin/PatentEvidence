from __future__ import annotations

import csv
import io
import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ImportedCandidate:
    publication_number: str
    publication_number_normalized: str
    title: str
    abstract: str
    publication_date: str | None = None
    applicant: str | None = None
    ipc_classification: str | None = None
    source_type: str = "cnipr_manual"
    raw_metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_pub_number(pub_no: str) -> str:
    """Normalize publication number by removing spaces, dots, hyphens and uppercasing."""
    cleaned = re.sub(r"[\s\.\-_/]", "", pub_no).upper()
    return cleaned


class CniprResultsImporter:
    """Parses CNIPR official CSV/Excel exports or formatted text into structured candidates."""

    def import_from_csv(self, csv_content: str) -> list[ImportedCandidate]:
        results: list[ImportedCandidate] = []
        if not csv_content.strip():
            return results

        # Try to detect delimiter (comma, tab, semicolon)
        sample = csv_content[:1024]
        delimiter = "\t" if "\t" in sample else ","

        reader = csv.reader(io.StringIO(csv_content), delimiter=delimiter)
        rows = list(reader)
        if not rows:
            return results

        # Header detection
        headers = [h.strip() for h in rows[0]]
        pub_idx = -1
        title_idx = -1
        abs_idx = -1
        date_idx = -1
        app_idx = -1
        ipc_idx = -1

        for i, h in enumerate(headers):
            h_clean = h.lower().replace("（", "(").replace("）", ")").strip()
            if any(k in h_clean for k in ("公开号", "公告号", "公开(公告)号", "申请号", "申请(专利)号", "pub_no", "publication", "doc_number")):
                if pub_idx == -1:
                    pub_idx = i
            elif any(k in h_clean for k in ("发明名称", "专利名称", "名称", "标题", "题名", "title")):
                if title_idx == -1:
                    title_idx = i
            elif any(k in h_clean for k in ("摘要", "文摘", "摘要(文摘)", "abstract")):
                if abs_idx == -1:
                    abs_idx = i
            elif any(k in h_clean for k in ("公开日", "公告日", "公开(公告)日", "申请日", "date")):
                if date_idx == -1:
                    date_idx = i
            elif any(k in h_clean for k in ("申请人", "专利权人", "申请人/专利权人", "当前权利人", "applicant", "assignee")):
                if app_idx == -1:
                    app_idx = i
            elif any(k in h_clean for k in ("主分类号", "分类号", "ipc", "cpc")):
                if ipc_idx == -1:
                    ipc_idx = i

        start_row = 1 if pub_idx != -1 else 0
        if pub_idx == -1:
            pub_idx = 0
            title_idx = 1 if len(headers) > 1 else 0

        for row in rows[start_row:]:
            if not row or len(row) <= pub_idx or not row[pub_idx].strip():
                continue

            raw_pub = row[pub_idx].strip()
            norm_pub = normalize_pub_number(raw_pub)
            if not norm_pub:
                continue

            title = row[title_idx].strip() if title_idx >= 0 and len(row) > title_idx else f"专利 {norm_pub}"
            abstract = row[abs_idx].strip() if abs_idx >= 0 and len(row) > abs_idx else ""
            pub_date = row[date_idx].strip() if date_idx >= 0 and len(row) > date_idx else None
            applicant = row[app_idx].strip() if app_idx >= 0 and len(row) > app_idx else None
            ipc = row[ipc_idx].strip() if ipc_idx >= 0 and len(row) > ipc_idx else None

            results.append(
                ImportedCandidate(
                    publication_number=raw_pub,
                    publication_number_normalized=norm_pub,
                    title=title or f"专利 {norm_pub}",
                    abstract=abstract,
                    publication_date=pub_date,
                    applicant=applicant,
                    ipc_classification=ipc,
                    source_type="cnipr_manual",
                    raw_metadata={"raw_row": row},
                )
            )

        return results

    def import_from_text(self, text: str) -> list[ImportedCandidate]:
        """Parse raw text lines (e.g. publication numbers or tab-separated entries)."""
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        results: list[ImportedCandidate] = []

        for line in lines:
            if "\t" in line or "," in line:
                # Delegate to CSV parser for line
                parsed = self.import_from_csv(line)
                results.extend(parsed)
            else:
                norm_pub = normalize_pub_number(line)
                if norm_pub:
                    results.append(
                        ImportedCandidate(
                            publication_number=line,
                            publication_number_normalized=norm_pub,
                            title=f"专利 {norm_pub}",
                            abstract="",
                            source_type="cnipr_manual",
                        )
                    )
        return results
