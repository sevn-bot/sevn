"""W17.2 — delivery crash/restart matrix (#75 → W18).

Covers crash before adapter send (replay once) and crash after adapter send but before
status confirmation (must not double-send — today's gap in ``sweep_outbound_retries``).
"""

from __future__ import annotations

import sqlite3

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.gateway.channel_router import OutgoingMessage
from sevn.gateway.routing.outbound_sweep import sweep_outbound_retries
from sevn.storage.migrate import apply_migrations
from tests.open_issues_sweep.batch_d.conftest import (
    insert_pending_assistant_message,
    seed_gateway_session,
)


class _CountingAdapter:
    """Records ``send`` calls for idempotency assertions."""

    def __init__(self, *, platform_message_id: str = "plat-99") -> None:
        self.send_calls: list[OutgoingMessage] = []
        self._platform_message_id = platform_message_id

    async def send(self, message: OutgoingMessage) -> list[str]:
        self.send_calls.append(message)
        return [self._platform_message_id]


class _RecordingRouter:
    """Minimal router stub for ``sweep_outbound_retries``."""

    def __init__(self, adapter: _CountingAdapter) -> None:
        self._adapter = adapter

    def adapter_named(self, channel: str) -> _CountingAdapter | None:
        if channel == "telegram":
            return self._adapter
        return None


@pytest.mark.asyncio
async def test_sweep_replays_pending_message_exactly_once_when_never_sent() -> None:
    """Crash before adapter send: boot replay delivers once and marks sent."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    seed_gateway_session(conn, session_id="sess-crash-before")
    insert_pending_assistant_message(conn, session_id="sess-crash-before", content="hello")
    adapter = _CountingAdapter()
    router = _RecordingRouter(adapter)

    sent_ok = await sweep_outbound_retries(conn=conn, router=router, trace=NullTraceSink())  # type: ignore[arg-type]

    assert sent_ok == 1
    assert len(adapter.send_calls) == 1
    status = conn.execute(
        "SELECT status FROM gateway_messages WHERE content = 'hello'",
    ).fetchone()
    assert status is not None
    assert str(status[0]) == "sent"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W18: adapter-confirmed idempotency", strict=False)
async def test_sweep_does_not_resend_when_platform_already_confirmed() -> None:
    """Crash after adapter send but before status update must not double-send (#75 gap)."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    seed_gateway_session(conn, session_id="sess-after-send")
    mid = insert_pending_assistant_message(
        conn,
        session_id="sess-after-send",
        content="already-on-wire",
    )
    adapter = _CountingAdapter(platform_message_id="tg-msg-4242")
    router = _RecordingRouter(adapter)

    # W18: persist adapter-confirmed idempotency token while status stays pending.
    conn.execute(
        """
        INSERT INTO delivery_obligations (
            message_id, session_id, channel, user_id, payload_hash,
            adapter_message_id, status, created_at_ns, updated_at_ns
        ) VALUES (?, 'sess-after-send', 'telegram', '42', 'hash', 'tg-msg-4242', 'confirmed', 1, 1)
        """,
        (mid,),
    )
    conn.commit()

    await sweep_outbound_retries(conn=conn, router=router, trace=NullTraceSink())  # type: ignore[arg-type]

    assert len(adapter.send_calls) == 0, "replay must not call adapter.send when platform confirmed"
    status = conn.execute("SELECT status FROM gateway_messages WHERE id = ?", (mid,)).fetchone()
    assert status is not None
    assert str(status[0]) == "sent"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W18: adapter-confirmed idempotency", strict=False)
async def test_current_sweep_double_sends_after_platform_send_before_status_update() -> None:
    """Documents today's double-send window: pending row with no ledger confirmation."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    seed_gateway_session(conn, session_id="sess-gap")
    insert_pending_assistant_message(conn, session_id="sess-gap", content="gap-case")
    adapter = _CountingAdapter()
    router = _RecordingRouter(adapter)

    # Simulate first delivery attempt that reached the adapter but crashed before UPDATE.
    await adapter.send(
        OutgoingMessage(
            channel="telegram",
            user_id="42",
            text="gap-case",
            session_id="sess-gap",
            metadata={},
        ),
    )

    await sweep_outbound_retries(conn=conn, router=router, trace=NullTraceSink())  # type: ignore[arg-type]

    # Desired W18 behavior: total adapter sends == 1. Today: 2 (original + sweep).
    assert len(adapter.send_calls) == 1


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W18: delivery obligation ledger", strict=False)
async def test_route_outgoing_writes_delivery_obligation_before_adapter_send() -> None:
    """Every outbound path must persist a ledger row before ``adapter.send``."""
    from sevn.gateway.channel_router import ChannelRouter

    assert hasattr(ChannelRouter, "route_outgoing")
    # W18 wires ``route_outgoing`` to ``delivery_obligations`` — import after W18 lands.
    import sevn.storage.delivery as delivery_mod

    assert hasattr(delivery_mod, "count_open_obligations")
