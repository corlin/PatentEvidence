import pytest
from unittest.mock import patch, MagicMock
from adapters.search.uspto import UsptoSearchAdapter


@pytest.mark.asyncio
async def test_uspto_adapter_fallback_to_fixture_sandbox():
    adapter = UsptoSearchAdapter(cli_path="/nonexistent/path/uspto-cli")
    results = await adapter.search("quantization sparse", limit=5)

    assert len(results) >= 1
    assert results[0].source_type == "uspto"
    assert results[0].publication_number.startswith("US")
    assert "Neural" in results[0].title or "Matrix" in results[0].title or "Quantiz" in results[0].title


@pytest.mark.asyncio
async def test_uspto_adapter_native_with_per_user_key():
    adapter = UsptoSearchAdapter(api_key="secret-user-key")

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "results": [
            {
                "patent_number": "US9999999B2",
                "patent_title": "Subprocess USPTO Patent",
                "patent_abstract": "Mock USPTO abstract",
            }
        ]
    }

    with patch("httpx.AsyncClient.post", return_value=fake_resp) as mock_post:
        results = await adapter.search("transformer sparse", limit=2)
        assert len(results) == 1
        assert results[0].publication_number == "US9999999B2"
        assert results[0].source_type == "uspto"

        # Verify API key was passed in header
        headers = mock_post.call_args[1]["headers"]
        assert headers["X-API-KEY"] == "secret-user-key"
