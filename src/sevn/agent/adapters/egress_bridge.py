"""httpx egress bridge for native pydantic-ai models via the sevn proxy (W2).

Module: sevn.agent.adapters.egress_bridge
Depends: httpx, sevn.agent.providers.transport, sevn.agent.providers.transport_http,
    sevn.agent.tracing.redacting_sink, sevn.agent.tracing.sink, sevn.proxy.forward

Exports:
    resolve_proxy_shared_secret — read ``SEVN_PROXY_SHARED_SECRET`` from process env.
    EgressBridgeContext — trace + correlation fields for provider checkpoints.
    redact_llm_request_snapshot — redact headers/body like the proxy transport path.
    redact_httpx_request_snapshot — redact one outbound httpx request for trace attrs.
    redact_proxy_transport_request — reference snapshot via ``_ProxyTransport.auth_header``.
    build_sevn_httpx_event_hooks — request/response hooks (secret, redaction, trace).
    build_sevn_anthropic_client — ``httpx.AsyncClient`` for ``AnthropicProvider(http_client=…)``.
    build_sevn_openai_client — OpenAI/Responses analog.

Examples:
    >>> from sevn.agent.adapters.egress_bridge import PROXY_TOKEN_HEADER
    >>> PROXY_TOKEN_HEADER
    'X-Sevn-Proxy-Token'
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from time import time_ns
from typing import TYPE_CHECKING, Any

import httpx

from sevn.agent.providers.transport import _response_tokens
from sevn.agent.providers.transport_http import _redacted_request_body_shape
from sevn.agent.tracing.provider_call import emit_provider_call
from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy, redact_attrs
from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.proxy.forward import redact_headers

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sevn.agent.providers.transport import _ProxyTransport

PROXY_TOKEN_HEADER = "X-Sevn-Proxy-Token"  # nosec B105 — HTTP header name, not a secret
"""Header carrying the gateway→proxy shared secret (``specs/07-egress-proxy.md``)."""

_EGRESS_SPAN_EXTENSION_KEY = "sevn_egress_span_id"
_EGRESS_START_NS_EXTENSION_KEY = "sevn_egress_start_ns"

_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)


def resolve_proxy_shared_secret(*, env: Mapping[str, str] | None = None) -> str | None:
    """Return ``SEVN_PROXY_SHARED_SECRET`` when set and non-empty.

    Args:
        env (mapping | None): Env mapping; defaults to ``os.environ``.

    Returns:
        str | None: Stripped secret text or ``None`` when unset.

    Examples:
        >>> resolve_proxy_shared_secret(env={"SEVN_PROXY_SHARED_SECRET": "  tok  "})
        'tok'
        >>> resolve_proxy_shared_secret(env={}) is None
        True
    """
    mapping = os.environ if env is None else env
    raw = mapping.get("SEVN_PROXY_SHARED_SECRET", "")
    text = raw.strip() if isinstance(raw, str) else ""
    return text or None


@dataclass(frozen=True)
class EgressBridgeContext:
    """Correlation + trace sink for one native-model HTTP round-trip."""

    trace: TraceSink | None
    session_id: str
    turn_id: str
    tier: str | None = None
    parent_span_id: str | None = None
    redaction_policy: TraceRedactionPolicy | None = None
    model_id: str = ""
    regime: str = "PER_TOKEN"
    transport: str = "anthropic"


def _parse_json_object(content: bytes) -> dict[str, Any]:
    """Parse request/response bytes as a JSON object when possible.

    Args:
        content (bytes): Raw HTTP body bytes.

    Returns:
        dict[str, Any]: Parsed object or ``{}`` when empty/invalid.

    Examples:
        >>> _parse_json_object(b'{"model": "m"}')["model"]
        'm'
        >>> _parse_json_object(b"")
        {}
    """
    if not content:
        return {}
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def redact_llm_request_snapshot(
    *,
    headers: dict[str, str],
    body: dict[str, Any],
    redaction_policy: TraceRedactionPolicy | None = None,
) -> dict[str, object]:
    """Return redaction-safe request metadata matching the proxy transport path.

    Composes :func:`sevn.proxy.forward.redact_headers` and
    :func:`sevn.agent.providers.transport_http._redacted_request_body_shape` — the
    same primitives used when ``_ProxyTransport`` logs a bad request.

    Args:
        headers (dict[str, str]): Outbound HTTP headers (may include auth secrets).
        body (dict[str, Any]): Provider-shaped JSON body.
        redaction_policy (TraceRedactionPolicy | None): Optional workspace policy
            applied to the snapshot mapping after transport-level redaction.

    Returns:
        dict[str, object]: ``{"headers": …, "body": …}`` safe for trace attrs.

    Examples:
        >>> snap = redact_llm_request_snapshot(
        ...     headers={"x-api-key": "abcdef123456"},
        ...     body={"model": "m", "messages": [{"role": "user", "content": "secret"}]},
        ... )
        >>> snap["headers"]["x-api-key"]
        '<redacted:12>'
        >>> "secret" not in str(snap["body"])
        True
    """
    normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
    snapshot: dict[str, object] = {
        "headers": redact_headers(normalized_headers),
        "body": _redacted_request_body_shape(body),
    }
    if redaction_policy is not None:
        redacted = redact_attrs(snapshot, redaction_policy)
        return dict(redacted)
    return snapshot


def redact_proxy_transport_request(
    transport: _ProxyTransport,
    *,
    model_id: str,
    body: dict[str, Any],
    redaction_policy: TraceRedactionPolicy | None = None,
) -> dict[str, object]:
    """Reference redaction snapshot for ``_ProxyTransport`` header + body parity (W2.4).

    Args:
        transport (_ProxyTransport): Proxy-backed transport under test.
        model_id (str): Catalog model id passed to :meth:`_ProxyTransport.auth_header`.
        body (dict[str, Any]): Provider-shaped JSON body.
        redaction_policy (TraceRedactionPolicy | None): Optional workspace policy.

    Returns:
        dict[str, object]: Redacted snapshot comparable to :func:`redact_llm_request_snapshot`.

    Examples:
        >>> from sevn.agent.providers.transport import AnthropicTransport
        >>> t = AnthropicTransport(
        ...     proxy_base_url="http://proxy",
        ...     extra_headers={"X-Sevn-Proxy-Token": "sec"},
        ... )
        >>> snap = redact_proxy_transport_request(
        ...     t, model_id="anthropic/claude", body={"model": "m", "messages": []},
        ... )
        >>> snap["headers"]["x-sevn-proxy-token"]
        'sec'
    """
    headers = transport.auth_header(model_id)
    return redact_llm_request_snapshot(
        headers=headers,
        body=body,
        redaction_policy=redaction_policy,
    )


_HOP_BY_HOP_HEADERS: frozenset[str] = frozenset(
    {
        "host",
        "content-length",
        "accept",
        "accept-encoding",
        "connection",
        "user-agent",
        "content-type",
    },
)


def _wire_headers_for_trace(request: httpx.Request) -> dict[str, str]:
    """Return non-hop-by-hop request headers for trace snapshots.

    Args:
        request (httpx.Request): Outbound httpx request.

    Returns:
        dict[str, str]: Header names to values excluding hop-by-hop fields.

    Examples:
        >>> req = httpx.Request("GET", "http://example.com", headers={"x-api-key": "k"})
        >>> _wire_headers_for_trace(req)["x-api-key"]
        'k'
    """
    out: dict[str, str] = {}
    for key, value in request.headers.items():
        if key.lower() in _HOP_BY_HOP_HEADERS:
            continue
        out[str(key)] = str(value)
    return out


def redact_httpx_request_snapshot(
    request: httpx.Request,
    *,
    redaction_policy: TraceRedactionPolicy | None = None,
) -> dict[str, object]:
    """Redact one outbound ``httpx.Request`` for trace attrs.

    Args:
        request (httpx.Request): Request about to leave the gateway.
        redaction_policy (TraceRedactionPolicy | None): Optional workspace policy.

    Returns:
        dict[str, object]: Redacted snapshot of headers + JSON body shape.

    Examples:
        >>> req = httpx.Request(
        ...     "POST",
        ...     "http://proxy/llm/anthropic/messages",
        ...     headers={"x-api-key": "longsecretvalue"},
        ...     json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
        ... )
        >>> snap = redact_httpx_request_snapshot(req)
        >>> snap["headers"]["x-api-key"].startswith("<redacted:")
        True
    """
    headers = _wire_headers_for_trace(request)
    body = _parse_json_object(request.content)
    return redact_llm_request_snapshot(
        headers=headers,
        body=body,
        redaction_policy=redaction_policy,
    )


def _redact_response_snapshot(
    response: httpx.Response,
    *,
    redaction_policy: TraceRedactionPolicy | None = None,
) -> dict[str, object]:
    """Build a redaction-safe response snapshot for ``provider.after`` attrs.

    Args:
        response (httpx.Response): Upstream/proxy HTTP response.
        redaction_policy (TraceRedactionPolicy | None): Optional workspace policy.

    Returns:
        dict[str, object]: Status, redacted headers, and optional body shape.

    Examples:
        >>> resp = httpx.Response(200, json={"id": "m"}, request=httpx.Request("GET", "http://x"))
        >>> snap = _redact_response_snapshot(resp)
        >>> snap["status_code"]
        200
    """
    headers = {str(k): str(v) for k, v in response.headers.items()}
    body = _parse_json_object(response.content)
    snapshot: dict[str, object] = {
        "status_code": response.status_code,
        "headers": redact_headers(headers),
    }
    if body:
        snapshot["body"] = _redacted_request_body_shape(body)
    elif response.content:
        snapshot["body_bytes"] = len(response.content)
    if redaction_policy is not None:
        redacted = redact_attrs(snapshot, redaction_policy)
        return dict(redacted)
    return snapshot


def _inject_proxy_token(request: httpx.Request, shared_secret: str | None) -> None:
    """Attach ``X-Sevn-Proxy-Token`` when a shared secret is configured.

    Args:
        request (httpx.Request): Outbound request mutated in place.
        shared_secret (str | None): Proxy guard token from ``SEVN_PROXY_SHARED_SECRET``.

    Returns:
        None: Mutates ``request.headers`` in place.

    Examples:
        >>> req = httpx.Request("POST", "http://proxy/llm/anthropic/messages")
        >>> _inject_proxy_token(req, "sec")
        >>> req.headers["x-sevn-proxy-token"]
        'sec'
    """
    if shared_secret and shared_secret.strip():
        request.headers[PROXY_TOKEN_HEADER] = shared_secret.strip()


async def _emit_provider_before(
    request: httpx.Request,
    *,
    ctx: EgressBridgeContext,
) -> None:
    """Emit ``provider.before`` and stash span correlation on the request.

    Args:
        request (httpx.Request): Outbound request about to be sent.
        ctx (EgressBridgeContext): Trace sink and correlation ids.

    Returns:
        None: Emits asynchronously when ``ctx.trace`` is set.

    Examples:
        >>> import asyncio
        >>> req = httpx.Request("POST", "http://proxy/llm/anthropic/messages")
        >>> asyncio.run(
        ...     _emit_provider_before(
        ...         req,
        ...         ctx=EgressBridgeContext(trace=None, session_id="s", turn_id="t"),
        ...     ),
        ... )
        >>> isinstance(req.extensions.get("sevn_egress_span_id"), str)
        True
    """
    span_id = str(uuid.uuid4())
    start_ns = time_ns()
    request.extensions[_EGRESS_SPAN_EXTENSION_KEY] = span_id
    request.extensions[_EGRESS_START_NS_EXTENSION_KEY] = start_ns
    if ctx.trace is None:
        return
    attrs: dict[str, object] = {
        "method": request.method,
        "url": str(request.url),
        "request": redact_httpx_request_snapshot(request, redaction_policy=ctx.redaction_policy),
    }
    await ctx.trace.emit(
        TraceEvent(
            kind="provider.before",
            span_id=span_id,
            parent_span_id=ctx.parent_span_id,
            session_id=ctx.session_id,
            turn_id=ctx.turn_id,
            tier=ctx.tier,
            ts_start_ns=start_ns,
            ts_end_ns=None,
            status="started",
            attrs=attrs,
        ),
    )


async def _emit_provider_after(
    response: httpx.Response,
    *,
    ctx: EgressBridgeContext,
) -> None:
    """Emit ``provider.after`` for the span opened in :func:`_emit_provider_before`.

    Args:
        response (httpx.Response): HTTP response paired with the traced request.
        ctx (EgressBridgeContext): Trace sink and correlation ids.

    Returns:
        None: Emits asynchronously when ``ctx.trace`` is set.

    Examples:
        >>> import asyncio
        >>> req = httpx.Request("POST", "http://proxy/llm/anthropic/messages")
        >>> req.extensions["sevn_egress_span_id"] = "span-1"
        >>> req.extensions["sevn_egress_start_ns"] = 1
        >>> resp = httpx.Response(200, request=req)
        >>> asyncio.run(
        ...     _emit_provider_after(
        ...         resp,
        ...         ctx=EgressBridgeContext(trace=None, session_id="s", turn_id="t"),
        ...     ),
        ... ) is None
        True
    """
    request = response.request
    span_id = request.extensions.get(_EGRESS_SPAN_EXTENSION_KEY)
    start_ns = request.extensions.get(_EGRESS_START_NS_EXTENSION_KEY)
    if not isinstance(span_id, str) or not isinstance(start_ns, int):
        return
    if ctx.trace is None:
        return
    end_ns = time_ns()
    status = "ok" if response.is_success else "error"
    attrs: dict[str, object] = {
        "method": request.method,
        "url": str(request.url),
        "response": _redact_response_snapshot(response, redaction_policy=ctx.redaction_policy),
    }
    await ctx.trace.emit(
        TraceEvent(
            kind="provider.after",
            span_id=span_id,
            parent_span_id=ctx.parent_span_id,
            session_id=ctx.session_id,
            turn_id=ctx.turn_id,
            tier=ctx.tier,
            ts_start_ns=start_ns,
            ts_end_ns=end_ns,
            status=status,
            attrs=attrs,
        ),
    )
    tokens_in, tokens_out = 0, 0
    if response.is_success:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                tokens_in, tokens_out = _response_tokens(payload, kind=ctx.transport)
        except (json.JSONDecodeError, TypeError, ValueError):
            tokens_in, tokens_out = 0, 0
    model_id = ctx.model_id or "unknown"
    await emit_provider_call(
        ctx.trace,
        span_id=span_id,
        parent_span_id=ctx.parent_span_id,
        session_id=ctx.session_id,
        turn_id=ctx.turn_id,
        model_id=model_id,
        regime=ctx.regime,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        transport=ctx.transport,
        tier=ctx.tier,
        status=status,
        ts_start_ns=start_ns,
        ts_end_ns=end_ns,
    )


def build_sevn_httpx_event_hooks(
    *,
    ctx: EgressBridgeContext,
    shared_secret: str | None,
) -> dict[str, list[Any]]:
    """Build httpx ``event_hooks`` for secret injection, redaction, and trace checkpoints.

    Args:
        ctx (EgressBridgeContext): Trace sink + correlation ids.
        shared_secret (str | None): Value for :data:`PROXY_TOKEN_HEADER`.

    Returns:
        dict[str, list]: ``{"request": [...], "response": [...]}`` hook lists.

    Examples:
        >>> hooks = build_sevn_httpx_event_hooks(
        ...     ctx=EgressBridgeContext(trace=None, session_id="s", turn_id="t"),
        ...     shared_secret="sec",
        ... )
        >>> "request" in hooks and "response" in hooks
        True
    """

    async def on_request(request: httpx.Request) -> None:
        _inject_proxy_token(request, shared_secret)
        await _emit_provider_before(request, ctx=ctx)

    async def on_response(response: httpx.Response) -> None:
        await _emit_provider_after(response, ctx=ctx)

    return {"request": [on_request], "response": [on_response]}


def build_sevn_anthropic_client(
    *,
    proxy_base: str,
    shared_secret: str | None,
    trace: TraceSink | None,
    redactor: TraceRedactionPolicy | None = None,
    session_id: str = "-",
    turn_id: str = "-",
    tier: str | None = None,
    parent_span_id: str | None = None,
    timeout: httpx.Timeout | None = None,
    model_id: str = "",
    regime: str = "PER_TOKEN",
    transport: str = "anthropic",
) -> httpx.AsyncClient:
    """Build an ``httpx.AsyncClient`` for ``AnthropicProvider(http_client=…)``.

    Pair with ``AnthropicProvider(base_url=<proxy_base>, http_client=client)`` — the
    provider ``base_url`` routes requests; the client ``base_url`` alone is ignored
    (W0.2 / spike).

    Args:
        proxy_base (str): Egress proxy origin (no trailing slash required).
        shared_secret (str | None): ``X-Sevn-Proxy-Token`` value when configured.
        trace (TraceSink | None): Optional trace sink for ``provider.before/after``.
        redactor (TraceRedactionPolicy | None): Workspace redaction for trace attrs.
        session_id (str): Session correlation id for trace rows.
        turn_id (str): Turn correlation id for trace rows.
        tier (str | None): Executor tier label (e.g. ``"B"``).
        parent_span_id (str | None): Parent span for checkpoint linkage.
        timeout (httpx.Timeout | None): Client timeout; defaults to W2 sketch values.
        model_id (str): Catalog model id for ``provider.call`` attribution.
        regime (str): Budget regime label for ``provider.call`` attrs.
        transport (str): Wire label for ``provider.call`` attrs (e.g. ``"anthropic"``).

    Returns:
        httpx.AsyncClient: Configured async client (caller owns lifecycle).

    Examples:
        >>> client = build_sevn_anthropic_client(
        ...     proxy_base="http://127.0.0.1:8787",
        ...     shared_secret="sec",
        ...     trace=None,
        ...     redactor=None,
        ... )
        >>> str(client.base_url).rstrip("/")
        'http://127.0.0.1:8787'
    """
    ctx = EgressBridgeContext(
        trace=trace,
        session_id=session_id,
        turn_id=turn_id,
        tier=tier,
        parent_span_id=parent_span_id,
        redaction_policy=redactor,
        model_id=model_id,
        regime=regime,
        transport=transport,
    )
    return httpx.AsyncClient(
        base_url=proxy_base.rstrip("/"),
        event_hooks=build_sevn_httpx_event_hooks(ctx=ctx, shared_secret=shared_secret),
        timeout=timeout or _DEFAULT_TIMEOUT,
    )


def build_sevn_openai_client(
    *,
    proxy_base: str,
    shared_secret: str | None,
    trace: TraceSink | None,
    redactor: TraceRedactionPolicy | None = None,
    session_id: str = "-",
    turn_id: str = "-",
    tier: str | None = None,
    parent_span_id: str | None = None,
    timeout: httpx.Timeout | None = None,
    model_id: str = "",
    regime: str = "PER_TOKEN",
    transport: str = "chat_completions",
) -> httpx.AsyncClient:
    """Build an ``httpx.AsyncClient`` for ``OpenAIProvider(http_client=…)``.

    Uses the same secret header, redaction, and trace hooks as
    :func:`build_sevn_anthropic_client`.

    Args:
        proxy_base (str): Egress proxy origin.
        shared_secret (str | None): ``X-Sevn-Proxy-Token`` value when configured.
        trace (TraceSink | None): Optional trace sink.
        redactor (TraceRedactionPolicy | None): Workspace redaction for trace attrs.
        session_id (str): Session correlation id.
        turn_id (str): Turn correlation id.
        tier (str | None): Executor tier label.
        parent_span_id (str | None): Parent span id.
        timeout (httpx.Timeout | None): Client timeout.
        model_id (str): Catalog model id for ``provider.call`` attribution.
        regime (str): Budget regime label for ``provider.call`` attrs.
        transport (str): Wire label for ``provider.call`` attrs (e.g. ``"chat_completions"``)

    Returns:
        httpx.AsyncClient: Configured async client.

    Examples:
        >>> client = build_sevn_openai_client(
        ...     proxy_base="http://proxy",
        ...     shared_secret=None,
        ...     trace=None,
        ...     redactor=None,
        ... )
        >>> client.timeout.read
        120.0
    """
    return build_sevn_anthropic_client(
        proxy_base=proxy_base,
        shared_secret=shared_secret,
        trace=trace,
        redactor=redactor,
        session_id=session_id,
        turn_id=turn_id,
        tier=tier,
        parent_span_id=parent_span_id,
        timeout=timeout,
        model_id=model_id,
        regime=regime,
        transport=transport,
    )


__all__ = [
    "PROXY_TOKEN_HEADER",
    "EgressBridgeContext",
    "build_sevn_anthropic_client",
    "build_sevn_httpx_event_hooks",
    "build_sevn_openai_client",
    "redact_httpx_request_snapshot",
    "redact_llm_request_snapshot",
    "redact_proxy_transport_request",
    "resolve_proxy_shared_secret",
]
