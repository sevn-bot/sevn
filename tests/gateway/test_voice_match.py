"""Voice shortcut matching tests (`plan/control-surface-wave-plan.md` Wave 3)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sevn.gateway.commands.shortcuts_store import add_shortcut
from sevn.gateway.commands.voice_match import (
    format_voice_matched_message,
    match_voice_shortcut,
)


def test_exact_match_returns_shortcut() -> None:
    root = Path(tempfile.mkdtemp())
    add_shortcut(
        root,
        {"name": "standup", "description": "Daily", "type": "prompt", "payload": {}},
    )
    row = match_voice_shortcut(root, "standup please")
    assert row is not None
    assert row["name"] == "standup"


def test_no_match_returns_none() -> None:
    root = Path(tempfile.mkdtemp())
    assert match_voice_shortcut(root, "hello world") is None


def test_audit_message_format() -> None:
    assert format_voice_matched_message("standup") == "→ /standup (voice-matched)"
