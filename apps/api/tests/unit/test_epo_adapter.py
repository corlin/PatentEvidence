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
async def test_epo_adapter_subprocess_parsing():
    adapter = EpoSearchAdapter(cli_path="/usr/local/bin/epo-cli")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = '{"results": [{"publication_number": "EP9999999A1", "title": "Subprocess Test Patent", "abstract": "Mock abstract"}]}'

    with patch("subprocess.run", return_value=mock_proc):
        results = await adapter.search("neural accelerator", limit=2)
        assert len(results) == 1
        assert results[0].publication_number == "EP9999999A1"
        assert results[0].title == "Subprocess Test Patent"
        assert results[0].source_type == "epo"
