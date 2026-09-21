from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from adapters.search.base import BaseSearchAdapter, SearchResultItem
from patent_evidence_api.search.services import SearchExecutionService, SearchStrategyService


class ProviderRecordAdapter(BaseSearchAdapter):
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
                provider_record={
                    "id": "https://openalex.org/W4283693873",
                    "doi": "https://doi.org/10.1109/lra.2022.3187876",
                    "display_name": "The SoftHand Pro",
                },
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
    retrieved_at = started_at + timedelta(seconds=7)
    finished_at = retrieved_at + timedelta(seconds=1)
    times = iter((started_at, retrieved_at, finished_at))
    service = SearchExecutionService(clock=lambda: next(times))

    result = await service.execute_public_search(
        session,  # type: ignore[arg-type]
        organization_id=uuid4(),
        case_id=uuid4(),
        strategy={"boolean_query_standard": "SoftHand"},
        adapter=ProviderRecordAdapter(),
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
    assert params["retrieved_at"] == retrieved_at


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
