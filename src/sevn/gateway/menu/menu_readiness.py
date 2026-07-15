"""Operator readiness gating for Telegram ``/config`` buttons.

Module: sevn.gateway.menu.menu_readiness
Depends: sevn.gateway.menu.menu_registry

Telegram inline buttons cannot be greyed out natively. Non-Ready buttons stay
visible with a prefix emoji and answer ``cfg:disabled:*`` with a short toast.

Exports:
    readiness_for_callback — resolve readiness for one ``callback_data`` string.
    gate_config_keyboard_rows — lock non-Ready buttons in a keyboard build.
    config_menu_help_catalog_text — long Help caption for ``/config`` Help tile.
    config_menu_level_help_text — help body for one ``/config`` screen level.
    config_section_catalog — ``/config`` section titles and blurbs for docs.
    readiness_user_label — map internal readiness tier to user-facing label.

Examples:
    >>> readiness_for_callback("cfg:section:session")
    'Ready'
    >>> readiness_for_callback("cfg:toggle:gateway.queue_mode:steer") in {"Ready", "WIP"}
    True
"""

from __future__ import annotations

import re
from typing import Any, Literal

from sevn.gateway.menu.menu_registry import (
    is_nav_chrome_callback,
    is_section_tile_callback,
    match_menu_button_spec,
)

_CHROME_CALLBACKS: frozenset[str] = frozenset(
    {
        "cfg:nav:back",
        "cfg:nav:help",
        "cfg:nav:home",
        "cfg:nav:close",
    },
)

MenuReadiness = Literal["Ready", "WIP", "Stub", "Not Started"]

DISABLED_CALLBACK_PREFIX = "cfg:disabled:"

_READINESS_PREFIX: dict[MenuReadiness, str] = {
    "Ready": "",
    "WIP": "🚧",
    "Stub": "📋",
    "Not Started": "🔒",
}

# Operator-approved pressable actions (edit this set to widen/narrow the live menu).
_READY_SPEC_IDS: frozenset[str] = frozenset(
    {
        # Root navigation + chrome
        "C0.1",
        "C0.2",
        "C0.3",
        "C0.4",
        "C0.5",
        "C0.6",
        "C0.7",
        "C0.8",
        "C0.10",
        "C0.11",
        "C0.14",
        "C0.15",
        "C0.16",
        "C0.17",
        "C0.18",
        "C0.19",
        "C0.20",
        "C0.21",
        "C0.22",
        "C0.23",
        "C*.1",
        "C*.2",
        "C*.3",
        "C*.4",
        "C21.1",
        "C21.2",
        "C21.3",
        # Session QA + queue
        "C1.1",
        "C1.2",
        "C1.3",
        "C1.4",
        "C1.5",
        "C1.6",
        # Voice (TTS mode + STT provider cycle — Wave W4)
        "C3.1",
        "C3.2",
        "C3.3",
        "C3.4",
        # Channels (routing footer + reply keyboard)
        "C5.1",
        "C5.2",
        # Security (owner LLM-guard kill-switches)
        "C11.3",
        "C11.4",
        "C11.5",
        # Logs section (Wave TE-9)
        "C20.1",
        "C20.2",
        "C20.3",
        "C20.4",
        "C20.5",
        "C20.6",
        "C20.7",
        "C20.8",
        "C20.9",
        # My sevn bot — service restarts (owner, 2-step)
        "C18.4",
        "C18.5",
        # CodeMode tier-B toggle (W8 operator surface)
        "C24.1",
        # Sub-agents (W7)
        "C25.1",
        "C25.2",
        "C25.3",
        "C25.4",
        "C25.5",
        "C25.6",
        "C25.7",
        "C25.8",
        # Social Media Manager (W3)
        "C7.4",
        "C7.5",
        "C7.6",
        "C7.7",
    },
)

_PICKER_PAGE_RE = re.compile(r"^cfg:models:page:[a-z_]+:\d+$")

