"""Dashboard test helper — emit provider.call via production path (#10 W10.1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sevn.agent.tracing import SQLiteSink
from sevn.agent.tracing.provider_call import PROVIDER_CALL_KIND, emit_provider_call


async def emit_provider_call_rows(
    traces_db: Path,
    *,
    session_id: str = "sess-a",
    turn_id: str = "t1",
    model_id: str = "anthropic/claude-sonnet-4-6",
    regime: str = "SUBSCRIPTION",
    tokens_in: int = 100,
    tokens_out: int = 50,
    transport: str = "anthropic",
    tier: str = "B",
    subscription_window_remaining: float | int | None = 73,
    subscription_window_id: str | None = "win-1",
) -> None:
    """Emit provider.call rows into traces_db via ``emit_provider_call``.

    Args:
        traces_db (Path): SQLite traces database path.
        session_id (str): Session id for trace rows.
        turn_id (str): Turn id for trace rows.
        model_id (str): Catalog model id.
        regime (str): Budget regime label.
        tokens_in (int): Input tokens.
        tokens_out (int): Output tokens.
        transport (str): Wire/transport label.
        tier (str): Executor tier label.
        subscription_window_remaining (float | int | None): Optional subscription window attr.
        subscription_window_id (str | None): Optional subscription window id.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(emit_provider_call_rows)
        True
    """
    extra: dict[str, object] = {}
    if subscription_window_remaining is not None:
        extra["subscription_window_remaining"] = subscription_window_remaining
    if subscription_window_id is not None:
        extra["subscription_window_id"] = subscription_window_id
    sink = SQLiteSink(traces_db)
    await emit_provider_call(
        sink,
        span_id=f"test-provider-{session_id}-{turn_id}",
        parent_span_id=None,
        session_id=session_id,
        turn_id=turn_id,
        model_id=model_id,
        regime=regime,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        transport=transport,
        tier=tier,
        status="ok",
        ts_start_ns=100,
        ts_end_ns=200,
        extra_attrs=extra or None,
    )
    await sink.close()


def count_provider_call_rows(conn: sqlite3.Connection) -> int:
    """Return number of provider.call rows.

    Args:
        conn (sqlite3.Connection): Open traces database connection.

    Returns:
        int: Row count.

    Examples:
        >>> import sqlite3
        >>> count_provider_call_rows(sqlite3.connect(":memory:"))
        0
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM trace_events WHERE kind = ?",
        (PROVIDER_CALL_KIND,),
    ).fetchone()
    return int(row[0]) if row is not None else 0
