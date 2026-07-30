"""W8.4 — one-turn ``/model --once`` override must not leak (#88 → W10).

Mirror the ``set_regen_target`` / ``take_regen_target`` consume-and-clear lifecycle.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from tests.open_issues_sweep.batch_b.conftest import baseline_minimal_workspace

from sevn.config.model_resolution import ModelSlot, resolve_model_slot
from sevn.gateway.session_manager import SessionManager


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            channel TEXT,
            user_id TEXT,
            metadata TEXT
        );
        """
    )
    return conn


@pytest.mark.xfail(reason="green after W10: model-once override consume-and-clear", strict=False)
def test_model_once_override_cleared_after_successful_take() -> None:
    cfg = baseline_minimal_workspace()
    persisted = resolve_model_slot(cfg, ModelSlot.tier_b)
    mgr = SessionManager(_memory_conn())
    mgr.set_model_once_override("sess-1", "openai/gpt-4o")
    assert mgr.take_model_once_override("sess-1") == "openai/gpt-4o"
    assert mgr.take_model_once_override("sess-1") is None
    assert resolve_model_slot(cfg, ModelSlot.tier_b) == persisted


@pytest.mark.xfail(reason="green after W10: model-once cleared after failed turn", strict=False)
def test_model_once_override_cleared_after_failure_path() -> None:
    cfg = baseline_minimal_workspace()
    persisted = resolve_model_slot(cfg, ModelSlot.tier_b)
    mgr = SessionManager(_memory_conn())
    mgr.set_model_once_override("sess-2", "openai/gpt-4o")

    consumed = mgr.take_model_once_override("sess-2")
    assert consumed == "openai/gpt-4o"
    mgr.clear_model_once_override_after_turn("sess-2", success=False)

    assert mgr.take_model_once_override("sess-2") is None
    assert mgr.peek_model_once_override("sess-2") is None
    assert resolve_model_slot(cfg, ModelSlot.tier_b) == persisted


@pytest.mark.xfail(reason="green after W10: /model --once parses and stages override", strict=False)
def test_core_command_model_once_stages_without_persisting(tmp_path: Path) -> None:
    from sevn.gateway.commands.core_commands import CoreCommandHandler

    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text('{"schema_version":1,"gateway":{"token":"x"*64}}', encoding="utf-8")
    handler = CoreCommandHandler.__new__(CoreCommandHandler)
    handler._sevn_json = sevn_json
    handler._workspace = baseline_minimal_workspace()
    handler._session_id = "sess-cmd"
    handler._session_manager = SessionManager(_memory_conn())

    reply = handler._handle_model("--once openai/gpt-4o")
    assert "openai/gpt-4o" in reply
    assert handler._session_manager.peek_model_once_override("sess-cmd") == "openai/gpt-4o"
    assert resolve_model_slot(handler._workspace, ModelSlot.tier_b) == "minimax/MiniMax-M2.7"