_CONFIG_SECTION_CATALOG: tuple[tuple[str, str, str, MenuReadiness], ...] = (
    (
        "Session",
        "Quick-action bar on assistant replies (Regen, 👍/👎, Share, Feedback) and per-session queue mode (cancel vs steer).",
        "Toggle QA buttons on the next bot reply; queue mode changes how overlapping messages are handled.",
        "Ready",
    ),
    (
        "Agents",
        "Agent display name, persona files (IDENTITY.md, SOUL.md, USER.md), and Mission Control persona editor.",
        "Edit display name via form when wired; persona editing is dashboard-first when web_ui.url is set.",
        "WIP",
    ),
    (
        "Models",
        "Triager, Tier B, and Tier C/D model slots; unified-model toggle; swap last model.",
        "Paginated pickers and swap require catalog models; Mission Control Models tab when URL configured.",
        "WIP",
    ),
    (
        "Voice",
        "TTS mode (off / all / when asked) and STT provider cycle for Telegram and webchat.",
        "TTS and STT buttons are Ready; changes persist after reload.",
        "Ready",
    ),
    (
        "Channels",
        "Telegram reply keyboard (/new /menu /help), routing footer (intent·tier), DM policy, notify policy.",
        "Reply keyboard and show-routing toggles are Ready; DM policy cycle is WIP.",
        "WIP",
    ),
    (
        "Secrets",
        "Logical secret refs in sevn.json and add-secret wizard (owner-only).",
        "Wizard writes via secrets backend; list/remove deferred to dashboard.",
        "WIP",
    ),
    (
        "Skills",
        "Bundled and workspace skills; enable/disable when schema allows; refresh index.",
        "Per-skill toggles schema-gated; heavy editing in Mission Control Skills tab.",
        "WIP",
    ),
    (
        "Tools",
        "Native tools and plugin toggles; MCP server matrix (dashboard-first).",
        "Plugin toggles need schema + checkout; MCP not inlined in Telegram yet.",
        "WIP",
    ),
    (
        "RLM",
        "λ-RLM executor toggle, Tier C/D backend cycle, REPL lifetime display.",
        "Backend cycle only when λ-RLM on and allowlist non-empty.",
        "WIP",
    ),
    (
        "Code",
        "MYCODE and code-review-graph toggles; Mission Control Code tab.",
        "Toggles gate tool registration at runtime.",
        "WIP",
    ),
    (
        "Security",
        "Heuristic-only LLM scanner toggle; Mission Control Security tab.",
        "Scanner reloads on toggle.",
        "WIP",
    ),
    (
        "Self-Improve",
        "Self-improve enabled flag; jobs/traces in Mission Control.",
        "Run-improve-now not in menu (CLI/dashboard).",
        "WIP",
    ),
    (
        "Second Brain",
        "Second Brain enabled; ingest schedule caption; MC tab.",
        "Ingest schedule not a schema toggle path yet.",
        "WIP",
    ),
    (
        "Sub-agents",
        "Level-1/level-2 concurrency limits, global override, queue mode (incl. multi), live L1/L2 counts, Running kill submenu.",
        "Toggle, limit forms, queue cycle, and Running kill buttons are Ready when supervisor is wired; Mission Control panel when web_ui.url is set.",
        "Ready",
    ),
    (
        "Integrations",
        "Integration ids from workspace doc; add via Mission Control.",
        "Per-id Telegram toggles need schema paths.",
        "Stub",
    ),
    (
        "Dashboard",
        "Pinned status message: create/update pin, refresh, unpin, Mission Control link.",
        "Refresh requires an existing pin registry entry for this chat/topic.",
        "WIP",
    ),
    (
        "Shortcuts",
        "Custom slash shortcuts (add/delete) republished to setMyCommands.",
        "Add shortcut uses multi-step form; delete is owner/auth filtered.",
        "WIP",
    ),
    (
        "Notifications",
        "Telegram notify policy cycle (all / errors / none).",
        "Policy affects which gateway events push to Telegram.",
        "WIP",
    ),
    (
        "Advanced",
        "Auto-resume tier B, trace redaction, nested RLM / Self-Improve / Second Brain / CodeMode, Mission Control.",
        "RLM, Self-Improve, and Second Brain moved from root; gateway/proxy restart under My sevn bot.",
        "WIP",
    ),
    (
        "CodeMode",
        "Tier-B CodeMode (Monty run_code over triager-listed tools); default off.",
        "Writes agent.codemode.enabled; flat tool path when disabled.",
        "Ready",
    ),
    (
        "Logs",
        "Tail gateway/proxy logs, grep, traces, trace-redaction toggle.",
        "Owner-only diagnostics; deployment id is under My sevn bot.",
        "Ready",
    ),
    (
        "Slash help",
        "Slash command shortcuts (/new, /menu, /help, /status, …).",
        "Each button runs the matching slash handler in chat.",
        "Ready",
    ),
    (
        "sevn.bot",
        "Sync upstream checkout, list bug and feature evolution issues.",
        "Sync runs ``sevn sync --latest`` (git fetch + setup + optional gateway restart).",
        "Ready",
    ),
    (
        "My sevn bot",
        "Deployment id and owner gateway/proxy restart (two-step confirm).",
        "Restart uses service manager; deployment id mirrors /status.",
        "Ready",
    ),
)


