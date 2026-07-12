"""Serialize-time replay hygiene for ``provider_turn_messages`` (W3)."""

from __future__ import annotations

from unittest.mock import patch

from sevn.agent.transcript_replay import (
    TranscriptRow,
    build_cross_turn_message_history,
    sanitize_provider_turn_messages_for_storage,
    slim_transcript_for_log_provenance,
)


def test_sanitize_strips_trailing_orphan_tool_use() -> None:
    raw = [
        {"role": "user", "content": "fetch page"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "On it."},
                {"type": "tool_use", "id": "rc1", "name": "run_code", "input": {"code": "x=1"}},
            ],
        },
    ]
    sanitized, stripped = sanitize_provider_turn_messages_for_storage(raw)
    assert stripped == 1
    assert len(sanitized) == 2
    assistant_content = sanitized[1]["content"]
    if isinstance(assistant_content, str):
        assert assistant_content == "On it."
    else:
        assert isinstance(assistant_content, list)
        assert all(block.get("type") != "tool_use" for block in assistant_content)
        assert assistant_content[0]["text"] == "On it."


def test_sanitize_preserves_paired_tool_rounds() -> None:
    raw = [
        {"role": "user", "content": "read a.py"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "r1", "name": "read", "input": {"path": "a.py"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "r1",
                    "content": '{"ok": true, "data": "print(1)"}',
                },
            ],
        },
        {"role": "assistant", "content": [{"type": "text", "text": "File contains print(1)."}]},
    ]
    sanitized, stripped = sanitize_provider_turn_messages_for_storage(raw)
    assert stripped == 0
    assert sanitized == raw


def test_build_cross_turn_history_sanitizes_legacy_orphans() -> None:
    events: list[tuple[str, dict[str, object]]] = []

    def _capture(event: str, **fields: object) -> None:
        events.append((event, fields))

    rows = [
        TranscriptRow(role="user", text="earlier"),
        TranscriptRow(
            role="assistant",
            text="partial",
            provider_turn_messages=[
                {"role": "user", "content": "earlier"},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "rc1",
                            "name": "run_code",
                            "input": {},
                        },
                    ],
                },
            ],
        ),
    ]
    with patch("sevn.agent.transcript_replay.debug_event", side_effect=_capture):
        history = build_cross_turn_message_history(rows, replay_provider_history=True)
    assert history
    assert any(name == "transcript_replay.sanitized_orphans" for name, _ in events)


def test_slim_transcript_for_log_provenance_keeps_one_prior_user_line() -> None:
    rows = [
        TranscriptRow(role="user", text="older question"),
        TranscriptRow(role="assistant", text="older answer"),
        TranscriptRow(role="user", text="Wemby stats in finals?"),
        TranscriptRow(role="assistant", text="Game 4: Knicks 107, Spurs 106."),
    ]
    slim = slim_transcript_for_log_provenance(rows)
    assert len(slim) == 1
    assert slim[0].role == "user"
    assert slim[0].text == "Wemby stats in finals?"
    history = build_cross_turn_message_history(slim, replay_provider_history=False)
    assert len(history) == 1
