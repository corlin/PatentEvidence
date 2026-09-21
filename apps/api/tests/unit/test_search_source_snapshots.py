from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from adapters.search.base import (
    BaseSearchAdapter,
    ProviderRecordSnapshot,
    SearchResultItem,
)
from patent_evidence_api.search.services import SearchExecutionService, SearchStrategyService


class ProviderRecordAdapter(BaseSearchAdapter):
    def __init__(self, retrieved_at: datetime) -> None:
        self.retrieved_at = retrieved_at

    async def search(
        self, query: str, limit: int = 20, **kwargs: Any
    ) -> list[SearchResultItem]:
        return [
            SearchResultItem(
                publication_number="DOI:10.1109/lra.2022.3187876",
                title="The SoftHand Pro",
                abstract="Complete official abstract",
                source_type="openalex",
                raw_metadata={
                    "source_url": "https://openalex.org/W4283693873",
                },
                provider_snapshot=ProviderRecordSnapshot.from_record(
                    source_type="openalex",
                    source_identifier="DOI:10.1109/lra.2022.3187876",
                    source_url="https://openalex.org/W4283693873",
                    retrieved_at=self.retrieved_at,
                    record={
                        "id": "https://openalex.org/W4283693873",
                        "doi": "https://doi.org/10.1109/lra.2022.3187876",
                        "display_name": "The SoftHand Pro",
                    },
                ),
            )
        ]


class RecordingSession:
    def __init__(self, candidate_id: UUID) -> None:
        self.candidate_id = candidate_id
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self, statement: Any, params: dict[str, Any] | None = None
    ) -> MagicMock:
        sql = str(statement)
        self.calls.append((sql, params or {}))
        result = MagicMock()
        if "INSERT INTO search_candidates" in sql:
            result.scalar_one.return_value = self.candidate_id
        return result


class StrategySession:
    def __init__(self) -> None:
        self.results = iter(
            (
                SimpleNamespace(
                    fetchone=lambda: SimpleNamespace(
                        technical_field="robotics", title="SoftHand"
                    )
                ),
                SimpleNamespace(fetchone=lambda: SimpleNamespace(id=uuid4())),
                SimpleNamespace(fetchall=lambda: []),
                MagicMock(),
            )
        )

    async def execute(
        self, statement: Any, params: dict[str, Any] | None = None
    ) -> Any:
        return next(self.results)


@pytest.mark.asyncio
async def test_search_strategy_returns_its_persisted_timestamp() -> None:
    now = datetime(2026, 9, 21, 2, 20, tzinfo=timezone.utc)
    result = await SearchStrategyService(clock=lambda: now).generate_strategy(
        StrategySession(),  # type: ignore[arg-type]
        organization_id=uuid4(),
        case_id=uuid4(),
        actor_identity_id=uuid4(),
    )

    assert result["created_at"] == now.isoformat()
    assert result["updated_at"] == now.isoformat()


