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

# Curated allowlist keyed to https://docs.twexapi.io/openapi.json (+ v3 thread).
TWEXAPI_OPS: dict[str, tuple[str, str]] = {
    "search": ("POST", "/twitter/advanced_search"),
    "search_page": ("POST", "/twitter/advanced_search/page"),
    "hashtags": ("POST", "/twitter/hashtags"),
    "users": ("POST", "/twitter/users"),
    "users_by_ids": ("POST", "/twitter/users/by_ids"),
    "timeline_page": ("POST", "/twitter/{screen_name}/timeline/page"),
    "tweet_detail": ("POST", "/twitter/tweets/lookup"),
    "replies_page": ("POST", "/twitter/tweets/{tweet_id}/replies/page"),
    "trending_topics": ("GET", "/twitter/{country}/trending"),
    "balance": ("GET", "/balance"),
    # §4 tweet-actions / users / articles (cookie-bearing writes where noted)
    "like_tweet": ("POST", "/twitter/tweets/{tweet_id}/like"),
    "unlike_tweet": ("DELETE", "/twitter/tweets/{tweet_id}/like"),
    "retweet": ("POST", "/twitter/tweets/{tweet_id}/retweet"),
    "delete_retweet": ("DELETE", "/twitter/tweets/{tweet_id}/retweet"),
    "bookmark": ("POST", "/twitter/tweets/{tweet_id}/bookmark"),
    "delete_bookmark": ("DELETE", "/twitter/tweets/{tweet_id}/bookmark"),
    "create_tweet_or_reply": ("POST", "/twitter/tweets/create"),
    "create_quote_tweet": ("POST", "/twitter/tweets/quote"),
    "create_tweet_thread": ("POST", "/v3/twitter/tweets/create-thread"),
    "delete_tweets": ("POST", "/twitter/tweets/delete-batch"),
    "post_tweet_auto_cookie": ("POST", "/twitter/post-tweet-without-cookie"),
    "follow_user": ("POST", "/twitter/user/follow"),
    "fetch_article_markdown": ("GET", "/x/article/{tweet_id}/markdown"),
}

# Ops whose JSON body is a raw array (not an object) per OpenAPI.
TWEXAPI_ARRAY_BODY_OPS: frozenset[str] = frozenset({"users", "users_by_ids", "tweet_detail"})

# Cookie-bearing write ops (DB7/DB8) — require operator cookie (and often proxy).
TWEXAPI_WRITE_OPS: frozenset[str] = frozenset(
    {
        "like_tweet",
        "unlike_tweet",
        "retweet",
        "delete_retweet",
        "bookmark",
        "delete_bookmark",
        "create_tweet_or_reply",
        "create_quote_tweet",
        "create_tweet_thread",
        "delete_tweets",
        "follow_user",
    }
)

__all__ = [
    "TWEXAPI_ARRAY_BODY_OPS",
    "TWEXAPI_OPS",
    "TWEXAPI_WRITE_OPS",
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
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.request(
                    method.upper(),
                    url,
                    headers=self._headers(),
                    params=params,
                    json=json_body,
                )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Never echo response body — may contain cookie/proxy echoes.
            status = exc.response.status_code if exc.response is not None else "?"
            msg = f"TwexAPI {method.upper()} {rendered} failed: HTTP {status}"
            raise TwexApiError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"TwexAPI {method.upper()} {rendered} failed: {type(exc).__name__}"
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

    async def call_write_op(
        self,
        op: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        path_params: dict[str, str] | None = None,
        cookie: str | None = None,
        proxy: str | None = None,
    ) -> Any:
        """Dispatch a cookie-bearing TwexAPI write operation (DB7).

        Merges ``cookie`` / ``proxy`` into the JSON body. Secret values are never
        included in raised :class:`TwexApiError` messages (convention 13).

        Args:
            op (str): Write op id (must be in :data:`TWEXAPI_WRITE_OPS`).
            params (dict[str, Any] | None): Query parameters.
            body (dict[str, Any] | None): Additional JSON body fields.
            path_params (dict[str, str] | None): Path placeholder values.
            cookie (str | None): Operator Twitter cookie / auth_token.
            proxy (str | None): Optional residential proxy URL.

        Returns:
            Any: Parsed JSON payload.

        Raises:
            TwexApiError: When ``op`` is not a write op, cookie is missing, or
                the HTTP call fails.

        Examples:
            >>> "like_tweet" in TWEXAPI_WRITE_OPS
            True
        """
        key = op.strip().lower()
        if key not in TWEXAPI_WRITE_OPS:
            known = ", ".join(sorted(TWEXAPI_WRITE_OPS))
            msg = f"not a TwexAPI write op {op!r}; known: {known}"
            raise TwexApiError(msg)
        if not isinstance(cookie, str) or not cookie.strip():
            raise TwexApiError("TwexAPI write op requires cookie")
        merged: dict[str, Any] = dict(body or {})
        merged["cookie"] = cookie.strip()
        if isinstance(proxy, str) and proxy.strip():
            merged["proxy"] = proxy.strip()
        try:
            return await self.call_op(
                key,
                params=params,
                body=merged,
                path_params=path_params,
            )
        except TwexApiError:
            raise
        except Exception as exc:
            msg = f"TwexAPI write op {key!r} failed: {type(exc).__name__}"
            raise TwexApiError(msg) from exc
