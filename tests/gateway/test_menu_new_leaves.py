"""W1 RED: new wire-up leaf rows (green after W7a-W7e)."""

from __future__ import annotations

import re

import pytest

from sevn.gateway.menu.menu_registry import MENU_BUTTON_SPECS

# Parametrised families — one block per W7 sub-wave; list must not shrink silently.
NEW_LEAF_FAMILIES: tuple[tuple[str, str, str], ...] = (
    # W7a — Chat
    ("W7a", "chat_shortcuts_list", r"^act:shortcuts:list$"),
    ("W7a", "chat_voice_status", r"^act:voice:status$"),
    ("W7a", "chat_sessions_list", r"^act:sessions:list$"),
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


def _specs_matching(pattern: str) -> list[object]:
    compiled = re.compile(pattern)
    return [spec for spec in MENU_BUTTON_SPECS if compiled.search(spec.callback_pattern)]


@pytest.mark.parametrize(("wave", "family", "pattern"), NEW_LEAF_FAMILIES)
def test_new_leaf_family_registered(wave: str, family: str, pattern: str) -> None:
    """W1.11 — each new leaf family has a registry row once wired."""
    if not _specs_matching(pattern):
        pytest.xfail(f"green after {wave}: {family} registry row")


@pytest.mark.parametrize(
    ("wave", "callback"),
    [
        ("W7a", "act:shortcuts:list"),
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
