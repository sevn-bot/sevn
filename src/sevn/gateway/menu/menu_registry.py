"""Declarative Telegram control-surface button inventory (`plan/telegram-menu-full-wiring-wave-plan.md`).

Module: sevn.gateway.menu.menu_registry
Depends: dataclasses, re

Exports:
    MenuButtonSpec — one registered button or slash command row.
    match_menu_button_spec — resolve ``callback_data`` to a spec.
    is_nav_chrome_callback — Back/Home/Close chrome exempt from implemented gate.
    is_section_tile_callback — section navigation tiles exempt from implemented gate.
    registry_implementation_counts — implemented vs not-implemented totals.

Examples:
    >>> spec = match_menu_button_spec("cfg:section:session")
    >>> spec is not None and spec.spec_id == "C0.1"
    True
    >>> counts = registry_implementation_counts()
    >>> counts["total"] >= 90
    True
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

MenuSurface = Literal["A", "B", "C", "D", "E", "F"]

_NAV_CHROME_CALLBACKS: frozenset[str] = frozenset(
    {
        "nav:back",
        "menu:home",
        "menu:close",
        "cfg:nav:back",
        "cfg:nav:help",
        "cfg:nav:home",
        "cfg:nav:close",
    },
)

_SECTION_TILE_PREFIXES: tuple[str, ...] = ("cfg:section:", "menu:section:")


def _toggle(path: str) -> str:
    """Return a regex matching ``cfg:toggle:<path>:true|false``.

    Args:
        path (str): Dot path under ``sevn.json``.

    Returns:
        str: Anchored regex pattern.

    Examples:
        >>> _toggle("gateway.queue_mode").endswith(":.+$")
        True
    """
    escaped = re.escape(path)
    return rf"^cfg:toggle:{escaped}:.+$"


def _exact(callback: str) -> str:
    """Anchor an exact ``callback_data`` string as a regex.

    Args:
        callback (str): Literal callback payload.

    Returns:
        str: Anchored regex pattern.

    Examples:
        >>> _exact("menu:open_config") == "^menu:open_config$"
        True
    """
    return f"^{re.escape(callback)}$"


@dataclass(frozen=True)
class MenuButtonSpec:
    """One Telegram control-surface button or slash command from the TMF inventory."""

    spec_id: str
    callback_pattern: str
    surface: MenuSurface
    section: str
    label: str
    implemented: bool
    owner_only: bool = False
    requires_web_ui: bool = False
    notes: str | None = None


def _build_menu_button_specs() -> tuple[MenuButtonSpec, ...]:
    """Construct the full TMF surfaces A-F button inventory.

    Returns:
        tuple[MenuButtonSpec, ...]: Frozen registry rows.

    Examples:
        >>> len(_build_menu_button_specs()) >= 90
        True
    """
    specs: list[MenuButtonSpec] = []

    def add(
        spec_id: str,
        pattern: str,
        surface: MenuSurface,
        section: str,
        label: str,
        *,
        implemented: bool,
        owner_only: bool = False,
        requires_web_ui: bool = False,
        notes: str | None = None,
    ) -> None:
        specs.append(
            MenuButtonSpec(
                spec_id=spec_id,
                callback_pattern=pattern,
                surface=surface,
                section=section,
                label=label,
                implemented=implemented,
                owner_only=owner_only,
                requires_web_ui=requires_web_ui,
                notes=notes,
            ),
        )

    # --- A. Persistent reply keyboard (text → slash handlers) ---
    for sid, label in (
        ("A1", "/new"),
        ("A2", "/menu"),
        ("A3", "/help"),
    ):
        add(sid, _exact(label), "A", "reply_keyboard", label, implemented=True)

    # --- B. Registered slash commands (no callback_data) ---
    slash_rows: tuple[tuple[str, str, bool, str | None], ...] = (
        ("B1", "/start", True, None),
        ("B2", "/help", True, None),
        ("B3", "/new", True, None),
        ("B4", "/status", True, "Add to Help + Diagnostics in TMF Wave 2"),
        ("B5", "/stop", True, "Wire pin menu:cmd:stop in TMF Wave 2"),
        ("B6", "/config", True, None),
        ("B7", "/voice", True, "PARTIAL; menu execute in TMF Wave 2"),
        ("B8", "/model", True, "PARTIAL; menu execute in TMF Wave 2"),
        ("B9", "/shortcut", False, "User shortcuts; form wizard TMF Wave 3"),
        ("B10", "/logs", True, "Tail gateway/proxy logs; owner-only (TE-3)"),
        ("B11", "/traces", True, "Recent traces / span lookup; owner-only (TE-3)"),
    )
    for spec_id, cmd, implemented, notes in slash_rows:
        add(
            spec_id,
            _exact(cmd),
            "B",
            "setMyCommands",
            cmd,
            implemented=implemented,
            notes=notes,
        )

    # --- C0. /config root tiles + chrome ---
    # NOTE: C0.19 is the **Logs** tile per `specs/18-channel-telegram.md` §4.7
    # (TE-4). Help moved to C0.20 and Close to C0.21 to keep numbering monotonic.
    # C0.19 and C20.* flipped Ready in Wave TE-9 (`menu_readiness._READY_SPEC_IDS`).
    config_root: tuple[tuple[str, str, str], ...] = (
        ("C0.1", "Session", "session"),
        ("C0.2", "Agents", "agents"),
        ("C0.3", "Models", "models"),
        ("C0.4", "Voice", "voice"),
        ("C0.5", "Channels", "channels"),
        ("C0.6", "Secrets", "secrets"),
        ("C0.7", "Skills", "skills"),
        ("C0.8", "Tools", "tools"),
        ("C0.10", "Code", "code"),
        ("C0.11", "Security", "security"),
        ("C0.14", "Integrations", "integrations"),
        ("C0.15", "Dashboard", "dashboard"),
        ("C0.16", "Shortcuts", "shortcuts"),
        ("C0.17", "Notifications", "notifications"),
        ("C0.18", "Advanced", "advanced"),
        ("C0.19", "Logs", "logs"),
        ("C0.20", "Slash help", "help"),
        ("C0.22", "sevn.bot", "sevn_bot"),
        ("C0.23", "My sevn bot", "my_sevn_bot"),
    )
    for spec_id, label, sid in config_root:
        add(
            spec_id,
            _exact(f"cfg:section:{sid}"),
            "C",
            "root",
            label,
            implemented=True,
        )
    add("C0.21", _exact("cfg:nav:close"), "C", "root", "Close", implemented=True)
    for spec_id, label, cb in (
        ("C*.1", "Back", "cfg:nav:back"),
        ("C*.2", "Help", "cfg:nav:help"),
        ("C*.3", "Home", "cfg:nav:home"),
        ("C*.4", "Close", "cfg:nav:close"),
    ):
        add(
            spec_id,
            _exact(cb),
            "C",
            "chrome",
            label,
            implemented=True,
            notes="Back stack TMF Wave 10",
        )

    # --- C1. Session ---
    for spec_id, label, path in (
        ("C1.1", "Regen", "channels.telegram.quick_actions.show_regen"),
        ("C1.2", "Up", "channels.telegram.quick_actions.show_thumbs_up"),
        ("C1.3", "Down", "channels.telegram.quick_actions.show_thumbs_down"),
        ("C1.4", "Share", "channels.telegram.quick_actions.show_share"),
        ("C1.5", "Feedback", "channels.telegram.quick_actions.show_feedback"),
    ):
        add(
            spec_id,
            _toggle(path),
            "C",
            "session",
            label,
            implemented=True,
            notes="QA bar gating proven TMF Wave 1",
        )
    add(
        "C1.6",
        _toggle("gateway.queue_mode"),
        "C",
        "session",
        "Queue cancel↔steer↔multi",
        implemented=True,
        notes="JSON; cycles cancel/steer/multi (W4/W7)",
    )

    # --- C2. Help ---
    for spec_id, cmd in (
        ("C2.1", "help"),
        ("C2.2", "menu"),
        ("C2.3", "new"),
        ("C2.4", "voice"),
        ("C2.5", "model"),
        ("C2.6", "status"),
        ("C2.7", "stop"),
    ):
        add(
            spec_id,
            _exact(f"cfg:help:cmd:{cmd}"),
            "C",
            "help",
            f"/{cmd}",
            implemented=True,
            notes="Command invoke TMF Wave 2",
        )
    add(
        "C2.8",
        _exact("cfg:help:cmd:config"),
        "C",
        "help",
        "/config",
        implemented=False,
        notes="Optional; redundant with /config root",
    )

    # --- C3. Voice ---
    for spec_id, mode in (("C3.1", "off"), ("C3.2", "all")):
        add(
            spec_id,
            _exact(f"cfg:voice:mode:{mode}"),
            "C",
            "voice",
            f"TTS: {mode}",
            implemented=True,
            notes="TTS runtime verified TMF Wave 7",
        )
    add(
        "C3.3",
        _exact("cfg:voice:mode:when_asked"),
        "C",
        "voice",
        "TTS: when_asked",
        implemented=True,
        notes="TTS runtime verified TMF Wave 7",
    )
    add(
        "C3.4",
        r"^cfg:voice:stt:.*$",
        "C",
        "voice",
        "STT provider cycle",
        implemented=True,
        notes="Cycles voice.stt_providers primary; wired TMF Wave W4",
    )

    # --- C4. Models ---
    add(
        "C4.1",
        _toggle("providers.use_main_model_for_all"),
        "C",
        "models",
        "Unified model",
        implemented=True,
        notes="OK; verified slot resolution TMF Wave 5",
    )
    add(
        "C4.2",
        r"^cfg:models:page:triager:\d+$",
        "C",
        "models",
        "Triager picker",
        implemented=True,
    )
    add(
        "C4.3",
        r"^cfg:models:page:tier_b:\d+$",
        "C",
        "models",
        "Tier B picker",
        implemented=True,
    )
    add(
        "C4.4",
        r"^cfg:models:page:tier_cd:\d+$",
        "C",
        "models",
        "Tier C/D picker",
        implemented=True,
    )
    add(
        "C4.5",
        _exact("cfg:models:swap"),
        "C",
        "models",
        "Swap last model",
        implemented=True,
    )
    add(
        "C4.5-pick",
        r"^cfg:models:pick:.*$",
        "C",
        "models",
        "Model pick selection",
        implemented=True,
        notes="Paginated picker row callback",
    )
    add(
        "C4.6",
        r"^https?://.*#models$",
        "C",
        "models",
        "Open Models tab",
        implemented=True,
        requires_web_ui=True,
    )

    # --- C5. Channels ---
    add(
        "C5.1",
        _toggle("channels.telegram.reply_keyboard.enabled"),
        "C",
        "channels",
        "Reply keyboard",
        implemented=True,
        notes="Reply keyboard runtime verified TMF Wave 7",
    )
    add(
        "C5.2",
        _toggle("channels.telegram.show_routing"),
        "C",
        "channels",
        "Show routing",
        implemented=True,
        notes="Routing footer gating proven TMF Wave 1",
    )
    add(
        "C5.3",
        _toggle("channels.telegram.dm_policy"),
        "C",
        "channels",
        "DM policy cycle",
        implemented=True,
        notes="open→pairing→allowlist→disabled TMF Wave 7",
    )
    add(
        "C5.4",
        r"^caption:channels:telegram_mode$",
        "C",
        "channels",
        "Telegram mode",
        implemented=True,
        notes="Read-only caption (poll/webhook) TMF Wave 7",
    )
    add(
        "C5.5",
        _toggle("channels.webchat.tts_inline"),
        "C",
        "channels",
        "Webchat TTS inline",
        implemented=False,
        notes="OMIT button; caption-only (schema path absent) TMF Wave 7",
    )

    # --- C6. Secrets ---
    add(
        "C6.1",
        _exact("form:secret_wizard"),
        "C",
        "secrets",
        "+ Add secret",
        implemented=True,
        owner_only=True,
        notes="form wizard; TMF Wave 3",
    )
    add(
        "C6.1b",
        r"^form:secret_wizard:[a-zA-Z0-9._-]+$",
        "C",
        "skills:social_media_manager",
        "Set TwexAPI key (scoped wizard)",
        implemented=True,
        owner_only=True,
        notes="SMM TwexAPI key wizard with preset alias",
    )
    add(
        "C6.2",
        r"^caption:secrets:refs$",
        "C",
        "secrets",
        "List refs",
        implemented=True,
        notes="caption lists ref key names; TMF Wave 3",
    )
    add(
        "C6.3", r"^act:secret:.*$", "C", "secrets", "Remove ref", implemented=False, notes="MISSING"
    )

    # --- C7. Skills ---
    add(
        "C7.1",
        r"^https?://.*#skills$",
        "C",
        "skills",
        "Open Skills tab",
        implemented=True,
        requires_web_ui=True,
        notes="URL; OMIT when no web_ui.url",
    )
    add(
        "C7.2",
        r"^cfg:toggle:skills\.[^.]+\.enabled:(?:true|false)$",
        "C",
        "skills",
        "Enable/disable skill",
        implemented=True,
        notes="Top-N toggles when skills schema allows child enabled",
    )
    add(
        "C7.3",
        _exact("cfg:skills:refresh"),
        "C",
        "skills",
        "Refresh skill index",
        implemented=True,
        notes="Caption refresh; TMF Wave 8",
    )
    add(
        "C7.4",
        _exact("cfg:section:skills:social_media_manager"),
        "C",
        "skills",
        "Social Media Manager submenu",
        implemented=True,
        notes="Per-platform medium cycles; schema-gated when skills.social_media_manager declared",
    )
    add(
        "C7.5",
        r"^cfg:cycle:skills\.social_media_manager\.(?:default_medium|platforms\.[^.]+\.medium):(?:browser|twexapi)$",
        "C",
        "skills:social_media_manager",
        "Platform/default medium cycle",
        implemented=True,
        notes="TwexAPI only on X; browser universal (D3/D4)",
    )
    add(
        "C7.6",
        _toggle("skills.social_media_manager.twexapi.enabled"),
        "C",
        "skills:social_media_manager",
        "TwexAPI enabled toggle",
        implemented=True,
        notes="D13 default false until operator enables",
    )
    add(
        "C7.7",
        _exact("form:secret_wizard"),
        "C",
        "skills:social_media_manager",
        "Set TwexAPI key",
        implemented=True,
        notes="Secret wizard; store SEVN_SECRET_TWEXAPI",
    )

    # --- C8. Tools ---
    add(
        "C8.1",
        r"^https?://.*#tools$",
        "C",
        "tools",
        "Open Tools tab",
        implemented=True,
        requires_web_ui=True,
        notes="URL; OMIT when no web_ui.url",
    )
    add(
        "C8.2",
        r"^cfg:toggle:tools\.[^.]+\.enabled:(?:true|false)$",
        "C",
        "tools",
        "Enable plugin tool",
        implemented=True,
        notes="Top-N plugin toggles when tools schema allows child enabled",
    )
    add(
        "C8.3",
        r"^https?://.*#tools$",
        "C",
        "tools",
        "MCP servers (dashboard)",
        implemented=True,
        requires_web_ui=True,
        notes="MCP link via Tools tab URL; OMIT when no web_ui.url",
    )

    # --- C9. RLM ---
    add(
        "C9.1",
        _toggle("executors.tier_cd.lambda_rlm.enabled"),
        "C",
        "rlm",
        "λ-RLM enabled",
        implemented=True,
        notes="Reloads executor λ gate; schema-gated render",
    )
    add(
        "C9.2",
        _toggle("rlm.c_d_backend"),
        "C",
        "rlm",
        "Tier C/D backend cycle",
        implemented=True,
        notes="Cycle when λ-RLM on + allowlist non-empty; else caption-only",
    )
    add(
        "C9.3",
        r"^cfg:section:rlm$",
        "C",
        "rlm",
        "REPL lifetime display",
        implemented=True,
        notes="Caption-only in config_menu_message_text",
    )
    add(
        "C9.4",
        r"^https?://.*#rlm$",
        "C",
        "rlm",
        "Open RLM tab",
        implemented=True,
        requires_web_ui=True,
        notes="OMIT when no web_ui.url",
    )

    # --- C10. Code ---
    add(
        "C10.1",
        _toggle("code_understanding.mycode.enabled"),
        "C",
        "code",
        "MYCODE",
        implemented=True,
        notes="Runtime via code_understanding.mycode.enabled reload",
    )
    add(
        "C10.2",
        _toggle("code_understanding.code_review_graph.enabled"),
        "C",
        "code",
        "Review graph",
        implemented=True,
        notes="Runtime via code_review_graph_mcp_enabled reload",
    )
    add(
        "C10.3",
        r"^https?://.*#code$",
        "C",
        "code",
        "Open Code tab",
        implemented=True,
        requires_web_ui=True,
        notes="OMIT when no web_ui.url",
    )

    # --- C11. Security ---
    add(
        "C11.1",
        _toggle("security.scanner.heuristic_only"),
        "C",
        "security",
        "Heuristic-only",
        implemented=True,
        notes="Reloads LLMGuardScanner on toggle (TMF-9)",
    )
    add(
        "C11.2",
        r"^https?://.*#security$",
        "C",
        "security",
        "Open Security tab",
        implemented=True,
        requires_web_ui=True,
        notes="OMIT when no web_ui.url; scanner reload on heuristic toggle",
    )
    add(
        "C11.3",
        _toggle("channels.telegram.owner_scanner_overrides.disable_text"),
        "C",
        "security",
        "Skip guard on my text",
        implemented=True,
        notes="Owner-actor text scans bypassed when on; reloads scanner",
    )
    add(
        "C11.4",
        _toggle("channels.telegram.owner_scanner_overrides.disable_links"),
        "C",
        "security",
        "Skip guard on my links",
        implemented=True,
        notes="Owner-actor link scans bypassed when on; mixed-kind only skipped when every kind is disabled",
    )
    add(
        "C11.5",
        _toggle("channels.telegram.owner_scanner_overrides.disable_documents"),
        "C",
        "security",
        "Skip guard on my documents",
        implemented=True,
        notes="Owner-actor attachment scans bypassed when on",
    )

    # --- C12. Self-Improve ---
    add(
        "C12.1",
        _toggle("self_improve.enabled"),
        "C",
        "self_improve",
        "Self-improve enabled",
        implemented=True,
        notes="JSON",
    )
    add(
        "C12.2",
        r"^https?://.*#traces$",
        "C",
        "self_improve",
        "View jobs / Traces",
        implemented=True,
        requires_web_ui=True,
        notes="OMIT when no web_ui.url",
    )
    add(
        "C12.3",
        r"^act:self_improve:run$",
        "C",
        "self_improve",
        "Run improve now",
        implemented=False,
        notes="Defer — CLI/dashboard only",
    )

    # --- C13. Second Brain ---
    add(
        "C13.1",
        _toggle("second_brain.enabled"),
        "C",
        "second_brain",
        "Second Brain enabled",
        implemented=True,
        notes="JSON",
    )
    add(
        "C13.2",
        r"^cfg:section:second_brain$",
        "C",
        "second_brain",
        "Ingest schedule",
        implemented=True,
        notes="Caption-only; ingest_batch_cron not in schema properties",
    )
    add(
        "C13.3",
        r"^https?://.*#second_brain$",
        "C",
        "second_brain",
        "Open Second Brain tab",
        implemented=True,
        requires_web_ui=True,
        notes="OMIT when no web_ui.url",
    )

    add(
        "C13.4",
        r"^form:second_brain_vault_path$",
        "C",
        "second_brain",
        "Set vault path",
        implemented=True,
        notes="Owner text-reply wizard",
    )
    add(
        "C13.5",
        r"^form:second_brain_vault_browse$",
        "C",
        "second_brain",
        "Browse folders",
        implemented=True,
        notes="Owner folder browser wizard",
    )

    # --- C25. Sub-agents (Advanced nested) ---
    add(
        "C25.1",
        _toggle("subagents.enabled"),
        "C",
        "subagents",
        "Sub-agents enabled",
        implemented=True,
        notes="JSON; W7 operator surface",
    )
    add(
        "C25.2",
        _exact("cfg:section:subagents_running"),
        "C",
        "subagents",
        "Running L1/L2 counts",
        implemented=True,
        notes="Live registry snapshot + Running submenu",
    )
    add(
        "C25.3",
        r"^form:subagents_max_override$",
        "C",
        "subagents",
        "Global override",
        implemented=True,
        notes="Numeric form wizard",
    )
    add(
        "C25.4",
        r"^form:subagents_limits:(triager|tier_b|tier_c|tier_d)$",
        "C",
        "subagents",
        "Per-role limits",
        implemented=True,
        notes="Two-step L1/L2 numeric wizard",
    )
    add(
        "C25.5",
        r"^act:subagents:kill:[a-z0-9]+$",
        "C",
        "subagents_running",
        "Kill sub-agent",
        implemented=True,
        owner_only=True,
        notes="Owner-only cooperative kill via supervisor (D13)",
    )
    add(
        "C25.6",
        _exact("act:subagents:kill_all"),
        "C",
        "subagents_running",
        "Kill all L1",
        implemented=True,
        owner_only=True,
        notes="Owner-only kill-all (D13)",
    )
    add(
        "C25.7",
        r"^https?://.*#subagents$",
        "C",
        "subagents",
        "Open Sub-agents panel",
        implemented=True,
        requires_web_ui=True,
        notes="OMIT when no web_ui.url",
    )
    add(
        "C25.8",
        _exact("cfg:section:subagents"),
        "C",
        "advanced",
        "Open Sub-agents",
        implemented=True,
        notes="Nested section under Advanced (W7)",
    )

    # --- C14. Integrations ---
    add(
        "C14.1",
        r"^https?://.*#integrations$",
        "C",
        "integrations",
        "+ Add integration",
        implemented=True,
        requires_web_ui=True,
        notes="URL; OMIT when no web_ui.url",
    )
    add(
        "C14.2",
        r"^cfg:toggle:integration\.[^.]+\.enabled:(?:true|false)$",
        "C",
        "integrations",
        "Toggle integration",
        implemented=True,
        notes="Rendered only when integration.<id>.enabled is schema-declared",
    )
    add(
        "C14.3",
        _exact("cfg:integrations:refresh"),
        "C",
        "integrations",
        "Refresh list",
        implemented=True,
        notes="Refresh integration id caption; TMF Wave 8",
    )

    # --- C15. Dashboard ---
    add(
        "C15.1",
        _exact("cfg:dashboard:refresh_pin"),
        "C",
        "dashboard",
        "Refresh pin",
        implemented=True,
        notes="Requires pin in _telegram_dashboard_pins; TMF Wave 4",
    )
    add(
        "C15.2",
        r"^https?://",
        "C",
        "dashboard",
        "Open Mission Control",
        implemented=True,
        requires_web_ui=True,
        notes="URL when web_ui.url set",
    )
    add(
        "C15.3",
        _exact("cfg:dashboard:create_pin"),
        "C",
        "dashboard",
        "Create/update pin",
        implemented=True,
        notes="Pin lifecycle TMF Wave 4",
    )
    add(
        "C15.4",
        _exact("cfg:dashboard:unpin"),
        "C",
        "dashboard",
        "Unpin",
        implemented=True,
        notes="Optional unpin; TMF Wave 4",
    )

    # --- C16. Shortcuts ---
    add(
        "C16.1",
        r"^act:shortcut_delete:[^:]+$",
        "C",
        "shortcuts",
        "Delete shortcut",
        implemented=True,
        notes="content_root + is_owner on nav refresh; TMF Wave 1",
    )
    add(
        "C16.2",
        _exact("form:shortcut_add"),
        "C",
        "shortcuts",
        "+ Add shortcut",
        implemented=True,
        notes="form wizard; TMF Wave 3",
    )
    for spec_id, label in (("C16.3", "Edit shortcut"), ("C16.4", "Run shortcut")):
        add(spec_id, r"^short:run:.*$", "C", "shortcuts", label, implemented=False, notes="MISSING")

    # --- C17. Notifications ---
    add(
        "C17.1",
        _toggle("channels.telegram.telegram_notify_policy"),
        "C",
        "notifications",
        "Notify policy cycle",
        implemented=True,
        notes="Notify policy cycle verified TMF Wave 7",
    )

    # --- C18. Advanced ---
    add(
        "C18.1",
        _toggle("gateway.restart.auto_resume_b"),
        "C",
        "advanced",
        "Auto-resume tier B",
        implemented=True,
        notes="JSON",
    )
    add(
        "C18.2",
        _toggle("tracing.redaction.enabled"),
        "C",
        "advanced",
        "Trace redaction",
        implemented=True,
        notes="JSON",
    )
    add(
        "C18.3",
        r"^https?://",
        "C",
        "advanced",
        "Open Mission Control",
        implemented=True,
        requires_web_ui=True,
        notes="URL when web_ui.url set",
    )
    add(
        "C18.4",
        r"^act:gateway:restart(:confirm|:cancel)?$",
        "C",
        "my_sevn_bot",
        "Restart gateway",
        implemented=True,
        owner_only=True,
        notes="2-step confirm; TMF Wave 6",
    )
    add(
        "C18.5",
        r"^act:proxy:restart(:confirm|:cancel)?$",
        "C",
        "my_sevn_bot",
        "Restart proxy",
        implemented=True,
        owner_only=True,
        notes="2-step confirm; TMF Wave 6",
    )
    add(
        "C18.6",
        r"^https?://.*#config$",
        "C",
        "advanced",
        "Validate config",
        implemented=False,
        requires_web_ui=True,
        notes="MISSING",
    )
    add(
        "C18.7",
        _exact("cfg:section:rlm"),
        "C",
        "advanced",
        "Open RLM",
        implemented=True,
        notes="Nested section; moved from root C0.9",
    )
    add(
        "C18.8",
        _exact("cfg:section:self_improve"),
        "C",
        "advanced",
        "Open Self-Improve",
        implemented=True,
        notes="Nested section; moved from root C0.12",
    )
    add(
        "C18.9",
        _exact("cfg:section:second_brain"),
        "C",
        "advanced",
        "Open Second Brain",
        implemented=True,
        notes="Nested section; moved from root C0.13",
    )
    add(
        "C18.10",
        _exact("cfg:section:codemode"),
        "C",
        "advanced",
        "Open CodeMode",
        implemented=True,
        notes="Nested CodeMode submenu (W8 operator toggle)",
    )

    # --- C24. CodeMode (Advanced nested) ---
    add(
        "C24.1",
        _toggle("agent.codemode.enabled"),
        "C",
        "codemode",
        "CodeMode enabled",
        implemented=True,
        notes="W8 tier-B Monty run_code; default off",
    )

    # --- C20. Logs (TE-4; 🚧 until TE-9) ---
    add(
        "C20.1",
        r"^cfg:logs:tail:gateway:\d+$",
        "C",
        "logs",
        "Tail gateway",
        implemented=True,
        owner_only=True,
    )
    add(
        "C20.2",
        r"^cfg:logs:tail:proxy:\d+$",
        "C",
        "logs",
        "Tail proxy",
        implemented=True,
        owner_only=True,
    )
    add(
        "C20.3",
        _exact("form:logs:grep"),
        "C",
        "logs",
        "Grep logs (form)",
        implemented=True,
        owner_only=True,
    )
    add(
        "C20.4",
        r"^cfg:logs:traces:\d+$",
        "C",
        "logs",
        "Recent traces",
        implemented=True,
        owner_only=True,
    )
    add(
        "C20.5",
        _exact("form:logs:span_id"),
        "C",
        "logs",
        "Trace by id (form)",
        implemented=True,
        owner_only=True,
    )
    add(
        "C20.6",
        _exact("cfg:logs:toggle_redaction"),
        "C",
        "logs",
        "Toggle redaction",
        implemented=True,
        owner_only=True,
    )
    add(
        "C20.8",
        _exact("cfg:logs:toggle_logfire"),
        "C",
        "logs",
        "Toggle Logfire export",
        implemented=True,
        owner_only=True,
    )
    add(
        "C20.9",
        _exact("form:logs:logfire_token"),
        "C",
        "logs",
        "Set Logfire token (form)",
        implemented=True,
        owner_only=True,
    )
    add(
        "C20.7",
        _exact("cfg:logs:deployment_id"),
        "C",
        "my_sevn_bot",
        "Deployment id",
        implemented=True,
        notes="Shows gateway deployment id in chat",
    )

    # --- C21. sevn.bot ---
    add(
        "C21.1",
        _exact("act:sevn_bot:sync"),
        "C",
        "sevn_bot",
        "Sync (latest)",
        implemented=True,
        owner_only=True,
        notes="Runs sevn sync --latest on resolved checkout",
    )
    add(
        "C21.2",
        _exact("act:sevn_bot:bugs"),
        "C",
        "sevn_bot",
        "Bugs",
        implemented=True,
        notes="Lists recent bug evolution issues",
    )
    add(
        "C21.3",
        _exact("act:sevn_bot:features"),
        "C",
        "sevn_bot",
        "Features",
        implemented=True,
        notes="Lists recent feature evolution issues",
    )

    # --- C19. Agents ---
    add(
        "C19.1",
        r"^https?://",
        "C",
        "agents",
        "Edit persona",
        implemented=True,
        requires_web_ui=True,
        notes="URL when web_ui.url set; no Advanced fallback (TMF Wave 8)",
    )
    add(
        "C19.2",
        _exact("form:agent:display_name"),
        "C",
        "agents",
        "Edit display name",
        implemented=True,
        notes="Form wizard → agent.display_name; TMF Wave 8",
    )
    add(
        "C19.3",
        r"^https?://.*#identity$",
        "C",
        "agents",
        "Open IDENTITY.md",
        implemented=True,
        requires_web_ui=True,
        notes="Dashboard identity deep-link; OMIT when no web_ui.url",
    )

    # --- D. /menu recovery tree ---
    for spec_id, label, sid in (
        ("D0.1", "Identity/About", "identity"),
        ("D0.2", "Quick actions", "quick"),
        ("D0.3", "Workspace", "workspace"),
        ("D0.4", "Diagnostics", "diagnostics"),
    ):
        add(
            spec_id,
            _exact(f"menu:section:{sid}"),
            "D",
            "root",
            label,
            implemented=True,
        )
    add("D0.5", _exact("menu:open_config"), "D", "root", "Open /config", implemented=True)
    for spec_id, label, cb in (
        ("D0.6", "Back", "nav:back"),
        ("D0.7", "Home", "menu:home"),
        ("D0.8", "Close", "menu:close"),
    ):
        add(spec_id, _exact(cb), "D", "chrome", label, implemented=True)

    add(
        "D1.1",
        _exact("menu:section:identity"),
        "D",
        "identity",
        "Skills (N)",
        implemented=False,
        notes="OMIT self-loop; was NOOP",
    )

    for spec_id, cmd in (
        ("D2.1", "new"),
        ("D2.2", "help"),
        ("D2.3", "voice"),
        ("D2.4", "model"),
        ("D2.5", "status"),
        ("D2.6", "stop"),
    ):
        add(
            spec_id,
            _exact(f"menu:cmd:{cmd}"),
            "D",
            "quick",
            f"/{cmd}",
            implemented=True,
            notes="Command invoke TMF Wave 2",
        )

    add(
        "D3.1",
        r"^https?://",
        "D",
        "workspace",
        "Open Web UI",
        implemented=True,
        requires_web_ui=True,
        notes="URL when configured",
    )
    add(
        "D3.2",
        _exact("menu:section:workspace"),
        "D",
        "workspace",
        "Web UI not configured",
        implemented=False,
        notes="OMIT noop stub",
    )

    add(
        "D4.1",
        _exact("menu:cmd:status"),
        "D",
        "diagnostics",
        "/status",
        implemented=True,
        notes="Command invoke TMF Wave 2",
    )

    # --- E. QA bar ---
    for spec_id, action in (
        ("E1", "regen"),
        ("E2", "up"),
        ("E3", "down"),
    ):
        add(
            spec_id,
            rf"^qa:\d+:{action}$",
            "E",
            "qa_bar",
            action,
            implemented=True,
            notes="Gated by Session toggles; proven TMF Wave 1",
        )
    add(
        "E4",
        r"^https?://.*/webapp/share",
        "E",
        "qa_bar",
        "Share",
        implemented=True,
        notes="WebApp URL",
    )
    add(
        "E5",
        r"^https?://.*/webapp/feedback",
        "E",
        "qa_bar",
        "Feedback",
        implemented=True,
        notes="WebApp URL",
    )

    # --- F. Pinned dashboard keyboard ---
    for spec_id, cmd in (
        ("F1", "new"),
        ("F2", "stop"),
        ("F3", "status"),
        ("F4", "voice"),
        ("F5", "model"),
    ):
        add(
            spec_id,
            _exact(f"menu:cmd:{cmd}"),
            "F",
            "pin",
            f"/{cmd}",
            implemented=True,
            notes="Command invoke TMF Wave 2",
        )
    add(
        "F6",
        _exact("cfg:section:shortcuts"),
        "F",
        "pin",
        "Shortcuts",
        implemented=True,
        notes="Opens /config Shortcuts",
    )
    add(
        "F6-legacy",
        _exact("cfg:shortcuts"),
        "F",
        "pin",
        "Shortcuts (legacy)",
        implemented=False,
        notes="Forbidden unparsed callback",
    )

    return tuple(specs)


MENU_BUTTON_SPECS: tuple[MenuButtonSpec, ...] = _build_menu_button_specs()

_COMPILED_SPECS: tuple[tuple[re.Pattern[str], MenuButtonSpec], ...] = tuple(
    (re.compile(spec.callback_pattern), spec) for spec in MENU_BUTTON_SPECS
)


def match_menu_button_spec(callback_data: str) -> MenuButtonSpec | None:
    """Return the first registry spec matching ``callback_data``.

    Args:
        callback_data (str): Telegram inline ``callback_data``.

    Returns:
        MenuButtonSpec | None: Matching spec, or ``None`` when unregistered.

    Examples:
        >>> match_menu_button_spec("cfg:toggle:gateway.queue_mode:steer") is not None
        True
        >>> match_menu_button_spec("cfg:shortcuts") is not None
        True
    """
    stripped = callback_data.strip()
    for pattern, spec in _COMPILED_SPECS:
        if pattern.match(stripped):
            return spec
    return None


def is_nav_chrome_callback(callback_data: str) -> bool:
    """Return whether ``callback_data`` is shared Back/Home/Close chrome.

    Args:
        callback_data (str): Telegram inline ``callback_data``.

    Returns:
        bool: ``True`` for navigation chrome callbacks.

    Examples:
        >>> is_nav_chrome_callback("cfg:nav:home")
        True
        >>> is_nav_chrome_callback("cfg:toggle:gateway.queue_mode:steer")
        False
    """
    return callback_data.strip() in _NAV_CHROME_CALLBACKS


def is_section_tile_callback(callback_data: str) -> bool:
    """Return whether ``callback_data`` opens a config or menu section tile.

    Args:
        callback_data (str): Telegram inline ``callback_data``.

    Returns:
        bool: ``True`` for ``cfg:section:*`` / ``menu:section:*`` navigation tiles.

    Examples:
        >>> is_section_tile_callback("cfg:section:voice")
        True
        >>> is_section_tile_callback("cfg:help:cmd:help")
        False
    """
    stripped = callback_data.strip()
    return any(stripped.startswith(prefix) for prefix in _SECTION_TILE_PREFIXES)


def registry_implementation_counts() -> dict[str, int]:
    """Count registry rows by ``implemented`` flag.

    Returns:
        dict[str, int]: Keys ``total``, ``implemented``, ``not_implemented``.

    Examples:
        >>> c = registry_implementation_counts()
        >>> c["implemented"] + c["not_implemented"] == c["total"]
        True
    """
    total = len(MENU_BUTTON_SPECS)
    implemented = sum(1 for spec in MENU_BUTTON_SPECS if spec.implemented)
    return {
        "total": total,
        "implemented": implemented,
        "not_implemented": total - implemented,
    }


__all__ = [
    "MENU_BUTTON_SPECS",
    "MenuButtonSpec",
    "MenuSurface",
    "is_nav_chrome_callback",
    "is_section_tile_callback",
    "match_menu_button_spec",
    "registry_implementation_counts",
]
