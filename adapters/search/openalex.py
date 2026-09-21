from __future__ import annotations

import logging
import re
import urllib.parse
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import httpx

from adapters.search.base import (
    BaseSearchAdapter,
    ProviderRecordSnapshot,
    SearchResultItem,
)

logger = logging.getLogger(__name__)
Clock = Callable[[], datetime]


def default_clock() -> datetime:
    return datetime.now(timezone.utc)


class OpenAlexSearchAdapter(BaseSearchAdapter):
    """Pure Python native adapter for OpenAlex worldwide public patent & research repository."""

    OPENALEX_API_URL = "https://api.openalex.org/works"

    def __init__(
        self,
        timeout_seconds: float = 30.0,
        clock: Clock = default_clock,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.clock = clock

    def _reconstruct_abstract(self, inverted_index: dict[str, list[int]] | None) -> str:
        if not inverted_index:
            return ""
        words: list[tuple[int, str]] = []
        for word, positions in inverted_index.items():
            for pos in positions:
                words.append((pos, word))
        words.sort(key=lambda x: x[0])
        return " ".join(w[1] for w in words)

    def _extract_doi(self, query: str) -> str | None:
        match = re.fullmatch(
            r"\s*(?:(?:https?://(?:dx\.)?doi\.org/)|(?:doi:\s*))?(10\.\d{4,9}/\S+)\s*",
            query,
            flags=re.IGNORECASE,
        )
        return match.group(1) if match else None

    def _extract_openalex_id(self, query: str) -> str | None:
        match = re.fullmatch(
            r"\s*(?:https?://openalex\.org/)?(W\d+)\s*",
            query,
            flags=re.IGNORECASE,
        )
        return match.group(1).upper() if match else None

    @staticmethod
    def _unique_names(values: list[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))

    def _parse_work(
        self, work: dict[str, Any], retrieved_at: datetime
    ) -> SearchResultItem:
        doi = work.get("doi")
        openalex_id = work.get("id")
        identifier = doi or openalex_id or ""
        publication_number = identifier.replace("https://doi.org/", "DOI:").replace(
            "https://openalex.org/", "OPENALEX:"
        )
        title = work.get("title") or work.get("display_name") or "Untitled OpenAlex work"
        abstract = self._reconstruct_abstract(work.get("abstract_inverted_index"))
        publication_date = work.get("publication_date")
        if not publication_date and work.get("publication_year"):
            publication_date = str(work["publication_year"])

        authorships = work.get("authorships") or []
        authors = self._unique_names(
            [authorship.get("author", {}).get("display_name", "") for authorship in authorships]
        )
        institutions = self._unique_names(
            [
                institution.get("display_name", "")
                for authorship in authorships
                for institution in (authorship.get("institutions") or [])
            ]
        )
        primary_topic = work.get("primary_topic") or {}
        topic = primary_topic.get("display_name")
        primary_location = work.get("primary_location") or {}
        source = primary_location.get("source") or {}
        source_url = primary_location.get("landing_page_url") or openalex_id
        google_patents_url = f"https://patents.google.com/?q={urllib.parse.quote_plus(title)}"

        return SearchResultItem(
            publication_number=publication_number,
            title=title,
            abstract=abstract,
            publication_date=publication_date,
            applicant=None,
            ipc_classification=None,
            source_type="openalex",
            raw_metadata={
                "doi": doi,
                "openalex_id": openalex_id,
                "authors": authors,
                "institutions": institutions,
                "primary_topic": topic,
                "journal": source.get("display_name"),
                "work_type": work.get("type"),
                "publication_date": publication_date,
                "source_url": source_url,
                "google_patents_url": google_patents_url,
                "cited_by_count": work.get("cited_by_count", 0),
            },
            provider_snapshot=ProviderRecordSnapshot.from_record(
                source_type="openalex",
                source_identifier=publication_number,
                source_url=source_url,
                retrieved_at=retrieved_at,
                record=work,
            ),
        )

    async def search(self, query: str, limit: int = 20) -> list[SearchResultItem]:
        # Extract meaningful search keywords
        tokens = [t.strip('()"') for t in query.split() if len(t.strip('()"')) > 1 and t not in ("AND", "OR", "NOT")]
        clean_query = " ".join(tokens[:4]) if tokens else "machine learning patent"

        headers = {
            "User-Agent": "PatentEvidence-Search/1.0 (mailto:admin@patent.com)",
            "Accept": "application/json",
        }
        doi = self._extract_doi(query)
        openalex_id = self._extract_openalex_id(query)
        url = self.OPENALEX_API_URL
        params: dict[str, Any] = {"search": clean_query, "per_page": min(limit, 25)}
        if doi:
            url = f"{self.OPENALEX_API_URL}/https://doi.org/{doi}"
            params = {}
        elif openalex_id:
            url = f"{self.OPENALEX_API_URL}/{openalex_id}"
            params = {}
        direct_lookup = doi is not None or openalex_id is not None

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=self.timeout_seconds,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    retrieved_at = self.clock()
                    works = [data] if direct_lookup else data.get("results", [])
                    return [self._parse_work(work, retrieved_at) for work in works]
                if direct_lookup and resp.status_code == 404:
                    return []
                resp.raise_for_status()
        except Exception as exc:
            logger.warning("OpenAlex live search request failed: %r", exc)
            raise
        return []
