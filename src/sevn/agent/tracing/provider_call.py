"""Canonical ``provider.call`` trace emission for dashboard budget and provider stats.

Module: sevn.agent.tracing.provider_call
Depends: sevn.agent.tracing.sink

Exports:
    emit_provider_call — write one ``provider.call`` span with PRD §5.11 attrs.

Also exposes the module-level constant ``PROVIDER_CALL_KIND`` (``'provider.call'``).

Canonical attrs (Pre-0 #1 W0):
    ``cost.tokens_in``, ``cost.tokens_out``, ``model.id``, ``regime``, ``transport``,
    ``latency_ms``, ``tier``, ``status``.
"""

from __future__ import annotations

from sevn.agent.tracing.sink import TraceEvent, TraceSink

PROVIDER_CALL_KIND = "provider.call"


def _latency_ms(start_ns: int, end_ns: int) -> float:
    """Compute elapsed milliseconds between two nanosecond timestamps.

    Args:
        start_ns (int): Start time in nanoseconds.
        end_ns (int): End time in nanoseconds.

    Returns:
        float: Non-negative elapsed milliseconds.

    Examples:
        >>> _latency_ms(0, 2_000_000)
        2.0
    """
    if end_ns <= start_ns:
        return 0.0
    return round((end_ns - start_ns) / 1_000_000.0, 3)


async def emit_provider_call(
    trace: TraceSink | None,
    *,
    span_id: str,
    parent_span_id: str | None,
    session_id: str,
    turn_id: str,
    model_id: str,
    regime: str,
    tokens_in: int,
    tokens_out: int,
    transport: str,
    tier: str | None = None,
    status: str = "ok",
    ts_start_ns: int,
    ts_end_ns: int | None = None,
    extra_attrs: dict[str, object] | None = None,
) -> None:
    """Emit one ``provider.call`` row with canonical cost attrs.

    Args:
        trace (TraceSink | None): Destination sink; no-op when ``None``.
        span_id (str): Span id (may match a wire-specific provider span).
        parent_span_id (str | None): Turn root span for linkage.
        session_id (str): Gateway session id.
        turn_id (str): Turn correlation id.
        model_id (str): Catalog model id.
        regime (str): Budget regime label (``PER_TOKEN``, ``SUBSCRIPTION``, …).
        tokens_in (int): Input token count.
        tokens_out (int): Output token count.
        transport (str): Wire/transport label (``anthropic``, ``chat_completions``, …).
        tier (str | None): Executor tier (``A``, ``B``, ``C``, …).
        status (str): Span status (``ok``, ``error``, …).
        ts_start_ns (int): Start timestamp in nanoseconds.
        ts_end_ns (int | None): End timestamp; defaults to ``ts_start_ns``.
        extra_attrs (dict[str, object] | None): Optional non-canonical attrs merged in.

    Returns:
        None: Always.

    Examples:
        >>> import asyncio
        >>> from sevn.agent.tracing.sink import NullTraceSink
        >>> asyncio.run(emit_provider_call(
        ...     NullTraceSink(),
        ...     span_id="s1",
        ...     parent_span_id=None,
        ...     session_id="sess",
        ...     turn_id="turn",
        ...     model_id="anthropic/claude-sonnet-4-6",
        ...     regime="PER_TOKEN",
        ...     tokens_in=10,
        ...     tokens_out=5,
        ...     transport="anthropic",
        ...     tier="B",
        ...     ts_start_ns=1,
        ...     ts_end_ns=2,
        ... )) is None
        True
    """
    if trace is None:
        return
    end_ns = ts_end_ns if ts_end_ns is not None else ts_start_ns
    attrs: dict[str, object] = {
        "cost.tokens_in": tokens_in,
        "cost.tokens_out": tokens_out,
        "model.id": model_id,
        "regime": regime,
        "transport": transport,
        "latency_ms": _latency_ms(ts_start_ns, end_ns),
        "status": status,
    }
    if tier is not None:
        attrs["tier"] = tier
    if extra_attrs:
        attrs.update(extra_attrs)
    await trace.emit(
        TraceEvent(
            kind=PROVIDER_CALL_KIND,
            span_id=span_id,
            parent_span_id=parent_span_id,
            session_id=session_id,
            turn_id=turn_id,
            tier=tier,
            ts_start_ns=ts_start_ns,
            ts_end_ns=end_ns,
            status=status,
            attrs=attrs,
        ),
    )


__all__ = ["PROVIDER_CALL_KIND", "emit_provider_call"]
