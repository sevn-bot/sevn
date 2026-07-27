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
    >>> spec = match_menu_button_spec("cfg:section:chat")
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
        ("B5", "/stop", True, "L1 picker + ALL when L1 runs; session cancel when empty (#27)"),
        ("B12", "/agents", True, "Running L1/L2 inventory slash + pin (#28)"),
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
    # W3 redesign: eight intent tiles (D16). Demoted root slugs stay registered under
    # their parent section so W1.6 Ready snapshots still find every legacy callback.
    config_root: tuple[tuple[str, str, str], ...] = (
        ("C0.1", "Chat", "chat"),
        ("C0.2", "Agent", "agent"),
        ("C0.7", "Skills & Tools", "skills"),
        ("C0.10", "Memory", "memory"),
        ("C0.6", "Access", "access"),
        ("C0.19", "Health", "health"),
        ("C0.23", "Deployment", "deployment"),
        ("C0.20", "Help", "help"),
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
    config_root_demoted: tuple[tuple[str, str, str, str], ...] = (
        ("C0.3", "Models", "models", "agent"),
        ("C0.4", "Voice", "voice", "chat"),
        ("C0.5", "Channels", "channels", "chat"),
        ("C0.8", "Tools", "tools", "skills"),
        ("C0.11", "Security", "security", "access"),
        ("C0.14", "Integrations", "integrations", "skills"),
        ("C0.15", "Dashboard", "dashboard", "health"),
        ("C0.16", "Shortcuts", "shortcuts", "chat"),
        ("C0.17", "Notifications", "notifications", "chat"),
        ("C0.22", "sevn.bot", "sevn_bot", "help"),
        ("C0.9", "Code", "code", "memory"),
        ("C0.12", "Secrets", "secrets", "access"),
        ("C0.13", "Agents", "agents", "agent"),
        ("C0.27", "Session", "session", "chat"),
        ("C0.28", "Logs", "logs", "health"),
        ("C0.29", "My sevn bot", "my_sevn_bot", "deployment"),
    )
    for spec_id, label, sid, parent in config_root_demoted:
        add(
            spec_id,
            _exact(f"cfg:section:{sid}"),
            "C",
            parent,
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
            "chat_qa",
            label,
            implemented=True,
            notes="QA bar gating proven TMF Wave 1",
        )
    add(
        "C1.6",
        _toggle("gateway.queue_mode"),
        "C",
        "chat",
        "Queue cancel↔steer↔multi",
        implemented=True,
        notes="JSON; cycles cancel/steer/multi on Chat root (W5)",
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
            "chat_voice",
            f"TTS: {mode}",
            implemented=True,
            notes="TTS runtime verified TMF Wave 7",
        )
    add(
        "C3.3",
        _exact("cfg:voice:mode:when_asked"),
        "C",
        "chat_voice",
        "TTS: when_asked",
        implemented=True,
        notes="TTS runtime verified TMF Wave 7",
    )
    add(
        "C3.4",
        r"^cfg:voice:stt:.*$",
        "C",
        "chat_voice",
        "STT provider cycle",
        implemented=True,
        notes="Cycles voice.stt_providers primary; wired TMF Wave W4",
    )
    add(
        "C3.5",
        r"^cfg:voice:engine:.*$",
        "C",
        "chat_voice",
        "TTS engine cycle",
        implemented=True,
        notes="Cycles voice.local_tts_engine (kokoro / supertonic)",
    )
    add(
        "C3.6",
        _exact("act:voice:status"),
        "C",
        "chat_voice",
        "Probe backends",
        implemented=True,
        notes="Live STT/TTS health probe (W7a)",
    )
    add(
        "C3.7",
        _exact("act:voice:show"),
        "C",
        "chat_voice",
        "Voice settings",
        implemented=True,
        notes="Local voice settings dump (W7a)",
    )

    # --- C4. Models ---
    add(
        "C4.1",
        _toggle("providers.use_main_model_for_all"),
        "C",
        "agent",
        "Unified model",
        implemented=True,
        notes="OK; verified slot resolution TMF Wave 5",
    )
    add(
        "C4.2",
        r"^cfg:models:page:triager:\d+$",
        "C",
        "agent",
        "Triager picker",
        implemented=True,
    )
    add(
        "C4.3",
        r"^cfg:models:page:tier_b:\d+$",
        "C",
        "agent",
        "Tier B picker",
        implemented=True,
    )
    add(
        "C4.4",
        r"^cfg:models:page:tier_cd:\d+$",
        "C",
        "agent",
        "Tier C/D picker",
        implemented=True,
    )
    add(
        "C4.5",
        _exact("cfg:models:swap"),
        "C",
        "agent",
        "Swap last model",
        implemented=True,
    )
    add(
        "C4.5-pick",
        r"^cfg:models:pick:.*$",
        "C",
        "agent",
        "Model pick selection",
        implemented=True,
        notes="Paginated picker row callback",
    )
    add(
        "C4.6",
        r"^https?://.*#models$",
        "C",
        "agent",
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
    add(
        "C5.6",
        _exact("act:channels:status"),
        "C",
        "chat_channels",
        "Channel status",
        implemented=True,
        notes="Runtime health + session counts (W7a)",
    )
    add(
        "C5.7",
        _exact("act:channels:config"),
        "C",
        "chat_channels",
        "Channel config",
        implemented=True,
        notes="Editable channel toggles dump (W7a)",
    )

    # --- C6. Secrets ---
    add(
        "C6.1",
        _exact("form:secret_wizard"),
        "C",
        "access_secrets",
        "+ Add secret",
        implemented=True,
        owner_only=True,
        notes="form wizard; TMF Wave 3",
    )
    add(
        "C6.1b",
        # Exclude discogs.user_token so exact C7.18 wins (first-match registry).
        r"^form:secret_wizard:(?!discogs\.user_token$)[a-zA-Z0-9._-]+$",
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
        "access_secrets",
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
    from sevn.gateway.menu.menu_registry_discogs import register_discogs_menu_entries

    register_discogs_menu_entries(add)

    # --- C8. Tools ---
    add(
        "C8.1",
        r"^https?://.*#tools$",
        "C",
        "skills_tools",
        "Open Tools tab",
        implemented=True,
        requires_web_ui=True,
        notes="URL; OMIT when no web_ui.url",
    )
    add(
        "C8.2",
        r"^cfg:toggle:tools\.[^.]+\.enabled:(?:true|false)$",
        "C",
        "skills_tools",
        "Enable plugin tool",
        implemented=True,
        notes="Top-N plugin toggles when tools schema allows child enabled",
    )
    add(
        "C8.3",
        r"^https?://.*#tools$",
        "C",
        "skills_tools",
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
        "agent_lab",
        "λ-RLM enabled",
        implemented=True,
        notes="Reloads executor λ gate; schema-gated render",
    )
    add(
        "C9.2",
        _toggle("rlm.c_d_backend"),
        "C",
        "agent_lab",
        "Tier C/D backend cycle",
        implemented=True,
        notes="Cycle when λ-RLM on + allowlist non-empty; else caption-only",
    )
    add(
        "C9.3",
        r"^cfg:section:rlm$",
        "C",
        "agent_lab",
        "REPL lifetime display",
        implemented=True,
        notes="Caption-only in config_menu_message_text",
    )
    add(
        "C9.4",
        r"^https?://.*#rlm$",
        "C",
        "agent_lab",
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
        "memory_code",
        "MYCODE",
        implemented=True,
        owner_only=True,
        notes="Runtime via code_understanding.mycode.enabled reload",
    )
    add(
        "C10.2",
        _toggle("code_understanding.code_review_graph.enabled"),
        "C",
        "memory_code",
        "Review graph",
        implemented=True,
        owner_only=True,
        notes="Runtime via code_review_graph_mcp_enabled reload",
    )
    add(
        "C10.3",
        r"^https?://.*#code$",
        "C",
        "memory_code",
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
        "access_guard",
        "Heuristic-only",
        implemented=True,
        owner_only=True,
        notes="Reloads LLMGuardScanner on toggle (TMF-9)",
    )
    add(
        "C11.2",
        r"^https?://.*#security$",
        "C",
        "access_guard",
        "Open Security tab",
        implemented=True,
        requires_web_ui=True,
        notes="OMIT when no web_ui.url; scanner reload on heuristic toggle",
    )
    add(
        "C11.3",
        _toggle("channels.telegram.owner_scanner_overrides.disable_text"),
        "C",
        "access_guard",
        "Skip guard on my text",
        implemented=True,
        owner_only=True,
        notes="Owner-actor text scans bypassed when on; reloads scanner",
    )
    add(
        "C11.4",
        _toggle("channels.telegram.owner_scanner_overrides.disable_links"),
        "C",
        "access_guard",
        "Skip guard on my links",
        implemented=True,
        owner_only=True,
        notes="Owner-actor link scans bypassed when on; mixed-kind only skipped when every kind is disabled",
    )
    add(
        "C11.5",
        _toggle("channels.telegram.owner_scanner_overrides.disable_documents"),
        "C",
        "access_guard",
        "Skip guard on my documents",
        implemented=True,
        owner_only=True,
        notes="Owner-actor attachment scans bypassed when on",
    )

    # --- C12. Self-Improve ---
    add(
        "C12.1",
        _toggle("self_improve.enabled"),
        "C",
        "agent_lab",
        "Self-improve enabled",
        implemented=True,
        notes="JSON",
    )
    add(
        "C12.2",
        r"^https?://.*#traces$",
        "C",
        "agent_lab",
        "View jobs / Traces",
        implemented=True,
        requires_web_ui=True,
        notes="OMIT when no web_ui.url",
    )
    add(
        "C12.3",
        r"^act:self_improve:run$",
        "C",
        "agent_lab",
        "Run improve now",
        implemented=False,
        notes="Defer — CLI/dashboard only",
    )

    # --- C13. Second Brain ---
    add(
        "C13.1",
        _toggle("second_brain.enabled"),
        "C",
        "memory_sb",
        "Second Brain enabled",
        implemented=True,
        owner_only=True,
        notes="JSON",
    )
    add(
        "C13.2",
        r"^cfg:section:second_brain$",
        "C",
        "memory_sb",
        "Ingest schedule",
        implemented=True,
        notes="Caption-only; ingest_batch_cron not in schema properties",
    )
    add(
        "C13.3",
        r"^https?://.*#second_brain$",
        "C",
        "memory_sb",
        "Open Second Brain tab",
        implemented=True,
        requires_web_ui=True,
        notes="OMIT when no web_ui.url",
    )

    add(
        "C13.4",
        r"^form:second_brain_vault_path$",
        "C",
        "memory_sb",
        "Set vault path",
        implemented=True,
        notes="Owner text-reply wizard",
    )
    add(
        "C13.5",
        r"^form:second_brain_vault_browse$",
        "C",
        "memory_sb",
        "Browse folders",
        implemented=True,
        notes="Owner folder browser wizard",
    )
    add(
        "C13.6",
        r"^cfg:toggle:second_brain\.layout:(?:legacy|para)$",
        "C",
        "memory_sb",
        "Vault layout",
        implemented=True,
        owner_only=True,
        notes="legacy ↔ para cycle",
    )

    # --- C25. Sub-agents (Advanced nested) ---
    add(
        "C25.1",
        _toggle("subagents.enabled"),
        "C",
        "agent_subagents",
        "Sub-agents enabled",
        implemented=True,
        owner_only=True,
        notes="JSON; W7 operator surface",
    )
    add(
        "C25.2",
        _exact("cfg:section:subagents_running"),
        "C",
        "agent_subagents",
        "Running L1/L2 counts",
        implemented=True,
        notes="Live registry snapshot + Running submenu",
    )
    add(
        "C25.3",
        r"^form:subagents_max_override$",
        "C",
        "agent_subagents",
        "Global override",
        implemented=True,
        owner_only=True,
        notes="Numeric form wizard",
    )
    add(
        "C25.4",
        r"^form:subagents_limits:(triager|tier_b|tier_c|tier_d)$",
        "C",
        "agent_subagents",
        "Per-role limits",
        implemented=True,
        owner_only=True,
        notes="Two-step L1/L2 numeric wizard",
    )
    add(
        "C25.5",
        r"^act:subagents:kill:[a-z0-9]+$",
        "C",
        "agent_subagents_running",
        "Kill sub-agent",
        implemented=True,
        owner_only=True,
        notes="Owner-only cooperative kill via supervisor (D13)",
    )
    add(
        "C25.6",
        _exact("act:subagents:kill_all"),
        "C",
        "agent_subagents_running",
        "Kill all L1",
        implemented=True,
        owner_only=True,
        notes="Owner-only kill-all (D13)",
    )
    add(
        "C25.7",
        r"^https?://.*#subagents$",
        "C",
        "agent_subagents",
        "Open Sub-agents panel",
        implemented=True,
        requires_web_ui=True,
        notes="OMIT when no web_ui.url",
    )
    add(
        "C25.8",
        _exact("cfg:section:subagents"),
        "C",
        "agent",
        "Open Sub-agents",
        implemented=True,
        notes="Nav from Agent root (W5)",
    )

    # --- C26. Chat sessions (W7a) ---
    add(
        "C26.1",
        _exact("act:sessions:list"),
        "C",
        "chat_sessions",
        "List sessions",
        implemented=True,
        notes="Gateway SQLite session index (W7a)",
    )
    add(
        "C26.2",
        _exact("form:sessions:history"),
        "C",
        "chat_sessions",
        "Session history",
        implemented=True,
        notes="Form → fetch_session_history (W7a)",
    )
    add(
        "C26.3",
        _exact("form:sessions:send"),
        "C",
        "chat_sessions",
        "Send to another session",
        implemented=True,
        notes="Form → send_to_session (W7a)",
    )

    # --- C27. Agent leaves (W7b) ---
    add(
        "C27.1",
        _exact("act:agent:status"),
        "C",
        "agent",
        "Active runs",
        implemented=True,
        notes="Gateway run snapshots (W7b)",
    )
    add(
        "C27.2",
        _exact("act:agent:sampling:show"),
        "C",
        "agent_sampling",
        "Show params",
        implemented=True,
        notes="LLM_params_config.json dump (W7b)",
    )
    add(
        "C27.3",
        _exact("form:models:set_max_output_tokens"),
        "C",
        "agent_sampling",
        "Set max output tokens",
        implemented=True,
        notes="Form → set_agent_model_max_output_tokens (W7b)",
    )
    add(
        "C27.4",
        _exact("act:agent:config"),
        "C",
        "agent_identity",
        "Resolved slots",
        implemented=True,
        notes="Resolved model slots (W7b)",
    )
    add(
        "C27.5",
        _exact("act:self_improve:doctor"),
        "C",
        "agent_lab",
        "Improve doctor",
        implemented=True,
        notes="Self-improve config posture (W7b)",
    )
    add(
        "C27.6",
        _exact("form:improve:learn"),
        "C",
        "agent_lab",
        "Record lesson",
        implemented=True,
        notes="Append candidate_lessons.jsonl (W7b)",
    )
    add(
        "C27.7",
        _exact("act:self_improve:replay_sampler"),
        "C",
        "agent_lab",
        "Replay sampler",
        implemented=True,
        owner_only=True,
        notes="Developer replay-sampler aid (W7b)",
    )
    add(
        "C27.8",
        _exact("form:subagents:kill"),
        "C",
        "agent_subagents_running",
        "Kill one (form)",
        implemented=True,
        owner_only=True,
        notes="Form → subagents kill by id (W7b)",
    )

    # --- C28. Skills & Tools + Memory leaves (W7c) ---
    add(
        "C28.1",
        _exact("act:skills:list"),
        "C",
        "skills",
        "Skills list",
        implemented=True,
        notes="Gateway skills inventory (W7c)",
    )
    add(
        "C28.2",
        _exact("act:skills:sync"),
        "C",
        "skills",
        "Sync skills index",
        implemented=True,
        notes="Additive INDEX.md sync (W7c)",
    )
    add(
        "C28.3",
        _exact("act:skills:security-scan"),
        "C",
        "skills",
        "Security scan",
        implemented=True,
        notes="SkillSpector workspace scan (W7c)",
    )
    add(
        "C28.4",
        _exact("act:tools:health"),
        "C",
        "skills_tools",
        "Tool health",
        implemented=True,
        notes="Chronic tool/skill failure rows (W7c)",
    )
    add(
        "C28.5",
        _exact("cfg:section:memory_dreaming"),
        "C",
        "memory",
        "Dreaming nav",
        implemented=True,
        notes="Nav to memory_dreaming (W7c)",
    )
    add(
        "C28.6",
        _exact("act:memory:search"),
        "C",
        "memory",
        "Search memory",
        implemented=True,
        notes="Federated memory browse/search (W7c)",
    )
    add(
        "C28.7",
        _exact("act:memory:index"),
        "C",
        "memory",
        "Rebuild index",
        implemented=True,
        notes="Memory index hook (W7c)",
    )
    add(
        "C28.8",
        _exact("cfg:section:memory_openwiki"),
        "C",
        "memory",
        "OpenWiki nav",
        implemented=True,
        notes="Nav to memory_openwiki (W7c)",
    )
    add(
        "C28.9",
        _exact("act:second_brain:reindex"),
        "C",
        "memory_sb",
        "Reindex vault",
        implemented=True,
        notes="Witchcraft reindex (W7c)",
    )
    add(
        "C28.10",
        _exact("act:second_brain:setup"),
        "C",
        "memory_sb",
        "Bootstrap layout",
        implemented=True,
        notes="Second Brain setup/bootstrap (W7c)",
    )
    add(
        "C28.11",
        _exact("act:dreaming:status"),
        "C",
        "memory_dreaming",
        "Dreaming status",
        implemented=True,
        notes="Dreaming config summary (W7c)",
    )
    add(
        "C28.12",
        _exact("form:memory:backfill"),
        "C",
        "memory_dreaming",
        "Backfill window",
        implemented=True,
        notes="Form → grounded Dreaming backfill (W7c)",
    )
    add(
        "C28.13",
        _exact("act:dreaming:undo"),
        "C",
        "memory_dreaming",
        "Undo last batch",
        implemented=True,
        notes="Rollback last auto Dreaming batch (W7c)",
    )
    add(
        "C28.14",
        _exact("act:dreaming:reconcile_cron"),
        "C",
        "memory_dreaming",
        "Reconcile cron",
        implemented=True,
        notes="Rewrite Dreaming cron row (W7c)",
    )
    add(
        "C28.15",
        _exact("act:openui:install"),
        "C",
        "memory_openwiki",
        "Install CLI",
        implemented=True,
        notes="npm install openwiki CLI (W7c)",
    )
    add(
        "C28.16",
        _exact("form:openui:configure"),
        "C",
        "memory_openwiki",
        "Configure LLM key",
        implemented=True,
        notes="Form → integration.openwiki.llm_api_key (W7c)",
    )
    add(
        "C28.17",
        _exact("act:openui:setup"),
        "C",
        "memory_openwiki",
        "Install + key",
        implemented=True,
        notes="Install OpenWiki CLI then prompt for key (W7c)",
    )

    # --- C29. Access + Health leaves (W7d) ---
    add(
        "C29.1",
        _exact("act:secrets:list"),
        "C",
        "access_secrets",
        "List aliases",
        implemented=True,
        notes="Aliases + fingerprints only (W7d)",
    )
    add(
        "C29.2",
        _exact("form:secrets:rm"),
        "C",
        "access_secrets",
        "Remove secret",
        implemented=True,
        owner_only=True,
        notes="Form + two-step confirm (W7d)",
    )
    add(
        "C29.3",
        _exact("act:secrets:check-unlock"),
        "C",
        "access_secrets",
        "Unlock status",
        implemented=True,
        notes="Encrypted store unlock posture (W7d)",
    )
    add(
        "C29.4",
        _exact("act:providers:oauth:status"),
        "C",
        "access_providers",
        "OAuth status",
        implemented=True,
        notes="Provider OAuth summary (W7d)",
    )
    add(
        "C29.5",
        _exact("form:providers:oauth:login"),
        "C",
        "access_providers",
        "Link provider",
        implemented=True,
        notes="Form → OAuth login handoff (W7d)",
    )
    add(
        "C29.6",
        _exact("form:providers:oauth:logout"),
        "C",
        "access_providers",
        "Unlink provider",
        implemented=True,
        notes="Form → delete oauth.* secret (W7d)",
    )
    add(
        "C29.7",
        _exact("form:gh:github_token"),
        "C",
        "access",
        "GitHub token",
        implemented=True,
        notes="Form → integration.github.token (W7d)",
    )
    add(
        "C29.8",
        _exact("cfg:section:access_pairing"),
        "C",
        "access",
        "DM policy & pairing nav",
        implemented=True,
        notes="Nav to access_pairing (W7d)",
    )
    add(
        "C29.9",
        _exact("act:pairing:pending"),
        "C",
        "access_pairing",
        "Pending requests",
        implemented=True,
        notes="PairingStore.list_pending (W7d)",
    )
    add(
        "C29.10",
        _exact("form:pairing:approve"),
        "C",
        "access_pairing",
        "Approve pairing code",
        implemented=True,
        notes="Form → PairingStore.approve_code (W7d)",
    )
    add(
        "C29.11",
        _exact("act:doctor:run"),
        "C",
        "health",
        "Run doctor",
        implemented=True,
        notes="Local + gateway probes (W7d)",
    )
    add(
        "C29.12",
        _exact("act:usage:show"),
        "C",
        "health",
        "Usage & budget",
        implemented=True,
        notes="Budget rollups from traces (W7d)",
    )
    add(
        "C29.13",
        _exact("cfg:section:health_bundles"),
        "C",
        "health",
        "Turn bundles nav",
        implemented=True,
        notes="Nav to health_bundles (W7d)",
    )
    add(
        "C29.14",
        _exact("act:turn_bundles:export"),
        "C",
        "health_bundles",
        "Export / refresh",
        implemented=True,
        notes="Backfill turn JSONL bundles (W7d)",
    )
    add(
        "C29.15",
        _exact("form:turn_bundles:view"),
        "C",
        "health_bundles",
        "View a turn",
        implemented=True,
        notes="Form → view_turn_bundle explorer (W7d)",
    )
    add(
        "C29.16",
        _exact("act:tracing:config"),
        "C",
        "health_tracing",
        "Tracing config",
        implemented=True,
        notes="Logfire export status dump (W7d)",
    )
    add(
        "C29.17",
        _exact("cfg:section:access_providers"),
        "C",
        "access",
        "Provider logins nav",
        implemented=True,
        notes="Nav to access_providers (W7d)",
    )

    # --- C30. Deployment + Help leaves (W7e) ---
    for spec_id, pattern, section, label in (
        ("C30.1", _exact("cfg:section:deployment_services"), "deployment", "Services nav"),
        ("C30.2", _exact("act:services:gateway:start"), "deployment_services", "Start gateway"),
        ("C30.3", _exact("act:services:gateway:stop"), "deployment_services", "Stop gateway"),
        ("C30.4", _exact("act:services:gateway:status"), "deployment_services", "Gateway status"),
        ("C30.5", _exact("act:services:gateway:logs"), "deployment_services", "Gateway logs"),
        ("C30.6", _exact("act:services:proxy:start"), "deployment_services", "Start proxy"),
        ("C30.7", _exact("act:services:proxy:stop"), "deployment_services", "Stop proxy"),
        ("C30.8", _exact("act:services:proxy:status"), "deployment_services", "Proxy status"),
        ("C30.9", _exact("act:services:proxy:logs"), "deployment_services", "Proxy logs"),
        ("C30.10", _exact("cfg:section:deployment_tunnel"), "deployment", "Tunnel setup nav"),
        ("C30.11", _exact("act:tunnel:status"), "deployment_tunnel", "Tunnel status"),
        ("C30.12", _exact("act:tunnel:start"), "deployment_tunnel", "Start now (this boot)"),
        ("C30.13", _exact("act:tunnel:stop"), "deployment_tunnel", "Stop now (this boot)"),
        ("C30.14", _exact("form:tunnel:setup"), "deployment_tunnel", "Setup / change provider"),
        ("C30.15", _exact("cfg:section:deployment_config"), "deployment", "Config file nav"),
        ("C30.16", _exact("act:config:show"), "deployment_config", "Show sevn.json"),
        ("C30.17", _exact("act:config:validate"), "deployment_config", "Validate"),
        ("C30.18", _exact("form:config:set"), "deployment_config", "Set a key"),
        ("C30.19", _exact("act:config:sections"), "deployment_config", "Sections & SSOT paths"),
        ("C30.20", _exact("cfg:section:deployment_update"), "deployment", "Update & migrate nav"),
        ("C30.21", _exact("act:update:cli"), "deployment_update", "Update CLI"),
        ("C30.22", _exact("act:update:schema"), "deployment_update", "Schema posture"),
        ("C30.23", _exact("form:migrate:import"), "deployment_update", "Migrate / import"),
        ("C30.24", _exact("cfg:section:deployment_deploy"), "deployment", "Deploy to host nav"),
        ("C30.25", _exact("form:deploy:check"), "deployment_deploy", "Check SSH host"),
        ("C30.26", _exact("form:deploy:remote"), "deployment_deploy", "Deploy to remote"),
        (
            "C30.27",
            _exact("cfg:section:access_secrets"),
            "deployment_deploy",
            "Export bundle cross-link",
        ),
        ("C30.28", _exact("act:help:slash"), "help", "Slash commands"),
        ("C30.29", _exact("cfg:section:help_guides"), "help", "Guides nav"),
        ("C30.30", _exact("act:guides:list"), "help_guides", "List guides"),
        ("C30.31", _exact("form:guides:read"), "help_guides", "Read a guide"),
        ("C30.32", _exact("act:help:version"), "help", "CLI version"),
        ("C30.33", _exact("act:help:about"), "help", "about.sevn.bot"),
    ):
        add(
            spec_id,
            pattern,
            "C",
            section,
            label,
            implemented=True,
            owner_only=section.startswith("deployment"),
            notes="W7e deployment/help leaf",
        )
    add(
        "C30.34",
        r"^act:deploy:remote(:confirm|:cancel)?$",
        "C",
        "deployment_deploy",
        "Deploy to remote confirm",
        implemented=True,
        owner_only=True,
        notes="Two-step confirm (W7e)",
    )

    # --- C31. Build rows (W8) ---
    add(
        "C31.1",
        _exact("cfg:section:deployment_host"),
        "C",
        "deployment",
        "Host-only commands nav",
        implemented=True,
        owner_only=True,
        notes="Nav to deployment_host (W8)",
    )
    for spec_id, pattern, label in (
        ("C31.2", _exact("act:host:onboard"), "Onboard wizard"),
        ("C31.3", _exact("act:host:completion"), "Shell completion"),
        ("C31.4", _exact("act:host:shell-history"), "Shell-history hook"),
        ("C31.5", _exact("act:host:gateway-token"), "Set gateway token"),
        ("C31.6", _exact("act:host:dashboard-password"), "Set dashboard password"),
        ("C31.7", _exact("act:host:store-passphrase"), "Store passphrase"),
        ("C31.8", _exact("act:host:uninstall"), "Uninstall sevn"),
    ):
        add(
            spec_id,
            pattern,
            "C",
            "deployment_host",
            label,
            implemented=True,
            owner_only=True,
            notes="Host-only copy-paste card (W8, D17)",
        )
    add(
        "C31.9",
        _exact("cfg:section:help_dev"),
        "C",
        "help",
        "Developer nav",
        implemented=True,
        owner_only=True,
        notes="Checkout-gated nav (W8)",
    )
    for spec_id, pattern, label in (
        ("C31.10", _exact("act:dev:readme"), "README pipeline"),
        ("C31.11", _exact("act:dev:about-docs"), "About-docs"),
        ("C31.12", _exact("act:dev:gui-migrate"), "GUI migration notes"),
    ):
        add(
            spec_id,
            pattern,
            "C",
            "help_dev",
            label,
            implemented=True,
            owner_only=True,
            notes="Developer copy-paste card (W8)",
        )
    add(
        "C31.13",
        _exact("act:secrets:export-secrets"),
        "C",
        "access_secrets",
        "Export .env bundle",
        implemented=True,
        owner_only=True,
        notes="Two-step confirm + file delivery (W8)",
    )
    add(
        "C31.14",
        r"^act:secrets:export-secrets:(?:confirm|cancel)$",
        "C",
        "access_secrets",
        "Export bundle confirm",
        implemented=True,
        owner_only=True,
        notes="Confirm/cancel gate (W8)",
    )
    add(
        "C31.15",
        _exact("act:integrations:status"),
        "C",
        "skills_integrations",
        "Integration status",
        implemented=True,
        notes="Per-integration listing (W8)",
    )

    # --- C14. Integrations ---
    add(
        "C14.1",
        r"^https?://.*#integrations$",
        "C",
        "skills_integrations",
        "+ Add integration",
        implemented=True,
        requires_web_ui=True,
        notes="URL; OMIT when no web_ui.url",
    )
    add(
        "C14.2",
        r"^cfg:toggle:integration\.[^.]+\.enabled:(?:true|false)$",
        "C",
        "skills_integrations",
        "Toggle integration",
        implemented=True,
        notes="Rendered only when integration.<id>.enabled is schema-declared",
    )
    add(
        "C14.3",
        _exact("cfg:integrations:refresh"),
        "C",
        "skills_integrations",
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
        "chat_shortcuts",
        "Delete shortcut",
        implemented=True,
        notes="content_root + is_owner on nav refresh; TMF Wave 1",
    )
    add(
        "C16.2",
        _exact("form:shortcut_add"),
        "C",
        "chat_shortcuts",
        "+ Add shortcut",
        implemented=True,
        notes="form wizard; TMF Wave 3",
    )
    add(
        "C16.5",
        _exact("act:shortcuts:list"),
        "C",
        "chat_shortcuts",
        "List shortcuts",
        implemented=True,
        notes="shortcuts_store.list_visible_shortcuts (W7a)",
    )
    add(
        "C16.6",
        _exact("form:shortcut_remove"),
        "C",
        "chat_shortcuts",
        "Remove shortcut",
        implemented=True,
        notes="shortcuts_store.delete_shortcut form (W7a)",
    )
    for spec_id, label in (("C16.3", "Edit shortcut"), ("C16.4", "Run shortcut")):
        add(spec_id, r"^short:run:.*$", "C", "shortcuts", label, implemented=False, notes="MISSING")

    # --- C17. Notifications ---
    add(
        "C17.1",
        _toggle("channels.telegram.telegram_notify_policy"),
        "C",
        "chat",
        "Notify policy cycle",
        implemented=True,
        notes="Notify policy cycle verified TMF Wave 7",
    )
    add(
        "C17.2",
        r"^cfg:cycle:channels\.telegram\.telegram_notify_policy:.+$",
        "C",
        "chat",
        "Notify policy cycle (cfg:cycle alias)",
        implemented=True,
        notes="Registry alias for W1.11; live row uses cfg:toggle (W7a)",
    )

    # --- C18. Deployment / Lab (Advanced dissolved W5) ---
    add(
        "C18.1",
        _toggle("gateway.restart.auto_resume_b"),
        "C",
        "deployment",
        "Auto-resume tier B",
        implemented=True,
        owner_only=True,
        notes="JSON; moved from Advanced to Deployment (W5)",
    )
    add(
        "C18.3",
        r"^https?://",
        "C",
        "agent_lab",
        "Open Mission Control",
        implemented=True,
        requires_web_ui=True,
        notes="URL when web_ui.url set; Agent Lab (W5)",
    )
    add(
        "C18.4",
        r"^act:gateway:restart(:confirm|:cancel)?$",
        "C",
        "deployment",
        "Restart gateway",
        implemented=True,
        owner_only=True,
        notes="2-step confirm; TMF Wave 6",
    )
    add(
        "C18.5",
        r"^act:proxy:restart(:confirm|:cancel)?$",
        "C",
        "deployment",
        "Restart proxy",
        implemented=True,
        owner_only=True,
        notes="2-step confirm; TMF Wave 6",
    )
    add(
        "C18.6",
        r"^https?://.*#config$",
        "C",
        "deployment",
        "Validate config",
        implemented=False,
        requires_web_ui=True,
        notes="MISSING",
    )
    add(
        "C18.7",
        _exact("cfg:section:rlm"),
        "C",
        "agent_lab",
        "Open RLM",
        implemented=True,
        notes="Agent Lab nav (W5)",
    )
    add(
        "C18.8",
        _exact("cfg:section:self_improve"),
        "C",
        "agent_lab",
        "Open Self-Improve",
        implemented=True,
        notes="Agent Lab nav (W5)",
    )
    add(
        "C18.9",
        _exact("cfg:section:second_brain"),
        "C",
        "memory",
        "Open Second Brain",
        implemented=True,
        notes="Memory root nav (W5)",
    )
    add(
        "C18.10",
        _exact("cfg:section:codemode"),
        "C",
        "agent_lab",
        "Open CodeMode",
        implemented=True,
        notes="Agent Lab nav (W5)",
    )

    # --- C24. CodeMode (Advanced nested) ---
    add(
        "C24.1",
        _toggle("agent.codemode.enabled"),
        "C",
        "agent_lab",
        "CodeMode enabled",
        implemented=True,
        notes="W8 tier-B Monty run_code; default off",
    )

    # --- C20. Logs (TE-4; 🚧 until TE-9) ---
    add(
        "C20.1",
        r"^cfg:logs:tail:gateway:\d+$",
        "C",
        "health",
        "Tail gateway",
        implemented=True,
        owner_only=True,
    )
    add(
        "C20.2",
        r"^cfg:logs:tail:proxy:\d+$",
        "C",
        "health",
        "Tail proxy",
        implemented=True,
        owner_only=True,
    )
    add(
        "C20.3",
        _exact("form:logs:grep"),
        "C",
        "health",
        "Grep logs (form)",
        implemented=True,
        owner_only=True,
    )
    add(
        "C20.4",
        r"^cfg:logs:traces:\d+$",
        "C",
        "health",
        "Recent traces",
        implemented=True,
        owner_only=True,
    )
    add(
        "C20.5",
        _exact("form:logs:span_id"),
        "C",
        "health",
        "Trace by id (form)",
        implemented=True,
        owner_only=True,
    )
    add(
        "C20.6",
        _exact("cfg:logs:toggle_redaction"),
        "C",
        "health_tracing",
        "Toggle redaction",
        implemented=True,
        owner_only=True,
        notes="Single trace-redaction home on Health > Trace export (W5)",
    )
    add(
        "C20.6b",
        _toggle("tracing.redaction.enabled"),
        "C",
        "health_tracing",
        "Trace redaction enabled",
        implemented=True,
        owner_only=True,
        notes="Alternate toggle path; primary UX is cfg:logs:toggle_redaction (C20.6)",
    )
    add(
        "C20.8",
        _exact("cfg:logs:toggle_logfire"),
        "C",
        "health_tracing",
        "Toggle Logfire export",
        implemented=True,
        owner_only=True,
    )
    add(
        "C20.9",
        _exact("form:logs:logfire_token"),
        "C",
        "health_tracing",
        "Set Logfire token (form)",
        implemented=True,
        owner_only=True,
    )
    add(
        "C20.7",
        _exact("cfg:logs:deployment_id"),
        "C",
        "deployment",
        "Deployment id",
        implemented=True,
        notes="Shows gateway deployment id in chat",
    )
    add(
        "C20.7a",
        _exact("cfg:logs:version_id"),
        "C",
        "deployment",
        "Version id",
        implemented=True,
        notes="Shows build version_id from sevn.json in chat",
    )
    add(
        "C22.1",
        r"^act:tunnel:on(:confirm|:cancel)?$",
        "C",
        "deployment",
        "Turn tunnel on",
        implemented=True,
        owner_only=True,
        notes="2-step confirm; sets infrastructure.tunnel.autostart + starts now; survives host restart via gateway boot",
    )
    add(
        "C22.2",
        _exact("act:tunnel:off"),
        "C",
        "deployment",
        "Turn tunnel off",
        implemented=True,
        owner_only=True,
        notes="Clears autostart + stops the running tunnel",
    )

    # --- C21. sevn.bot ---
    add(
        "C21.1",
        _exact("act:sevn_bot:sync"),
        "C",
        "help",
        "Sync (latest)",
        implemented=True,
        owner_only=True,
        notes="Runs sevn sync --latest on resolved checkout",
    )
    add(
        "C21.2",
        _exact("act:sevn_bot:bugs"),
        "C",
        "help",
        "Bugs",
        implemented=True,
        notes="Lists recent bug evolution issues",
    )
    add(
        "C21.3",
        _exact("act:sevn_bot:features"),
        "C",
        "help",
        "Features",
        implemented=True,
        notes="Lists recent feature evolution issues",
    )

    # --- C19. Agents ---
    add(
        "C19.1",
        r"^https?://",
        "C",
        "agent_identity",
        "Edit persona",
        implemented=True,
        requires_web_ui=True,
        notes="URL when web_ui.url set; no Advanced fallback (TMF Wave 8)",
    )
    add(
        "C19.2",
        _exact("form:agent:display_name"),
        "C",
        "agent_identity",
        "Edit display name",
        implemented=True,
        notes="Form wizard → agent.display_name; TMF Wave 8",
    )
    add(
        "C19.3",
        r"^https?://.*#identity$",
        "C",
        "agent_identity",
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
        ("D2.4", "model"),
        ("D2.5", "status"),
        ("D2.6", "stop"),
        ("D2.7", "agents"),
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
        ("F4", "agents"),
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
