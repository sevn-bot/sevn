"""Shared helpers for telegram menu redesign tests (W1 RED suite)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.menu.menu import _CONFIG_SECTIONS, build_config_menu_keyboard
from sevn.gateway.menu.menu_readiness import readiness_for_callback
from sevn.gateway.menu.menu_registry import match_menu_button_spec

REPO_ROOT = Path(__file__).resolve().parents[2]

# Tracked snapshot of the W0.3 baseline readiness sets. The full wave artefact
# (rows, anchors, section deltas) stays local-only under
# .ignorelocal/waves/telegram-menu-baseline.json, which is gitignored and
# therefore absent in CI — these two sets are the part the suite asserts on, so
# they live in tests/fixtures/ where every runner can read them.
BASELINE_JSON = REPO_ROOT / "tests/fixtures/gateway/telegram_menu_baseline_spec_ids.json"

# Redesign contract (D16, redesign HTML root block) — implementation lands in W3+.
REDESIGN_OWNER_ROOT_TILES: tuple[tuple[str, str, bool], ...] = (
    ("💬 Chat", "chat", False),
    ("🧠 Agent", "agent", False),
    ("🧩 Skills & Tools", "skills", False),
    ("📚 Memory", "memory", False),
    ("🔐 Access", "access", True),
    ("📊 Health", "health", False),
    ("🖥 Deployment", "deployment", True),
    ("❓ Help", "help", False),
)

REDESIGN_NON_OWNER_ROOT_SLUGS: tuple[str, ...] = ("chat", "agent", "skills", "help")

REDESIGN_MAX_ROWS_PER_SCREEN = 14
REDESIGN_MAX_TAP_DEPTH = 3
DEPTH_EXCEPTION_SECTIONS: frozenset[str] = frozenset(
    {"skills:discogs:setup", "subagents_running"},
)

# W6 retired section ids → new home (D14). Empty string means explicit "moved/gone" answer.
RETIRED_SECTION_ALIASES: dict[str, str] = {
    "session": "chat",
    "channels": "chat",
    "notifications": "chat",
    "shortcuts": "chat",
    "voice": "chat",
    "agents": "agent",
    "models": "agent",
    "rlm": "agent",
    "codemode": "agent",
    "self_improve": "agent",
    "subagents": "agent",
    # Retargeted from "agent" during PR #63 review: a stale tap must reach the
    # Running submenu itself, not bounce one level up to the Agent root tile.
    "subagents_running": "agent_subagents_running",
    "tools": "skills",
    "integrations": "skills",
    "code": "memory",
    "second_brain": "memory",
    "secrets": "access",
    "security": "access",
    "logs": "health",
    "dashboard": "health",
    "my_sevn_bot": "deployment",
    "sevn_bot": "help",
    "advanced": "",
}

DEFAULT_DOCS_WORKSPACE = WorkspaceConfig.minimal(
    web_ui={"url": "https://app.example/mission-control"},
)


def load_baseline_ready_spec_ids() -> frozenset[str]:
    """Return the W0.3 Ready spec-id snapshot (never-regress set)."""
    data = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    return frozenset(str(x) for x in data["ready_spec_ids"])


def load_baseline_wip_spec_ids() -> frozenset[str]:
    """Return the W0.3 WIP spec-id set (gated backlog)."""
    data = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    return frozenset(str(x) for x in data["wip_spec_ids"])


def _keyboard_sections() -> tuple[str, ...]:
    return ("root", *sorted(_CONFIG_SECTIONS))


def iter_rendered_buttons(
    workspace: WorkspaceConfig | None = None,
    *,
    is_owner: bool = True,
) -> list[tuple[str, str, str]]:
    """Yield ``(section, label, callback_data)`` for every rendered menu button."""
    ws = workspace if workspace is not None else DEFAULT_DOCS_WORKSPACE
    out: list[tuple[str, str, str]] = []
    for section in _keyboard_sections():
        kwargs: dict[str, Any] = {"is_owner": is_owner}
        if section == "agent_subagents_running":
            kwargs["subagent_running_rows"] = ()
        kb = build_config_menu_keyboard(ws, section=section, **kwargs)  # type: ignore[arg-type]
        for row in kb.get("inline_keyboard", []):
            for btn in row:
                label = str(btn.get("text", ""))
                cb = btn.get("callback_data")
                if isinstance(cb, str) and cb:
                    out.append((section, label, cb))
    return out


def collect_live_ready_spec_ids(
    workspace: WorkspaceConfig | None = None,
    *,
    is_owner: bool = True,
) -> set[str]:
    """Collect spec ids whose callbacks resolve to Ready on the live menu tree."""
    ready: set[str] = set()
    for _section, _label, cb in iter_rendered_buttons(workspace, is_owner=is_owner):
        spec = match_menu_button_spec(cb)
        if spec is None:
            continue
        if readiness_for_callback(cb) == "Ready":
            ready.add(spec.spec_id)
    return ready


def root_section_tile_callbacks(*, is_owner: bool = True) -> list[str]:
    """Return root ``cfg:section:*`` callbacks in render order."""
    ws = DEFAULT_DOCS_WORKSPACE
    kb = build_config_menu_keyboard(ws, section="root", is_owner=is_owner)
    out: list[str] = []
    for row in kb.get("inline_keyboard", []):
        for btn in row:
            cb = btn.get("callback_data")
            if isinstance(cb, str) and cb.startswith("cfg:section:"):
                out.append(cb)
    return out


def count_rows_for_section(section: str, *, is_owner: bool = True) -> int:
    """Count inline keyboard rows for one section (including chrome)."""
    ws = DEFAULT_DOCS_WORKSPACE
    kwargs: dict[str, Any] = {"is_owner": is_owner}
    if section == "agent_subagents_running":
        kwargs["subagent_running_rows"] = ()
    kb = build_config_menu_keyboard(ws, section=section, **kwargs)  # type: ignore[arg-type]
    return len(kb.get("inline_keyboard", []))


def callbacks_matching_pattern(pattern: str) -> list[str]:
    """Return live callback_data strings whose registry pattern contains ``pattern``."""
    hits: list[str] = []
    for _section, _label, cb in iter_rendered_buttons():
        if pattern in cb:
            hits.append(cb)
    return hits


def trace_redaction_callback_count() -> int:
    """Count live trace-redaction toggle rows (W5 de-dup target)."""
    return len(callbacks_matching_pattern("toggle_redaction"))


# Legacy section ids → canonical nested section for keyboard/caption tests (W6).
LEGACY_TO_CANONICAL_SECTION: dict[str, str] = {
    "session": "chat_qa",
    "voice": "chat_voice",
    "channels": "chat_channels",
    "notifications": "chat",
    "shortcuts": "chat_shortcuts",
    "models": "agent",
    "agents": "agent_identity",
    "rlm": "agent_lab",
    "codemode": "agent_lab",
    "self_improve": "agent_lab",
    "subagents": "agent_subagents",
    "subagents_running": "agent_subagents_running",
    "tools": "skills_tools",
    "integrations": "skills_integrations",
    "code": "memory_code",
    "second_brain": "memory_sb",
    "secrets": "access_secrets",
    "security": "access_guard",
    "logs": "health",
    "dashboard": "health",
    "my_sevn_bot": "deployment",
    "sevn_bot": "help",
}


def canonical_section(legacy_or_current: str) -> str:
    """Map a retired section id to its canonical nested section when applicable."""
    key = legacy_or_current.strip().lower()
    return LEGACY_TO_CANONICAL_SECTION.get(key, key)


def queue_mode_callback_count() -> int:
    """Count live queue-mode cycle rows (W5 de-dup target)."""
    return len(callbacks_matching_pattern("gateway.queue_mode"))


def current_root_tile_count(*, is_owner: bool = True) -> int:
    """Count section tiles on the root keyboard."""
    return len(root_section_tile_callbacks(is_owner=is_owner))
