"""W1 RED: Advanced dissolution + de-dupe targets (green after W5)."""

from __future__ import annotations

from sevn.gateway.menu.menu import _CONFIG_SECTIONS, build_config_menu_keyboard
from tests.gateway.telegram_menu_redesign_helpers import (
    DEFAULT_DOCS_WORKSPACE,
    queue_mode_callback_count,
    trace_redaction_callback_count,
)


def test_advanced_section_id_absent() -> None:
    """W1.8 — Advanced tile is dissolved; section id must not remain."""
    assert "advanced" not in _CONFIG_SECTIONS


def test_auto_resume_b_reachable_from_deployment() -> None:
    """W1.8 — gateway.restart.auto_resume_b moved next to Deployment restart rows."""
    kb = build_config_menu_keyboard(DEFAULT_DOCS_WORKSPACE, section="deployment")  # type: ignore[arg-type]
    callbacks = [
        btn.get("callback_data")
        for row in kb.get("inline_keyboard", [])
        for btn in row
        if isinstance(btn.get("callback_data"), str)
    ]
    assert any("gateway.restart.auto_resume_b" in cb for cb in callbacks)


def test_exactly_one_trace_redaction_control() -> None:
    """W1.8 — duplicate Advanced trace-redaction row (C18.2) is removed."""
    assert trace_redaction_callback_count() == 1


def test_exactly_one_queue_mode_control_on_chat() -> None:
    """W1.8 — queue mode lives on Chat; Sub-agents duplicate removed."""
    assert queue_mode_callback_count() == 1
    kb = build_config_menu_keyboard(DEFAULT_DOCS_WORKSPACE, section="chat")  # type: ignore[arg-type]
    chat_callbacks = [
        btn.get("callback_data")
        for row in kb.get("inline_keyboard", [])
        for btn in row
        if isinstance(btn.get("callback_data"), str)
    ]
    assert any("gateway.queue_mode" in cb for cb in chat_callbacks)
