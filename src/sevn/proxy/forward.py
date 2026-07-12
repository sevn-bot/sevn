"""Httpx forward primitives for the egress proxy (test seam).

Module: sevn.proxy.forward
Depends: httpx, loguru

Also used as the documented HTTP seam for stateless outbound JSON posts.
Local iteration: ``make ci-changed`` after editing this module (pairs with
``tests/proxy/test_proxy_app.py`` when present).

Exports:
    post_json — buffered POST; returned response is safe after the client exits.
    post_sse_stream — streaming POST; caller must close response then client.
    summarize_request_body — structured one-liner for a proxy egress body (no secrets).
    redact_headers — return a copy with auth headers masked for logging.

Examples:
    >>> import inspect
    >>> from sevn.proxy.forward import post_json, post_sse_stream
    >>> inspect.iscoroutinefunction(post_json)
    True
    >>> inspect.iscoroutinefunction(post_sse_stream)
    True
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from loguru import logger

_SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {"authorization", "x-api-key", "anthropic-version", "api-key", "x-auth-token"}
)
"""Header names whose values are masked before logging."""

_BODY_LOG_TRUNCATE_CHARS: int = 600
"""Maximum upstream-body length emitted in error log lines (no secrets in body)."""

_FRAMING_HEADERS: frozenset[str] = frozenset({"content-length", "host", "transfer-encoding"})
"""Framing headers (lower-case) never forwarded to an upstream — httpx recomputes them.

