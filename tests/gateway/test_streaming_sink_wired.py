"""Gateway streaming sink wiring for Telegram (`plan/gateway-operator-recovery-wave-plan.md` W5)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.executors.b_types import BTurnOutcome, ChannelPayload
from sevn.agent.tracing.sink import NullTraceSink
from sevn.channels.telegram import TelegramAdapter
from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway import agent_turn as agent_turn_mod
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "triager"
_E2E_STUB = _FIXTURE_DIR / "e2e_tier_b_stub.json"


class _CaptureTelegram(TelegramAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.sent_texts: list[str] = []

    async def send(self, message: Any) -> list[str]:
        self.sent_texts.append(message.text)
        return [str(1000 + len(self.sent_texts))]

    async def edit_text(
        self,
        *,
        channel_message_id: str,
        new_text: str,
        metadata: dict[str, Any] | None = None,
        send_split_followups: bool = True,
    ) -> bool:
        _ = channel_message_id, new_text, metadata, send_split_followups
        return True


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _router_bundle(
    tmp_path: Path, conn: sqlite3.Connection
) -> tuple[ChannelRouter, Any, WorkspaceLayout]:
    root = tmp_path / "w"
    root.mkdir()
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "providers": {"tier_default": {"triager": "stub/model", "B": "stub/tier-b"}},
            "permissions": {"scope_narrowing": {"enabled": False}},
            "security": {"scanner": {"heuristic_only": True}},
            "triager": {
                "group_scope": "all",
                "relax_greeting_lists": False,
                "fast_greeting_path": False,
            },
            "gateway": {
                "first_session_intro": {"enabled": False},
                "output": {"tier_b_answer_mode": "stream"},
                "token": "${SECRET:keychain:sevn.gateway.token}",
            },
        },
    )
    layout = WorkspaceLayout(root / "sevn.json", root)
    sessions = SessionManager(conn)
    media = MediaStore(conn, root)
    from sevn.security.llm_guard_scanner import LLMGuardScanner

    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=sessions,
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=media,
    )
    return router, ws, layout


@pytest.mark.asyncio
async def test_telegram_stream_mode_wires_non_none_streaming_sink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telegram tier-B turns in ``stream`` mode pass a non-``None`` ``streaming_sink``."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    observed_sink: Any = object()

    async def _fake_run_b_turn(**kwargs: Any) -> BTurnOutcome:
        nonlocal observed_sink
        observed_sink = kwargs.get("streaming_sink")
        return BTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text="wired."),),
            escalation=None,
            rounds_used=1,
        )

    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _fake_run_b_turn)

    conn = _memory_conn()
    router, ws, layout = _router_bundle(tmp_path, conn)
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    run_turn = build_agent_run_turn(router, conn, ws, layout, NullTraceSink())
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-stream-wire",
            channel="telegram",
            user_id="u-stream-wire",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="hello",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 9014, "message_id": 1}),
            turn_id="t-test",
        )
        await run_turn(session_id, "corr-stream-wire")
        assert observed_sink is not None
        assert callable(observed_sink)
    finally:
        conn.close()
