from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping


def _reject_non_finite_json_number(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


@dataclass(frozen=True)
class ProviderRecordSnapshot:
    source_type: str
    source_identifier: str
    source_url: str | None
    retrieved_at: datetime
    payload_json: str

    def __post_init__(self) -> None:
        if not self.source_type.strip():
            raise ValueError("provider snapshot source type is required")
        if not self.source_identifier.strip():
            raise ValueError("provider snapshot source identifier is required")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("provider snapshot retrieved_at must be timezone-aware")
        payload = json.loads(
            self.payload_json,
            parse_constant=_reject_non_finite_json_number,
        )
        if not isinstance(payload, dict):
            raise ValueError("provider snapshot payload must be a JSON object")
        canonical_payload = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if self.payload_json != canonical_payload:
            raise ValueError("provider snapshot payload must be canonical JSON")

    @classmethod
    def from_record(
        cls,
        *,
        source_type: str,
        source_identifier: str,
        source_url: str | None,
        retrieved_at: datetime,
        record: dict[str, Any],
    ) -> ProviderRecordSnapshot:
        return cls(
            source_type=source_type,
            source_identifier=source_identifier,
            source_url=source_url,
            retrieved_at=retrieved_at,
            payload_json=json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )


@dataclass(frozen=True)
class SearchResultItem:
    publication_number: str
    title: str
    abstract: str
    publication_date: str | None = None
    applicant: str | None = None
    ipc_classification: str | None = None
    source_type: str = "google_patents"
    raw_metadata: Mapping[str, Any] | None = None
    provider_snapshot: ProviderRecordSnapshot | None = None

    def __post_init__(self) -> None:
        if self.raw_metadata is not None:
            object.__setattr__(self, "raw_metadata", MappingProxyType(dict(self.raw_metadata)))
        if self.provider_snapshot is None:
            return
        if self.provider_snapshot.source_type != self.source_type:
            raise ValueError("provider snapshot source type does not match result")
        if self.provider_snapshot.source_identifier != self.publication_number:
            raise ValueError("provider snapshot source identifier does not match result")
        if (
            self.raw_metadata is not None
            and "source_url" in self.raw_metadata
            and self.raw_metadata["source_url"] != self.provider_snapshot.source_url
        ):
            raise ValueError("provider snapshot source URL does not match result metadata")


class BaseSearchAdapter(ABC):
    """Abstract interface for external search providers."""

    @abstractmethod
    async def search(self, query: str, limit: int = 20, **kwargs: Any) -> list[SearchResultItem]:
        """Execute search query and return list of result items."""
        raise NotImplementedError
