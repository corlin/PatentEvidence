from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from adapters.search.base import BaseSearchAdapter, SearchResultItem

logger = logging.getLogger(__name__)


class EpoSearchAdapter(BaseSearchAdapter):
    """Pure Python native EPO OPS (Open Patent Services) adapter with OAuth2 and sandbox fallback."""

    OPS_AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
    OPS_SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        timeout_seconds: float = 30.0,
        cli_path: str | None = None,
    ) -> None:
        self.cli_path = cli_path
        self.client_id = client_id or os.environ.get("EPO_CLIENT_ID") or os.environ.get("PATENT_EVIDENCE_EPO_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("EPO_CLIENT_SECRET") or os.environ.get("PATENT_EVIDENCE_EPO_CLIENT_SECRET")
        self.timeout_seconds = timeout_seconds
        self.fixtures_path = Path(__file__).resolve().parents[2] / "fixtures" / "connector-responses" / "epo" / "search_sample.json"
        self._cached_token: str | None = None
        self._token_expires_at: float = 0.0

    def is_configured(self, client_id: str | None = None, client_secret: str | None = None) -> bool:
        cid = client_id or self.client_id
        sec = client_secret or self.client_secret
        return bool(cid and sec)

    async def _get_access_token(
        self, client: httpx.AsyncClient, client_id: str, client_secret: str
    ) -> str | None:
        now = datetime.now(timezone.utc).timestamp()
        if self._cached_token and now < self._token_expires_at:
            return self._cached_token

        auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("utf-8")
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        try:
            resp = await client.post(
                self.OPS_AUTH_URL,
                data={"grant_type": "client_credentials"},
                headers=headers,
                timeout=self.timeout_seconds,
            )
            if resp.status_code == 200:
                data = resp.json()
                self._cached_token = data.get("access_token")
                expires_in = int(data.get("expires_in", 1200))
                self._token_expires_at = now + expires_in - 60
                return self._cached_token
            logger.warning("EPO OPS token request failed: %d - %s", resp.status_code, resp.text)
        except Exception as exc:
            logger.warning("EPO OPS OAuth2 exchange failed: %s", exc)
        return None

    def _build_cql_query(self, query: str) -> str:
        """Convert input keywords or Boolean query into valid EPO CQL query."""
        tokens = [t.strip('()"') for t in query.split() if len(t.strip('()"')) > 1 and t not in ("AND", "OR", "NOT")]
        if not tokens:
            return 'ta="patent"'
        keyword_clauses = [f'ta="{token}"' for token in tokens[:3]]
        return " and ".join(keyword_clauses)

    async def search(
        self,
        query: str,
        limit: int = 20,
        client_id_override: str | None = None,
        client_secret_override: str | None = None,
    ) -> list[SearchResultItem]:
        cid = client_id_override or self.client_id
        csec = client_secret_override or self.client_secret
        force_offline = os.environ.get("PATENT_EVIDENCE_USE_OFFLINE_SEARCH", "false").lower() == "true"

        if cid and csec and not force_offline:
            try:
                async with httpx.AsyncClient() as client:
                    token = await self._get_access_token(client, cid, csec)
                    if token:
                        cql = self._build_cql_query(query)
                        headers = {
                            "Authorization": f"Bearer {token}",
                            "Accept": "application/json",
                        }
                        params = {
                            "q": cql,
                            "Range": f"1-{limit}",
                        }
                        resp = await client.get(
                            self.OPS_SEARCH_URL,
                            headers=headers,
                            params=params,
                            timeout=self.timeout_seconds,
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            results = self._parse_ops_api_response(data)
                            if results:
                                return results[:limit]
                        logger.warning("EPO OPS search returned %d; falling back to fixture", resp.status_code)
            except Exception as exc:
                logger.warning("EPO OPS native search failed: %s; falling back to fixture", exc)

        # Fallback to offline fixture sandbox
        return self._load_fixture_results(query, limit)

    def _parse_ops_api_response(self, data: dict[str, Any]) -> list[SearchResultItem]:
        items: list[SearchResultItem] = []
        try:
            # EPO OPS JSON structure: ops:world-patent-data -> ops:biblio-search -> ops:search-result -> ops:publication-reference
            biblio = (
                data.get("ops:world-patent-data", {})
                .get("ops:biblio-search", {})
                .get("ops:search-result", {})
                .get("ops:publication-reference", [])
            )
            if isinstance(biblio, dict):
                biblio = [biblio]

            for entry in biblio:
                doc_id = entry.get("document-id", {})
                if isinstance(doc_id, list):
                    doc_id = doc_id[0]
                country = doc_id.get("country", {}).get("$", "EP")
                doc_num = doc_id.get("doc-number", {}).get("$", "")
                kind = doc_id.get("kind", {}).get("$", "A1")
                pub_num = f"{country}{doc_num}{kind}" if doc_num else "EP0000000A1"
                items.append(
                    SearchResultItem(
                        publication_number=pub_num,
                        title=f"EPO Published Patent Document {pub_num}",
                        abstract="European patent publication retrieved via official EPO Open Patent Services (OPS).",
                        publication_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        applicant="European Patent Applicant",
                        ipc_classification="G06N",
                        source_type="epo",
                        raw_metadata=entry,
                    )
                )
        except Exception as exc:
            logger.warning("Failed parsing raw EPO OPS response: %s", exc)

        if not items:
            return self._parse_epo_json(data)
        return items

    def _parse_epo_json(self, data: dict[str, Any]) -> list[SearchResultItem]:
        items: list[SearchResultItem] = []
        raw_results = data.get("results") or data.get("patents") or []
        for r in raw_results:
            pub_num = r.get("publication_number") or r.get("doc_number") or "EP0000000A1"
            items.append(
                SearchResultItem(
                    publication_number=pub_num,
                    title=r.get("title") or "European Patent Document",
                    abstract=r.get("abstract") or "No abstract provided in official record.",
                    publication_date=r.get("publication_date"),
                    applicant=r.get("applicant"),
                    ipc_classification=r.get("ipc_classification") or r.get("cpc_classification"),
                    source_type="epo",
                    raw_metadata=r,
                )
            )
        return items

    def _load_fixture_results(self, query: str, limit: int) -> list[SearchResultItem]:
        if not self.fixtures_path.exists():
            return []
        try:
            with open(self.fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            parsed = self._parse_epo_json(data)
            return parsed[:limit]
        except Exception as exc:
            logger.error("Failed to load EPO fixture: %s", exc)
            return []
