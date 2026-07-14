"""Wave 10: ``dispatch_run`` delegates to shared ``build_agent_run_turn``."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.executors.b_types import ResolvedTierBModel
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.tracing.sink import NullTraceSink, TraceEvent, TraceSink
from sevn.config.workspace_config import WorkspaceConfig, parse_workspace_config
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations
from sevn.triggers.delivery import trigger_runs_dir
from sevn.triggers.dispatcher import dispatch_run
from sevn.triggers.request import DispatchRequest, ResultChannel
from sevn.workspace.layout import WorkspaceLayout

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "triager"
_E2E_STUB = _FIXTURE_DIR / "e2e_tier_b_stub.json"


class _ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return

    async def close(self) -> None:
        return


def _openai_assistant_text(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class _ScriptedChatTransport(ChatCompletionsTransport):
    def __init__(self, fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> None:
        super().__init__(proxy_base_url="http://dispatch-run.test.invalid")
        self._fn = fn

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        return await self._fn(dict(request))


def _memory_conn():
    import sqlite3

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _router_bundle(
    tmp_path: Path, conn: Any
) -> tuple[ChannelRouter, WorkspaceConfig, WorkspaceLayout]:
    root = tmp_path / "w"
    root.mkdir()
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "workspace_root": str(root),
            "triager": {"group_scope": "all", "relax_greeting_lists": False},
            "providers": {"tier_default": {"triager": "stub/model", "B": "stub/tier-b"}},
            "permissions": {"scope_narrowing": {"enabled": False}},
            "security": {"scanner": {"heuristic_only": True}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    layout = WorkspaceLayout(root / "sevn.json", root)
    sessions = SessionManager(conn)
    media = MediaStore(conn, root)
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
async def test_dispatch_run_delegates_to_build_agent_run_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``dispatch_run`` bootstraps session + invokes shared ``run_turn``."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    async def _scripted(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text("Trigger run finished.")

    async def _bundle_factory(_ws: WorkspaceConfig) -> ResolvedTierBModel:
        transport = _ScriptedChatTransport(_scripted)
        return ResolvedTierBModel(
            model_id="openai/gpt-trigger",
            transport=transport,
            budget=ModelBudget(model_id="openai/gpt-trigger", regime=BudgetRegime.FREE_LOCAL),
        )

    conn = _memory_conn()
    router, ws, layout = _router_bundle(tmp_path, conn)
    run_turn = build_agent_run_turn(
        router,
        conn,
        ws,
        layout,
        NullTraceSink(),
        tier_b_bundle_factory=_bundle_factory,
    )
    sink = _ListSink()
    trace: TraceSink = sink  # type: ignore[assignment]
    cid = "corr-trigger-10"
    req = DispatchRequest(
        prompt="run nightly summary",
        result_channel=ResultChannel(kind="LOG"),
        correlation_id=cid,
        trigger_meta={"transport": "unit"},
    )
    await dispatch_run(
        req,
        workspace=ws,
        content_root=layout.content_root,
        trace=trace,
        hooks=None,
        run_turn=run_turn,
        session_manager=router.session_manager,
    )
    agent_spans = [e for e in sink.events if e.kind == "trigger.agent_dispatch"]
    assert len(agent_spans) >= 2
    assert any(e.status == "completed" for e in agent_spans)
    assert not any(e.kind == "executor.tier_stub" for e in sink.events)
    log_path = trigger_runs_dir(layout.content_root) / f"{cid}.json"
    assert log_path.is_file()
    body = json.loads(log_path.read_text(encoding="utf-8"))
    assert body["status"] == "completed"
    assert body["assistant_messages"]
    assert "Trigger run finished" in " ".join(body["assistant_messages"])
    triage_count = int(conn.execute("SELECT COUNT(*) FROM triage_decisions").fetchone()[0])
    assert triage_count == 1
    conn.close()
