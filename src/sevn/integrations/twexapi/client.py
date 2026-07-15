"""HTTP client for TwexAPI REST endpoints (https://docs.twexapi.io/).

Module: sevn.integrations.twexapi.client
Depends: httpx

Exports:
    TwexApiError — typed TwexAPI failure.
    TwexApiClient — thin Bearer-auth wrapper around TwexAPI paths.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from sevn.integrations.twexapi.config import DEFAULT_TWEXAPI_BASE_URL

_DEFAULT_HTTP_TIMEOUT_S = 60.0

# Curated allowlist keyed to https://docs.twexapi.io/openapi.json paths.
TWEXAPI_OPS: dict[str, tuple[str, str]] = {
    "search": ("POST", "/twitter/advanced_search"),
    "search_page": ("POST", "/twitter/advanced_search/page"),
    "users": ("POST", "/twitter/users"),
    "users_by_ids": ("POST", "/twitter/users/by_ids"),
    "timeline_page": ("POST", "/twitter/{screen_name}/timeline/page"),
    "tweet_detail": ("POST", "/twitter/tweets/lookup"),
    "replies_page": ("POST", "/twitter/tweets/{tweet_id}/replies/page"),
    "trending_topics": ("GET", "/twitter/{country}/trending"),
    "balance": ("GET", "/balance"),
}

# Ops whose JSON body is a raw array (not an object) per OpenAPI.
TWEXAPI_ARRAY_BODY_OPS: frozenset[str] = frozenset({"users", "users_by_ids", "tweet_detail"})

__all__ = [
    "TWEXAPI_ARRAY_BODY_OPS",
    "TWEXAPI_OPS",
    "TwexApiClient",
    "TwexApiError",
]


class TwexApiError(RuntimeError):
    """Raised when a TwexAPI call fails or returns an unexpected shape."""


class TwexApiClient:
    """Minimal TwexAPI REST client (Bearer token auth).

    Args:
        api_key (str): TwexAPI Bearer token.
        base_url (str): API base URL.
        timeout_s (float): Per-request HTTP timeout.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_TWEXAPI_BASE_URL,
        timeout_s: float = _DEFAULT_HTTP_TIMEOUT_S,
    ) -> None:
        """Create a TwexAPI client.

        Args:
            api_key (str): TwexAPI Bearer token.
            base_url (str): API base URL.
            timeout_s (float): Per-request HTTP timeout.

        Examples:
            >>> TwexApiClient("sk")._base_url.startswith("https://")
            True
        """
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        """Build Bearer auth headers.

        Returns:
            dict[str, str]: Request headers.

        Examples:
            >>> TwexApiClient("sk")._headers()["Authorization"]
            'Bearer sk'
        """
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
        path_params: dict[str, str] | None = None,
    ) -> Any:
        """Perform one TwexAPI HTTP request (internal; patchable in tests).

        Args:
            method (str): HTTP method.
            path (str): Path under the API base (may contain ``{placeholders}``).
            params (dict[str, Any] | None): Query string parameters.
            json_body (dict[str, Any] | list[Any] | None): JSON body (object or array).
            path_params (dict[str, str] | None): Values for path placeholders.

        Returns:
            Any: Parsed JSON body (object or list).

        Raises:
            TwexApiError: On HTTP errors or non-JSON payloads.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TwexApiClient("k")._request)
            True
        """
        rendered = path
        if path_params:
            for key, value in path_params.items():
                rendered = rendered.replace("{" + key + "}", quote(str(value), safe=""))
        url = f"{self._base_url}{rendered}"
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            response = await client.request(
                method.upper(),
                url,
                headers=self._headers(),
                params=params,
                json=json_body,
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            msg = f"TwexAPI {method.upper()} {rendered} failed: HTTP {response.status_code}"
            raise TwexApiError(msg) from exc
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            msg = f"TwexAPI {method.upper()} {rendered} returned non-JSON body"
            raise TwexApiError(msg) from exc

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
        path_params: dict[str, str] | None = None,
    ) -> Any:
        """Perform one TwexAPI HTTP request.

        Args:
            method (str): HTTP method.
            path (str): Path under the API base (may contain ``{placeholders}``).
            params (dict[str, Any] | None): Query string parameters.
            json_body (dict[str, Any] | list[Any] | None): JSON body (object or array).
            path_params (dict[str, str] | None): Values for path placeholders.

        Returns:
            Any: Parsed JSON body (object or list).

        Raises:
            TwexApiError: On HTTP errors or non-JSON payloads.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TwexApiClient("k").request)
            True
        """
        return await self._request(
            method,
            path,
            params=params,
            json_body=json_body,
            path_params=path_params,
        )

    async def call_op(
        self,
        op: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | list[Any] | None = None,
        path_params: dict[str, str] | None = None,
    ) -> Any:
        """Dispatch a named allowlisted TwexAPI operation.

        Args:
            op (str): Operation id (see :data:`TWEXAPI_OPS`).
            params (dict[str, Any] | None): Query parameters.
            body (dict[str, Any] | list[Any] | None): JSON body.
            path_params (dict[str, str] | None): Path placeholder values.

        Returns:
            Any: Parsed JSON payload.

        Raises:
            TwexApiError: When ``op`` is unknown or the request fails.

        Examples:
            >>> "search" in TWEXAPI_OPS
            True
        """
        key = op.strip().lower()
        if key not in TWEXAPI_OPS:
            known = ", ".join(sorted(TWEXAPI_OPS))
            msg = f"unknown TwexAPI op {op!r}; known: {known}"
            raise TwexApiError(msg)
        method, path = TWEXAPI_OPS[key]
        return await self._request(
            method,
            path,
            params=params,
            json_body=body,
            path_params=path_params,
        )
