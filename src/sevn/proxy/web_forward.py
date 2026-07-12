"""Generic web fetch + Brave search forwarders for agent web tools (`specs/07-egress-proxy.md`).

Holds provider keys (Brave) on the proxy process; gateway tool host calls these routes
with session / shared-secret headers only.

Module: sevn.proxy.web_forward
Depends: httpx, sevn.proxy.settings

Exports:
    web_fetch_json — execute an outbound HTTP request and return a JSON-safe payload.
    brave_search_json — call Brave Search API with proxy-held credentials.

Examples:
    >>> "GET" in ALLOWED_FETCH_METHODS
    True
"""

from __future__ import annotations

from typing import Any, Final
from urllib.parse import urlparse

import httpx
from loguru import logger

from sevn.proxy.http_client import PROXY_HTTP_LIMITS, build_proxy_upstream_timeout
from sevn.proxy.settings import ProxySettings

ALLOWED_FETCH_METHODS: Final[frozenset[str]] = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}
)
MAX_HTML_FETCH_CHARS: Final[int] = 1_000_000
_DEFAULT_CHUNK_LENGTH: Final[int] = 10_000
_MIN_CHUNK_LENGTH: Final[int] = 256
_MAX_CHUNK_LENGTH: Final[int] = 100_000
_LOW_CONTENT_CHAR_THRESHOLD: Final[int] = 2_000
_DEFAULT_UA: Final[str] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_DEFAULT_ACCEPT: Final[str] = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
_DEFAULT_ACCEPT_LANGUAGE: Final[str] = "en-US,en;q=0.9"
_BRAVE_SEARCH_URL: Final[str] = "https://api.search.brave.com/res/v1/web/search"


