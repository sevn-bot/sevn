"""E2E-only echo dispatch for local diagnostics / harness stacks.

Module: sevn.gateway.api.e2e_echo
Depends: asyncio, sevn.gateway.channel_router, sevn.gateway.session_manager

Exports:
    build_echo_run_turn — factory for a :class:`~sevn.gateway.channel_router.ChannelRouter`
        ``run_turn`` that echoes the latest user line over ``route_outgoing``.

The module-level constant ``SEVN_E2E_ECHO_DELAY_ENV`` records the env var
name read by the echo run-turn before sending the outbound reply (test stacks
only — `specs/17-gateway.md` §2.9). Gated by ``SEVN_E2E_ECHO_TURN`` in
``http_server``; kept as a thin diagnostics echo after the TS E2E harness removal.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from typing import TYPE_CHECKING

from loguru import logger

from sevn.gateway.channel_router import OutgoingMessage
from sevn.gateway.session_manager import latest_messages, load_session_row

if TYPE_CHECKING:
    from sevn.gateway.channel_router import ChannelRouter, RunTurnFn


SEVN_E2E_ECHO_DELAY_ENV = "SEVN_E2E_ECHO_DELAY_MS"


def _echo_delay_seconds() -> float:
    """Parse :data:`SEVN_E2E_ECHO_DELAY_ENV` into a non-negative seconds delay.

    Returns:
        float: Seconds to sleep before sending the echo outbound. ``0.0`` when
            the env var is unset, non-numeric, or non-positive — keeping the
            production-default path free of artificial latency.

    Examples:
        >>> import os
        >>> os.environ.pop("SEVN_E2E_ECHO_DELAY_MS", None) and None
        >>> _echo_delay_seconds()
        0.0
    """
    raw = os.environ.get(SEVN_E2E_ECHO_DELAY_ENV)
    if raw is None:
        return 0.0
    try:
        ms = int(str(raw).strip())
    except ValueError:
        logger.warning(
            "gateway.e2e_echo_delay_invalid env={} value={!r}",
            SEVN_E2E_ECHO_DELAY_ENV,
            raw,
        )
        return 0.0
    if ms <= 0:
        return 0.0
    return ms / 1000.0


def build_echo_run_turn(
    router: ChannelRouter,
    conn: sqlite3.Connection,
) -> RunTurnFn:
    """Return a ``run_turn`` that echoes the latest user message (E2E / local only).

    Args:
        router (ChannelRouter): Router used for ``route_outgoing``.
        conn (sqlite3.Connection): Open gateway SQLite handle.

    Returns:
        RunTurnFn: Async callable matching :class:`ChannelRouter` dispatch glue.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(build_echo_run_turn)
        True
    """

    async def _echo(session_id: str, correlation_id: str) -> None:
        _ = correlation_id
        rows = await asyncio.to_thread(latest_messages, conn, session_id)
        user_text = ""
        for row in reversed(rows):
            if row.get("role") == "user" and row.get("kind") == "message":
                user_text = str(row.get("content") or "")
                break
        sess = await asyncio.to_thread(load_session_row, conn, session_id)
        channel = sess.channel if sess is not None else "webchat"
        user_id = sess.user_id if sess is not None else "owner"
        reply = f"echo: {user_text}" if user_text else "echo: ok"
        delay = _echo_delay_seconds()
        if delay > 0.0:
            await asyncio.sleep(delay)
        await router.route_outgoing(
            OutgoingMessage(
                channel=channel,
                user_id=user_id,
                text=reply,
                session_id=session_id,
            ),
        )

    return _echo
