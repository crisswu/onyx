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

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_REQUEST_TIMEOUT_SECONDS = 60


class TavilyClient(WebSearchProvider):
    def __init__(self, api_key: str, num_results: int = 10) -> None:
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._num_results = max(1, num_results)

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> list[WebSearchResult]:
        payload: dict[str, Any] = {
            "query": query,
            "max_results": self._num_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }

        response = requests.post(
            TAVILY_SEARCH_URL,
            headers=self._headers,
            json=payload,
            timeout=TAVILY_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        data = response.json()
        raw_results = data.get("results") or []

        results: list[WebSearchResult] = []
        for raw_result in raw_results:
            if not isinstance(raw_result, dict):
                continue

            link = _clean_string(raw_result.get("url"))
            if not link:
                continue

            results.append(
                WebSearchResult(
                    title=_clean_string(raw_result.get("title")),
                    link=link,
                    snippet=_clean_string(raw_result.get("content")),
                    author=None,
                    published_date=_parse_published_date(
                        _clean_string(raw_result.get("published_date"))
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
                    "Tavily API key validation failed: search returned no results.",
                )
        except OnyxError:
            raise
        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            error_msg = _build_error_message(e.response) if e.response else str(e)
            if status_code in {401, 403}:
                raise OnyxError(
                    OnyxErrorCode.CREDENTIAL_INVALID,
                    f"Invalid Tavily API key: {error_msg}",
                ) from e
            if status_code == 429:
                raise OnyxError(
                    OnyxErrorCode.RATE_LIMITED,
                    f"Tavily API rate limit exceeded: {error_msg}",
                ) from e
            raise OnyxError(
                OnyxErrorCode.CREDENTIAL_INVALID,
                f"Tavily API key validation failed: {error_msg}",
            ) from e
        except Exception as e:
            raise OnyxError(
                OnyxErrorCode.CREDENTIAL_INVALID,
                f"Tavily API key validation failed: {e}",
            ) from e

        logger.info("Web search provider test succeeded for Tavily.")
        return {"status": "ok"}


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
    return str(data)
