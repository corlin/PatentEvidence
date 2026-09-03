from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from adapters.search.epo import EpoSearchAdapter
from adapters.search.uspto import UsptoSearchAdapter
from adapters.search.openalex import OpenAlexSearchAdapter
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
                "abstract_inverted_index": inv_index,
            }
        ]
    }

    with patch("httpx.AsyncClient.get", return_value=fake_resp):
        items = await adapter.search("LLM quantization", limit=5)
        assert len(items) == 1
        assert items[0].publication_number == "DOI:10.1145/12345.67890"
        assert items[0].title == "Empirical Study on LLM Quantization"
        assert items[0].applicant == "Beijing AI Institute"
        assert "A quantized model method." in items[0].abstract
        assert items[0].raw_metadata is not None
        assert "patents.google.com" in items[0].raw_metadata["google_patents_url"]


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
