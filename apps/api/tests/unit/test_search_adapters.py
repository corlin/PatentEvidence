from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from adapters.search.epo import EpoSearchAdapter
from adapters.search.uspto import UsptoSearchAdapter
from adapters.search.openalex import OpenAlexSearchAdapter
from patent_evidence_api.search.services import CandidateTriageService
from modules.search.importer import CniprResultsImporter


@pytest.mark.asyncio
async def test_epo_adapter_cql_generation_and_fixture_fallback() -> None:
    adapter = EpoSearchAdapter()
    assert adapter._build_cql_query('("sparse" AND "quantization")') == 'ta="sparse" and ta="quantization"'

    # When no key is provided, falls back cleanly to fixture
    results = await adapter.search("matrix quantization", limit=2)
    assert len(results) >= 1
    assert results[0].source_type == "epo"
    assert "EP" in results[0].publication_number


@pytest.mark.asyncio
async def test_epo_adapter_oauth2_and_live_search() -> None:
    adapter = EpoSearchAdapter(client_id="test_id", client_secret="test_secret")
    assert adapter.is_configured()

    from unittest.mock import MagicMock

    fake_token_resp = MagicMock()
    fake_token_resp.status_code = 200
    fake_token_resp.json.return_value = {"access_token": "mock_token", "expires_in": 1200}

    fake_search_resp = MagicMock()
    fake_search_resp.status_code = 200
    fake_search_resp.json.return_value = {
        "ops:world-patent-data": {
            "ops:biblio-search": {
                "ops:search-result": {
                    "ops:publication-reference": [
                        {
                            "document-id": {
                                "country": {"$": "EP"},
                                "doc-number": {"$": "4123456"},
                                "kind": {"$": "A1"},
                            }
                        }
                    ]
                }
            }
        }
    }

    with patch("httpx.AsyncClient.post", return_value=fake_token_resp):
        with patch("httpx.AsyncClient.get", return_value=fake_search_resp):
            items = await adapter.search("quantization", limit=5)
            assert len(items) == 1
            assert items[0].publication_number == "EP4123456A1"
            assert items[0].source_type == "epo"


@pytest.mark.asyncio
async def test_uspto_adapter_fixture_fallback_and_key_override() -> None:
    adapter = UsptoSearchAdapter()
    assert not adapter.is_configured()

    # Fallback to fixture
    items = await adapter.search("sparse attention", limit=2)
    assert len(items) >= 1
    assert items[0].source_type == "uspto"
    assert "US" in items[0].publication_number

    from unittest.mock import MagicMock
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "patentFileWrapperDataBag": [
            {
                "applicationMetaData": {
                    "applicationNumberText": "16123456",
                    "patentNumber": "US11888999B2",
                    "inventionTitle": "Quantization Engine for Neural Acceleration",
                    "filingDate": "2023-05-10",
                    "firstInventorName": "Smith; John",
                    "ipcClassText": "G06F 17/16",
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post", return_value=fake_resp):
        results = await adapter.search("quantization", api_key_override="custom-key-123")
        assert len(results) == 1
        assert results[0].publication_number == "US11888999B2"
        assert "Quantization Engine" in results[0].title
        assert results[0].applicant == "Smith; John"


@pytest.mark.asyncio
async def test_openalex_adapter_abstract_reconstruction_and_parsing() -> None:
    adapter = OpenAlexSearchAdapter()
    inv_index = {"A": [0], "quantized": [1], "model": [2], "method.": [3]}
    abstract = adapter._reconstruct_abstract(inv_index)
    assert abstract == "A quantized model method."

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "results": [
            {
                "id": "https://openalex.org/W99999",
                "doi": "https://doi.org/10.1145/12345.67890",
                "title": "Empirical Study on LLM Quantization",
                "publication_year": 2024,
                "publication_date": "2024-02-18",
                "authorships": [
                    {
                        "author": {"display_name": "Alice Researcher"},
                        "institutions": [{"display_name": "Beijing AI Institute"}],
                    }
                ],
                "primary_topic": {"display_name": "Machine Learning"},
                "primary_location": {
                    "landing_page_url": "https://doi.org/10.1145/12345.67890",
                    "source": {"display_name": "Journal of Reliable Evidence"},
                },
                "type": "article",
                "abstract_inverted_index": inv_index,
            }
        ]
    }

    with patch("httpx.AsyncClient.get", return_value=fake_resp):
        items = await adapter.search("LLM quantization", limit=5)
        assert len(items) == 1
        assert items[0].publication_number == "DOI:10.1145/12345.67890"
        assert items[0].title == "Empirical Study on LLM Quantization"
        assert items[0].applicant is None
        assert items[0].ipc_classification is None
        assert "A quantized model method." in items[0].abstract
        assert items[0].raw_metadata is not None
        assert "patents.google.com" in items[0].raw_metadata["google_patents_url"]
        assert items[0].raw_metadata["authors"] == ["Alice Researcher"]
        assert items[0].raw_metadata["institutions"] == ["Beijing AI Institute"]
        assert items[0].raw_metadata["journal"] == "Journal of Reliable Evidence"
        assert items[0].raw_metadata["primary_topic"] == "Machine Learning"
        assert items[0].raw_metadata["work_type"] == "article"
        assert items[0].raw_metadata["source_url"] == "https://doi.org/10.1145/12345.67890"


@pytest.mark.asyncio
async def test_openalex_adapter_exact_doi_preserves_full_abstract() -> None:
    adapter = OpenAlexSearchAdapter()
    long_index = {f"word{index}": [index] for index in range(120)}
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "id": "https://openalex.org/W4283693873",
        "doi": "https://doi.org/10.1109/lra.2022.3187876",
        "display_name": "The SoftHand Pro",
        "publication_date": "2022-07-05",
        "authorships": [],
        "abstract_inverted_index": long_index,
    }

    with patch("httpx.AsyncClient.get", return_value=fake_resp) as get:
        items = await adapter.search("DOI:10.1109/LRA.2022.3187876", limit=5)

    assert len(items) == 1
    assert items[0].publication_number == "DOI:10.1109/lra.2022.3187876"
    assert items[0].abstract.endswith("word119")
    assert not items[0].abstract.endswith("...")
    assert get.call_args.args[0].endswith(
        "/works/https://doi.org/10.1109/LRA.2022.3187876"
    )


@pytest.mark.asyncio
async def test_openalex_adapter_zero_results_and_provider_failure_do_not_fabricate_candidates() -> None:
    adapter = OpenAlexSearchAdapter()
    empty_resp = MagicMock()
    empty_resp.status_code = 200
    empty_resp.json.return_value = {"results": []}

    with patch("httpx.AsyncClient.get", return_value=empty_resp):
        assert await adapter.search("a query with no result") == []

    with patch("httpx.AsyncClient.get", side_effect=TimeoutError("provider unavailable")):
        with pytest.raises(TimeoutError, match="provider unavailable"):
            await adapter.search("a query during outage")

    failed_request = httpx.Request("GET", adapter.OPENALEX_API_URL)
    failed_response = httpx.Response(503, request=failed_request)
    with patch("httpx.AsyncClient.get", return_value=failed_response):
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.search("a query during provider failure")


@pytest.mark.asyncio
async def test_openalex_adapter_exact_openalex_id_lookup() -> None:
    adapter = OpenAlexSearchAdapter()
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "id": "https://openalex.org/W4283693873",
        "display_name": "The SoftHand Pro",
        "authorships": [],
    }

    with patch("httpx.AsyncClient.get", return_value=fake_resp) as get:
        items = await adapter.search("https://openalex.org/W4283693873")

    assert len(items) == 1
    assert items[0].publication_number == "OPENALEX:W4283693873"
    assert get.call_args.args[0].endswith("/works/W4283693873")


