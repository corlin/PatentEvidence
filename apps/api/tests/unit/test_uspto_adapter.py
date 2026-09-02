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
async def test_uspto_adapter_subprocess_with_per_user_key():
    adapter = UsptoSearchAdapter(cli_path="/usr/local/bin/uspto-cli", api_key="secret-user-key")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = '{"patents": [{"patent_number": "US9999999B2", "patent_title": "Subprocess USPTO Patent", "patent_abstract": "Mock USPTO abstract"}]}'

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        results = await adapter.search("transformer sparse", limit=2)
        assert len(results) == 1
        assert results[0].publication_number == "US9999999B2"
        assert results[0].source_type == "uspto"

        # Verify per-user API key was passed in environment
        env = mock_run.call_args[1]["env"]
        assert env["USPTO_API_KEY"] == "secret-user-key"
