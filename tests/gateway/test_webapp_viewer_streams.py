"""Viewer in-memory stream store lifecycle and bounds (finding-8, W3)."""

from __future__ import annotations

import time
from typing import Any

import pytest

from sevn.gateway.webapp import webapp_viewer as viewer_mod
from sevn.gateway.webapp.webapp_viewer import (
    append_viewer_stream_chunk,
    mark_viewer_stream_done,
    register_viewer_stream,
    viewer_stream_snapshot,
)

# W3 remediation contract (finding-8) — pin until exported from webapp_viewer.
_EXPECTED_VIEWER_STREAM_MAX_ENTRIES = 256
_EXPECTED_VIEWER_STREAM_TTL_SECONDS = 1800.0


def _stream_limits() -> tuple[int, float]:
    max_entries = getattr(
        viewer_mod,
        "VIEWER_STREAM_MAX_ENTRIES",
        _EXPECTED_VIEWER_STREAM_MAX_ENTRIES,
    )
    ttl = getattr(viewer_mod, "VIEWER_STREAM_TTL_SECONDS", _EXPECTED_VIEWER_STREAM_TTL_SECONDS)
    return int(max_entries), float(ttl)


@pytest.fixture(autouse=True)
def _clear_viewer_streams() -> Any:
    viewer_mod._VIEWER_STREAMS.clear()
    yield
    viewer_mod._VIEWER_STREAMS.clear()


def test_viewer_stream_register_append_done_snapshot_lifecycle() -> None:
    """register → append → mark_done → snapshot incremental poll contract."""
    register_viewer_stream("life-1", chunks=["alpha"], done=False)
    append_viewer_stream_chunk("life-1", "beta")
    mark_viewer_stream_done("life-1")

    first = viewer_stream_snapshot("life-1", offset=0)
    assert first == {"chunks": ["alpha", "beta"], "done": True, "next_offset": 2}

    tail = viewer_stream_snapshot("life-1", offset=1)
    assert tail == {"chunks": ["beta"], "done": True, "next_offset": 2}


def test_viewer_stream_snapshot_missing_stream_is_terminal() -> None:
    """Unknown stream ids return an empty terminal snapshot."""
    snap = viewer_stream_snapshot("missing-stream", offset=3)
    assert snap == {"chunks": [], "done": True, "next_offset": 3}


def test_viewer_stream_append_creates_stream_when_missing() -> None:
    """append_viewer_stream_chunk seeds a stream when the id is new."""
    append_viewer_stream_chunk("lazy-1", "only")
    snap = viewer_stream_snapshot("lazy-1", offset=0)
    assert snap["chunks"] == ["only"]
    assert snap["done"] is False


def test_viewer_streams_enforce_max_entries() -> None:
    """W3: bounded store evicts oldest entries when max size exceeded (finding-8)."""
    max_entries, _ttl = _stream_limits()
    for idx in range(max_entries + 1):
        register_viewer_stream(f"cap-{idx}", chunks=[str(idx)], done=True)

    assert len(viewer_mod._VIEWER_STREAMS) <= max_entries
    assert "cap-0" not in viewer_mod._VIEWER_STREAMS
    assert f"cap-{max_entries}" in viewer_mod._VIEWER_STREAMS


def test_viewer_streams_evict_expired_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    """W3: entries past TTL are removed on access (finding-8)."""
    _max, ttl = _stream_limits()
    now = {"t": 1000.0}
    monkeypatch.setattr(
        viewer_mod, "time", type("T", (), {"time": staticmethod(lambda: now["t"])})()
    )

    register_viewer_stream("ttl-1", chunks=["stale"], done=True)
    now["t"] += ttl + 1.0

    evict = getattr(viewer_mod, "evict_stale_viewer_streams", None)
    if callable(evict):
        evict()
    else:
        register_viewer_stream("ttl-probe", chunks=["probe"], done=True)

    assert "ttl-1" not in viewer_mod._VIEWER_STREAMS
    snap = viewer_stream_snapshot("ttl-1", offset=0)
    assert snap["chunks"] == []
    assert snap["done"] is True


def test_viewer_stream_state_records_monotonic_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    """W3: stream state tracks created/updated time for TTL eviction."""
    now = {"t": time.time()}
    monkeypatch.setattr(
        viewer_mod, "time", type("T", (), {"time": staticmethod(lambda: now["t"])})()
    )
    register_viewer_stream("ts-1", chunks=["x"], done=False)
    state = viewer_mod._VIEWER_STREAMS["ts-1"]
    created = getattr(state, "created_at", None) or getattr(state, "updated_at", None)
    assert created is not None
    assert float(created) == pytest.approx(now["t"], rel=0, abs=1.0)
