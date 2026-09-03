import pytest
from unittest.mock import patch, MagicMock
from adapters.search.epo import EpoSearchAdapter


@pytest.mark.asyncio
async def test_epo_adapter_fallback_to_fixture_sandbox():
    adapter = EpoSearchAdapter(cli_path="/nonexistent/path/epo-cli")
    results = await adapter.search("quantization sparse", limit=5)

    assert len(results) >= 1
    assert results[0].source_type == "epo"
    assert results[0].publication_number.startswith("EP")
    assert "Neural" in results[0].title or "Quantiz" in results[0].title


@pytest.mark.asyncio
async def test_epo_adapter_native_parsing():
    adapter = EpoSearchAdapter(client_id="test_id", client_secret="test_secret")

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "results": [
            {
                "publication_number": "EP9999999A1",
                "title": "Subprocess Test Patent",
                "abstract": "Mock abstract",
            }
        ]
    }

    with patch("adapters.search.epo.EpoSearchAdapter._get_access_token", return_value="token123"):
        with patch("httpx.AsyncClient.get", return_value=fake_resp):
            results = await adapter.search("neural accelerator", limit=2)
            assert len(results) == 1
            assert results[0].publication_number == "EP9999999A1"
            assert results[0].title == "Subprocess Test Patent"
            assert results[0].source_type == "epo"
