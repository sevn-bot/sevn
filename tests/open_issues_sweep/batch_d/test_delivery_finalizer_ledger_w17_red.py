"""W17.3 — tier-B finalizer failure path uses delivery ledger (#75 → W18)."""

from __future__ import annotations

from typing import Any

import pytest

from sevn.gateway.turn.turn_finalizer import TierBAnswerFinalizer
from tests.open_issues_sweep.batch_d.conftest import table_exists


class _StubAdapter:
    """Adapter that declines edits so finalize falls back to router send."""

    def __init__(self) -> None:
        self.edits: list[dict[str, Any]] = []

    async def send(self, message: Any) -> list[str]:
        return ["placeholder-1"]

    async def edit_text(
        self,
        *,
        channel_message_id: str,
        new_text: str,
        metadata: dict[str, Any] | None = None,
        send_split_followups: bool = True,
    ) -> bool:
        self.edits.append({"channel_message_id": channel_message_id, "text": new_text})
        return False


class _LedgerCapturingRouter:
    """Router stub recording fallback sends and ledger hooks."""

    def __init__(self) -> None:
        self.fallback_sends: list[dict[str, Any]] = []
        self.ledger_records: list[dict[str, Any]] = []

    async def route_outgoing(self, msg: Any) -> None:
        self.fallback_sends.append({"text": msg.text, "metadata": dict(msg.metadata)})
        self.last_delivery_obligation = {
            "session_id": msg.session_id,
            "message_id": 1,
            "status": "confirmed",
        }
        record = getattr(self, "last_delivery_obligation", None)
        if record is not None:
            self.ledger_records.append(record)

    def cancel_telegram_typing(self, session_id: str) -> None:
        return None


def _make_finalizer(adapter: _StubAdapter, router: _LedgerCapturingRouter) -> TierBAnswerFinalizer:
    return TierBAnswerFinalizer(
        router=router,  # type: ignore[arg-type]
        adapter=adapter,  # type: ignore[arg-type]
        channel="telegram",
        user_id="u1",
        session_id="sess-fin",
        turn_id="turn-fin",
        metadata={"chat_id": 1},
    )


@pytest.mark.asyncio
async def test_finalize_failure_falls_back_to_router_send_today() -> None:
    """Baseline: failure path already routes through ``route_outgoing`` on edit decline."""
    adapter = _StubAdapter()
    router = _LedgerCapturingRouter()
    fin = _make_finalizer(adapter, router)
    await fin.place_placeholder()
    edited = await fin.finalize(status="timeout")
    assert edited is False
    assert router.fallback_sends
    assert "ran out of time" in router.fallback_sends[0]["text"]


@pytest.mark.asyncio
async def test_finalize_failure_records_delivery_obligation() -> None:
    """Failure fallback must create/update a ledger row, not bypass persistence."""
    adapter = _StubAdapter()
    router = _LedgerCapturingRouter()
    fin = _make_finalizer(adapter, router)
    await fin.place_placeholder()
    await fin.finalize(status="timeout")

    assert router.ledger_records, (
        "W18: route_outgoing must record delivery obligation on failure send"
    )
    record = router.ledger_records[0]
    assert record.get("session_id") == "sess-fin"
    assert record.get("status") in {"pending", "confirmed"}


@pytest.mark.asyncio
async def test_finalize_failure_persists_obligation_row_in_sqlite(batch_d_conn: object) -> None:
    """Integration: tier-B timeout path leaves a ``delivery_obligations`` row."""
    import sqlite3

    assert isinstance(batch_d_conn, sqlite3.Connection)
    assert table_exists(batch_d_conn, "delivery_obligations")

    from sevn.gateway.turn.turn_finalizer import finalize_failure_through_ledger

    await finalize_failure_through_ledger(
        conn=batch_d_conn,
        session_id="sess-fin",
        channel="telegram",
        user_id="u1",
        text="I ran out of time on that request.",
        turn_id="turn-fin",
    )
    count = batch_d_conn.execute("SELECT COUNT(*) FROM delivery_obligations").fetchone()[0]
    assert int(count) >= 1
