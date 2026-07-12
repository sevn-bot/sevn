"""Web search and fetch tools (`plan/tools-skills-full-inventory-wave-plan.md` Wave 5).

``serp`` uses DuckDuckGo via ``ddgs`` (no API key). ``web_search`` and ``web_fetch``
delegate to the egress proxy so provider credentials never load in the tool host.

Module: sevn.tools.web
Depends: asyncio, httpx, markdownify, sevn.config.settings, sevn.tools.base,
    sevn.tools.context, sevn.tools.decorator

Exports:
    serp_tool — DuckDuckGo search via ``ddgs``.
    web_search_tool — Brave search via ``POST /web/brave/search`` on the egress proxy.
    get_page_content_tool — Fetch URL markdown via proxy + ``markdownify``.
    web_fetch_tool — Full HTTP via ``POST /web/fetch`` on the egress proxy.
    register_web_tools — register the four tools on a ``ToolExecutor``.
    build_egress_web_headers — assemble proxy auth headers for tests and dispatch.
    proxy_post_json — POST JSON to an egress proxy route (injectable in tests).
    reset_proxy_http_client_for_tests — close module-level proxy client (tests only).

Examples:
    >>> from sevn.tools.web import build_egress_web_headers
    >>> headers = build_egress_web_headers(
    ...     proxy_url="http://127.0.0.1:8787",
    ...     session_token="sess",
    ...     proxy_shared_secret="shared",
    ... )
    >>> headers["X-Sevn-Session-Token"]
    'sess'
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlparse

import httpx
from markdownify import markdownify as html_to_markdown

from sevn.config.defaults import (
    PROXY_TOOL_TO_PROXY_TIMEOUT_CONNECT_S,
    PROXY_TOOL_TO_PROXY_TIMEOUT_POOL_S,
    PROXY_TOOL_TO_PROXY_TIMEOUT_READ_S,
    PROXY_TOOL_TO_PROXY_TIMEOUT_WRITE_S,
)
from sevn.config.settings import ProcessSettings
from sevn.logging.structured import debug_event
from sevn.tools.base import enveloped_failure, enveloped_success, maybe_spill_large_payload
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool, tool_from_decorated

if TYPE_CHECKING:
    from sevn.tools.base import ToolExecutor

_HAS_DDGS = importlib.util.find_spec("ddgs") is not None
_HAS_READABILITY = importlib.util.find_spec("readability") is not None
_MARKDOWNIFY_STRIP_TAGS: Final[tuple[str, ...]] = (
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "aside",
    "noscript",
    "svg",
    "iframe",
)

DEFAULT_SEARCH_COUNT: Final[int] = 5
MAX_SEARCH_COUNT: Final[int] = 30
MAX_HTML_FETCH_CHARS: Final[int] = 1_000_000
HTML_FETCH_CHUNK_CHARS: Final[int] = 10_000
_LOW_CONTENT_HINT: Final[str] = "retry without max_length or use serp for URLs"
# Deprecated aliases — prefer MAX_HTML_FETCH_CHARS / HTML_FETCH_CHUNK_CHARS.
DEFAULT_WEB_FETCH_MAX_CHARS: Final[int] = HTML_FETCH_CHUNK_CHARS
DEFAULT_PAGE_MAX_CHARS: Final[int] = HTML_FETCH_CHUNK_CHARS
_PROXY_FETCH_PATH: Final[str] = "/web/fetch"
_PROXY_BRAVE_PATH: Final[str] = "/web/brave/search"
_SESSION_TOKEN_HEADER: Final[str] = "X-Sevn-Session-Token"
_PROXY_TOKEN_HEADER: Final[str] = "X-Sevn-Proxy-Token"
_TOOL_TO_PROXY_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(
    connect=PROXY_TOOL_TO_PROXY_TIMEOUT_CONNECT_S,
    read=PROXY_TOOL_TO_PROXY_TIMEOUT_READ_S,
    write=PROXY_TOOL_TO_PROXY_TIMEOUT_WRITE_S,
    pool=PROXY_TOOL_TO_PROXY_TIMEOUT_POOL_S,
)

_PROXY_HTTP_CLIENT: httpx.AsyncClient | None = None
_PROXY_HTTP_CLIENT_KEY: tuple[str, str, str] | None = None

_WEB_TOOLS: tuple[Any, ...] = ()


def build_egress_web_headers(
    *,
    proxy_url: str | None,
    session_token: str | None,
    proxy_shared_secret: str | None,
) -> dict[str, str]:
    """Build auth headers for egress proxy ``/web/*`` routes.

    Args:
        proxy_url (str | None): Resolved ``SEVN_PROXY_URL`` (must be non-empty to call).
        session_token (str | None): Per-run ``SEVN_SESSION_TOKEN`` when set.
        proxy_shared_secret (str | None): Optional ``SEVN_PROXY_SHARED_SECRET`` guard value.

    Returns:
        dict[str, str]: Headers to merge on proxy POST requests.

    Examples:
        >>> hdrs = build_egress_web_headers(
        ...     proxy_url="http://127.0.0.1:8787",
        ...     session_token="abc",
        ...     proxy_shared_secret="sec",
        ... )
        >>> hdrs["X-Sevn-Session-Token"]
        'abc'
        >>> hdrs["X-Sevn-Proxy-Token"]
        'sec'
    """
    _ = proxy_url
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if session_token and session_token.strip():
        headers[_SESSION_TOKEN_HEADER] = session_token.strip()
    if proxy_shared_secret and proxy_shared_secret.strip():
        headers[_PROXY_TOKEN_HEADER] = proxy_shared_secret.strip()
    return headers


def _resolve_process_egress() -> tuple[str | None, str | None, str | None]:
    """Read proxy URL, session token, and shared secret from process env.

    Returns:
        tuple[str | None, str | None, str | None]: ``(proxy_url, session_token, shared_secret)``.

    Examples:
        >>> isinstance(_resolve_process_egress(), tuple)
        True
    """
    ps = ProcessSettings()
    proxy_url = (ps.proxy_url or "").strip() or None
    session_token = (ps.session_token or "").strip() or None
    shared_secret = os.environ.get("SEVN_PROXY_SHARED_SECRET", "").strip() or None
    return proxy_url, session_token, shared_secret


def _proxy_client_cache_key(*, proxy_url: str, headers: dict[str, str]) -> tuple[str, str, str]:
    """Build a cache key for the module-level tool→proxy ``AsyncClient``.

    Args:
        proxy_url (str): Egress proxy origin.
        headers (dict[str, str]): Auth headers from :func:`build_egress_web_headers`.

    Returns:
        tuple[str, str, str]: ``(origin, session_token, shared_secret)`` tuple.

    Examples:
        >>> _proxy_client_cache_key(
        ...     proxy_url="http://127.0.0.1:8787",
        ...     headers={"X-Sevn-Session-Token": "s", "X-Sevn-Proxy-Token": "p"},
        ... )
        ('http://127.0.0.1:8787', 's', 'p')
    """
    return (
        proxy_url.rstrip("/"),
        headers.get(_SESSION_TOKEN_HEADER, ""),
        headers.get(_PROXY_TOKEN_HEADER, ""),
    )


def _get_proxy_client(*, proxy_url: str, headers: dict[str, str]) -> httpx.AsyncClient:
    """Return a reused ``AsyncClient`` for tool→proxy ``POST /web/*`` calls.

    Args:
        proxy_url (str): Egress proxy origin without trailing slash.
        headers (dict[str, str]): Auth headers (``Content-Type`` applied per request).

    Returns:
        httpx.AsyncClient: Module-scoped client; closed on process teardown or reset.

    Examples:
        >>> client = _get_proxy_client(
        ...     proxy_url="http://127.0.0.1:8787",
        ...     headers={"X-Sevn-Session-Token": "abc"},
        ... )
        >>> str(client.base_url).rstrip("/")
        'http://127.0.0.1:8787'
    """
    global _PROXY_HTTP_CLIENT, _PROXY_HTTP_CLIENT_KEY
    key = _proxy_client_cache_key(proxy_url=proxy_url, headers=headers)
    if _PROXY_HTTP_CLIENT is not None and key == _PROXY_HTTP_CLIENT_KEY:
        return _PROXY_HTTP_CLIENT
    auth_headers = {k: v for k, v in headers.items() if k.lower() != "content-type" and v}
    _PROXY_HTTP_CLIENT = httpx.AsyncClient(
        base_url=proxy_url.rstrip("/"),
        timeout=_TOOL_TO_PROXY_TIMEOUT,
        headers=auth_headers,
    )
    _PROXY_HTTP_CLIENT_KEY = key
    return _PROXY_HTTP_CLIENT


async def reset_proxy_http_client_for_tests() -> None:
    """Close and clear the module-level proxy client (tests only).

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(reset_proxy_http_client_for_tests)
        True
    """
    global _PROXY_HTTP_CLIENT, _PROXY_HTTP_CLIENT_KEY
    if _PROXY_HTTP_CLIENT is not None:
        aclose = getattr(_PROXY_HTTP_CLIENT, "aclose", None)
        if aclose is not None:
            await aclose()
    _PROXY_HTTP_CLIENT = None
    _PROXY_HTTP_CLIENT_KEY = None


async def proxy_post_json(
    *,
    proxy_url: str,
    path: str,
    body: dict[str, Any],
    headers: dict[str, str],
    timeout_s: float = 30.0,
    client: httpx.AsyncClient | None = None,
) -> tuple[int, dict[str, Any]]:
    """POST JSON to ``{proxy_url}{path}`` and return status + parsed object.

    Args:
        proxy_url (str): Egress proxy origin without trailing slash.
        path (str): Route beginning with ``/``.
        body (dict[str, Any]): JSON request payload.
        headers (dict[str, str]): Auth headers from :func:`build_egress_web_headers`.
        timeout_s (float): Per-request read override when not using the shared client.
        client (httpx.AsyncClient | None): Injectable client for tests; when omitted
            the module-level shared client is used.

    Returns:
        tuple[int, dict[str, Any]]: HTTP status and parsed JSON object (or ``detail`` envelope).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(proxy_post_json)
        True
    """
    req_headers = dict(headers)
    if "Content-Type" not in req_headers and "content-type" not in {k.lower() for k in req_headers}:
        req_headers["Content-Type"] = "application/json"
    http = client or _get_proxy_client(proxy_url=proxy_url, headers=headers)
    per_request_timeout = httpx.Timeout(timeout_s) if client is not None else None
    response = await http.post(
        path,
        json=body,
        headers=req_headers,
        timeout=per_request_timeout,
    )
    try:
        data = response.json()
    except json.JSONDecodeError:
        return response.status_code, {
            "detail": f"proxy returned non-JSON body (status {response.status_code})",
        }
    if not isinstance(data, dict):
        return response.status_code, {"detail": "proxy returned non-object JSON"}
    return response.status_code, data


def _proxy_required_error(*, tool_name: str) -> str:
    """Return a §3.1 failure envelope when ``SEVN_PROXY_URL`` is unset.

    Args:
        tool_name (str): Tool that requires the egress proxy.

    Returns:
        str: JSON envelope string.

    Examples:
        >>> import json
        >>> env = json.loads(_proxy_required_error(tool_name="web_fetch"))
        >>> env["ok"]
        False
    """
    return enveloped_failure(
        (
            f"SEVN_PROXY_URL is not configured; {tool_name} requires the egress proxy "
            "(normally paired with the gateway). Use serp for keyless web search."
        ),
        code=ToolResultCode.PERMISSION_DENIED,
        data={"readiness": "needs_proxy", "fallback_tool": "serp"},
    )


def _brave_key_required_error() -> str:
    """Return a §3.1 failure when Brave API key is missing on the proxy.

    Returns:
        str: JSON envelope string.

    Examples:
        >>> import json
        >>> env = json.loads(_brave_key_required_error())
        >>> env["code"]
        'PERMISSION_DENIED'
    """
    return enveloped_failure(
        (
            "web_search requires a Brave Search API key in egress proxy secrets "
            "(brave not configured). Configure it with "
            "`sevn secrets put web.brave.api_key --value <key>` then restart the proxy, "
            "or use serp for keyless DuckDuckGo search."
        ),
        code=ToolResultCode.PERMISSION_DENIED,
        data={"readiness": "needs_brave_key", "fallback_tool": "serp"},
    )


async def _serp_fallback_or_error(
    ctx: ToolContext,
    *,
    query: str,
    count: int,
    reason: str,
    error_envelope: str,
) -> str:
    """Answer an unavailable ``web_search`` call with keyless serp results.

    When the Brave path cannot run (no proxy, no API key, upstream 503), run
    the same query through DuckDuckGo instead of surfacing the infrastructure
    failure to the model. The success payload is annotated with the substitute
    provider and the reason so the answer never silently masks the
    misconfiguration. When serp itself cannot run, the original error envelope
    is returned unchanged.

    Args:
        ctx (ToolContext): Invocation context (spill directory / session).
        query (str): Search query (already stripped and non-empty).
        count (int): Requested result count (re-capped for serp).
        reason (str): Why the Brave path was unavailable.
        error_envelope (str): §3.1 failure envelope to fall back to.

    Returns:
        str: Annotated serp success envelope, or ``error_envelope``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_serp_fallback_or_error)
        True
    """
    if not _HAS_DDGS:
        return error_envelope
    capped = max(1, min(int(count), MAX_SEARCH_COUNT))
    try:
        results = await asyncio.to_thread(_serp_search_sync, query, capped, None)
    except Exception:
        return error_envelope
    payload = {
        "query": query,
        "count": len(results),
        "results": results,
        "provider": "serp",
        "fallback_from": "web_search",
        "fallback_reason": reason,
    }
    envelope = enveloped_success(payload)
    return maybe_spill_large_payload(ctx.workspace_path, ctx.session_id, envelope_str=envelope)


def _validate_http_url(url: str) -> str | None:
    """Return an error message when ``url`` is not http(s).

    Args:
        url (str): Candidate URL.

    Returns:
        str | None: Validation error or ``None`` when acceptable.

    Examples:
        >>> _validate_http_url("https://example.com") is None
        True
        >>> _validate_http_url("ftp://x") is not None
        True
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return "url must use http or https"
    if not parsed.netloc:
        return "url must include a host"
    return None


def _serp_search_sync(query: str, count: int, region: str | None) -> list[dict[str, Any]]:
    """Run a blocking DuckDuckGo search via ``ddgs``.

    Args:
        query (str): Search query.
        count (int): Maximum results (capped).
        region (str | None): Optional region code.

    Returns:
        list[dict[str, Any]]: Raw result rows from ``ddgs``.

    Examples:
        >>> isinstance(_serp_search_sync.__name__, str)
        True
    """
    kwargs: dict[str, Any] = {"max_results": count}
    if region:
        kwargs["region"] = region
    if not _HAS_DDGS:
        return []
    from ddgs import DDGS as _ddgs_cls

    return list(_ddgs_cls().text(query, **kwargs))


def _extract_main_html(html: str, *, mode: str) -> str:
    """Scope HTML to main article content before markdown conversion.

    Args:
        html (str): Full HTML document body.
        mode (str): ``"auto"`` tries ``readability-lxml`` when importable;
            ``"full"`` returns the input unchanged.

    Returns:
        str: Scoped HTML for ``markdownify``.

    Examples:
        >>> _extract_main_html("<article><p>x</p></article>", mode="full")
        '<article><p>x</p></article>'
    """
    if mode == "full":
        return html
    if mode != "auto" or not _HAS_READABILITY:
        return html
    try:
        from readability import Document

        return str(Document(html).summary())
    except Exception:
        return html


def _html_to_markdown_text(html: str, *, url: str | None = None) -> str:
    """Convert HTML to markdown using ``markdownify``.

    Args:
        html (str): HTML document body.
        url (str | None): Source URL — only its length is logged on thin output.

    Returns:
        str: Markdown text.

    Examples:
        >>> _html_to_markdown_text("<h1>Hi</h1><p>There</p>").strip().startswith("#")
        True
    """
    markdown = html_to_markdown(
        html,
        heading_style="ATX",
        strip=list(_MARKDOWNIFY_STRIP_TAGS),
    ).strip()
    if len(markdown) < 200 and len(html) > 5000:
        debug_event("web.markdownify_thin_output", url_len=len(url) if url else 0)
    return markdown


def _low_content_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Return envelope fields when the proxy flagged a thin fetch body.

    Args:
        data (dict[str, Any]): Raw proxy payload from ``POST /web/fetch``.

    Returns:
        dict[str, Any]: ``low_content`` and ``hint`` when the proxy set ``low_content``.

    Examples:
        >>> _low_content_fields({"low_content": True})
        {'low_content': True, 'hint': 'retry without max_length or use serp for URLs'}
        >>> _low_content_fields({})
        {}
    """
    if not data.get("low_content"):
        return {}
    return {"low_content": True, "hint": _LOW_CONTENT_HINT}


@sevn_tool(
    name="serp",
    category="web",
    description="Search the web via DuckDuckGo (ddgs; no API key).",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
            "count": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_SEARCH_COUNT,
                "description": f"Number of results (default {DEFAULT_SEARCH_COUNT}).",
            },
            "region": {
                "type": "string",
                "description": "Optional region code (e.g. us-en, uk-en).",
            },
        },
        "required": ["query"],
    },
    large_result=True,
    abortable=True,
    see_also=("web_search", "get_page_content"),
)
async def serp_tool(
    ctx: ToolContext,
    *,
    query: str,
    count: int = DEFAULT_SEARCH_COUNT,
    region: str | None = None,
) -> str:
    """Search the web with DuckDuckGo and return structured results.

    Args:
        ctx (ToolContext): Invocation context.
        query (str): Search query.
        count (int): Maximum results.
        region (str | None): Optional ddgs region.

    Returns:
        str: §3.1 JSON envelope (may spill when large).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(serp_tool)
        True
    """
    _ = ctx
    needle = query.strip()
    if not needle:
        return enveloped_failure("query must be non-empty", code=ToolResultCode.VALIDATION_ERROR)
    if not _HAS_DDGS:
        return enveloped_failure(
            "ddgs is not installed",
            code=ToolResultCode.INTERNAL_ERROR,
        )
    capped = max(1, min(int(count), MAX_SEARCH_COUNT))
    region_val = region.strip() if isinstance(region, str) and region.strip() else None
    try:
        results = await asyncio.to_thread(_serp_search_sync, needle, capped, region_val)
    except Exception as exc:
        return enveloped_failure(
            f"serp search failed: {exc}",
            code=ToolResultCode.INTERNAL_ERROR,
        )
    payload = {"query": needle, "count": len(results), "results": results}
    envelope = enveloped_success(payload)
    return maybe_spill_large_payload(ctx.workspace_path, ctx.session_id, envelope_str=envelope)


@sevn_tool(
    name="web_search",
    category="web",
    description=(
        "Premium web search via Brave (proxy + Brave API key); falls back to "
        "keyless serp automatically when Brave is unavailable."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
            "count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "description": f"Number of results (default {DEFAULT_SEARCH_COUNT}).",
            },
        },
        "required": ["query"],
    },
    large_result=True,
    abortable=True,
    see_also=("serp", "get_page_content"),
)
async def web_search_tool(
    ctx: ToolContext,
    *,
    query: str,
    count: int = DEFAULT_SEARCH_COUNT,
) -> str:
    """Search the web via Brave using proxy-held credentials.

    When the Brave path is unavailable (no proxy, missing API key, upstream
    503), the query runs through keyless serp instead and the payload is
    annotated with ``provider``/``fallback_reason``.

    Args:
        ctx (ToolContext): Invocation context.
        query (str): Search query.
        count (int): Maximum results.

    Returns:
        str: §3.1 JSON envelope (may spill when large).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(web_search_tool)
        True
    """
    needle = query.strip()
    if not needle:
        return enveloped_failure("query must be non-empty", code=ToolResultCode.VALIDATION_ERROR)

    proxy_url, session_token, shared_secret = _resolve_process_egress()
    if not proxy_url:
        return await _serp_fallback_or_error(
            ctx,
            query=needle,
            count=count,
            reason="egress proxy not configured (SEVN_PROXY_URL unset)",
            error_envelope=_proxy_required_error(tool_name="web_search"),
        )

    headers = build_egress_web_headers(
        proxy_url=proxy_url,
        session_token=session_token,
        proxy_shared_secret=shared_secret,
    )
    status, data = await proxy_post_json(
        proxy_url=proxy_url,
        path=_PROXY_BRAVE_PATH,
        body={"query": needle, "count": count},
        headers=headers,
    )
    if status == 503:
        detail = str(data.get("detail") or "brave search unavailable").lower()
        if "brave" in detail or "not configured" in detail:
            return await _serp_fallback_or_error(
                ctx,
                query=needle,
                count=count,
                reason="Brave API key not configured in egress proxy secrets",
                error_envelope=_brave_key_required_error(),
            )
        return await _serp_fallback_or_error(
            ctx,
            query=needle,
            count=count,
            reason=str(data.get("detail") or "brave search unavailable"),
            error_envelope=enveloped_failure(
                str(data.get("detail") or "brave search unavailable"),
                code=ToolResultCode.PERMISSION_DENIED,
                data={"fallback_tool": "serp"},
            ),
        )
    if status >= 400:
        detail = str(data.get("detail") or f"proxy returned status {status}")
        return enveloped_failure(detail, code=ToolResultCode.INTERNAL_ERROR)

    envelope = enveloped_success(data)
    return maybe_spill_large_payload(ctx.workspace_path, ctx.session_id, envelope_str=envelope)


async def _proxy_web_fetch_single(
    *,
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    max_length: int | None = None,
    byte_offset: int | None = None,
    chunk_length: int | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """Fetch a URL through the egress proxy in a single ``POST /web/fetch`` call.

    Args:
        url (str): Target URL.
        method (str): HTTP verb.
        headers (dict[str, str] | None): Optional request headers.
        body (str | None): Optional request body.
        max_length (int | None): Optional response character cap for non-chunk mode.
        byte_offset (int | None): Optional byte offset for chunked Range fetch.
        chunk_length (int | None): Optional chunk size when ``byte_offset`` is set.

    Returns:
        tuple[str | None, dict[str, Any]]: ``(error_envelope, data)``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_proxy_web_fetch_single)
        True
    """
    target = url.strip()
    if not target:
        return (
            enveloped_failure("url must be non-empty", code=ToolResultCode.VALIDATION_ERROR),
            {},
        )
    url_err = _validate_http_url(target)
    if url_err is not None:
        return enveloped_failure(url_err, code=ToolResultCode.VALIDATION_ERROR), {}

    proxy_url, session_token, shared_secret = _resolve_process_egress()
    if not proxy_url:
        return _proxy_required_error(tool_name="web_fetch"), {}

    req_headers = build_egress_web_headers(
        proxy_url=proxy_url,
        session_token=session_token,
        proxy_shared_secret=shared_secret,
    )
    payload: dict[str, Any] = {
        "url": target,
        "method": method.upper(),
    }
    if max_length is not None:
        payload["max_length"] = max_length
    if byte_offset is not None:
        payload["byte_offset"] = byte_offset
        payload["chunk_length"] = chunk_length or HTML_FETCH_CHUNK_CHARS
    if headers:
        payload["headers"] = headers
    if body is not None:
        payload["body"] = body

    status, data = await proxy_post_json(
        proxy_url=proxy_url,
        path=_PROXY_FETCH_PATH,
        body=payload,
        headers=req_headers,
    )
    if status >= 400:
        detail = str(data.get("detail") or f"proxy returned status {status}")
        code = ToolResultCode.VALIDATION_ERROR if status == 422 else ToolResultCode.INTERNAL_ERROR
        return enveloped_failure(detail, code=code), {}

    return None, data


async def _proxy_web_fetch_batched(
    *,
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    max_html_chars: int = MAX_HTML_FETCH_CHARS,
) -> tuple[str | None, dict[str, Any]]:
    """Fetch a large GET response via one streaming ``POST /web/fetch`` call.

    The egress proxy streams upstream bytes internally; this helper no longer
    loops Range chunks unless callers use :func:`_proxy_web_fetch_single` with
    an explicit ``byte_offset``.

    Args:
        url (str): Target URL.
        method (str): HTTP verb (streaming default applies to GET only).
        headers (dict[str, str] | None): Optional request headers.
        body (str | None): Optional request body.
        max_html_chars (int): Maximum assembled HTML characters.

    Returns:
        tuple[str | None, dict[str, Any]]: ``(error_envelope, data)`` with assembled
        ``text`` and upstream metadata from the proxy stream.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_proxy_web_fetch_batched)
        True
    """
    if method.upper() != "GET":
        return await _proxy_web_fetch_single(
            url=url,
            method=method,
            headers=headers,
            body=body,
            max_length=max_html_chars if max_html_chars < MAX_HTML_FETCH_CHARS else None,
        )

    proxy_max_length = max_html_chars if max_html_chars < MAX_HTML_FETCH_CHARS else None
    err, data = await _proxy_web_fetch_single(
        url=url,
        method=method,
        headers=headers,
        body=body,
        max_length=proxy_max_length,
    )
    if err is not None:
        return err, {}

    text = str(data.get("text") or "")
    truncated_at_cap = len(text) > max_html_chars
    if truncated_at_cap:
        text = text[:max_html_chars]

    assembled = {
        **data,
        "text": text,
        "truncated": truncated_at_cap or bool(data.get("truncated")),
        "batched": False,
        "streamed": True,
        "chunks_fetched": 1,
    }
    return None, assembled


async def _proxy_web_fetch(
    *,
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    max_length: int | None = None,
    max_html_chars: int | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """Fetch a URL through the egress proxy without spilling.

    Shared core for :func:`web_fetch_tool` and :func:`get_page_content_tool`.
    GET requests use :func:`_proxy_web_fetch_batched` up to ``max_html_chars``;
    other verbs use a single proxy call.

    Args:
        url (str): Target URL.
        method (str): HTTP verb.
        headers (dict[str, str] | None): Optional request headers.
        body (str | None): Optional request body.
        max_length (int | None): Legacy single-fetch cap (non-GET or explicit small cap).
        max_html_chars (int | None): Assembled HTML budget for GET batched fetch.

    Returns:
        tuple[str | None, dict[str, Any]]: ``(error_envelope, data)``. When the
        first element is non-``None`` it is a §3.1 failure envelope and ``data``
        is empty; otherwise ``data`` is the raw proxy payload.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_proxy_web_fetch)
        True
    """
    budget = max_html_chars if max_html_chars is not None else MAX_HTML_FETCH_CHARS
    if max_length is not None:
        budget = min(budget, max_length)

    if method.upper() == "GET":
        return await _proxy_web_fetch_batched(
            url=url,
            method=method,
            headers=headers,
            body=body,
            max_html_chars=budget,
        )

    return await _proxy_web_fetch_single(
        url=url,
        method=method,
        headers=headers,
        body=body,
        max_length=max_length,
    )


@sevn_tool(
    name="web_fetch",
    category="web",
    description="Full HTTP request via egress proxy (method, headers, body).",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL (http or https)."},
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
                "description": "HTTP method (default GET).",
            },
            "headers": {
                "type": "object",
                "description": "Optional request headers.",
            },
            "body": {
                "type": "string",
                "description": "Optional request body for POST/PUT/PATCH.",
            },
            "max_length": {
                "type": "integer",
                "minimum": 256,
                "description": (
                    "Optional cap on response chars. Omit to fetch the full body; "
                    "large results spill to disk and are paged with `read`."
                ),
            },
        },
        "required": ["url"],
    },
    large_result=True,
    abortable=True,
    see_also=("get_page_content", "integration_call"),
)
async def web_fetch_tool(
    ctx: ToolContext,
    *,
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    max_length: int | None = None,
) -> str:
    """Perform an HTTP request through the egress proxy.

    Args:
        ctx (ToolContext): Invocation context.
        url (str): Target URL.
        method (str): HTTP verb.
        headers (dict[str, str] | None): Optional headers.
        body (str | None): Optional body.
        max_length (int | None): Optional response character cap. ``None``
            returns the full body; oversized results spill to disk.

    Returns:
        str: §3.1 JSON envelope (may spill when large).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(web_fetch_tool)
        True
    """
    err, data = await _proxy_web_fetch(
        url=url,
        method=method,
        headers=headers,
        body=body,
        max_length=max_length,
    )
    if err is not None:
        return err

    envelope = enveloped_success(data)
    return maybe_spill_large_payload(ctx.workspace_path, ctx.session_id, envelope_str=envelope)


@sevn_tool(
    name="get_page_content",
    category="web",
    description="Fetch a URL and return clean markdown (via egress proxy + markdownify).",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Page URL (http or https)."},
            "max_length": {
                "type": "integer",
                "minimum": 256,
                "description": (
                    "Optional cap on markdown chars. Omit to extract the full page; "
                    "large results spill to disk and are paged with `read`."
                ),
            },
            "save_to": {
                "type": "string",
                "description": (
                    "Optional workspace-relative path to write markdown directly "
                    "(skips spill round-trip for fetch → file → pdf pipelines)."
                ),
            },
            "extract": {
                "type": "string",
                "enum": ["auto", "full"],
                "default": "auto",
                "description": (
                    "Content scoping before markdownify. "
                    '"auto" (default) uses readability-lxml when installed, else strip-only; '
                    '"full" converts the entire fetched HTML.'
                ),
            },
        },
        "required": ["url"],
    },
    large_result=True,
    abortable=True,
    see_also=("web_fetch", "serp"),
)
async def get_page_content_tool(
    ctx: ToolContext,
    *,
    url: str,
    max_length: int | None = None,
    save_to: str | None = None,
    extract: str = "auto",
) -> str:
    """Fetch a page through the proxy and convert HTML to markdown.

    Args:
        ctx (ToolContext): Invocation context.
        url (str): Page URL.
        max_length (int | None): Optional markdown character cap. ``None``
            returns the full converted page; oversized markdown spills to disk
            and is paged with ``read`` rather than being truncated.
        save_to (str | None): When set, write markdown to this workspace-relative
            path and return ``saved_path`` instead of spilling inline content.
        extract (str): ``"auto"`` scopes to main content when readability is
            available; ``"full"`` converts the entire fetched HTML.

    Returns:
        str: §3.1 JSON envelope with ``markdown`` or ``saved_path`` (may spill when large).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(get_page_content_tool)
        True
    """
    # Fetch through the shared, non-spilling core so the raw HTML ``text`` is
    # always available here. Request the full body (``max_length=None``) when the
    # caller wants the full page; otherwise pull enough HTML to cover the
    # requested markdown budget with headroom for stripped markup.
    html_budget = (
        MAX_HTML_FETCH_CHARS if max_length is None else min(max_length * 4, MAX_HTML_FETCH_CHARS)
    )
    err, data = await _proxy_web_fetch(url=url, method="GET", max_html_chars=html_budget)
    if err is not None:
        return err

    html = str(data.get("text") or "")
    if not html.strip():
        return enveloped_failure(
            "fetched page had empty body",
            code=ToolResultCode.INTERNAL_ERROR,
            data={"url": url, "status_code": data.get("status_code")},
        )

    extract_mode = extract if extract in ("auto", "full") else "auto"
    scoped_html = _extract_main_html(html, mode=extract_mode)

    try:
        markdown = _html_to_markdown_text(scoped_html, url=url)
    except Exception as exc:
        return enveloped_failure(
            f"markdown conversion failed: {exc}",
            code=ToolResultCode.INTERNAL_ERROR,
        )

    truncated = max_length is not None and len(markdown) > max_length
    if truncated:
        markdown = markdown[:max_length]

    if save_to and save_to.strip():
        from sevn.tools.paths import WorkspacePathError, resolve_artifact_tool_path

        try:
            prefix = ctx.artifact_output_prefix.strip() or "out"
            target, _rel = resolve_artifact_tool_path(
                ctx.workspace_path,
                save_to.strip(),
                output_prefix=prefix,
            )
        except PermissionError as exc:
            return enveloped_failure(str(exc), code=ToolResultCode.PERMISSION_DENIED)
        except (ValueError, WorkspacePathError) as exc:
            return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
        rel = target.resolve().relative_to(ctx.workspace_path.resolve()).as_posix()
        payload = {
            "url": url,
            "status_code": data.get("status_code"),
            "content_type": data.get("content_type"),
            "saved_path": rel,
            "bytes": target.stat().st_size,
            "truncated": truncated or bool(data.get("truncated")),
            "spill_avoided": True,
            **_low_content_fields(data),
        }
        return enveloped_success(payload)

    payload = {
        "url": url,
        "status_code": data.get("status_code"),
        "content_type": data.get("content_type"),
        "markdown": markdown,
        "truncated": truncated or bool(data.get("truncated")),
        **_low_content_fields(data),
    }
    envelope = enveloped_success(payload)
    return maybe_spill_large_payload(ctx.workspace_path, ctx.session_id, envelope_str=envelope)


_WEB_TOOLS = (
    serp_tool,
    web_search_tool,
    get_page_content_tool,
    web_fetch_tool,
)


def register_web_tools(executor: ToolExecutor) -> None:
    """Register Wave 5 web/search/fetch tools.

    Args:
        executor (ToolExecutor): Registry under construction.

    Returns:
        None

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.web import register_web_tools
        >>> exe = ToolExecutor()
        >>> register_web_tools(exe)
        >>> "serp" in {d.name for d in exe.definitions()}
        True
    """
    for tool_fn in _WEB_TOOLS:
        executor.register(tool_from_decorated(tool_fn))


__all__ = [
    "DEFAULT_PAGE_MAX_CHARS",
    "DEFAULT_SEARCH_COUNT",
    "DEFAULT_WEB_FETCH_MAX_CHARS",
    "HTML_FETCH_CHUNK_CHARS",
    "MAX_HTML_FETCH_CHARS",
    "build_egress_web_headers",
    "get_page_content_tool",
    "proxy_post_json",
    "register_web_tools",
    "reset_proxy_http_client_for_tests",
    "serp_tool",
    "web_fetch_tool",
    "web_search_tool",
]