def readiness_for_callback(callback_data: str) -> MenuReadiness:
    """Return operator readiness for one inline ``callback_data`` string.

    Args:
        callback_data (str): Raw Telegram callback payload.

    Returns:
        MenuReadiness: Pressability tier for the button.

    Examples:
        >>> readiness_for_callback("cfg:nav:home")
        'Ready'
        >>> readiness_for_callback("cfg:section:tools")
        'Ready'
    """
    raw = callback_data.strip()
    if is_nav_chrome_callback(raw) or is_section_tile_callback(raw):
        return "Ready"
    if _PICKER_PAGE_RE.match(raw):
        return "Ready"
    spec = match_menu_button_spec(raw)
    if spec is not None:
        if spec.spec_id in _READY_SPEC_IDS:
            return "Ready"
        if not spec.implemented:
            return "Not Started"
        return "WIP"
    if raw.startswith(DISABLED_CALLBACK_PREFIX):
        return "Not Started"
    return "WIP"


def _lock_button(btn: dict[str, Any], *, readiness: MenuReadiness, spec_id: str) -> dict[str, Any]:
    """Return a locked variant of one inline button dict.

    Args:
        btn (dict[str, Any]): Telegram inline button (text + callback_data or url).
        readiness (MenuReadiness): Non-Ready tier.
        spec_id (str): Registry id for the disabled callback payload.

    Returns:
        dict[str, Any]: Button dict with prefix and ``cfg:disabled:`` callback.

    Examples:
        >>> b = _lock_button({"text": "Foo", "callback_data": "x"}, readiness="WIP", spec_id="C9.1")
        >>> b["callback_data"].startswith("cfg:disabled:")
        True
    """
    if "url" in btn:
        prefix = _READINESS_PREFIX.get(readiness, "🔒")
        text = str(btn.get("text", ""))
        if prefix and not text.startswith(prefix):
            return {**btn, "text": f"{prefix} {text}"}
        return btn
    prefix = _READINESS_PREFIX.get(readiness, "🔒")
    text = str(btn.get("text", ""))
    if prefix and not text.startswith(("🔒", "🚧", "📋")):
        text = f"{prefix} {text}"
    return {
        "text": text,
        "callback_data": f"{DISABLED_CALLBACK_PREFIX}{spec_id}",
    }


