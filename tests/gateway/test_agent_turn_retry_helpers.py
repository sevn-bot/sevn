"""Plan 003 — direct characterization of agent_turn retry/failure helpers.

Tests the private helpers imported from ``sevn.gateway.agent_turn``:

- ``_collect_partial_progress``
- ``_is_deterministic_harness_failure``
- ``_is_executor_timeout_cancel_outcome``
- ``_looks_unfinished_assistant_reply``
- ``_resolve_retry_back_reference``
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sevn.agent.executors.b_types import EXECUTOR_TIMEOUT_CANCEL_DETAIL
from sevn.gateway.agent_turn import (
    _collect_partial_progress,
    _is_deterministic_harness_failure,
    _is_executor_timeout_cancel_outcome,
    _looks_unfinished_assistant_reply,
    _resolve_retry_back_reference,
)
from sevn.gateway.turn_finalizer import TierBAnswerFinalizer
from sevn.storage.migrate import apply_migrations

# ---------------------------------------------------------------------------
# W1 — outcome factory + classifier / partial-progress helpers
# ---------------------------------------------------------------------------


def _outcome(**kwargs: object) -> SimpleNamespace:
    """Minimal ``BTurnOutcome``-shaped namespace for helper unit tests."""
    defaults: dict[str, object] = {
        "failure_detail": "",
        "final_messages": (),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _message_payload(text: str) -> SimpleNamespace:
    """Outbound message payload with only ``text`` read by ``_collect_partial_progress``."""
    return SimpleNamespace(text=text)


def _tier_b_finalizer(*, streamed_text: str) -> TierBAnswerFinalizer:
    """``TierBAnswerFinalizer`` with ``partial_progress_text`` seeded via streamed body."""
    adapter = MagicMock()
    router = MagicMock()
    fin = TierBAnswerFinalizer(
        router=router,
        adapter=adapter,
        channel="telegram",
        user_id="1",
        session_id="s1",
        turn_id="t1",
    )
    fin._last_streamed_text = streamed_text
    return fin


@pytest.mark.parametrize("outcome", [None, _outcome(failure_detail="tool_unavailable")])
def test_is_executor_timeout_cancel_outcome_negative(outcome: SimpleNamespace | None) -> None:
    """Non-cancel outcomes (including ``None``) are not timeout-cancel partials."""
    assert not _is_executor_timeout_cancel_outcome(outcome)


def test_is_executor_timeout_cancel_outcome_positive() -> None:
    """Doctest shape: ``failure_detail`` equals ``EXECUTOR_TIMEOUT_CANCEL_DETAIL``."""
    outcome = _outcome(failure_detail=EXECUTOR_TIMEOUT_CANCEL_DETAIL)
    assert _is_executor_timeout_cancel_outcome(outcome)


@pytest.mark.parametrize(
    ("no_answer_reason", "failure_detail", "expected"),
    [
        (None, "cd.decompose schema/parse failed", True),
        (None, "opener-only output (no substantive answer)", False),
        ("timeout", None, False),
        ("timeout", "returned 400 for /v1/messages", True),
        ("timeout", "triager_bound_tools_unused", False),
        ("exception", None, False),
        ("exception", "llm_transport_bad_request path=/v1/messages", True),
        ("exception", "promised_but_idle (motion-promise, no tool calls)", False),
        # Empty-output retry exhaustion reproduces on a widened retry (live-session fix).
        (None, "Exceeded maximum output retries (3)", True),
    ],
)
def test_is_deterministic_harness_failure_reason_outcome_matrix(
    no_answer_reason: str | None,
    failure_detail: str | None,
    *,
    expected: bool,
) -> None:
    """Reason x outcome branches complement W8 marker-inventory pins."""
    outcome = None if failure_detail is None else _outcome(failure_detail=failure_detail)
    assert (
        _is_deterministic_harness_failure(
            no_answer_reason=no_answer_reason,
            outcome=outcome,
        )
        is expected
    )


def test_collect_partial_progress_both_none() -> None:
    """Doctest: no finalizer and no outcome yields ``None``."""
    assert _collect_partial_progress(finalizer=None, outcome=None) is None


def test_collect_partial_progress_from_finalizer() -> None:
    """Streaming placeholder text is preferred over outcome payloads."""
    fin = _tier_b_finalizer(streamed_text="Partial answer so far.")
    assert _collect_partial_progress(finalizer=fin, outcome=None) == "Partial answer so far."


def test_collect_partial_progress_from_outcome_final_messages() -> None:
    """Non-empty ``final_messages[].text`` is joined when the finalizer has no text."""
    outcome = _outcome(
        final_messages=(
            _message_payload(" first part "),
            _message_payload("second part"),
        ),
    )
    assert _collect_partial_progress(finalizer=None, outcome=outcome) == "first part\n\nsecond part"


@pytest.mark.parametrize(
    ("streamed_text", "outcome_messages"),
    [
        ("   ", ()),
        ("", (_message_payload("  "),)),
        ("", (_message_payload(""), _message_payload("\t"))),
    ],
)
def test_collect_partial_progress_whitespace_only_returns_none(
    streamed_text: str,
    outcome_messages: tuple[SimpleNamespace, ...],
) -> None:
    """Whitespace-only partials are stripped away and treated as absent."""
    fin = _tier_b_finalizer(streamed_text=streamed_text) if streamed_text else None
    outcome = _outcome(final_messages=outcome_messages) if outcome_messages else None
    assert _collect_partial_progress(finalizer=fin, outcome=outcome) is None


# ---------------------------------------------------------------------------
# W2 — unfinished-reply classifier + sqlite back-reference resolver
# ---------------------------------------------------------------------------

_SESSION_ROW = ("s1", "telegram:1", "telegram", "1", "t", "t", None, None, None)


def _memory_conn() -> sqlite3.Connection:
    """In-memory gateway DB with migrations applied."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    return conn


