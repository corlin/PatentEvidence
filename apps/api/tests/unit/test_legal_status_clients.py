"""HTTP clients for legal-status sources: explicit failures, never fabricated status."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from adapters.legal_status.clients import (
    EpoOpsLegalClient,
    LegalStatusSourceError,
    QuotaExceeded,
    UsptoOdpClient,
)


def _run(coro):
    return asyncio.run(coro)


def test_odp_returns_first_file_wrapper_and_sends_key() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("X-API-KEY")
        seen["q"] = request.url.params.get("q")
        return httpx.Response(200, json={"count": 1, "patentFileWrapperDataBag": [{"applicationNumberText": "11543692"}]})

    client = UsptoOdpClient("k", transport=httpx.MockTransport(handler), backoff_seconds=0)
    record = _run(client.file_wrapper("7252747"))
    assert record == {"applicationNumberText": "11543692"}
    assert seen == {"key": "k", "q": "applicationMetaData.patentNumber:7252747"}


@pytest.mark.parametrize("response", [httpx.Response(404, json={"code": "404"}), httpx.Response(200, json={"count": 0})])
def test_odp_not_found_is_none_not_a_status(response: httpx.Response) -> None:
    client = UsptoOdpClient("k", transport=httpx.MockTransport(lambda r: response), backoff_seconds=0)
    assert _run(client.file_wrapper("1")) is None


def test_odp_retries_transient_errors_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("tls eof")
        if calls["n"] == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"patentFileWrapperDataBag": [{"ok": True}]})

    client = UsptoOdpClient("k", transport=httpx.MockTransport(handler), backoff_seconds=0)
    assert _run(client.file_wrapper("1")) == {"ok": True}
    assert calls["n"] == 3


def test_odp_persistent_failure_raises() -> None:
    client = UsptoOdpClient("k", transport=httpx.MockTransport(lambda r: httpx.Response(500)), backoff_seconds=0)
    with pytest.raises(LegalStatusSourceError):
        _run(client.file_wrapper("1"))


def test_odp_requires_a_key(monkeypatch) -> None:
    monkeypatch.delenv("PATENT_EVIDENCE_USPTO_API_KEY", raising=False)
    with pytest.raises(LegalStatusSourceError):
        UsptoOdpClient()


def _ops_handler(legal_response: httpx.Response, counter: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/accesstoken"):
            counter["token"] = counter.get("token", 0) + 1
            return httpx.Response(200, json={"access_token": "t", "expires_in": "1199"})
        counter["legal"] = counter.get("legal", 0) + 1
        counter["auth"] = request.headers.get("Authorization")
        counter["path"] = request.url.path
        return legal_response

    return handler


def test_ops_fetches_legal_with_cached_token() -> None:
    counter: dict = {}
    client = EpoOpsLegalClient(
        "id", "secret", transport=httpx.MockTransport(_ops_handler(httpx.Response(200, json={"ops:legal": []}), counter)),
        backoff_seconds=0,
    )

    async def two_calls():
        await client.legal("EP", "1801605", "B1")
        return await client.legal("EP", "1819002", "B1")

    assert _run(two_calls()) == {"ops:legal": []}
    assert counter["token"] == 1 and counter["legal"] == 2
    assert counter["auth"] == "Bearer t"
    assert counter["path"] == "/3.2/rest-services/legal/publication/docdb/EP.1819002.B1"


def test_ops_not_found_is_none() -> None:
    client = EpoOpsLegalClient("id", "s", transport=httpx.MockTransport(_ops_handler(httpx.Response(404), {})), backoff_seconds=0)
    assert _run(client.legal("EP", "1", "B1")) is None


def test_ops_quota_is_a_distinct_error() -> None:
    response = httpx.Response(403, text="<fault><code>CLIENT.RobotDetected</code><message>quota per week exceeded</message></fault>")
    client = EpoOpsLegalClient("id", "s", transport=httpx.MockTransport(_ops_handler(response, {})), backoff_seconds=0)
    with pytest.raises(QuotaExceeded):
        _run(client.legal("EP", "1", "B1"))


def test_ops_token_failure_raises() -> None:
    client = EpoOpsLegalClient("id", "s", transport=httpx.MockTransport(lambda r: httpx.Response(401)), backoff_seconds=0)
    with pytest.raises(LegalStatusSourceError):
        _run(client.legal("EP", "1", "B1"))


# ------------------------------------------------------------- claim documents (ADR 0009)

GRANT_URI = "https://api.uspto.gov/api/v1/datasets/products/files/PTGRXML-SPLT/2026/ipg260519/1_2.xml"


def test_grant_xml_refuses_urls_outside_uspto() -> None:
    client = UsptoOdpClient("k", transport=httpx.MockTransport(lambda r: httpx.Response(200)), backoff_seconds=0)
    with pytest.raises(LegalStatusSourceError):
        _run(client.grant_xml_response("https://evil.example/files/x.xml"))


def test_grant_xml_follows_signed_redirect_without_key_or_signature() -> None:
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("X-API-KEY")))
        if request.url.host == "api.uspto.gov":
            return httpx.Response(302, headers={"location": "https://data.uspto.gov/files/1_2.xml?Expires=1&Signature=secret"})
        return httpx.Response(200, content=b"<claims/>")

    client = UsptoOdpClient("k", transport=httpx.MockTransport(handler), backoff_seconds=0)
    response = _run(client.grant_xml_response(GRANT_URI))
    assert response.raw == b"<claims/>"
    assert seen[0][1] == "k" and seen[1][1] is None  # key only to api.uspto.gov
    assert "Signature" not in response.request_ref and "secret" not in response.request_ref


def test_grant_xml_refuses_redirect_to_other_host() -> None:
    handler = lambda r: httpx.Response(302, headers={"location": "https://evil.example/x"})  # noqa: E731
    client = UsptoOdpClient("k", transport=httpx.MockTransport(handler), backoff_seconds=0)
    with pytest.raises(LegalStatusSourceError):
        _run(client.grant_xml_response(GRANT_URI))


def test_ops_claims_not_found_is_none() -> None:
    client = EpoOpsLegalClient("id", "s", transport=httpx.MockTransport(_ops_handler(httpx.Response(404), {})), backoff_seconds=0)
    response = _run(client.claims_response("EP", "1819002", "A1"))
    assert response.data is None and response.raw is None
    assert response.request_ref.endswith("/EP.1819002.A1/claims")