@pytest.mark.asyncio
async def test_candidate_listing_returns_stored_raw_metadata() -> None:
    raw_metadata = {
        "doi": "https://doi.org/10.1109/lra.2022.3187876",
        "authors": ["Cosimo Della Santina"],
        "source_url": "https://openalex.org/W4283693873",
    }
    row = SimpleNamespace(
        id=uuid4(),
        publication_number="DOI:10.1109/lra.2022.3187876",
        publication_number_normalized="DOI101109LRA20223187876",
        title="The SoftHand Pro",
        abstract="Complete abstract",
        publication_date="2022-07-05",
        applicant="Cosimo Della Santina",
        ipc_classification="Robotics",
        source_type="openalex",
        raw_metadata=json.dumps(raw_metadata),
        relevance_score=95,
        created_at=datetime.now(timezone.utc),
        triage_status="pending",
        exclusion_reason=None,
        notes=None,
        triaged_at=None,
    )
    result = MagicMock()
    result.fetchall.return_value = [row]
    session = SimpleNamespace(execute=AsyncMock(return_value=result))

    items = await CandidateTriageService().list_candidates(
        session, uuid4(), uuid4()
    )

    assert items[0]["raw_metadata"] == raw_metadata


def test_cnipr_importer_official_sample() -> None:
    importer = CniprResultsImporter()
    sample_csv = """公开(公告)号,发明名称,申请人/专利权人,公开(公告)日,主分类号,摘要
CN117283912A,大模型量化系统,华为技术有限公司,2024-03-15,G06N 3/08,特征分析与低秩奇异值分解混合量化。
CN116549201B,稀疏矩阵计算介质,百度在线网络技术,2023-11-20,G06F 17/16,针对大模型注意力层激活值动态范围。"""

    candidates = importer.import_from_csv(sample_csv)
    assert len(candidates) == 2
    assert candidates[0].publication_number == "CN117283912A"
    assert candidates[0].publication_number_normalized == "CN117283912A"
    assert candidates[0].title == "大模型量化系统"
    assert candidates[0].applicant == "华为技术有限公司"
    assert candidates[0].ipc_classification == "G06N 3/08"

    assert candidates[1].publication_number == "CN116549201B"
    assert candidates[1].applicant == "百度在线网络技术"
