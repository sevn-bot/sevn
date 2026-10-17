"""Durable outbox (D10)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest


def _url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'sevn.db'}"


async def _outbox(tmp_path: Path) -> object:
    from sevn.store.db import upgrade
    from sevn.store.outbox import Outbox

    url = _url(tmp_path)
    await upgrade(url)
    return Outbox(url)


def _rows(tmp_path: Path) -> list[tuple[int, object]]:
    with sqlite3.connect(tmp_path / "sevn.db") as connection:
        fetched = connection.execute("SELECT seq, payload FROM events ORDER BY seq").fetchall()
    rows: list[tuple[int, object]] = []
    for seq, payload in fetched:
        if isinstance(payload, str):
            payload = json.loads(payload)
        rows.append((int(seq), payload))
    return rows


async def test_append_is_monotonic(tmp_path: Path) -> None:
    box = await _outbox(tmp_path)
    events = await asyncio.gather(
        *(box.append("system.ping", "system", {"i": i}) for i in range(50))  # type: ignore[attr-defined]
    )
    seqs = sorted(event.seq for event in events)
    assert seqs == list(range(seqs[0], seqs[0] + 50))


async def test_since_returns_ordered_after(tmp_path: Path) -> None:
    box = await _outbox(tmp_path)
    created = []
    for i in range(5):
        created.append(await box.append("system.ping", "bot", {"i": i}))  # type: ignore[attr-defined]
    assert created[0].seq == 1
    got = await box.since(3)  # type: ignore[attr-defined]
    assert [event.seq for event in got] == [4, 5]
    assert [event.payload["i"] for event in got] == [3, 4]


async def test_since_pruned_raises_resync_required(tmp_path: Path) -> None:
    from sevn.store.outbox import ResyncRequired

    box = await _outbox(tmp_path)
    for i in range(4):
        await box.append("system.ping", "system", {"i": i})  # type: ignore[attr-defined]
    await box.prune(max_age=timedelta(days=7), max_rows=2)  # type: ignore[attr-defined]
    remaining = _rows(tmp_path)
    assert [payload["i"] for _seq, payload in remaining] == [2, 3]
    with pytest.raises(ResyncRequired) as exc:
        await box.since(0)  # type: ignore[attr-defined]
    assert exc.value.code == "resync_required"
    assert exc.value.min_seq == remaining[0][0]


async def test_prune_by_age(tmp_path: Path) -> None:
    from freezegun import freeze_time

    box = await _outbox(tmp_path)
    with freeze_time("2026-01-01T00:00:00+00:00", tick=False):
        old = await box.append("system.ping", "system", {"note": "old"})  # type: ignore[attr-defined]
    with freeze_time("2026-01-09T00:00:00+00:00", tick=False):
        fresh = await box.append("system.ping", "system", {"note": "fresh"})  # type: ignore[attr-defined]
        await box.prune(max_age=timedelta(days=7), max_rows=100_000)  # type: ignore[attr-defined]
    seqs = {seq for seq, _payload in _rows(tmp_path)}
    assert old.seq not in seqs
    assert fresh.seq in seqs
