"""OpenUI render-error promotion into self-improve buckets."""

from __future__ import annotations

from sevn.self_improve.openui_telemetry import record_openui_render_error, snapshot_openui_buckets


def test_record_and_snapshot_buckets() -> None:
    record_openui_render_error(workspace_id="ws-test", reason="tunnel_down")
    snap = snapshot_openui_buckets("ws-test")
    assert snap.get("tunnel_down", 0) >= 1
