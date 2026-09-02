import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from adapters.llm.client import LlmClient, LlmError, LlmConfigurationError
from adapters.llm.schemas import FeatureExtractionResultSchema, FeatureItemSchema


@pytest.mark.asyncio
async def test_llm_client_missing_key_raises_configuration_error():
    client = LlmClient(api_key=None)
    with patch.dict("os.environ", {}, clear=True):
        client.api_key = None
        with pytest.raises(LlmConfigurationError, match="not configured"):
            await client.generate_completion([{"role": "user", "content": "hello"}])


@pytest.mark.asyncio
async def test_llm_client_generate_structured_success():
    client = LlmClient(api_key="sk-test-mock-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"technical_field": "AI", "technical_problem": "Latency", "features": [{"feature_code": "F1", "feature_type": "preamble", "feature_statement": "A neural accelerator", "source_paragraph_id": "0001", "citation_quote": "A neural accelerator is provided."}]}'
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await client.generate_structured(
            messages=[{"role": "user", "content": "Extract features"}],
            response_model=FeatureExtractionResultSchema,
        )

        assert isinstance(res, FeatureExtractionResultSchema)
        assert res.technical_field == "AI"
        assert len(res.features) == 1
        assert res.features[0].feature_code == "F1"
        assert res.features[0].feature_type == "preamble"


@pytest.mark.asyncio
async def test_llm_client_tenant_byok_override():
    client = LlmClient(api_key="default-key", base_url="https://default.api.com")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "tenant output"}}]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        output = await client.generate_completion(
            messages=[{"role": "user", "content": "hi"}],
            api_key_override="tenant-custom-key",
            base_url_override="https://tenant-private-gateway.com/v1",
        )

        assert output == "tenant output"
        # Verify the custom tenant credentials were used in the request
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://tenant-private-gateway.com/v1/chat/completions"
        assert call_args[1]["headers"]["Authorization"] == "Bearer tenant-custom-key"