@pytest.mark.asyncio
async def test_public_search_appends_hashed_raw_source_snapshot() -> None:
    candidate_id = uuid4()
    session = RecordingSession(candidate_id)
    started_at = datetime(2026, 9, 21, 2, 30, tzinfo=timezone.utc)
    provider_retrieved_at = started_at + timedelta(seconds=7)
    results_received_at = provider_retrieved_at + timedelta(seconds=2)
    finished_at = results_received_at + timedelta(seconds=1)
    times = iter((started_at, results_received_at, finished_at))
    service = SearchExecutionService(clock=lambda: next(times))

    result = await service.execute_public_search(
        session,  # type: ignore[arg-type]
        organization_id=uuid4(),
        case_id=uuid4(),
        strategy={"boolean_query_standard": "SoftHand"},
        adapter=ProviderRecordAdapter(provider_retrieved_at),
        actor_identity_id=uuid4(),
        source_type="openalex",
    )

    assert result["results_count"] == 1
    snapshot_calls = [
        (sql, params)
        for sql, params in session.calls
        if "INSERT INTO source_result_snapshots" in sql
    ]
    assert len(snapshot_calls) == 1
    params = snapshot_calls[0][1]
    expected_payload = json.dumps(
        {
            "display_name": "The SoftHand Pro",
            "doi": "https://doi.org/10.1109/lra.2022.3187876",
            "id": "https://openalex.org/W4283693873",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert params["candidate_id"] == candidate_id
    assert params["source_identifier"] == "DOI:10.1109/lra.2022.3187876"
    assert params["source_url"] == "https://openalex.org/W4283693873"
    assert params["payload"] == expected_payload
    assert "payload_sha256" not in params
    assert "encode(sha256" in snapshot_calls[0][0]
    assert params["retrieved_at"] == provider_retrieved_at


def test_provider_record_snapshot_is_canonical_and_rejects_naive_time() -> None:
    retrieved_at = datetime(2026, 9, 21, 2, 30, tzinfo=timezone.utc)
    snapshot = ProviderRecordSnapshot.from_record(
        source_type="openalex",
        source_identifier="OPENALEX:W1",
        source_url="https://openalex.org/W1",
        retrieved_at=retrieved_at,
        record={"z": 1, "a": "证据"},
    )

    assert snapshot.payload_json == '{"a":"证据","z":1}'
    with pytest.raises(ValueError, match="timezone-aware"):
        ProviderRecordSnapshot.from_record(
            source_type="openalex",
            source_identifier="OPENALEX:W1",
            source_url=None,
            retrieved_at=retrieved_at.replace(tzinfo=None),
            record={},
        )

    with pytest.raises(ValueError, match="canonical JSON"):
        ProviderRecordSnapshot(
            source_type="openalex",
            source_identifier="OPENALEX:W1",
            source_url=None,
            retrieved_at=retrieved_at,
            payload_json='{"z": 1, "a": 2}',
        )

    with pytest.raises(ValueError, match="non-finite JSON number"):
        ProviderRecordSnapshot(
            source_type="openalex",
            source_identifier="OPENALEX:W1",
            source_url=None,
            retrieved_at=retrieved_at,
            payload_json='{"score":NaN}',
        )


def test_search_result_rejects_mismatched_provider_snapshot_identity() -> None:
    snapshot = ProviderRecordSnapshot.from_record(
        source_type="openalex",
        source_identifier="OPENALEX:W2",
        source_url=None,
        retrieved_at=datetime.now(timezone.utc),
        record={},
    )

    with pytest.raises(ValueError, match="source identifier"):
        SearchResultItem(
            publication_number="OPENALEX:W1",
            title="Mismatch",
            abstract="",
            source_type="openalex",
            provider_snapshot=snapshot,
        )


def test_search_result_keeps_provider_snapshot_identity_immutable() -> None:
    snapshot = ProviderRecordSnapshot.from_record(
        source_type="openalex",
        source_identifier="OPENALEX:W1",
        source_url="https://openalex.org/W1",
        retrieved_at=datetime.now(timezone.utc),
        record={},
    )
    item = SearchResultItem(
        publication_number="OPENALEX:W1",
        title="Immutable",
        abstract="",
        source_type="openalex",
        raw_metadata={"source_url": "https://openalex.org/W1"},
        provider_snapshot=snapshot,
    )

    with pytest.raises(FrozenInstanceError):
        item.publication_number = "OPENALEX:W2"  # type: ignore[misc]

    assert item.raw_metadata is not None
    with pytest.raises(TypeError):
        item.raw_metadata["source_url"] = "https://example.com/mutated"  # type: ignore[index]

    with pytest.raises(ValueError, match="source URL"):
        SearchResultItem(
            publication_number="OPENALEX:W1",
            title="URL mismatch",
            abstract="",
            source_type="openalex",
            raw_metadata={"source_url": "https://example.com/not-the-source"},
            provider_snapshot=snapshot,
        )


def test_source_snapshot_migration_is_tenant_scoped_and_append_only() -> None:
    migration = (
        Path(__file__).parents[2]
        / "migrations"
        / "versions"
        / "0012_source_result_snapshots.py"
    ).read_text()

    assert '"source_result_snapshots"' in migration
    assert 'enable_force_rls("source_result_snapshots")' in migration
    assert "GRANT SELECT, INSERT ON source_result_snapshots" in migration
    assert '["organization_id", "case_id", "search_job_id"]' in migration
    assert '["organization_id", "case_id", "candidate_id"]' in migration
    assert 'ondelete="CASCADE"' not in migration
    assert "payload_sha256 = encode(sha256" in migration
    assert "GRANT SELECT, INSERT, UPDATE" not in migration
    assert "GRANT SELECT, INSERT, UPDATE, DELETE" not in migration
