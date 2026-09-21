from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class SearchResultItem:
    publication_number: str
    title: str
    abstract: str
    publication_date: str | None = None
    applicant: str | None = None
    ipc_classification: str | None = None
    source_type: str = "google_patents"
    raw_metadata: dict[str, Any] | None = None
    provider_record: dict[str, Any] | None = None


class BaseSearchAdapter(ABC):
    """Abstract interface for external search providers."""

    @abstractmethod
    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> list[SearchResultItem]:
        """Execute search query and return list of result items."""
        raise NotImplementedError
