from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.tools.tool_implementations.web_search.models import WebSearchProvider
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

BOCHA_WEB_SEARCH_URL = "https://api.bochaai.com/v1/web-search"
BOCHA_MAX_RESULTS_PER_REQUEST = 50
BOCHA_REQUEST_TIMEOUT_SECONDS = 60
BOCHA_FRESHNESS_OPTIONS = {
    "noLimit",
    "oneYear",
    "oneMonth",
    "oneWeek",
    "oneDay",
}


class BochaClient(WebSearchProvider):
    def __init__(
        self,
        api_key: str,
        *,
        num_results: int = 10,
        timeout_seconds: int = BOCHA_REQUEST_TIMEOUT_SECONDS,
        freshness: str | None = None,
        summary: bool = True,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Bocha provider config 'timeout_seconds' must be > 0.")

        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._num_results = max(1, min(num_results, BOCHA_MAX_RESULTS_PER_REQUEST))
        self._timeout_seconds = timeout_seconds
        self._freshness = _normalize_freshness(freshness)
        self._summary = summary

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> list[WebSearchResult]:
        payload: dict[str, Any] = {
            "query": query,
            "count": self._num_results,
            "summary": self._summary,
        }
        if self._freshness is not None:
            payload["freshness"] = self._freshness

        response = requests.post(
            BOCHA_WEB_SEARCH_URL,
            headers=self._headers,
            json=payload,
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()

        data = response.json()
        web_pages = _extract_web_pages(data)
        raw_results = web_pages.get("value") if isinstance(web_pages, dict) else []

        results: list[WebSearchResult] = []
        if not isinstance(raw_results, list):
            return results

        for raw_result in raw_results:
            if not isinstance(raw_result, dict):
                continue

            link = _clean_string(raw_result.get("url"))
            if not link:
                continue

            results.append(
                WebSearchResult(
                    title=_clean_string(raw_result.get("name")),
                    link=link,
                    snippet=_build_snippet(raw_result),
                    author=_clean_string(raw_result.get("siteName")) or None,
                    published_date=_parse_published_date(
                        _clean_string(raw_result.get("datePublished"))
                    ),
                )
            )

        return results

    def test_connection(self) -> dict[str, str]:
        try:
            test_results = self.search("test")
            if not test_results or not any(result.link for result in test_results):
                raise OnyxError(
                    OnyxErrorCode.CREDENTIAL_INVALID,
                    "Bocha API key validation failed: search returned no results.",
                )
        except OnyxError:
            raise
        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            error_msg = _build_error_message(e.response) if e.response else str(e)
            if status_code in {401, 403}:
                raise OnyxError(
                    OnyxErrorCode.CREDENTIAL_INVALID,
                    f"Invalid Bocha API key: {error_msg}",
                ) from e
            if status_code == 429:
                raise OnyxError(
                    OnyxErrorCode.RATE_LIMITED,
                    f"Bocha API rate limit exceeded: {error_msg}",
                ) from e
            raise OnyxError(
                OnyxErrorCode.CREDENTIAL_INVALID,
                f"Bocha API key validation failed: {error_msg}",
            ) from e
        except Exception as e:
            raise OnyxError(
                OnyxErrorCode.CREDENTIAL_INVALID,
                f"Bocha API key validation failed: {e}",
            ) from e

        logger.info("Web search provider test succeeded for Bocha.")
        return {"status": "ok"}


def _extract_web_pages(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}

    direct_web_pages = data.get("webPages")
    if isinstance(direct_web_pages, dict):
        return direct_web_pages

    nested_data = data.get("data")
    if isinstance(nested_data, dict):
        nested_web_pages = nested_data.get("webPages")
        if isinstance(nested_web_pages, dict):
            return nested_web_pages

    return {}


def _build_snippet(raw_result: dict[str, Any]) -> str:
    summary = _clean_string(raw_result.get("summary"))
    if summary:
        return summary
    return _clean_string(raw_result.get("snippet"))


def _clean_string(value: Any) -> str:
    return str(value or "").strip()


def _parse_published_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _build_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:500]

    if isinstance(data, dict):
        detail = data.get("detail") or data.get("error") or data.get("message")
        if detail:
            return str(detail)

        code = data.get("code")
        msg = data.get("msg")
        if code or msg:
            return f"{code}: {msg}" if code and msg else str(code or msg)

    return str(data)


def _normalize_freshness(freshness: str | None) -> str | None:
    if freshness is None:
        return None

    normalized = freshness.strip()
    if not normalized:
        return None
    if normalized in BOCHA_FRESHNESS_OPTIONS:
        return normalized
    if _is_iso_date(normalized) or _is_iso_date_range(normalized):
        return normalized

    raise ValueError(
        "Bocha provider config 'freshness' must be one of "
        "noLimit, oneYear, oneMonth, oneWeek, oneDay, YYYY-MM-DD, "
        "or YYYY-MM-DD..YYYY-MM-DD."
    )


def _is_iso_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _is_iso_date_range(value: str) -> bool:
    start, separator, end = value.partition("..")
    if not separator:
        return False
    return _is_iso_date(start) and _is_iso_date(end)
