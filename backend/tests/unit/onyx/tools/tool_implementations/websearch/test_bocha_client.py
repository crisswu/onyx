from __future__ import annotations

from typing import Any
from typing import cast

import pytest
import requests

import onyx.tools.tool_implementations.web_search.clients.bocha_client as bocha_module
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.tools.tool_implementations.web_search.clients.bocha_client import BochaClient


class DummyResponse:
    def __init__(
        self,
        *,
        status_code: int,
        payload: dict[str, Any] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            http_error = requests.HTTPError(f"{self.status_code} Client Error")
            http_error.response = cast(requests.Response, self)
            raise http_error

    def json(self) -> dict[str, Any]:
        if self._payload is None:
            raise ValueError("No JSON payload")
        return self._payload


def test_search_maps_bocha_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BochaClient(
        api_key="test-key",
        num_results=100,
        timeout_seconds=12,
        freshness="oneWeek",
    )
    captured_payload: dict[str, Any] | None = None

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal captured_payload
        captured_payload = kwargs["json"]
        return DummyResponse(
            status_code=200,
            payload={
                "webPages": {
                    "value": [
                        {
                            "name": "Result 1",
                            "url": "https://example.com/one",
                            "snippet": "Snippet 1",
                            "summary": "Summary 1",
                            "siteName": "Example",
                            "datePublished": "2024-07-22T00:00:00+08:00",
                        },
                        {
                            "name": "Result without URL",
                            "summary": "Should be skipped",
                        },
                    ]
                }
            },
        )

    monkeypatch.setattr(bocha_module.requests, "post", _mock_post)

    results = client.search("onyx")

    assert captured_payload == {
        "query": "onyx",
        "count": 50,
        "summary": True,
        "freshness": "oneWeek",
    }
    assert len(results) == 1
    assert results[0].title == "Result 1"
    assert results[0].link == "https://example.com/one"
    assert results[0].snippet == "Summary 1"
    assert results[0].author == "Example"
    assert results[0].published_date is not None
    assert results[0].published_date.isoformat() == "2024-07-22T00:00:00+08:00"


def test_search_supports_data_wrapped_bocha_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = BochaClient(api_key="test-key", num_results=5)

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            status_code=200,
            payload={
                "data": {
                    "webPages": {
                        "value": [
                            {
                                "name": "Wrapped Result",
                                "url": "https://example.com/wrapped",
                                "snippet": "Wrapped snippet",
                            },
                        ]
                    }
                }
            },
        )

    monkeypatch.setattr(bocha_module.requests, "post", _mock_post)

    results = client.search("onyx")

    assert len(results) == 1
    assert results[0].title == "Wrapped Result"
    assert results[0].link == "https://example.com/wrapped"
    assert results[0].snippet == "Wrapped snippet"


@pytest.mark.parametrize(
    ("freshness", "expected"),
    [
        ("oneDay", "oneDay"),
        ("2026-07-30", "2026-07-30"),
        ("2026-07-01..2026-07-30", "2026-07-01..2026-07-30"),
    ],
)
def test_constructor_accepts_valid_freshness_values(
    freshness: str,
    expected: str,
) -> None:
    client = BochaClient(api_key="test-key", freshness=freshness)

    assert client._freshness == expected  # noqa: SLF001


def test_constructor_rejects_invalid_freshness() -> None:
    with pytest.raises(ValueError, match="freshness"):
        BochaClient(api_key="test-key", freshness="lastHour")


def test_test_connection_maps_invalid_key_errors() -> None:
    client = BochaClient(api_key="test-key")

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        http_error = requests.HTTPError("401 Client Error")
        http_error.response = cast(
            requests.Response,
            DummyResponse(
                status_code=401,
                payload={"code": "unauthorized", "msg": "Invalid API key"},
            ),
        )
        raise http_error

    client.search = _mock_search  # ty: ignore[invalid-assignment]

    with pytest.raises(OnyxError) as exc_info:
        client.test_connection()

    assert exc_info.value.error_code == OnyxErrorCode.CREDENTIAL_INVALID
    assert "Invalid Bocha API key" in exc_info.value.detail


def test_test_connection_maps_rate_limit_errors() -> None:
    client = BochaClient(api_key="test-key")

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        http_error = requests.HTTPError("429 Client Error")
        http_error.response = cast(
            requests.Response,
            DummyResponse(status_code=429, payload={"message": "Too many requests"}),
        )
        raise http_error

    client.search = _mock_search  # ty: ignore[invalid-assignment]

    with pytest.raises(OnyxError) as exc_info:
        client.test_connection()

    assert exc_info.value.error_code == OnyxErrorCode.RATE_LIMITED
    assert "rate limit exceeded" in exc_info.value.detail