def gate_config_keyboard_rows(rows: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    """Lock non-Ready callback buttons; leave URL and navigation callbacks unchanged.

    Args:
        rows (list[list[dict[str, Any]]]): Inline keyboard rows without chrome.

    Returns:
        list[list[dict[str, Any]]]: Gated rows.

    Examples:
        >>> gate_config_keyboard_rows([[{"text": "x", "callback_data": "cfg:nav:home"}]])
        [[{'text': 'x', 'callback_data': 'cfg:nav:home'}]]
    """
    out: list[list[dict[str, Any]]] = []
    for row in rows:
        gated: list[dict[str, Any]] = []
        for btn in row:
            cb = btn.get("callback_data")
            if not isinstance(cb, str):
                gated.append(btn)
                continue
            tier = readiness_for_callback(cb)
            if tier == "Ready":
                gated.append(btn)
                continue
            spec = match_menu_button_spec(cb)
            spec_id = spec.spec_id if spec is not None else "unknown"
            gated.append(_lock_button(btn, readiness=tier, spec_id=spec_id))
        if gated:
            out.append(gated)
    return out


def config_section_catalog() -> tuple[tuple[str, str, str, MenuReadiness], ...]:
    """Return ``/config`` section titles and blurbs for operator docs.

    Returns:
        tuple[tuple[str, str, str, MenuReadiness], ...]: ``(title, short, long, tier)`` rows.

    Examples:
        >>> titles = [row[0] for row in config_section_catalog()]
        >>> "Session" in titles and "Tools" in titles
        True
    """
    return _CONFIG_SECTION_CATALOG


_READINESS_USER_LABEL: dict[MenuReadiness, str] = {
    "Ready": "Available",
    "WIP": "Coming soon",
    "Stub": "Coming soon",
    "Not Started": "Not yet available",
}


def readiness_user_label(tier: MenuReadiness) -> str:
    """Map internal readiness tier to user-facing label.

    Args:
        tier (MenuReadiness): Registry readiness value.

    Returns:
        str: Plain-language availability label.

    Examples:
        >>> readiness_user_label("Ready")
        'Available'
        >>> readiness_user_label("WIP")
        'Coming soon'
    """
    return _READINESS_USER_LABEL[tier]


def _button_help_line(btn: dict[str, Any]) -> str | None:
    """Format one inline button as a help catalog line.

    Args:
        btn (dict[str, Any]): Telegram inline button dict.

    Returns:
        str | None: Help line, or ``None`` when the button is omitted.

    Examples:
        >>> _button_help_line({"text": "Foo", "callback_data": "cfg:nav:home"}) is None
        True
        >>> "Regen" in (_button_help_line({"text": "Regen", "callback_data": "cfg:toggle:x:y"}) or "")
        True
    """
    cb = btn.get("callback_data")
    if isinstance(cb, str) and cb.strip() in _CHROME_CALLBACKS:
        return None
    if "url" in btn:
        label = str(btn.get("text", "Open link")).strip()
        return f"▸ {label}\nOpens Mission Control or an external URL."
    if not isinstance(cb, str) or not cb.strip():
        return None
    spec = match_menu_button_spec(cb.strip())
    tier = readiness_for_callback(cb.strip())
    label = str(btn.get("text", spec.label if spec else cb)).strip()
    for prefix in ("🚧 ", "🔒 ", "📋 "):
        if label.startswith(prefix):
            label = label.removeprefix(prefix)
    detail = (spec.notes if spec and spec.notes else spec.label if spec else "").strip()
    if not detail:
        detail = "Tap to act on this screen."
    return f"▸ {label} [{tier}]\n{detail}"


def config_menu_level_help_text(
    section: str,
    *,
    markup: dict[str, Any] | None = None,
    is_owner: bool = True,
) -> str:
    """Build help text listing every action on one ``/config`` screen.

    Args:
        section (str): Active ``ConfigSection`` id.
        markup (dict[str, Any] | None): Keyboard markup from ``build_config_menu_keyboard``.
        is_owner (bool): Whether the operator is workspace owner (filters owner-only rows).

    Returns:
        str: Plain-text help suitable for a new Telegram message.

    Examples:
        >>> config_menu_level_help_text("root").startswith("Help — /config root")
        True
        >>> "Navigation" in config_menu_level_help_text(
        ...     "sevn_bot",
        ...     markup={"inline_keyboard": [[{"text": "Sync", "callback_data": "act:sevn_bot:sync"}]]},
        ... )
        True
    """
    title = section.replace("_", " ").strip() or "root"
    if section == "root":
        title = "/config root"
    elif section == "sevn_bot":
        title = "sevn.bot"
    elif section == "my_sevn_bot":
        title = "My sevn bot"
    lines = [f"Help — {title}", ""]
    body_rows: list[list[dict[str, Any]]] = []
    if isinstance(markup, dict):
        raw_rows = markup.get("inline_keyboard")
        if isinstance(raw_rows, list) and len(raw_rows) >= 1:
            body_rows = raw_rows[:-1]
    if section == "root" and not body_rows:
        from sevn.gateway.menu.menu import _CONFIG_ROOT_TILES

        catalog_by_title = {row[0]: row for row in _CONFIG_SECTION_CATALOG}
        section_titles = {
            "session": "Session",
            "agents": "Agents",
            "models": "Models",
            "voice": "Voice",
            "channels": "Channels",
            "secrets": "Secrets",
            "skills": "Skills",
            "tools": "Tools",
            "rlm": "RLM",
            "code": "Code",
            "security": "Security",
            "self_improve": "Self-Improve",
            "second_brain": "Second Brain",
            "integrations": "Integrations",
            "dashboard": "Dashboard",
            "shortcuts": "Shortcuts",
            "notifications": "Notifications",
            "advanced": "Advanced",
            "codemode": "CodeMode",
            "logs": "Logs",
            "help": "Slash help",
            "sevn_bot": "sevn.bot",
            "my_sevn_bot": "My sevn bot",
        }
        for label, sid, _cb in _CONFIG_ROOT_TILES:
            cat = catalog_by_title.get(section_titles.get(sid, ""))
            lines.append(f"▸ {label} [Ready]")
            if cat is not None:
                _title, short, long_desc, tier = cat
                lines.append(short)
                lines.append(long_desc)
                lines.append(f"Tier: {tier}")
            else:
                lines.append("Opens this section.")
            lines.append("")
    else:
        for row in body_rows:
            for btn in row:
                if not isinstance(btn, dict):
                    continue
                cb = btn.get("callback_data")
                if (
                    not is_owner
                    and isinstance(cb, str)
                    and cb.startswith(("act:gateway:", "act:proxy:"))
                ):
                    continue
                line = _button_help_line(btn)
                if line:
                    lines.append(line)
                    lines.append("")
    if section == "help":
        lines.append("Slash shortcuts also available via the buttons on this screen.")
    lines.append("Navigation: ⬅ Back · ❓ Help · 🏠 Home · ❌ Close")
    return "\n".join(lines).strip()


def config_menu_help_catalog_text() -> str:
    """Build the long Help caption listing every ``/config`` root tile.

    Returns:
        str: Telegram HTML-safe plain text (no markup) for the Help section.

    Examples:
        >>> "Session" in config_menu_help_catalog_text()
        True
        >>> "Tools" in config_menu_help_catalog_text()
        True
    """
    lines = [
        "Help — /config menu catalog",
        "",
        "Tap a root tile to open that section. Buttons marked 🚧/🔒 in a section are visible but not active until marked Ready.",
        "",
    ]
    for title, short, long_desc, tier in _CONFIG_SECTION_CATALOG:
        lines.append(f"▸ {title} [{tier}]")
        lines.append(short)
        lines.append(long_desc)
        lines.append("")
    lines.append(
        "Slash shortcuts: /new /menu /help /config /status /stop /voice /model — type in chat."
    )
    return "\n".join(lines).strip()


__all__ = [
    "config_menu_help_catalog_text",
    "config_menu_level_help_text",
    "config_section_catalog",
    "gate_config_keyboard_rows",
    "readiness_for_callback",
    "readiness_user_label",
]
