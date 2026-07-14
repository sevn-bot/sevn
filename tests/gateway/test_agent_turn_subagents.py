"""L1 sub-agent registration lifecycle in the gateway turn spine (W3.1, `plan/sub-agents-
orchestration-wave-plan.md`) — fake model transports, zero LLM calls.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sevn.agent.executors.b_types import ResolvedTierBModel
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.subagents.models import SubAgentStatus
from sevn.agent.subagents.registry import SubAgentRegistry
from sevn.agent.subagents.supervisor import SubAgentSupervisor
from sevn.agent.tracing.sink import NullTraceSink
from sevn.channels.telegram import TelegramAdapter
from sevn.config.workspace_config import WorkspaceConfig, parse_workspace_config
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

if TYPE_CHECKING:
    import pytest

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "triager"
_E2E_STUB = _FIXTURE_DIR / "e2e_tier_b_stub.json"
_E2E_SPECIALIST_GRANT_STUB = _FIXTURE_DIR / "e2e_tier_b_specialist_grant_stub.json"


def _openai_assistant_text(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class _ScriptedChatTransport(ChatCompletionsTransport):
    def __init__(self, text: str) -> None:
        super().__init__(proxy_base_url="http://agent-turn-subagents.test.invalid")
        self._text = text

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        _ = request
        return _openai_assistant_text(self._text)


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
        _ = channel_message_id, metadata, send_split_followups
        self.sent_texts.append(new_text)
        return True


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _router_bundle(
    tmp_path: Path,
    conn: sqlite3.Connection,
) -> tuple[ChannelRouter, WorkspaceConfig, WorkspaceLayout]:
    root = tmp_path / "w"
    root.mkdir()
    ws = parse_workspace_config(
        {
            "schema_version": 1,
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


async def _bundle_factory(_ws: WorkspaceConfig) -> ResolvedTierBModel:
    transport = _ScriptedChatTransport("All good — L1 tracking works.")
    return ResolvedTierBModel(
        model_id="openai/gpt-tier-b",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-tier-b", regime=BudgetRegime.FREE_LOCAL),
    )


async def _drive_one_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    subagent_supervisor: SubAgentSupervisor | None,
    bundle_factory: Any = _bundle_factory,
    fixture_path: Path = _E2E_STUB,
) -> sqlite3.Connection:
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(fixture_path))
    conn = _memory_conn()
    router, ws, layout = _router_bundle(tmp_path, conn)
    router.register_adapter(_CaptureTelegram())
    if subagent_supervisor is not None:
        router._subagent_supervisor = subagent_supervisor
    run_turn = build_agent_run_turn(
        router,
        conn,
        ws,
        layout,
        NullTraceSink(),
        tier_b_bundle_factory=bundle_factory,
    )
    session_id = await router.session_manager.ensure_session(
        scope_key="telegram:u-subagents",
        channel="telegram",
        user_id="u-subagents",
    )
    await router.session_manager.add_message(
        session_id,
        role="user",
        kind="message",
        content="please check my workspace health",
        visible_to_llm=1,
        status="sent",
        metadata_blob=json.dumps({"chat_id": 9020, "message_id": 1}),
        turn_id="t-test",
    )
    await run_turn(session_id, "corr-subagents-1")
    return conn


async def test_l1_registration_tracks_triager_and_tier_b_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A classic (non-``multi``) turn registers exactly one triager + one tier_b L1 run,
    both landing at ``done`` — the degenerate "L1 with concurrency 1" case (D1).
    """
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry)

    await _drive_one_turn(tmp_path, monkeypatch, subagent_supervisor=supervisor)

    runs = await registry.snapshot()
    by_role = {run.role: run for run in runs if run.level == 1}
    assert set(by_role) == {"triager", "tier_b"}
    assert by_role["triager"].status == SubAgentStatus.DONE
    assert by_role["tier_b"].status == SubAgentStatus.DONE
    assert by_role["triager"].task_summary
    assert by_role["tier_b"].task_summary


async def test_l1_registration_is_noop_without_supervisor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Classic-path behavior is unchanged when no supervisor is wired (most unit tests)."""
    conn = await _drive_one_turn(tmp_path, monkeypatch, subagent_supervisor=None)
    row = conn.execute(
        "SELECT status FROM gateway_turn_metadata WHERE turn_id = 'corr-subagents-1'",
    ).fetchone()
    assert row is not None
    assert row[0] == "ok"


async def test_l1_executor_run_marked_failed_on_unhandled_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unhandled exception during tier-B dispatch finalizes the L1 run as ``failed``."""
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry)

    async def _boom(_ws: WorkspaceConfig) -> ResolvedTierBModel:
        msg = "synthetic tier-B bundle failure"
        raise RuntimeError(msg)

    await _drive_one_turn(
        tmp_path,
        monkeypatch,
        subagent_supervisor=supervisor,
        bundle_factory=_boom,
    )

    runs = await registry.snapshot()
    by_role = {run.role: run for run in runs if run.level == 1}
    assert by_role["tier_b"].status == SubAgentStatus.FAILED
    # Triage itself succeeded before the bundle factory blew up.
    assert by_role["triager"].status == SubAgentStatus.DONE


async def test_triager_specialist_grant_flows_into_tool_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``TriageResult.specialist_grants`` (W3.4) reaches the tier-B ``ToolContext`` as
    ``subagent_specialist_grants`` — the field the ``spawn_subagent`` tool gates on.
    """
    from sevn.gateway import agent_turn as agent_turn_mod

    captured: dict[str, Any] = {}
    orig = agent_turn_mod._tool_context_for_turn

    def _spy(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return orig(**kwargs)

    monkeypatch.setattr(agent_turn_mod, "_tool_context_for_turn", _spy)
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry)

    await _drive_one_turn(
        tmp_path,
        monkeypatch,
        subagent_supervisor=supervisor,
        fixture_path=_E2E_SPECIALIST_GRANT_STUB,
    )

    assert captured["subagent_specialist_grants"] == frozenset({"media_generator"})
    assert captured["subagent_role"] == "tier_b"
    assert captured["subagent_parent_id"]
    assert captured["subagent_supervisor"] is supervisor
