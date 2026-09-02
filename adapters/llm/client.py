from __future__ import annotations

import json
import logging
import os
from typing import Any, Type, TypeVar
import httpx
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LlmError(Exception):
    """Base exception for LLM adapter operations."""
    pass


class LlmConfigurationError(LlmError):
    """Raised when LLM is not configured and no mock/offline fallback is available."""
    pass


class LlmClient:
    """Enterprise OpenAI-compatible client with tenant key override and structured output."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        default_model: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("PATENT_EVIDENCE_LLM_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.api_key = api_key or os.environ.get("PATENT_EVIDENCE_LLM_API_KEY")
        self.default_model = (
            default_model
            or os.environ.get("PATENT_EVIDENCE_LLM_MODEL")
            or "gpt-4o"
        )
        self.timeout_seconds = timeout_seconds

    def is_configured(self) -> bool:
        """Check if client has an active API key configured."""
        return bool(self.api_key)

    async def generate_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        model: str | None = None,
        api_key_override: str | None = None,
        base_url_override: str | None = None,
    ) -> str:
        """Generate plain text completion via chat/completions."""
        active_key = api_key_override or self.api_key
        if not active_key:
            raise LlmConfigurationError(
                "LLM API key is not configured in platform settings or tenant BYOK."
            )

        target_url = f"{base_url_override or self.base_url}/chat/completions"
        target_model = model or self.default_model

        headers = {
            "Authorization": f"Bearer {active_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                resp = await client.post(target_url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as exc:
                logger.error("LLM HTTP error %d: %s", exc.response.status_code, exc.response.text)
                raise LlmError(f"LLM provider error ({exc.response.status_code}): {exc.response.text}") from exc
            except Exception as exc:
                logger.error("LLM request failed: %s", exc)
                raise LlmError(f"LLM request connection failure: {exc}") from exc

    async def generate_structured(
        self,
        messages: list[dict[str, str]],
        response_model: Type[T],
        temperature: float = 0.1,
        model: str | None = None,
        api_key_override: str | None = None,
        base_url_override: str | None = None,
    ) -> T:
        """Generate structured JSON completion parsed into a target Pydantic model."""
        active_key = api_key_override or self.api_key
        if not active_key:
            raise LlmConfigurationError(
                "LLM API key is not configured in platform settings or tenant BYOK."
            )

        target_url = f"{base_url_override or self.base_url}/chat/completions"
        target_model = model or self.default_model

        # Append schema instructions to system message
        schema_json = json.dumps(response_model.model_json_schema(), ensure_ascii=False, indent=2)
        enriched_messages = list(messages)
        enriched_messages.append({
            "role": "system",
            "content": f"You MUST return valid JSON adhering exactly to this JSON Schema:\n{schema_json}\nDo not wrap output in markdown fences or commentary.",
        })

        headers = {
            "Authorization": f"Bearer {active_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": target_model,
            "messages": enriched_messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                resp = await client.post(target_url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                return response_model.model_validate(parsed)
            except (json.JSONDecodeError, ValidationError) as exc:
                logger.error("Failed to parse LLM structured output: %s", exc)
                raise LlmError(f"LLM returned invalid structured format: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                logger.error("LLM HTTP error %d: %s", exc.response.status_code, exc.response.text)
                raise LlmError(f"LLM provider error ({exc.response.status_code}): {exc.response.text}") from exc
            except Exception as exc:
                logger.error("LLM structured request failed: %s", exc)
                raise LlmError(f"LLM structured connection failure: {exc}") from exc
