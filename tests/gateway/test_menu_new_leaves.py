"""W1 RED: new wire-up leaf rows (green after W7a-W7e)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sevn.gateway.menu.menu_registry import MENU_BUTTON_SPECS

# Parametrised families — one block per W7 sub-wave; list must not shrink silently.
NEW_LEAF_FAMILIES: tuple[tuple[str, str, str], ...] = (
    # W7a - Chat (C3.6-7, C5.6-7, C16.5-6, C17.2, C26.1-3)
    ("W7a", "chat_shortcuts_list", r"^act:shortcuts:list$"),
    ("W7a", "chat_shortcuts_remove", r"^form:shortcut_remove$"),
    ("W7a", "chat_voice_status", r"^act:voice:status$"),
    ("W7a", "chat_voice_show", r"^act:voice:show$"),
    ("W7a", "chat_channels_status", r"^act:channels:status$"),
    ("W7a", "chat_channels_config", r"^act:channels:config$"),
    ("W7a", "chat_sessions_list", r"^act:sessions:list$"),
    ("W7a", "chat_sessions_history", r"^form:sessions:history$"),
    ("W7a", "chat_sessions_send", r"^form:sessions:send$"),
    ("W7a", "chat_notify_policy", r"^cfg:cycle:channels\.telegram\.telegram_notify_policy:.+$"),
    # W7b - Agent (C27.1-8 + sub-agent kill act:*)
    ("W7b", "agent_active_runs", r"^act:agent:status$"),
    ("W7b", "agent_sampling_show", r"^act:agent:sampling:show$"),
    ("W7b", "agent_sampling_set_tokens", r"^form:models:set_max_output_tokens$"),
    ("W7b", "agent_identity_config", r"^act:agent:config$"),
    ("W7b", "agent_lab_improve_doctor", r"^act:self_improve:doctor$"),
    ("W7b", "agent_lab_record_lesson", r"^form:improve:learn$"),
    ("W7b", "agent_lab_replay_sampler", r"^act:self_improve:replay_sampler$"),
    ("W7b", "agent_subagents_kill_form", r"^form:subagents:kill$"),
    ("W7b", "agent_subagents_kill_one", r"^act:subagents:kill:[a-z0-9]+$"),
    ("W7b", "agent_subagents_kill_all", r"^act:subagents:kill_all$"),
    # W7c — Skills & Tools + Memory (C28.1-17)
    ("W7c", "skills_list", r"^act:skills:list$"),
    ("W7c", "skills_sync", r"^act:skills:sync$"),
    ("W7c", "skills_security_scan", r"^act:skills:security\-scan$"),
    ("W7c", "tools_health", r"^act:tools:health$"),
    ("W7c", "memory_dreaming_nav", r"^cfg:section:memory_dreaming$"),
    ("W7c", "memory_search", r"^act:memory:search$"),
    ("W7c", "memory_index", r"^act:memory:index$"),
    ("W7c", "memory_openwiki_nav", r"^cfg:section:memory_openwiki$"),
    ("W7c", "second_brain_reindex", r"^act:second_brain:reindex$"),
    ("W7c", "second_brain_setup", r"^act:second_brain:setup$"),
    ("W7c", "dreaming_status", r"^act:dreaming:status$"),
    ("W7c", "dreaming_backfill", r"^form:memory:backfill$"),
    ("W7c", "dreaming_undo", r"^act:dreaming:undo$"),
    ("W7c", "dreaming_reconcile_cron", r"^act:dreaming:reconcile_cron$"),
    ("W7c", "openui_install", r"^act:openui:install$"),
    ("W7c", "openui_configure", r"^form:openui:configure$"),
    ("W7c", "openui_setup", r"^act:openui:setup$"),
    # W7d — Access + Health (C29.1-17)
    ("W7d", "secrets_list_aliases", r"^act:secrets:list$"),
    ("W7d", "secrets_remove_form", r"^form:secrets:rm$"),
    ("W7d", "secrets_unlock_status", r"^act:secrets:check\-unlock$"),
    ("W7d", "providers_oauth_status", r"^act:providers:oauth:status$"),
    ("W7d", "providers_oauth_login", r"^form:providers:oauth:login$"),
    ("W7d", "providers_oauth_logout", r"^form:providers:oauth:logout$"),
    ("W7d", "github_token_form", r"^form:gh:github_token$"),
    ("W7d", "access_pairing_nav", r"^cfg:section:access_pairing$"),
    ("W7d", "pairing_pending", r"^act:pairing:pending$"),
    ("W7d", "pairing_approve_form", r"^form:pairing:approve$"),
    ("W7d", "health_doctor", r"^act:doctor:run$"),
    ("W7d", "health_usage", r"^act:usage:show$"),
    ("W7d", "health_bundles_nav", r"^cfg:section:health_bundles$"),
    ("W7d", "turn_bundles_export", r"^act:turn_bundles:export$"),
    ("W7d", "turn_bundles_view_form", r"^form:turn_bundles:view$"),
    ("W7d", "tracing_config", r"^act:tracing:config$"),
    ("W7d", "access_providers_nav", r"^cfg:section:access_providers$"),
    # W7e — Deployment + Help
    ("W7e", "services_gateway_status", r"^act:services:gateway:status$"),
    ("W7e", "tunnel_status", r"^act:tunnel:status$"),
    ("W7e", "config_show", r"^act:config:show$"),
    ("W7e", "guides_list", r"^act:guides:list$"),
)

W7A_ACTION_CALLBACKS: tuple[str, ...] = (
    "act:shortcuts:list",
    "act:voice:status",
    "act:voice:show",
    "act:channels:status",
    "act:channels:config",
    "act:sessions:list",
)

W7B_ACTION_CALLBACKS: tuple[str, ...] = (
    "act:agent:status",
    "act:agent:sampling:show",
    "act:agent:config",
    "act:self_improve:doctor",
    "act:self_improve:replay_sampler",
)

W7C_ACTION_CALLBACKS: tuple[str, ...] = (
    "act:skills:list",
    "act:skills:sync",
    "act:skills:security-scan",
    "act:tools:health",
    "act:memory:search",
    "act:memory:index",
    "act:second_brain:reindex",
    "act:second_brain:setup",
    "act:dreaming:status",
    "act:dreaming:undo",
    "act:dreaming:reconcile_cron",
    "act:openui:install",
    "act:openui:setup",
)

W7D_ACTION_CALLBACKS: tuple[str, ...] = (
    "act:secrets:list",
    "act:secrets:check-unlock",
    "act:providers:oauth:status",
    "act:pairing:pending",
    "act:doctor:run",
    "act:usage:show",
    "act:turn_bundles:export",
    "act:tracing:config",
)


def _specs_matching(pattern: str) -> list[object]:
    """Return registry rows whose callback regex equals the family pattern."""
    family = re.compile(pattern)
    return [
        spec
        for spec in MENU_BUTTON_SPECS
        if re.compile(spec.callback_pattern).pattern == family.pattern
    ]


@pytest.mark.parametrize(("wave", "family", "pattern"), NEW_LEAF_FAMILIES)
def test_new_leaf_family_registered(wave: str, family: str, pattern: str) -> None:
    """W1.11 — each new leaf family has a registry row once wired."""
    matches = _specs_matching(pattern)
    if wave in ("W7a", "W7b", "W7c", "W7d"):
        assert matches, f"{family} missing registry row matching {pattern!r}"
        return
    if not matches:
        pytest.xfail(f"green after {wave}: {family} registry row")


@pytest.mark.parametrize("callback", W7A_ACTION_CALLBACKS)
@pytest.mark.asyncio
async def test_w7a_leaf_handler_returns_non_empty_answer(tmp_path: Path, callback: str) -> None:
    """W1.11 — W7a wired rows must post a non-empty answer (never silent no-op)."""
    from tests.gateway.test_menu import _build_config_router, _config_callback

    router, cap, _ = _build_config_router(tmp_path)
    msg = _config_callback(callback, callback_query_id=f"cq-{callback.replace(':', '-')}")
    await router.route_incoming(msg)
    assert cap.answered or cap.sent or cap.edited, f"{callback} silent no-op"
    if cap.sent:
        assert str(cap.sent[0][0]).strip()
    elif cap.answered:
        assert any(text for _cq, text in cap.answered if text)


@pytest.mark.parametrize("callback", W7B_ACTION_CALLBACKS)
@pytest.mark.asyncio
async def test_w7b_leaf_handler_returns_non_empty_answer(tmp_path: Path, callback: str) -> None:
    """W1.11 — W7b wired act:* rows must post a non-empty answer (never silent no-op)."""
    from tests.gateway.test_menu import _build_config_router, _config_callback

    router, cap, _ = _build_config_router(tmp_path)
    msg = _config_callback(callback, callback_query_id=f"cq-{callback.replace(':', '-')}")
    await router.route_incoming(msg)
    assert cap.answered or cap.sent or cap.edited, f"{callback} silent no-op"
    if cap.sent:
        assert str(cap.sent[0][0]).strip()
    elif cap.answered:
        assert any(text for _cq, text in cap.answered if text)


@pytest.mark.parametrize("callback", W7C_ACTION_CALLBACKS)
@pytest.mark.asyncio
async def test_w7c_leaf_handler_returns_non_empty_answer(tmp_path: Path, callback: str) -> None:
    """W1.11 — W7c wired act:* rows must post a non-empty answer (never silent no-op)."""
    from tests.gateway.test_menu import _build_config_router, _config_callback

    router, cap, _ = _build_config_router(tmp_path)
    msg = _config_callback(callback, callback_query_id=f"cq-{callback.replace(':', '-')}")
    await router.route_incoming(msg)
    assert cap.answered or cap.sent or cap.edited, f"{callback} silent no-op"
    if cap.sent:
        assert str(cap.sent[0][0]).strip()
    elif cap.answered:
        assert any(text for _cq, text in cap.answered if text)


@pytest.mark.parametrize("callback", W7D_ACTION_CALLBACKS)
@pytest.mark.asyncio
async def test_w7d_leaf_handler_returns_non_empty_answer(tmp_path: Path, callback: str) -> None:
    """W1.11 — W7d wired act:* rows must post a non-empty answer (never silent no-op)."""
    from tests.gateway.test_menu import _build_config_router, _config_callback

    router, cap, _ = _build_config_router(tmp_path)
    msg = _config_callback(callback, callback_query_id=f"cq-{callback.replace(':', '-')}")
    await router.route_incoming(msg)
    assert cap.answered or cap.sent or cap.edited, f"{callback} silent no-op"
    if cap.sent:
        assert str(cap.sent[0][0]).strip()
    elif cap.answered:
        assert any(text for _cq, text in cap.answered if text)


@pytest.mark.parametrize(
    ("wave", "callback"),
    [
        ("W7e", "act:config:show"),
    ],
)
@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W7e: callback invokes non-empty answer", strict=False)
async def test_new_leaf_handler_returns_non_empty_answer(wave: str, callback: str) -> None:
    """W1.11 — wired rows must post a non-empty answer (never silent no-op)."""
    from sevn.gateway.commands.menu_action_router import MenuActionRouter
    from sevn.gateway.menu.menu_registry import match_menu_button_spec

    assert match_menu_button_spec(callback) is not None
    assert hasattr(MenuActionRouter, "handle")
    _ = wave
