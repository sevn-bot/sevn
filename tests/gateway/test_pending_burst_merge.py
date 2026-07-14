"""Cancel-mode burst collapse re-triages on the merged pending user text (P1).

Under ``gateway.queue_mode = cancel`` a burst of quick successive messages is
superseded into a single surviving turn. The executor already sees every pending
user line, but triage historically only saw the *latest* message, so it picked a
narrow toolset and the earlier questions were answered with the wrong tools (the
MiniMax-M3 session: weather + list-folders answered with a who-are-you toolset).
``_pending_user_messages_text`` merges the trailing pending user lines so triage
sees the union of asked questions (`specs/17-gateway.md` §4.3).
"""

from __future__ import annotations

import sqlite3

from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway.agent_turn import _latest_user_message_text, _pending_user_messages_text
from sevn.gateway.triage.triage_context import triage_context_from_session
from sevn.storage.migrate import apply_migrations

_BURST = (
    "what is temperature in Amsterdam now?",
    "list only the folders in your workspace",
    "who are you?",
)


def _session_with_burst() -> sqlite3.Connection:
    """Seed a session with three unanswered user messages and no assistant reply."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    _ = conn.execute(
        "INSERT INTO gateway_sessions VALUES (?,?,?,?,?,?,?,?,?)",
        ("s1", "telegram:1", "telegram", "1", "t", "t", None, None, None),
    )
    for idx, text in enumerate(_BURST):
        _ = conn.execute(
            """
            INSERT INTO gateway_messages (
                session_id, role, kind, content, visible_to_llm, status,
                extras_json, created_at, turn_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("s1", "user", "message", text, 1, "sent", None, "t", f"t-{idx}"),
        )
    conn.commit()
    return conn


def test_pending_burst_merges_all_user_lines() -> None:
    """All three pending questions are folded into one merged triage input."""
    conn = _session_with_burst()
    merged = _pending_user_messages_text(conn, "s1")
    for text in _BURST:
        assert text in merged
    # Latest-only resolution would have dropped the first two questions.
    assert _latest_user_message_text(conn, "s1") == _BURST[-1]
    assert merged != _BURST[-1]


def test_pending_burst_stops_at_last_assistant_turn() -> None:
    """An already-answered earlier message is not resurrected into the merge."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    _ = conn.execute(
        "INSERT INTO gateway_sessions VALUES (?,?,?,?,?,?,?,?,?)",
        ("s1", "telegram:1", "telegram", "1", "t", "t", None, None, None),
    )
    rows = (
        ("user", "earlier answered question"),
        ("assistant", "here is the answer"),
        ("user", _BURST[0]),
        ("user", _BURST[1]),
        ("user", _BURST[2]),
    )
    for idx, (role, text) in enumerate(rows):
        _ = conn.execute(
            """
            INSERT INTO gateway_messages (
                session_id, role, kind, content, visible_to_llm, status,
                extras_json, created_at, turn_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("s1", role, "message", text, 1, "sent", None, "t", f"t-{idx}"),
        )
    conn.commit()
    merged = _pending_user_messages_text(conn, "s1")
    assert "earlier answered question" not in merged
    for text in _BURST:
        assert text in merged


def test_triage_input_carries_all_burst_questions() -> None:
    """``current_message`` exposes the union so triage can select all needed tools."""
    conn = _session_with_burst()
    merged = _pending_user_messages_text(conn, "s1")
    ws = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    ctx = triage_context_from_session(conn, "s1", ws, merged)
    for text in _BURST:
        assert text in ctx.current_message
    # The merged lines are folded into current_message, not duplicated as
    # trailing transcript turns.
    assert not any(line.startswith("user:") for line in ctx.transcript_turns)
