"""Wave TE-3 — owner-gated ``/logs`` and ``/traces`` slash commands.

Covers ``DiagnosticCommandHandler`` (owner refusal, tail output, redaction,
recent traces) and dispatcher routing without an agent turn.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.diagnostic_commands import (
    OWNER_ONLY_REFUSAL,
    DiagnosticCommandHandler,
)
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.commands.registry import DEFAULT_COMMAND_SPECS
from sevn.gateway.media_store import MediaStore
from sevn.gateway.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.workspace.layout import WorkspaceLayout
from tests.gateway.test_menu import _conn, _MenuCaptureTelegram, _workspace


def _seed_workspace(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "w"
    root.mkdir()
    sevn_json = root / "sevn.json"
    sevn_json.write_text(
        (
            '{"schema_version":1,"workspace_root":".",'
            '"gateway":{"host":"127.0.0.1","port":3001,"queue_mode":"cancel",'
            '"token":"${SECRET:keychain:sevn.gateway.token}"},'
            '"channels":{"telegram":{"quick_actions":{"show_regen":true}}},'
            '"security":{"scanner":{"heuristic_only":true}},'
            '"providers":{"use_main_model_for_all":false,'
            '"tier_default":{"triager":"test/triager","B":"test/tier-b"}}}'
        ),
        encoding="utf-8",
    )
    (root / "logs").mkdir()
    return root, sevn_json


def _build_owner_router(
    tmp_path: Path,
    *,
    owner_ids: frozenset[str] = frozenset({"owner1"}),
) -> tuple[ChannelRouter, _MenuCaptureTelegram, Path, Path]:
    root, sevn_json = _seed_workspace(tmp_path)
    ws = _workspace()
    conn = _conn()
    cap = _MenuCaptureTelegram()
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        run_turn=AsyncMock(),
        owner_user_ids=owner_ids,
    )
    router.register_adapter(cap)
    build_agent_run_turn(
        router,
        conn,
        ws,
        WorkspaceLayout(sevn_json, root),
        NullTraceSink(),
    )
    return router, cap, root, sevn_json


def _slash(text: str, *, user_id: str = "owner1") -> IncomingMessage:
    return IncomingMessage(
        channel="telegram",
        user_id=user_id,
        text=text,
        metadata={"chat_id": 42, "message_id": 99},
    )


def test_diagnostic_handler_matches_slash() -> None:
    h = DiagnosticCommandHandler.__new__(DiagnosticCommandHandler)
    assert h.matches_slash(_slash("/logs tail gateway"))
    assert h.matches_slash(_slash("/logs"))
    assert h.matches_slash(_slash("/traces recent"))
    assert not h.matches_slash(_slash("/help"))
    assert not h.matches_slash(_slash("/log"))


def test_dispatcher_recognises_logs_and_traces() -> None:
    spec_names = {spec.name for spec in DEFAULT_COMMAND_SPECS}
    assert "logs" in spec_names
    assert "traces" in spec_names
    dispatcher = CommandDispatcher()
    assert dispatcher.try_dispatch(_slash("/logs tail gateway")) is True
    assert dispatcher.try_dispatch(_slash("/traces recent 5")) is True


@pytest.mark.asyncio
async def test_logs_tail_owner_returns_pre_chunks(tmp_path: Path) -> None:
    router, cap, root, _ = _build_owner_router(tmp_path)
    (root / "logs" / "gateway.log").write_text(
        "alpha line\nbeta line\ngamma line\n",
        encoding="utf-8",
    )
    await router.route_incoming(_slash("/logs tail gateway 20"))
    assert cap.sent, "owner /logs tail should produce outbound messages"
    text, meta = cap.sent[-1]
    assert text.startswith("<pre>")
    assert text.endswith("</pre>")
    assert "gamma line" in text
    assert meta.get("parse_mode") == "HTML"
    # No agent turn was triggered
    router._run_turn.assert_not_called()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_logs_tail_non_owner_short_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, cap, root, _ = _build_owner_router(
        tmp_path,
        owner_ids=frozenset({"owner1"}),
    )
    (root / "logs" / "gateway.log").write_text(
        "secret data inside\n",
        encoding="utf-8",
    )

    import sevn.gateway.commands.diagnostic_commands as diag_cmds

    sentinel: dict[str, int] = {"calls": 0}

    def _spy_tail(*args: Any, **kwargs: Any) -> list[str]:
        sentinel["calls"] += 1
        return []

    monkeypatch.setattr(diag_cmds, "tail_service_log", _spy_tail)

    await router.route_incoming(_slash("/logs tail gateway", user_id="someone-else"))
    assert cap.sent, "non-owner should still receive a refusal"
    text, _meta = cap.sent[-1]
    assert text == OWNER_ONLY_REFUSAL
    assert sentinel["calls"] == 0


@pytest.mark.asyncio
async def test_logs_tail_redacts_when_policy_enabled(tmp_path: Path) -> None:
    router, cap, root, _ = _build_owner_router(tmp_path)
    secret_line = "2026-05-24 token=supersecret123 op=ok"
    (root / "logs" / "gateway.log").write_text(secret_line + "\n", encoding="utf-8")
    # Workspace defaults to redaction enabled (DEFAULT_TRACE_REDACTION_ENABLED=True)
    await router.route_incoming(_slash("/logs tail gateway 5"))
    text, _meta = cap.sent[-1]
    assert "supersecret123" not in text
    assert "<redacted>" in text


@pytest.mark.asyncio
async def test_traces_recent_owner_returns_pre_chunks(tmp_path: Path) -> None:
    router, cap, root, _ = _build_owner_router(tmp_path)
    # Seed a trace event into traces.db so list_trace_events returns something
    from sevn.agent.tracing.traces_migrate import apply_traces_migrations
    from sevn.storage.paths import traces_sqlite_path

    dot_sevn = root / ".sevn"
    dot_sevn.mkdir(exist_ok=True)
    db_path = traces_sqlite_path(dot_sevn)
    conn = sqlite3.connect(db_path)
    apply_traces_migrations(conn)
    conn.execute(
        """
        INSERT INTO trace_events
            (span_id, parent_span_id, session_id, turn_id, tier, kind,
             ts_start_ns, ts_end_ns, status, attrs_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("span1", None, "sess1", "turn1", "B", "gateway.turn", 1, 2, "ok", "{}"),
    )
    conn.commit()
    conn.close()

    await router.route_incoming(_slash("/traces recent 5"))
    assert cap.sent, "owner /traces recent should produce outbound messages"
    text, meta = cap.sent[-1]
    assert text.startswith("<pre>")
    assert "span1" in text
    assert meta.get("parse_mode") == "HTML"


@pytest.mark.asyncio
async def test_traces_recent_empty_when_db_missing(tmp_path: Path) -> None:
    router, cap, _root, _ = _build_owner_router(tmp_path)
    await router.route_incoming(_slash("/traces recent"))
    assert cap.sent
    text, _meta = cap.sent[-1]
    assert "no traces" in text.lower()


@pytest.mark.asyncio
async def test_logs_usage_when_no_subcommand(tmp_path: Path) -> None:
    router, cap, _root, _ = _build_owner_router(tmp_path)
    await router.route_incoming(_slash("/logs"))
    assert cap.sent
    text, _meta = cap.sent[-1]
    assert "Usage" in text


def test_owner_only_refusal_string_is_short() -> None:
    # Short, single-line refusal — never leaks state or implementation detail
    assert len(OWNER_ONLY_REFUSAL.splitlines()) == 1
    assert len(OWNER_ONLY_REFUSAL) <= 80
