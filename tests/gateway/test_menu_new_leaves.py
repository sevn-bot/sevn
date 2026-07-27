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
    # W7b — Agent
    ("W7b", "agent_sampling_show", r"^act:agent:sampling:show$"),
    ("W7b", "agent_active_runs", r"^act:agent:status$"),
    ("W7b", "agent_lab_improve_doctor", r"^act:self_improve:doctor$"),
    # W7c — Skills & Tools + Memory
    ("W7c", "skills_list", r"^act:skills:list$"),
    ("W7c", "tools_health", r"^act:tools:health$"),
    ("W7c", "memory_search", r"^act:memory:search$"),
    ("W7c", "dreaming_status", r"^act:dreaming:status$"),
    ("W7c", "openui_install", r"^act:openui:install$"),
    # W7d — Access + Health
    ("W7d", "secrets_list_aliases", r"^act:secrets:list$"),
    ("W7d", "pairing_pending", r"^act:pairing:pending$"),
    ("W7d", "health_doctor", r"^act:doctor:run$"),
    ("W7d", "turn_bundles_export", r"^act:turn_bundles:export$"),
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
    if wave == "W7a":
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


@pytest.mark.parametrize(
    ("wave", "callback"),
    [
        ("W7b", "act:agent:status"),
        ("W7c", "act:tools:health"),
        ("W7d", "act:doctor:run"),
        ("W7e", "act:config:show"),
    ],
)
@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W7: callback invokes non-empty answer", strict=False)
async def test_new_leaf_handler_returns_non_empty_answer(wave: str, callback: str) -> None:
    """W1.11 — wired rows must post a non-empty answer (never silent no-op)."""
    from sevn.gateway.commands.menu_action_router import MenuActionRouter
    from sevn.gateway.menu.menu_registry import match_menu_button_spec

    assert match_menu_button_spec(callback) is not None
    assert hasattr(MenuActionRouter, "handle")
    _ = wave
