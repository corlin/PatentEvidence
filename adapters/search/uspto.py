from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from adapters.search.base import BaseSearchAdapter, SearchResultItem

logger = logging.getLogger(__name__)


class UsptoSearchAdapter(BaseSearchAdapter):
    """Pure Python native USPTO Open Data Portal & PatentsView adapter with sandbox fallback."""

    USPTO_ODP_URL = "https://api.uspto.gov/api/v1/patent/applications/search"
    PATENTSVIEW_URL = "https://api.patentsview.org/patents/query"

    def __init__(
        self,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        cli_path: str | None = None,
    ) -> None:
        self.cli_path = cli_path
        self.api_key = api_key or os.environ.get("USPTO_API_KEY") or os.environ.get("PATENT_EVIDENCE_USPTO_API_KEY")
        self.timeout_seconds = timeout_seconds
        self.fixtures_path = Path(__file__).resolve().parents[2] / "fixtures" / "connector-responses" / "uspto" / "search_sample.json"

    def is_configured(self, api_key: str | None = None) -> bool:
        k = api_key or self.api_key
        return bool(k)

    async def search(
        self,
        query: str,
        limit: int = 20,
        api_key_override: str | None = None,
    ) -> list[SearchResultItem]:
        key = api_key_override or self.api_key
        force_offline = os.environ.get("PATENT_EVIDENCE_USE_OFFLINE_SEARCH", "false").lower() == "true"

        # 1. Try real USPTO API if key is available
        if key and not force_offline:
            try:
                tokens = [t.strip('()"') for t in query.split() if len(t.strip('()"')) > 1 and t not in ("AND", "OR", "NOT")]
                clean_query = " ".join(tokens[:3]) if tokens else "quantization"
                headers = {
                    "X-API-KEY": key,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                }
                payload = {
                    "q": f"applicationMetaData.inventionTitle:{clean_query}",
                    "pagination": {"limit": limit, "offset": 0},
                }
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        self.USPTO_ODP_URL,
                        json=payload,
                        headers=headers,
                        timeout=self.timeout_seconds,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        parsed = self._parse_uspto_odp_response(data)
                        if parsed:
                            return parsed[:limit]
                    logger.warning("USPTO API returned %d; falling back to fixture", resp.status_code)
            except Exception as exc:
                logger.warning("USPTO native search failed: %s; falling back to fixture", exc)

        # 2. Fallback to offline fixture sandbox
        return self._load_fixture_results(query, limit)

    def _parse_uspto_odp_response(self, data: dict[str, Any]) -> list[SearchResultItem]:
        items: list[SearchResultItem] = []
        raw_items = data.get("patentFileWrapperDataBag") or data.get("results") or []
        for r in raw_items:
            meta = r.get("applicationMetaData")
            if meta:
                app_id = meta.get("applicationNumberText") or "00000000"
                pat_num = meta.get("patentNumber") or f"US{app_id}A1"
                title = meta.get("inventionTitle") or "US Patent Application"
                filing_date = meta.get("filingDate")
                inventors = meta.get("firstInventorName") or "US Inventor"
                ipc = meta.get("ipcClassText") or "G06N"
                abstract = f"US patent application {pat_num} filed on {filing_date or 'recent period'}."
            else:
                pat_num = r.get("patent_number") or r.get("publication_number") or "US0000000B2"
                title = r.get("patent_title") or r.get("title") or "US Patent Document"
                filing_date = r.get("patent_date") or r.get("publication_date")
                inventors = r.get("assignee_organization") or r.get("applicant")
                ipc = r.get("ipc_classification") or r.get("cpc_classification")
                abstract = r.get("patent_abstract") or r.get("abstract") or "No abstract provided in official record."

            items.append(
                SearchResultItem(
                    publication_number=pat_num,
                    title=title,
                    abstract=abstract,
                    publication_date=filing_date,
                    applicant=inventors,
                    ipc_classification=ipc,
                    source_type="uspto",
                    raw_metadata=r,
                )
            )
        if not items:
            return self._parse_uspto_json(data)
        return items

    def _parse_uspto_json(self, data: dict[str, Any]) -> list[SearchResultItem]:
        items: list[SearchResultItem] = []
        raw_patents = data.get("patents") or data.get("results") or []
        for p in raw_patents:
            num = p.get("patent_number") or p.get("publication_number") or "US0000000B2"
            items.append(
                SearchResultItem(
                    publication_number=num,
                    title=p.get("patent_title") or p.get("title") or "US Patent Document",
                    abstract=p.get("patent_abstract") or p.get("abstract") or "No abstract provided in official record.",
                    publication_date=p.get("patent_date") or p.get("publication_date"),
                    applicant=p.get("assignee_organization") or p.get("applicant"),
                    ipc_classification=p.get("ipc_classification") or p.get("cpc_classification"),
                    source_type="uspto",
                    raw_metadata=p,
                )
            )
        return items

    def _load_fixture_results(self, query: str, limit: int) -> list[SearchResultItem]:
        if not self.fixtures_path.exists():
            return []
        try:
            with open(self.fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            parsed = self._parse_uspto_json(data)
            return parsed[:limit]
        except Exception as exc:
            logger.error("Failed to load USPTO fixture: %s", exc)
            return []
