"""WebSocket topic naming for trigger runs (`specs/30-non-interactive-triggers.md` §11)."""

from __future__ import annotations

from sevn.triggers.ws_topics import RUN_WS_TOPIC_PREFIX, trigger_run_ws_topic


def test_trigger_run_ws_topic_prefix() -> None:
    """Topic uses ``run.{id}`` WebSocket convention."""
    assert trigger_run_ws_topic("abc-123") == "run.abc-123"
    assert trigger_run_ws_topic("run.already") == "run.already"
    assert RUN_WS_TOPIC_PREFIX == "run."
