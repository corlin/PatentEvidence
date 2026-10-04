"""HTTP clients for legal-status sources (ADR 0005 stage 2).

Unlike the search adapters, these never fall back to fixtures or defaults:
a failed lookup raises, so no status is ever fabricated. "Not found" is
returned as ``None`` and must be treated as *unknown*, not as "not in force".
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx


@dataclass(frozen=True)
class SourceResponse:
    """A source answer with the exact bytes received, for hashing and archiving."""

    data: dict[str, Any] | None  # None means "not found" (unknown, not "not in force")
    raw: bytes | None
    request_ref: str  # method + URL + parameters, never credentials


class LegalStatusSourceError(Exception):
    """The source could not answer (transport, server, auth or quota)."""


class QuotaExceeded(LegalStatusSourceError):
    """The source refused because a usage quota or throttle limit was reached."""


async def _get_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
    attempts: int = 3,
    backoff_seconds: float = 2.0,
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = await client.get(url, headers=headers, params=params)
        except httpx.TransportError as exc:  # e.g. TLS EOF seen from OPS during the spike
            last_error = exc
        else:
            if response.status_code in (429, 500, 502, 503, 504):
                last_error = LegalStatusSourceError(f"HTTP {response.status_code} from {url}")
            else:
                return response
        if attempt < attempts - 1:
            await asyncio.sleep(backoff_seconds * (attempt + 1))
    raise LegalStatusSourceError(f"{url} failed after {attempts} attempts: {last_error}")


class UsptoOdpClient:
    """USPTO Open Data Portal file-wrapper lookup by patent number.

    Lookup is by patent number because Google Patents' US ``application_number``
    does not match the USPTO application number (measured 2026-10-04).
    """

    SEARCH_URL = "https://api.uspto.gov/api/v1/patent/applications/search"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 60.0,
        backoff_seconds: float = 2.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("PATENT_EVIDENCE_USPTO_API_KEY")
        if not self.api_key:
            raise LegalStatusSourceError("PATENT_EVIDENCE_USPTO_API_KEY is not configured")
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout_seconds)
        self._backoff = backoff_seconds

    async def aclose(self) -> None:
        await self._client.aclose()

    async def file_wrapper(self, patent_number: str) -> dict[str, Any] | None:
        return (await self.file_wrapper_response(patent_number)).data

    async def file_wrapper_response(self, patent_number: str) -> SourceResponse:
        params = {"q": f"applicationMetaData.patentNumber:{patent_number}", "limit": 1}
        request_ref = f"GET {self.SEARCH_URL}?{urlencode(params)}"
        response = await _get_with_retries(
            self._client,
            self.SEARCH_URL,
            headers={"X-API-KEY": self.api_key or "", "Accept": "application/json"},
            params=params,
            backoff_seconds=self._backoff,
        )
        if response.status_code == 404:
            return SourceResponse(None, None, request_ref)
        if response.status_code in (401, 403):
            raise LegalStatusSourceError(f"USPTO ODP refused the request (HTTP {response.status_code})")
        if response.status_code != 200:
            raise LegalStatusSourceError(f"USPTO ODP HTTP {response.status_code}")
        bag = response.json().get("patentFileWrapperDataBag") or []
        if not bag:
            return SourceResponse(None, None, request_ref)
        return SourceResponse(bag[0], response.content, request_ref)


class EpoOpsLegalClient:
    """EPO OPS 3.2 INPADOC legal events for one publication (docdb format)."""

    BASE_URL = "https://ops.epo.org/3.2"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 60.0,
        backoff_seconds: float = 2.0,
    ) -> None:
        self.client_id = client_id or os.environ.get("PATENT_EVIDENCE_EPO_CLIENT_ID") or os.environ.get("EPO_CLIENT_ID")
        self.client_secret = (
            client_secret
            or os.environ.get("PATENT_EVIDENCE_EPO_CLIENT_SECRET")
            or os.environ.get("EPO_CLIENT_SECRET")
        )
        if not (self.client_id and self.client_secret):
            raise LegalStatusSourceError("EPO OPS credentials are not configured")
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout_seconds)
        self._backoff = backoff_seconds
        self._token: str | None = None
        self._token_expires_at = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        try:
            response = await self._client.post(
                f"{self.BASE_URL}/auth/accesstoken",
                data={"grant_type": "client_credentials"},
                headers={"Authorization": f"Basic {basic}"},
            )
        except httpx.TransportError as exc:
            raise LegalStatusSourceError(f"EPO OPS token request failed: {exc}") from exc
        if response.status_code != 200:
            raise LegalStatusSourceError(f"EPO OPS token request HTTP {response.status_code}")
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.monotonic() + max(int(payload.get("expires_in", 1200)) - 60, 0)
        return self._token

    async def legal(self, country: str, number: str, kind: str) -> dict[str, Any] | None:
        return (await self.legal_response(country, number, kind)).data

    async def legal_response(self, country: str, number: str, kind: str) -> SourceResponse:
        url = f"{self.BASE_URL}/rest-services/legal/publication/docdb/{country}.{number}.{kind}"
        request_ref = f"GET {url}"
        token = await self._access_token()
        response = await _get_with_retries(
            self._client,
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            backoff_seconds=self._backoff,
        )
        if response.status_code == 404:
            return SourceResponse(None, None, request_ref)
        if response.status_code == 403:
            text = response.text
            if "quota" in text.lower() or "throttl" in text.lower():
                raise QuotaExceeded(f"EPO OPS quota or throttle limit: {text[:200]}")
            raise LegalStatusSourceError("EPO OPS refused the request (HTTP 403)")
        if response.status_code != 200:
            raise LegalStatusSourceError(f"EPO OPS HTTP {response.status_code}")
        return SourceResponse(response.json(), response.content, request_ref)