Forwarding an inbound ``content-length``/``host`` overrides httpx's own framing and
makes h11 raise ``LocalProtocolError`` when the re-serialized body length differs.
"""


def _sanitize_outbound_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of ``headers`` without framing headers (case-insensitive).

    Drops ``content-length``/``host``/``transfer-encoding`` so a stale inbound value
    cannot override httpx's computed framing. The caller's dict is never mutated.

    Args:
        headers (dict[str, str]): Proposed outbound headers (any key casing).

    Returns:
        dict[str, str]: Copy safe to hand to httpx.

    Examples:
        >>> _sanitize_outbound_headers({"Content-Length": "9", "x-api-key": "k"})
        {'x-api-key': 'k'}
        >>> _sanitize_outbound_headers({"Host": "127.0.0.1", "authorization": "Bearer t"})
        {'authorization': 'Bearer t'}
    """
    return {k: v for k, v in headers.items() if k.lower() not in _FRAMING_HEADERS}


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return ``headers`` with auth-bearing values replaced by ``"<redacted:N>"``.

    Args:
        headers (dict[str, str]): Outbound HTTP headers (case-sensitive keys).

    Returns:
        dict[str, str]: Copy safe to emit via ``loguru``.

    Examples:
        >>> redact_headers({"x-api-key": "abcdef1234"})
        {'x-api-key': '<redacted:10>'}
        >>> redact_headers({"content-type": "application/json"})
        {'content-type': 'application/json'}
    """
    out: dict[str, str] = {}
    for key, val in headers.items():
        if key.lower() in _SENSITIVE_HEADERS:
            out[key] = f"<redacted:{len(val) if isinstance(val, str) else 0}>"
        else:
            out[key] = val
    return out


def _summarize_responses_body(body: dict[str, Any]) -> dict[str, Any]:
    """Summarise a Codex/Responses-shaped egress body (``input``/``instructions``).

    The OAuth route translates chat-completions into the Responses schema, which
    has no ``messages`` key — so :func:`summarize_request_body`'s chat summary would
    log ``messages_count=0`` and look like the conversation was dropped. This path
    reports the Responses shape instead (no secrets, no content).

    Args:
        body (dict[str, Any]): Translated Responses body.

    Returns:
        dict[str, Any]: ``{"wire_format": "responses", "model": str | None,
        "stream": bool, "input_count": int, "instructions_chars": int,
        "include": list[str]}``.

    Examples:
        >>> _summarize_responses_body(
        ...     {"model": "gpt-5.5", "instructions": "be terse",
        ...      "input": [{"role": "user"}], "include": ["reasoning.encrypted_content"]}
        ... ) == {
        ...     "wire_format": "responses", "model": "gpt-5.5", "stream": False,
        ...     "input_count": 1, "instructions_chars": 8,
        ...     "include": ["reasoning.encrypted_content"],
        ... }
        True
    """
    input_field = body.get("input")
    input_count = len(input_field) if isinstance(input_field, list) else 0
    instructions = body.get("instructions")
    instructions_chars = len(instructions) if isinstance(instructions, str) else 0
    include_field = body.get("include")
    include = (
        [i for i in include_field if isinstance(i, str)] if isinstance(include_field, list) else []
    )
    return {
        "wire_format": "responses",
        "model": body.get("model") if isinstance(body.get("model"), str) else None,
        "stream": body.get("stream") is True,
        "input_count": input_count,
        "instructions_chars": instructions_chars,
        "include": include,
    }


def summarize_request_body(body: dict[str, Any]) -> dict[str, Any]:
    """Return a compact structured summary of a proxy egress body.

    Captures shape signals that matter when an upstream returns 4xx/5xx without
    forwarding any of the actual user/system content (PII / `.llmignore`).
    Codex/Responses bodies (``input``/``instructions``, no ``messages``) are
    summarised by their own shape via :func:`_summarize_responses_body`.

    Args:
        body (dict[str, Any]): Body that would be JSON-encoded for the upstream.

    Returns:
        dict[str, Any]: For chat-completions bodies ``{"model": str | None,
        "stream": bool, "max_tokens": int | None, "messages_count": int,
        "messages_roles": list[str], "system_chars": int}``; for Responses bodies
        the :func:`_summarize_responses_body` shape.

    Examples:
        >>> summarize_request_body(
        ...     {"model": "M", "messages": [{"role": "user", "content": "hi"}],
        ...      "system": "be terse", "max_tokens": 1024, "stream": False}
        ... ) == {
        ...     "model": "M", "stream": False, "max_tokens": 1024,
        ...     "messages_count": 1, "messages_roles": ["user"], "system_chars": 8,
        ... }
        True
        >>> summarize_request_body({"model": "M", "input": [{"role": "user"}]})["wire_format"]
        'responses'
    """
    if "messages" not in body and ("input" in body or "instructions" in body):
        return _summarize_responses_body(body)
    messages = body.get("messages")
    roles: list[str] = []
    if isinstance(messages, list):
        for m in messages:
            if isinstance(m, dict):
                role = m.get("role")
                if isinstance(role, str):
                    roles.append(role)
    system_field = body.get("system")
    if isinstance(system_field, str):
        system_chars = len(system_field)
    elif isinstance(system_field, list):
        system_chars = sum(
            len(b.get("text", "")) if isinstance(b, dict) and isinstance(b.get("text"), str) else 0
            for b in system_field
        )
    else:
        system_chars = 0
    max_tokens = body.get("max_tokens")
    return {
        "model": body.get("model") if isinstance(body.get("model"), str) else None,
        "stream": body.get("stream") is True,
        "max_tokens": int(max_tokens) if isinstance(max_tokens, int) else None,
        "messages_count": len(roles),
        "messages_roles": roles,
        "system_chars": system_chars,
    }


def _truncate(text: str, limit: int = _BODY_LOG_TRUNCATE_CHARS) -> str:
    """Trim ``text`` to ``limit`` chars and append a ``…(+N more)`` marker.

    Args:
        text (str): Decoded response body.
        limit (int): Maximum chars to retain inline.

    Returns:
        str: Truncated string safe for one-line log emission.

    Examples:
        >>> _truncate("abc", limit=10)
        'abc'
        >>> _truncate("abcdefghij", limit=4)
        'abcd…(+6 more)'
    """
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…(+{len(text) - limit} more)"


def _log_upstream_outcome(
    *,
    method: str,
    url: str,
    body: dict[str, Any],
    status: int,
    response_content: bytes,
    response_ct: str,
    elapsed_ms: int,
) -> None:
    """Emit an INFO/WARN line summarising a forwarded HTTP exchange.

    Args:
        method (str): HTTP verb (currently only ``POST``).
        url (str): Upstream URL.
        body (dict[str, Any]): Egress body summarised via :func:`summarize_request_body`.
        status (int): Upstream HTTP status.
        response_content (bytes): Buffered upstream body (truncated when logged).
        response_ct (str): Upstream ``content-type`` header.
        elapsed_ms (int): Round-trip wall-clock duration in milliseconds.

    Examples:
        >>> _log_upstream_outcome.__name__
        '_log_upstream_outcome'
    """
    summary = summarize_request_body(body)
    if status >= 400:
        try:
            preview = response_content.decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover — decode never raises with errors='replace'
            preview = repr(response_content[:_BODY_LOG_TRUNCATE_CHARS])
        logger.warning(
            "proxy upstream {method} {url} -> {status} ({elapsed_ms}ms) "
            "request={request} response_content_type={ct} response_body={body!r}",
            method=method,
            url=url,
            status=status,
            elapsed_ms=elapsed_ms,
            request=summary,
            ct=response_ct,
            body=_truncate(preview),
        )
        return
    logger.info(
        "proxy upstream {method} {url} -> {status} ({elapsed_ms}ms) request={request}",
        method=method,
        url=url,
        status=status,
        elapsed_ms=elapsed_ms,
        request=summary,
    )


async def post_json(
    *,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout_s: float = 120.0,
) -> httpx.Response:
    """POST JSON and return the buffered httpx response.

    The body is fully read inside the ``AsyncClient`` context (``raw.aread``)
    so the response remains usable — ``.content``, ``.status_code``,
    ``.headers`` — after the client closes. The response is **not** rebuilt:
    rebuilding via ``httpx.Response(content=raw.content, headers=raw.headers)``
    re-applies the ``Content-Encoding`` decoder against already-decoded bytes
    and fails for compressed upstream responses (e.g. MiniMax's ``br``).

    Emits a ``WARNING`` log line including request shape + truncated response
    body when the upstream returns ``status >= 400``; otherwise an ``INFO`` line
    with request shape only (no body, no secrets — see :func:`redact_headers` /
    :func:`summarize_request_body`).

    Args:
        url (str): Upstream URL.
        headers (dict[str, str]): Final headers including vendor auth.
        body (dict): JSON-serializable body object.
        timeout_s (float): Socket + read timeout in seconds.

    Returns:
        httpx.Response: Response with ``content`` populated.

    Examples:
        >>> import inspect
        >>> from sevn.proxy.forward import post_json
        >>> inspect.iscoroutinefunction(post_json)
        True
    """
    timeout = httpx.Timeout(timeout_s)
    headers = _sanitize_outbound_headers(headers)
    logger.debug(
        "proxy upstream POST {url} headers={headers} request={request}",
        url=url,
        headers=redact_headers(headers),
        request=summarize_request_body(body),
    )
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout) as client:
        raw = await client.post(url, json=body, headers=headers)
        await raw.aread()
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    _log_upstream_outcome(
        method="POST",
        url=url,
        body=body,
        status=raw.status_code,
        response_content=raw.content,
        response_ct=raw.headers.get("content-type", "application/json"),
        elapsed_ms=elapsed_ms,
    )
    return raw


async def post_sse_stream(
    *,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout_s: float = 120.0,
) -> tuple[httpx.AsyncClient, httpx.Response]:
    """POST with streaming response — caller must ``aclose`` both objects.

    On non-2xx upstream status the proxy route logs a ``WARNING`` once the body
    has been consumed (see ``sevn.proxy.app::sse_or_json``); here we emit a
    ``DEBUG`` request-only line before sending.

    Args:
        url (str): Upstream URL.
        headers (dict[str, str]): Final headers.
        body (dict): JSON body (often includes ``\"stream\": true``).
        timeout_s (float): Timeouts on the shared client.

    Returns:
        tuple[httpx.AsyncClient, httpx.Response]: Client and streaming response.

    Examples:
        >>> import inspect
        >>> from sevn.proxy.forward import post_sse_stream
        >>> inspect.iscoroutinefunction(post_sse_stream)
        True
    """
    timeout = httpx.Timeout(timeout_s)
    headers = _sanitize_outbound_headers(headers)
    logger.debug(
        "proxy upstream POST (stream) {url} headers={headers} request={request}",
        url=url,
        headers=redact_headers(headers),
        request=summarize_request_body(body),
    )
    client = httpx.AsyncClient(timeout=timeout)
    req = client.build_request("POST", url, json=body, headers=headers)
    resp = await client.send(req, stream=True)
    return client, resp


__all__ = [
    "post_json",
    "post_sse_stream",
    "redact_headers",
    "summarize_request_body",
]
