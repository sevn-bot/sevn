"""Telegram /config Sub-agents section tests (W7.4)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sevn.agent.subagents.registry import SubAgentRegistry
from sevn.agent.subagents.supervisor import SubAgentSpec, SubAgentSupervisor
from sevn.config.sections.subagents import SubAgentsWorkspaceConfig
from sevn.config.workspace_config import GatewayConfig, WorkspaceConfig
from sevn.gateway.commands.menu_action_router import MenuActionRouter, parse_action_callback
from sevn.gateway.commands.menu_form_handler import parse_form_callback
from sevn.gateway.menu.menu import (
    _build_subagents_keyboard_rows,
    _build_subagents_running_keyboard_rows,
    build_config_menu_keyboard,
    config_menu_message_text,
)


def test_subagents_keyboard_rows_include_toggle_limits_and_running() -> None:
    ws = WorkspaceConfig.minimal(subagents=SubAgentsWorkspaceConfig(enabled=True))
    rows = _build_subagents_keyboard_rows(ws, level1_count=2, level2_count=1)
    callbacks = [btn["callback_data"] for row in rows for btn in row]
    assert "cfg:toggle:subagents.enabled:false" in callbacks
    assert "cfg:section:agent_subagents_running" in callbacks
    assert "form:subagents_max_override" in callbacks
    assert any(cb.startswith("form:subagents_limits:") for cb in callbacks)


def test_every_rendered_section_callback_targets_a_live_section() -> None:
    """PR #63 review: a `cfg:section:*` button must not route through the alias table.

    The Running L1/L2 row kept emitting the pre-rename `subagents_running` id, so
    every tap was classified as a retired section and bounced back to the Agent
    root tile — a live, Ready-marked row that silently did nothing.

    Rows explicitly labelled "(legacy)" are exempt: those exist precisely to
    exercise the D14 alias table for callbacks held by older messages.
    """
    from sevn.gateway.menu.menu import _CONFIG_SECTIONS
    from tests.gateway.telegram_menu_redesign_helpers import iter_rendered_buttons

    retired = [
        (section, label, cb)
        for section, label, cb in iter_rendered_buttons()
        if cb.startswith("cfg:section:")
        and cb.removeprefix("cfg:section:") not in _CONFIG_SECTIONS
        and "(legacy)" not in label
    ]
    assert retired == []


def test_subagents_running_keyboard_owner_kill_buttons() -> None:
    running = (
        {"id": "a1f3", "role": "tier_b", "level": 1, "task_summary": "slow task"},
        {"id": "b2c4", "role": "triager", "level": 1, "task_summary": "classify"},
    )
    rows = _build_subagents_running_keyboard_rows(running, is_owner=True)
    callbacks = [btn["callback_data"] for row in rows for btn in row]
    assert "act:subagents:kill:a1f3" in callbacks
    assert "act:subagents:kill:b2c4" in callbacks
    assert "act:subagents:kill_all" in callbacks


def test_subagents_caption_shows_live_counts_and_limits() -> None:
    ws = WorkspaceConfig.minimal(
        subagents=SubAgentsWorkspaceConfig(max_override=4),
        gateway=GatewayConfig(
            token="${SECRET:keychain:sevn.gateway.token}",
            queue_mode="multi",
        ),
    )
    text = config_menu_message_text(
        ws,
        section="agent_subagents",
        subagent_level1_count=3,
        subagent_level2_count=2,
    )
    assert "Running: L1=3 L2=2" in text
    assert "Queue mode: multi" in text
    assert "Global override: 4" in text
    assert "Tier B: L1=4 L2=3" in text


def test_form_callbacks_for_subagents_limits() -> None:
    assert parse_form_callback("form:subagents_max_override") == "subagents_max_override"
    assert parse_form_callback("form:subagents_limits:tier_b") == "subagents_limits:tier_b"


def test_kill_action_callback_parsing() -> None:
    parsed = parse_action_callback("act:subagents:kill:a1f3")
    assert parsed == ("action", "subagents:kill:a1f3", None)


def test_infer_config_section_subagents_toggle() -> None:
    from sevn.gateway.commands.menu_action_router import infer_config_section_from_callback

    assert (
        infer_config_section_from_callback("cfg:toggle:subagents.enabled:true") == "agent_subagents"
    )


@pytest.mark.asyncio
async def test_menu_kill_action_routes_to_supervisor(tmp_path: Path) -> None:
    from sevn.gateway.channel_router import ChannelRouter, IncomingMessage

    ws = WorkspaceConfig.minimal()
    router = ChannelRouter.__new__(ChannelRouter)
    router._adapters = {}
    router._workspace = ws
    router._resolve_owner_flag = lambda _msg: True  # type: ignore[method-assign]
    router._config_menu_nav = {}

    supervisor = SubAgentSupervisor(registry=SubAgentRegistry(), config=SubAgentsWorkspaceConfig())
    router._subagent_supervisor = supervisor

    async def _work() -> None:
        await asyncio.sleep(120)

    handle = await supervisor.spawn(
        SubAgentSpec(
            level=1,
            role="tier_b",
            body=_work,
            session_id="s-menu",
            channel="telegram",
            task_summary="menu kill test",
        ),
    )
    run_id = handle.id

    mar = MenuActionRouter(
        workspace=ws,
        router=router,
        conn=__import__("sqlite3").connect(":memory:"),
        content_root=tmp_path,
        sevn_json_path=tmp_path / "sevn.json",
    )

    async def _noop_refresh(*_a, **_k) -> bool:
        return True

    mar._refresh_config_menu_after_action = _noop_refresh  # type: ignore[method-assign]

    msg = IncomingMessage(
        channel="telegram",
        user_id="1",
        text="",
        metadata={"callback_data": f"act:subagents:kill:{run_id}"},
    )
    toast = await mar.handle(msg, session_id="sess")
    assert toast is None or "Killed" in toast or toast == ""
    updated = await supervisor.registry.get(run_id)
    assert updated is not None
    assert updated.status.value == "killed"


def test_build_config_menu_keyboard_subagents_section() -> None:
    ws = WorkspaceConfig.minimal()
    kb = build_config_menu_keyboard(
        ws,
        section="agent_subagents",
        subagent_level1_count=1,
        subagent_level2_count=0,
    )
    body = kb["inline_keyboard"][:-1]
    assert any(
        btn.get("callback_data") == "cfg:section:agent_subagents_running"
        for row in body
        for btn in row
    )
