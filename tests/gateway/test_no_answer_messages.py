"""Typed no-answer fallback messages (transcript-review item #8).

Covers the reason → user-message mapping used by ``_emit_no_answer_fallback``. The
historic catch-all ``EXECUTOR_NO_ANSWER_FALLBACK`` is kept as a last resort for
unknown reasons; every known reason gets a specific, actionable line.

W6 coupling: ``NO_ANSWER_MESSAGES`` and ``TURN_EMPTY_FALLBACK_TEXT`` live in
``sevn.prompts.fallbacks``; unfinished-reply detection and retry/continuation
phrases share the same module.
"""

from __future__ import annotations

import sqlite3

import pytest

from sevn.gateway.agent_turn import (
    EXECUTOR_NO_ANSWER_FALLBACK,
    _is_retry_back_reference,
    _looks_unfinished_assistant_reply,
    _render_no_answer_message,
    _resolve_retry_back_reference,
)
from sevn.prompts.fallbacks import (
    CONTINUATION_PHRASES,
    NO_ANSWER_MESSAGES,
    RETRY_BACKREF_PHRASES,
    TURN_EMPTY_FALLBACK_TEXT,
    is_retry_back_reference_phrase,
    looks_like_unfinished_assistant_reply,
    match_continuation_phrase,
)
from sevn.storage.migrate import apply_migrations


@pytest.mark.parametrize(
    ("reason", "marker"),
    [
        ("timeout", "ran out of time"),
        ("timeout_expanded_retry", "expanded toolkit"),
        ("exception", "error interrupted"),
        ("exception_expanded_retry", "expanded-budget retry"),
        ("missing_outcome", "without producing an answer"),
        ("unhandled_exception", "unexpected error"),
    ],
)
def test_known_reasons_map_to_specific_messages(reason: str, marker: str) -> None:
    """Each known reason produces a tailored, recognisable user line."""
    out = _render_no_answer_message(reason)
    assert out != EXECUTOR_NO_ANSWER_FALLBACK
    assert marker.lower() in out.lower()


def test_empty_output_reason_uses_dedicated_message() -> None:
    """Reasons of shape ``empty_output:status=X`` route to the empty-output line."""
    out = _render_no_answer_message("empty_output:status=ok")
    assert out == TURN_EMPTY_FALLBACK_TEXT
    assert "nothing to send" in out.lower()


@pytest.mark.parametrize(
    "message",
    NO_ANSWER_MESSAGES.values(),
    ids=sorted(NO_ANSWER_MESSAGES.keys()),
)
def test_every_no_answer_message_recognized_as_unfinished(message: str) -> None:
    """W6.1: each typed no-answer line must match unfinished-reply detection."""
    assert looks_like_unfinished_assistant_reply(message)
    assert _looks_unfinished_assistant_reply(message)


def test_turn_empty_fallback_recognized_as_unfinished() -> None:
    """W6.2: router empty fallback shares the same source as ``empty_output`` reasons."""
    assert looks_like_unfinished_assistant_reply(TURN_EMPTY_FALLBACK_TEXT)


def test_retry_backref_phrases_are_subset_of_continuation_phrases() -> None:
    """W6.3: retry back-reference phrases must also match continuation detection."""
    assert RETRY_BACKREF_PHRASES <= CONTINUATION_PHRASES


@pytest.mark.parametrize("phrase", sorted(RETRY_BACKREF_PHRASES))
def test_retry_phrases_match_both_detectors(phrase: str) -> None:
    """W6.3: overlap phrases fire both retry back-ref and continuation matchers."""
    assert is_retry_back_reference_phrase(phrase)
    assert _is_retry_back_reference(phrase)
    assert match_continuation_phrase(phrase) == phrase


def test_continuation_only_phrases_do_not_trigger_retry_backref() -> None:
    """W6.3 precedence: ``go ahead`` continues in-flight work but is not a retry back-ref."""
    assert match_continuation_phrase("go ahead") == "go ahead"
    assert not is_retry_back_reference_phrase("go ahead")
    assert not _is_retry_back_reference("go ahead")


def test_unknown_reason_falls_back_to_generic_line() -> None:
    """Unknown reasons still produce *some* user-visible message (the historic catch-all)."""
    assert _render_no_answer_message("totally-made-up") == EXECUTOR_NO_ANSWER_FALLBACK


def test_is_retry_back_reference_matches_short_phrases() -> None:
    """Short retry utterances should trigger back-reference resolution."""
    assert _is_retry_back_reference("try again")
    assert _is_retry_back_reference("again?")
    assert not _is_retry_back_reference("please list source_code/src")


def test_resolve_retry_back_reference_recovers_previous_user_request() -> None:
    """`try again` after unfinished assistant fallback maps to prior user request."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    _ = conn.execute(
        "INSERT INTO gateway_sessions VALUES (?,?,?,?,?,?,?,?,?)",
        ("s1", "telegram:1", "telegram", "1", "t", "t", None, None, None),
    )
    _ = conn.execute(
        """
        INSERT INTO gateway_messages (
            session_id, role, kind, content, visible_to_llm, status,
            extras_json, created_at, turn_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "s1",
            "user",
            "message",
            "read source_code/src/sevn/prompts/triager.py",
            1,
            "sent",
            None,
            "t",
            "t-1",
        ),
    )
    _ = conn.execute(
        """
        INSERT INTO gateway_messages (
            session_id, role, kind, content, visible_to_llm, status,
            extras_json, created_at, turn_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "s1",
            "assistant",
            "message",
            "I finished the turn but had nothing to send. Try rephrasing the request.",
            1,
            "sent",
            None,
            "t",
            "t-1",
        ),
    )
    _ = conn.execute(
        """
        INSERT INTO gateway_messages (
            session_id, role, kind, content, visible_to_llm, status,
            extras_json, created_at, turn_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("s1", "user", "message", "try again", 1, "sent", None, "t", "t-2"),
    )
    conn.commit()
    target = _resolve_retry_back_reference(conn, "s1", latest_text="try again")
    assert target == "read source_code/src/sevn/prompts/triager.py"