def _validate_fetch_url(url: str) -> str | None:
    """Return an error message when ``url`` is not an http(s) URL.

    Args:
        url (str): Candidate URL from the tool payload.

    Returns:
        str | None: Human-readable error or ``None`` when valid.

    Examples:
        >>> _validate_fetch_url("https://example.com") is None
        True
        >>> _validate_fetch_url("file:///etc/passwd") is not None
        True
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return "url must use http or https"
    if not parsed.netloc:
        return "url must include a host"
    return None


def _parse_chunk_params(payload: dict[str, Any]) -> tuple[int | None, int | None]:
    """Parse optional ``byte_offset`` / ``chunk_length`` for chunked fetch mode.

    Args:
        payload (dict[str, Any]): Tool POST body.

    Returns:
        tuple[int | None, int | None]: ``(byte_offset, chunk_length)`` when chunk
        mode is requested, otherwise ``(None, None)``.

    Examples:
        >>> _parse_chunk_params({"url": "https://x", "byte_offset": 0})
        (0, 10000)
        >>> _parse_chunk_params({"url": "https://x"})
        (None, None)
    """
    if "byte_offset" not in payload:
        return None, None
    try:
        offset = max(0, int(payload["byte_offset"]))
    except (TypeError, ValueError):
        return None, None
    raw_chunk = payload.get("chunk_length", _DEFAULT_CHUNK_LENGTH)
    try:
        chunk_len = int(raw_chunk)
    except (TypeError, ValueError):
        chunk_len = _DEFAULT_CHUNK_LENGTH
    chunk_len = max(_MIN_CHUNK_LENGTH, min(chunk_len, _MAX_CHUNK_LENGTH))
    return offset, chunk_len


def _default_fetch_headers() -> dict[str, str]:
    """Return browser-like default headers for upstream HTML fetches.

    Returns:
        dict[str, str]: ``User-Agent``, ``Accept``, and ``Accept-Language``.

    Examples:
        >>> hdrs = _default_fetch_headers()
        >>> "User-Agent" in hdrs and "Accept" in hdrs
        True
    """
    return {
        "User-Agent": _DEFAULT_UA,
        "Accept": _DEFAULT_ACCEPT,
        "Accept-Language": _DEFAULT_ACCEPT_LANGUAGE,
    }


def _merge_fetch_headers(caller_headers: dict[str, str]) -> dict[str, str]:
    """Merge caller headers over :func:`_default_fetch_headers`.

    Args:
        caller_headers (dict[str, str]): Optional overrides from the tool payload.

    Returns:
        dict[str, str]: Merged outbound headers (caller wins on key collision).

    Examples:
        >>> merged = _merge_fetch_headers({"User-Agent": "custom"})
        >>> merged["User-Agent"]
        'custom'
        >>> "Accept-Language" in merged
        True
    """
    merged = _default_fetch_headers()
    merged.update(caller_headers)
    return merged


def _response_headers_dict(headers: httpx.Headers) -> dict[str, str]:
    """Normalize response headers to a lowercase-key dict.

    Args:
        headers (httpx.Headers): Upstream response headers.

    Returns:
        dict[str, str]: Lowercase header names to values.

    Examples:
        >>> _response_headers_dict(httpx.Headers({"Content-Length": "10"}))
        {'content-length': '10'}
    """
    return {k.lower(): v for k, v in headers.items()}


def _parse_content_length(headers: dict[str, str]) -> int | None:
    """Parse ``Content-Length`` when present and numeric.

    Args:
        headers (dict[str, str]): Lowercase response headers.

    Returns:
        int | None: Declared body length in bytes, or ``None``.

    Examples:
        >>> _parse_content_length({"content-length": "50000"})
        50000
        >>> _parse_content_length({}) is None
        True
    """
    raw = headers.get("content-length")
    if raw is None:
        return None
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return None


def _parse_content_range_total(headers: dict[str, str]) -> int | None:
    """Parse total entity length from a ``Content-Range`` header.

    Args:
        headers (dict[str, str]): Lowercase response headers.

    Returns:
        int | None: Total bytes when ``bytes */total`` or ``start-end/total`` is present.

    Examples:
        >>> _parse_content_range_total({"content-range": "bytes 0-499/50000"})
        50000
        >>> _parse_content_range_total({"content-range": "bytes */50000"})
        50000
    """
    raw = headers.get("content-range")
    if raw is None or "/" not in raw:
        return None
    total_s = raw.rsplit("/", 1)[-1].strip()
    if total_s == "*":
        return None
    try:
        return max(0, int(total_s))
    except (TypeError, ValueError):
        return None


def _headers_suggest_larger_body(headers: dict[str, str], body_byte_len: int) -> bool:
    """Return whether response headers imply more bytes than were received.

    Args:
        headers (dict[str, str]): Lowercase upstream response headers.
        body_byte_len (int): Decoded body length in bytes.

    Returns:
        bool: ``True`` when ``Content-Length`` or ``Content-Range`` exceeds ``body_byte_len``.

    Examples:
        >>> _headers_suggest_larger_body({"content-length": "50000"}, 500)
        True
        >>> _headers_suggest_larger_body({"content-length": "100"}, 500)
        False
    """
    content_length = _parse_content_length(headers)
    if content_length is not None and content_length > body_byte_len:
        return True
    range_total = _parse_content_range_total(headers)
    return range_total is not None and range_total > body_byte_len


def _needs_low_content_retry(
    status_code: int,
    text: str,
    headers: dict[str, str],
) -> bool:
    """Return whether a streaming fetch should retry once with a full GET.

    Args:
        status_code (int): Upstream HTTP status from the first stream.
        text (str): Decoded response body.
        headers (dict[str, str]): Lowercase upstream response headers.

    Returns:
        bool: ``True`` for HTTP 206 or thin bodies when headers imply more content.

    Examples:
        >>> _needs_low_content_retry(206, "css", {})
        True
        >>> _needs_low_content_retry(200, "x" * 100, {"content-length": "50000"})
        True
    """
    if status_code == 206:
        return True
    body_byte_len = len(text.encode("utf-8"))
    return len(text) < _LOW_CONTENT_CHAR_THRESHOLD and _headers_suggest_larger_body(
        headers,
        body_byte_len,
    )


def _is_still_low_content(status_code: int, text: str) -> bool:
    """Return whether a body is still considered low-content after retry.

    Args:
        status_code (int): Upstream HTTP status after retry.
        text (str): Decoded response body after retry.

    Returns:
        bool: ``True`` when status is 206 or decoded text is below the threshold.

    Examples:
        >>> _is_still_low_content(200, "x" * 100)
        True
        >>> _is_still_low_content(200, "x" * 3000)
        False
    """
    return status_code == 206 or len(text) < _LOW_CONTENT_CHAR_THRESHOLD


async def _fetch_upstream_streaming(
    *,
    url: str,
    headers: dict[str, str],
    max_chars: int | None,
    client: httpx.AsyncClient,
    request_timeout: httpx.Timeout | None = None,
) -> tuple[int, str, str, bool, dict[str, str]]:
    """Stream a GET response until character cap or EOF.

    Args:
        url (str): Target URL.
        headers (dict[str, str]): Outbound request headers.
        max_chars (int | None): Character cap; ``None`` uses ``MAX_HTML_FETCH_CHARS``.
        client (httpx.AsyncClient): Shared or short-lived httpx client.
        request_timeout (httpx.Timeout | None): Per-request timeout override for large pages.

    Returns:
        tuple[int, str, str, bool, dict[str, str]]: ``(status_code, content_type, text,
        truncated, response_headers)`` with lowercase response header keys.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_fetch_upstream_streaming)
        True
    """
    char_cap = max_chars if max_chars is not None else MAX_HTML_FETCH_CHARS
    buf = bytearray()
    status_code = 0
    content_type = ""
    response_headers: dict[str, str] = {}
    request_timeout = request_timeout or build_proxy_upstream_timeout(max_html_chars=char_cap)
    async with client.stream(
        "GET",
        url,
        headers=headers,
        follow_redirects=True,
        timeout=request_timeout,
    ) as resp:
        status_code = resp.status_code
        content_type = resp.headers.get("content-type", "")
        response_headers = _response_headers_dict(resp.headers)
        async for chunk in resp.aiter_bytes():
            buf.extend(chunk)
            text_so_far = bytes(buf).decode("utf-8", errors="replace")
            if len(text_so_far) >= char_cap:
                break
    text = bytes(buf).decode("utf-8", errors="replace")
    truncated = len(text) > char_cap
    if truncated:
        text = text[:char_cap]
    return status_code, content_type, text, truncated, response_headers


def _build_fetch_response(
    *,
    url: str,
    method: str,
    status_code: int,
    content_type: str,
    text: str,
    truncated: bool,
    byte_offset: int | None = None,
    bytes_returned: int | None = None,
    eof: bool | None = None,
    streamed: bool | None = None,
    low_content: bool | None = None,
) -> dict[str, Any]:
    """Build the JSON body for ``web_fetch_json`` success responses.

    Args:
        url (str): Requested URL.
        method (str): HTTP verb.
        status_code (int): Upstream HTTP status.
        content_type (str): Upstream ``Content-Type`` header value.
        text (str): Response body text (possibly truncated).
        truncated (bool): Whether ``max_length`` truncated the body.
        byte_offset (int | None): Chunk start offset when chunk mode is active.
        bytes_returned (int | None): Bytes returned in this chunk.
        eof (bool | None): Whether no further bytes remain upstream.
        streamed (bool | None): Whether the body was assembled via streaming GET.
        low_content (bool | None): Whether the body remained thin after optional retry.

    Returns:
        dict[str, Any]: JSON-safe payload.

    Examples:
        >>> body = _build_fetch_response(
        ...     url="https://x",
        ...     method="GET",
        ...     status_code=200,
        ...     content_type="text/html",
        ...     text="hi",
        ...     truncated=False,
        ... )
        >>> body["text"]
        'hi'
    """
    body: dict[str, Any] = {
        "url": url,
        "method": method,
        "status_code": status_code,
        "content_type": content_type,
        "text": text,
        "truncated": truncated,
    }
    if byte_offset is not None:
        body["byte_offset"] = byte_offset
        body["bytes_returned"] = bytes_returned if bytes_returned is not None else 0
        body["eof"] = bool(eof)
    if streamed is not None:
        body["streamed"] = streamed
    if low_content is not None:
        body["low_content"] = low_content
    return body


async def web_fetch_json(
    payload: dict[str, Any],
    *,
    settings: ProxySettings | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[int, dict[str, Any]]:
    """Perform an outbound HTTP request and return ``(status_code, body)``.

    Args:
        payload (dict[str, Any]): ``url``, optional ``method``, ``headers``, ``body``,
            ``max_length``, and optional ``byte_offset`` / ``chunk_length`` for
            Range-based chunked GET assembly.
        settings (ProxySettings | None): Reserved for future egress policy hooks.
        client (httpx.AsyncClient | None): Shared lifespan client; when omitted a
            short-lived client is created for this call only.

    Returns:
        tuple[int, dict[str, Any]]: Starlette status and JSON body.

    Examples:
        >>> import asyncio
        >>> status, body = asyncio.run(web_fetch_json({"url": "not-a-url"}))
        >>> status
        422
    """
    _ = settings
    url = str(payload.get("url") or "").strip()
    if not url:
        return 422, {"detail": "url is required"}
    url_err = _validate_fetch_url(url)
    if url_err is not None:
        return 422, {"detail": url_err}

    method = str(payload.get("method") or "GET").upper()
    if method not in ALLOWED_FETCH_METHODS:
        return 422, {"detail": f"unsupported method {method!r}"}

    raw_headers = payload.get("headers")
    caller_headers: dict[str, str] = {}
    if isinstance(raw_headers, dict):
        caller_headers = {str(k): str(v) for k, v in raw_headers.items()}
    headers = _merge_fetch_headers(caller_headers)

    body = payload.get("body")
    content: str | None = None
    if body is not None:
        content = str(body)
        if method in ("POST", "PUT", "PATCH") and not any(
            k.lower() == "content-type" for k in headers
        ):
            headers["Content-Type"] = "application/json"

    byte_offset, chunk_length = _parse_chunk_params(payload)
    chunk_mode = byte_offset is not None and method == "GET"

    raw_max = payload.get("max_length")
    cap: int | None
    if raw_max is None:
        # No cap requested: return the full body. Large results are handled by
        # the caller (spill to disk + paged ``read``), never silently truncated.
        cap = None
    else:
        try:
            cap = max(256, int(raw_max))
        except (TypeError, ValueError):
            cap = None

    range_headers = dict(headers)
    if chunk_mode and chunk_length is not None and byte_offset is not None:
        end = byte_offset + chunk_length - 1
        range_headers["Range"] = f"bytes={byte_offset}-{end}"

    use_streaming = byte_offset is None and method == "GET"
    char_budget = cap if cap is not None else MAX_HTML_FETCH_CHARS
    request_timeout = build_proxy_upstream_timeout(max_html_chars=char_budget)

    async def _execute(http: httpx.AsyncClient) -> tuple[int, dict[str, Any]]:
        if use_streaming:
            (
                status_code,
                content_type,
                text,
                truncated,
                resp_headers,
            ) = await _fetch_upstream_streaming(
                url=url,
                headers=headers,
                max_chars=cap,
                client=http,
                request_timeout=request_timeout,
            )
            low_content = False
            if _needs_low_content_retry(status_code, text, resp_headers):
                logger.info(
                    "web_fetch.low_content_retry url={} status={} len={}",
                    url,
                    status_code,
                    len(text),
                )
                (
                    status_code,
                    content_type,
                    text,
                    truncated,
                    resp_headers,
                ) = await _fetch_upstream_streaming(
                    url=url,
                    headers=headers,
                    max_chars=cap,
                    client=http,
                    request_timeout=request_timeout,
                )
                if _is_still_low_content(status_code, text):
                    low_content = True
            return 200, _build_fetch_response(
                url=url,
                method=method,
                status_code=status_code,
                content_type=content_type,
                text=text,
                truncated=truncated,
                streamed=True,
                low_content=low_content,
            )

        response = await http.request(
            method,
            url,
            headers=range_headers,
            content=content,
            timeout=request_timeout,
        )

        if chunk_mode and chunk_length is not None and byte_offset is not None:
            range_unsupported = response.status_code == 416 or (
                response.status_code == 200 and len(response.content) > chunk_length
            )
            if range_unsupported:
                fallback_cap = MAX_HTML_FETCH_CHARS
                fallback = await http.request(
                    method,
                    url,
                    headers=headers,
                    content=content,
                    timeout=request_timeout,
                )
                text = fallback.text
                truncated = len(text) > fallback_cap
                if truncated:
                    text = text[:fallback_cap]
                bytes_returned = len(text.encode("utf-8"))
                return 200, _build_fetch_response(
                    url=url,
                    method=method,
                    status_code=fallback.status_code,
                    content_type=fallback.headers.get("content-type", ""),
                    text=text,
                    truncated=truncated,
                    byte_offset=byte_offset,
                    bytes_returned=bytes_returned,
                    eof=True,
                )

            text = response.text
            bytes_returned = len(response.content)
            eof = bytes_returned < chunk_length or bytes_returned == 0
            return 200, _build_fetch_response(
                url=url,
                method=method,
                status_code=response.status_code,
                content_type=response.headers.get("content-type", ""),
                text=text,
                truncated=False,
                byte_offset=byte_offset,
                bytes_returned=bytes_returned,
                eof=eof,
            )

        text = response.text
        truncated = cap is not None and len(text) > cap
        if truncated:
            text = text[:cap]

        return 200, _build_fetch_response(
            url=url,
            method=method,
            status_code=response.status_code,
            content_type=response.headers.get("content-type", ""),
            text=text,
            truncated=truncated,
        )

    try:
        if client is not None:
            return await _execute(client)
        async with httpx.AsyncClient(
            timeout=request_timeout,
            limits=PROXY_HTTP_LIMITS,
            follow_redirects=True,
        ) as short_client:
            return await _execute(short_client)
    except httpx.HTTPError as exc:
        return 502, {"detail": f"upstream fetch failed: {exc}"}


async def brave_search_json(
    payload: dict[str, Any],
    *,
    settings: ProxySettings,
    client: httpx.AsyncClient | None = None,
) -> tuple[int, dict[str, Any]]:
    """Call Brave Search with the proxy-held API key.

    Args:
        payload (dict[str, Any]): ``query`` and optional ``count``.
        settings (ProxySettings): Proxy env including ``brave_api_key``.
        client (httpx.AsyncClient | None): Shared lifespan client; when omitted a
            short-lived client is created for this call only.

    Returns:
        tuple[int, dict[str, Any]]: Starlette status and JSON body.

    Examples:
        >>> import asyncio
        >>> from sevn.proxy.settings import ProxySettings
        >>> status, body = asyncio.run(
        ...     brave_search_json(
        ...         {"query": ""},
        ...         settings=ProxySettings(brave_api_key="test-key"),
        ...     )
        ... )
        >>> status
        422
    """
    if not settings.brave_api_key:
        return 503, {"detail": "brave not configured"}

    query = str(payload.get("query") or "").strip()
    if not query:
        return 422, {"detail": "query is required"}

    try:
        count = int(payload.get("count") or 5)
    except (TypeError, ValueError):
        count = 5
    count = max(1, min(count, 20))

    params: dict[str, str | int] = {"q": query, "count": count}
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": settings.brave_api_key,
    }

    try:
        brave_timeout = httpx.Timeout(15.0)
        if client is not None:
            response = await client.get(
                _BRAVE_SEARCH_URL,
                params=params,
                headers=headers,
                timeout=brave_timeout,
            )
        else:
            async with httpx.AsyncClient(timeout=brave_timeout) as short_client:
                response = await short_client.get(
                    _BRAVE_SEARCH_URL,
                    params=params,
                    headers=headers,
                )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        return 502, {"detail": f"brave search failed: {exc}"}

    results: list[dict[str, str]] = []
    if isinstance(data, dict):
        web_block = data.get("web")
        if isinstance(web_block, dict):
            raw_results = web_block.get("results")
            if isinstance(raw_results, list):
                for item in raw_results[:count]:
                    if not isinstance(item, dict):
                        continue
                    results.append(
                        {
                            "title": str(item.get("title") or ""),
                            "url": str(item.get("url") or ""),
                            "description": str(item.get("description") or ""),
                        }
                    )

    return 200, {"query": query, "count": len(results), "results": results}


__all__ = [
    "ALLOWED_FETCH_METHODS",
    "MAX_HTML_FETCH_CHARS",
    "brave_search_json",
    "web_fetch_json",
]