def _seed_messages(
    conn: sqlite3.Connection,
    rows: list[tuple[str, str, str]],
    *,
    session_id: str = "s1",
) -> None:
    """Insert ``gateway_sessions`` (once) and ``gateway_messages`` rows for resolver tests."""
    existing = conn.execute(
        "SELECT 1 FROM gateway_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if not existing:
        _ = conn.execute(
            "INSERT INTO gateway_sessions VALUES (?,?,?,?,?,?,?,?,?)",
            (
                session_id,
                f"{_SESSION_ROW[2]}:{_SESSION_ROW[3]}",
                _SESSION_ROW[2],
                _SESSION_ROW[3],
                _SESSION_ROW[4],
                _SESSION_ROW[5],
                _SESSION_ROW[6],
                _SESSION_ROW[7],
                _SESSION_ROW[8],
            ),
        )
    for role, kind, content in rows:
        _ = conn.execute(
            """
            INSERT INTO gateway_messages (
                session_id, role, kind, content, visible_to_llm, status,
                extras_json, created_at, turn_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, role, kind, content, 1, "sent", None, "t", "t-1"),
        )
    conn.commit()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("I finished the turn but had nothing to send.", True),
        ("Here are the folders you asked for.", False),
    ],
)
def test_looks_unfinished_assistant_reply_direct(text: str, *, expected: bool) -> None:
    """Doctest seeds for unfinished vs finished assistant bodies."""
    assert _looks_unfinished_assistant_reply(text) is expected


def test_resolve_retry_back_reference_non_retry_phrase() -> None:
    """Ordinary user text does not trigger back-reference resolution."""
    conn = _memory_conn()
    _seed_messages(conn, [("user", "message", "what's the weather")])
    assert _resolve_retry_back_reference(conn, "s1", latest_text="what's the weather") is None


def test_resolve_retry_back_reference_empty_session() -> None:
    """Retry phrase with no prior messages returns ``None``."""
    conn = _memory_conn()
    _ = conn.execute(
        "INSERT INTO gateway_sessions VALUES (?,?,?,?,?,?,?,?,?)",
        _SESSION_ROW,
    )
    conn.commit()
    assert _resolve_retry_back_reference(conn, "s1", latest_text="try again") is None


def test_resolve_retry_back_reference_anchor_at_zero() -> None:
    """Retry phrase as the first message cannot reference a prior request."""
    conn = _memory_conn()
    _seed_messages(conn, [("user", "message", "try again")])
    assert _resolve_retry_back_reference(conn, "s1", latest_text="try again") is None


def test_resolve_retry_back_reference_happy_path() -> None:
    """``try again`` after an unfinished assistant maps to the prior user request."""
    conn = _memory_conn()
    _seed_messages(
        conn,
        [
            ("user", "message", "read source_code/src/sevn/prompts/triager.py"),
            (
                "assistant",
                "message",
                "I finished the turn but had nothing to send. Try rephrasing the request.",
            ),
            ("user", "message", "try again"),
        ],
    )
    target = _resolve_retry_back_reference(conn, "s1", latest_text="try again")
    assert target == "read source_code/src/sevn/prompts/triager.py"


def test_resolve_retry_back_reference_finished_reply_between() -> None:
    """A finished assistant reply between anchor and request blocks recovery."""
    conn = _memory_conn()
    _seed_messages(
        conn,
        [
            ("user", "message", "list source_code/src"),
            ("assistant", "message", "Here are the folders you asked for."),
            ("user", "message", "try again"),
        ],
    )
    assert _resolve_retry_back_reference(conn, "s1", latest_text="try again") is None


def test_resolve_retry_back_reference_repeated_retry_phrases_use_last_anchor() -> None:
    """When retry phrases repeat, resolution anchors on the last occurrence."""
    conn = _memory_conn()
    _seed_messages(
        conn,
        [
            ("user", "message", "read source_code/src/sevn/prompts/triager.py"),
            ("assistant", "message", "I finished the turn but had nothing to send."),
            ("user", "message", "try again"),
            ("user", "message", "try again"),
        ],
    )
    target = _resolve_retry_back_reference(conn, "s1", latest_text="try again")
    assert target == "read source_code/src/sevn/prompts/triager.py"


def test_resolve_retry_back_reference_case_insensitive_needle_skip() -> None:
    """Prior user text that case-insensitively equals the retry phrase is skipped."""
    conn = _memory_conn()
    _seed_messages(
        conn,
        [
            ("user", "message", "Try Again"),
            ("assistant", "message", "I finished the turn but had nothing to send."),
            ("user", "message", "try again"),
        ],
    )
    assert _resolve_retry_back_reference(conn, "s1", latest_text="try again") is None
