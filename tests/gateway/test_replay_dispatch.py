"""Dashboard turn-replay worker dispatch tests (`specs/16-harness-discipline.md` §4.4)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sevn.agent.harness.snapshots import ReplayTurnNotReplayableError, queue_dashboard_turn_replay
from sevn.agent.tracing.traces_migrate import apply_traces_migrations
from sevn.gateway.post_turn_hooks import PostTurnContext
from sevn.gateway.replay_worker import TurnReplayWorker
from sevn.gateway.replay_worker_hooks import _post_turn_replay_terminal
from sevn.gateway.session_manager import SessionManager
from sevn.storage.migrate import apply_migrations


def _seed_session(conn: sqlite3.Connection, *, session_id: str, turn_id: str) -> None:
    conn.execute(
        """
        INSERT INTO gateway_sessions (
            session_id, scope_key, channel, user_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (session_id, f"webchat:{session_id}", "webchat", "owner", "2026-01-01", "2026-01-01"),
    )
    conn.execute(
        """
        INSERT INTO gateway_messages (
            session_id, role, kind, content, visible_to_llm, status,
            extras_json, created_at, turn_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            "user",
            "message",
            "hello replay",
            1,
            "sent",
            "{}",
            "2026-01-01",
            turn_id,
        ),
    )
    conn.commit()


def test_session_manager_replay_target_roundtrip() -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    sm = SessionManager(conn)
    sm.set_replay_target(
        "sess-1",
        user_text="hello",
        origin_turn_id="turn-old",
        replay_job_id="job-1",
    )
    assert sm.take_replay_target("sess-1") == ("hello", "turn-old", "job-1")
    assert sm.take_replay_target("sess-1") is None
    assert sm.pop_replay_terminal("sess-1") == ("job-1", "turn-old")


@pytest.mark.asyncio
async def test_replay_worker_stages_target_and_enqueues_dispatch() -> None:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    apply_migrations(conn)
    _seed_session(conn, session_id="sess-r", turn_id="turn-r")

    router = MagicMock()
    router._queue_mode = "queue"
    router._run_turn = AsyncMock()
    router._sessions = MagicMock()
    router._sessions.set_replay_target = MagicMock()
    router._sessions.enqueue_dispatch = AsyncMock()

    worker = TurnReplayWorker(sqlite_conn=conn, gateway_router=router)
    worker.schedule("job-1", session_id="sess-r", turn_id="turn-r")
    assert await worker.process_once() is True

    router._sessions.set_replay_target.assert_called_once_with(
        "sess-r",
        user_text="hello replay",
        origin_turn_id="turn-r",
        replay_job_id="job-1",
    )
    router._sessions.enqueue_dispatch.assert_awaited_once()
    kwargs = router._sessions.enqueue_dispatch.await_args.kwargs
    assert kwargs["queue_mode"] == "queue"
    assert kwargs["dispatch"] is router._run_turn


@pytest.mark.asyncio
async def test_replay_worker_publishes_failed_when_user_text_missing() -> None:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    apply_migrations(conn)
    conn.execute(
        """
        INSERT INTO gateway_sessions (
            session_id, scope_key, channel, user_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("sess-r2", "webchat:sess-r2", "webchat", "owner", "2026-01-01", "2026-01-01"),
    )
    conn.commit()

    router = MagicMock()
    router._queue_mode = "queue"
    router._sessions = MagicMock()
    router._sessions.enqueue_dispatch = AsyncMock()
    events: list[dict[str, str]] = []

    async def _capture(payload: dict[str, str]) -> None:
        events.append(dict(payload))

    worker = TurnReplayWorker(
        sqlite_conn=conn,
        gateway_router=router,
        job_event_fanout=_capture,
    )
    worker.schedule("job-2", session_id="sess-r2", turn_id="turn-r2")
    assert await worker.process_once() is True
    router._sessions.enqueue_dispatch.assert_not_awaited()
    assert events[-1]["status"] == "failed"


def test_queue_dashboard_turn_replay_rejects_non_replayable_turn() -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    traces_conn = sqlite3.connect(":memory:")
    apply_traces_migrations(traces_conn)
    _seed_session(conn, session_id="s1", turn_id="t1")
    conn.execute(
        """
        UPDATE gateway_messages
        SET kind = 'blocked', content = '/status'
        WHERE session_id = ? AND turn_id = ?
        """,
        ("s1", "t1"),
    )
    conn.commit()
    traces_conn.execute(
        """INSERT INTO trace_events (
            span_id, parent_span_id, session_id, turn_id, tier, kind,
            ts_start_ns, ts_end_ns, status, attrs_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("sp", None, "s1", "t1", "B", "b_turn", 1, 2, "ok", "{}"),
    )
    traces_conn.commit()
    with pytest.raises(ReplayTurnNotReplayableError):
        queue_dashboard_turn_replay(
            conn,
            traces_conn,
            session_id="s1",
            turn_id="t1",
            now_ns=1,
        )


def test_post_replay_api_schedules_worker(tmp_path: Path) -> None:
    from tests.ui.dashboard.test_system_api import _client, _login

    with _client(tmp_path) as client:
        headers = _login(client)
        conn: sqlite3.Connection = client.app.state.sqlite_conn
        conn.execute(
            """
            INSERT INTO gateway_sessions (
                session_id, scope_key, channel, user_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("s-post", "webchat:s-post", "webchat", "owner", "2026-01-01", "2026-01-01"),
        )
        conn.execute(
            """
            INSERT INTO gateway_messages (
                session_id, role, kind, content, visible_to_llm, status,
                extras_json, created_at, turn_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s-post",
                "user",
                "message",
                "run again",
                1,
                "sent",
                "{}",
                "2026-01-01",
                "t-post",
            ),
        )
        conn.commit()
        traces_conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_traces_migrations(traces_conn)
        traces_conn.execute(
            """INSERT INTO trace_events (
                span_id, parent_span_id, session_id, turn_id, tier, kind,
                ts_start_ns, ts_end_ns, status, attrs_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("sp-post", None, "s-post", "t-post", "B", "b_turn", 1, 2, "ok", "{}"),
        )
        traces_conn.commit()

        worker = MagicMock(spec=TurnReplayWorker)
        worker.schedule = MagicMock()
        client.app.state.replay_worker = worker

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "sevn.ui.dashboard.api.sessions.ensure_trace_connection",
                lambda _path: traces_conn,
            )
            resp = client.post(
                "/api/v1/sessions/s-post/turns/t-post/replay",
                json={"confirmed": True},
                headers=headers,
            )
        assert resp.status_code == 202
        worker.schedule.assert_called_once()
        args, kwargs = worker.schedule.call_args
        assert kwargs["session_id"] == "s-post"
        assert kwargs["turn_id"] == "t-post"
        assert args[0] == resp.json()["replay_job_id"]


@pytest.mark.asyncio
async def test_replay_terminal_post_turn_hook_maps_outcome() -> None:
    router = MagicMock()
    router._sessions = MagicMock()
    router._sessions.pop_replay_terminal.return_value = ("job-t", "turn-o")
    fanout = MagicMock()
    fanout.publish = AsyncMock()
    router._replay_job_event_fanout = fanout
    ctx = PostTurnContext(
        router=router,
        conn=sqlite3.connect(":memory:"),
        trace=MagicMock(),
        session_id="sess-1",
        correlation_id="turn-new",
        terminal_status="ok",
        turn_wall_ns=1_000_000_000,
    )
    await _post_turn_replay_terminal(ctx)
    fanout.publish.assert_awaited_once_with(
        {
            "replay_job_id": "job-t",
            "session_id": "sess-1",
            "turn_id": "turn-o",
            "event": "terminal",
            "status": "completed",
        },
    )


@pytest.mark.asyncio
async def test_agent_turn_emits_replay_attrs_on_gateway_turn_start() -> None:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    apply_migrations(conn)
    sm = SessionManager(conn)
    sm.set_replay_target(
        "sess-span",
        user_text="replay me",
        origin_turn_id="turn-src",
        replay_job_id="job-span",
    )

    router = MagicMock()
    router._sessions = sm
    router._workspace = MagicMock()
    router._workspace.model_dump.return_value = {}
    router.cancel_telegram_typing = MagicMock()
    router.route_outgoing = AsyncMock()
    router._replay_job_event_fanout = None

    layout = MagicMock()
    layout.content_root = Path("/tmp")

    with (
        patch(
            "sevn.gateway.agent_turn.load_session_row",
            return_value=MagicMock(channel="webchat", user_id="u1"),
        ),
        patch("sevn.gateway.agent_turn.supersede_awaiting_for_session", return_value=[]),
        patch("sevn.gateway.agent_turn._latest_user_message_text", return_value=""),
        patch("sevn.gateway.agent_turn._emit_gateway_span", new_callable=AsyncMock) as emit,
        patch("sevn.gateway.agent_turn.run_post_turn_hooks", new_callable=AsyncMock),
        patch(
            "sevn.gateway.agent_turn.triage_context_from_session",
            side_effect=AssertionError("stop after span"),
        ),
    ):
        from sevn.gateway.agent_turn import build_agent_run_turn

        run_turn = build_agent_run_turn(
            router,
            conn,
            router._workspace,
            layout,
            MagicMock(),
        )
        await run_turn("sess-span", "turn-new")

    turn_start = next(
        c for c in emit.await_args_list if c.kwargs.get("kind") == "gateway.turn.start"
    )
    attrs = turn_start.kwargs["attrs"]
    assert attrs["replay.of_turn_id"] == "turn-src"
    assert attrs["replay.kind"] == "dashboard_rerun"
