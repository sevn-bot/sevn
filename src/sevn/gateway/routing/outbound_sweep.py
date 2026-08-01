"""Boot-time retry for stuck assistant deliveries (`specs/17-gateway.md` §4.4).
Module: sevn.gateway.routing.outbound_sweep
Depends: sqlite3, channel_router types
Exports:
    sweep_outbound_retries — ``adapter.send`` for ``pending`` / ``failed`` assistant rows.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from typing import TYPE_CHECKING

from loguru import logger

from sevn.agent.tracing.sink import TraceEvent
from sevn.gateway.channel_router import OutgoingMessage
from sevn.storage.delivery import (
    confirm_delivery_after_send,
    create_delivery_obligation,
    fail_delivery_obligation,
    hash_delivery_payload,
    is_delivery_confirmed,
    reconcile_confirmed_obligation,
)

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceSink
    from sevn.gateway.channel_router import ChannelRouter


async def sweep_outbound_retries(
    *,
    conn: sqlite3.Connection,
    router: ChannelRouter,
    trace: TraceSink,
) -> int:
    """Re-attempt delivery for assistant rows left ``pending`` or ``failed``.
    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        router (ChannelRouter): Registry of channel adapters.
        trace (TraceSink): Emits ``gateway.boot.recovery`` rows.
    Returns:
        int: Count of rows successfully marked ``sent``.
    Examples:
        >>> import inspect
        >>> from sevn.gateway.routing.outbound_sweep import sweep_outbound_retries
        >>> inspect.iscoroutinefunction(sweep_outbound_retries)
        True
    """
    rows = conn.execute(
        """
        SELECT gm.id, gm.content, gm.status, gs.session_id, gs.channel, gs.user_id
        FROM gateway_messages gm
        JOIN gateway_sessions gs ON gs.session_id = gm.session_id
        WHERE gm.role = 'assistant'
          AND gm.kind = 'message'
          AND gm.status IN ('pending', 'failed')
        ORDER BY gm.id ASC
        """,
    ).fetchall()
    sent_ok = 0
    for row in rows:
        mid = int(row[0])
        content = str(row[1])
        session_id = str(row[3])
        channel = str(row[4])
        user_id = str(row[5])
        now_ns = time.time_ns()
        turn_id = uuid.uuid4().hex
        if is_delivery_confirmed(conn, mid):
            if reconcile_confirmed_obligation(conn, mid):
                sent_ok += 1
                await trace.emit(
                    TraceEvent(
                        kind="gateway.boot.recovery",
                        span_id=uuid.uuid4().hex,
                        parent_span_id=None,
                        session_id=session_id,
                        turn_id=turn_id,
                        tier=None,
                        ts_start_ns=now_ns,
                        ts_end_ns=time.time_ns(),
                        status="reconciled_sent",
                        attrs={"message_id": mid, "channel": channel},
                    ),
                )
            continue
        adapter = router.adapter_named(channel)
        if adapter is None:
            await trace.emit(
                TraceEvent(
                    kind="gateway.boot.recovery",
                    span_id=uuid.uuid4().hex,
                    parent_span_id=None,
                    session_id=session_id,
                    turn_id=turn_id,
                    tier=None,
                    ts_start_ns=now_ns,
                    ts_end_ns=now_ns,
                    status="unknown_adapter",
                    attrs={"message_id": mid, "channel": channel},
                ),
            )
            continue
        create_delivery_obligation(
            conn,
            message_id=mid,
            session_id=session_id,
            channel=channel,
            user_id=user_id,
            payload_hash=hash_delivery_payload(content),
            now_ns=now_ns,
        )
        out = OutgoingMessage(
            channel=channel,
            user_id=user_id,
            text=content,
            session_id=session_id,
            metadata={},
        )
        try:
            chunks = await adapter.send(out)
        except Exception:
            logger.exception("outbound_sweep_send_failed message_id={}", mid)
            fail_delivery_obligation(
                conn,
                message_id=mid,
                error_details="send_error",
                now_ns=time.time_ns(),
            )
            conn.execute(
                "UPDATE gateway_messages SET status = 'failed' WHERE id = ?",
                (mid,),
            )
            conn.commit()
            await trace.emit(
                TraceEvent(
                    kind="gateway.boot.recovery",
                    span_id=uuid.uuid4().hex,
                    parent_span_id=None,
                    session_id=session_id,
                    turn_id=turn_id,
                    tier=None,
                    ts_start_ns=now_ns,
                    ts_end_ns=time.time_ns(),
                    status="send_error",
                    attrs={"message_id": mid, "channel": channel},
                ),
            )
            continue
        adapter_message_id = confirm_delivery_after_send(
            conn,
            message_id=mid,
            chunks=chunks,
            now_ns=time.time_ns(),
        )
        conn.execute(
            "UPDATE gateway_messages SET status = 'sent' WHERE id = ?",
            (mid,),
        )
        conn.commit()
        sent_ok += 1
        await trace.emit(
            TraceEvent(
                kind="gateway.boot.recovery",
                span_id=uuid.uuid4().hex,
                parent_span_id=None,
                session_id=session_id,
                turn_id=turn_id,
                tier=None,
                ts_start_ns=now_ns,
                ts_end_ns=time.time_ns(),
                status="retried_sent",
                attrs={
                    "message_id": mid,
                    "channel": channel,
                    "adapter_message_id": adapter_message_id,
                },
            ),
        )
    return sent_ok
