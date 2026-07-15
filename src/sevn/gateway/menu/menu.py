"""Telegram ``/menu`` inline keyboard builder (`specs/18-channel-telegram.md` §4).

Module: sevn.gateway.menu.menu
Depends: sevn.agent.providers.budget, sevn.config.model_resolution, sevn.config.workspace_config

Exports:
    ConfigMenuRefreshContext — Telegram message coordinates for in-place ``/config`` refresh.
    ConfigMenuNavFrame — one screen in the per-message ``/config`` back stack.
    config_menu_nav_go — push current and navigate.
    config_menu_nav_pop — pop Back stack parent frame.
    config_menu_nav_home — clear stack to root.
    config_menu_nav_clear — drop stack on Close.
    config_menu_nav_key — stack dict key.
    get_config_menu_nav — load per-message stack state.
    config_menu_nav_push_current — push without leaving screen (restart confirm).
    refresh_config_menu_message — re-edit caption + keyboard after config mutations.
    subagent_menu_snapshot_from_router — live L1/L2 counts for Sub-agents menu screens.
    build_chat_menu_webapp_request — ``setChatMenuButton`` body for viewer launch (M2).
    sync_telegram_chat_menu_button — push or clear the chat menu Web App button (D12).
    MenuCallbackHandler — ``menu:*`` / ``nav:*`` edit-in-place handler (Wave B1).
    ConfigMenuHandler — ``/config`` 18-tile menu navigation handler (Wave 3).
    MenuToolSurface — protocol for menu About/diagnostics counts.
    build_menu_keyboard — sectioned inline keyboard for ``/menu``.
    build_config_menu_keyboard — 18-tile inline keyboard for ``/config``.
    build_service_restart_confirm_keyboard — Confirm/Cancel rows for service restart.
    service_restart_confirm_message — caption for restart confirmation screen.
    menu_message_text — caption text paired with each menu screen.
    config_menu_message_text — caption text for ``/config`` screens.
    parse_menu_callback_data — parse ``menu:*`` / ``nav:*`` callback payloads.
    parse_config_callback_data — parse ``cfg:nav:*`` / ``cfg:section:*`` payloads.
    parse_models_callback_data — parse ``cfg:models:*`` picker callbacks.
    menu_callback_matches — match inbound menu callbacks and ``/menu``.
    config_callback_matches — match inbound ``/config`` callbacks and slash.
    infer_budget_regime — map a catalog model id to :class:`BudgetRegime`.
    web_ui_url_from_workspace — resolve ``web_ui.url`` when configured.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

if TYPE_CHECKING:
    from sevn.gateway.channel_router import ChannelRouter, IncomingMessage

from sevn.agent.providers.budget import BudgetRegime
from sevn.agent.tracing.logfire_config import logfire_export_status
from sevn.config.defaults import (
    DEFAULT_GATEWAY_AUTO_RESUME_B,
    DEFAULT_RLM_C_D_BACKEND,
    DEFAULT_RLM_REPL_LIFETIME,
    DEFAULT_SECOND_BRAIN_ENABLED,
    DEFAULT_SELF_IMPROVE_ENABLED,
    DEFAULT_TIER_CD_LAMBDA_RLM_ENABLED,
    DEFAULT_TRACE_REDACTION_ENABLED,
    DEFAULT_TRIAGER_TIER_B_SKILL_CAP,
    DEFAULT_TRIAGER_TIER_B_TOOL_CAP,
    DEFAULT_VOICE_STT_PROVIDERS,
)
from sevn.config.model_resolution import (
    ModelSlot,
    codemode_enabled,
    list_catalog_model_ids,
    model_picker_slot_keys,
    model_picker_slots_for_key,
    resolve_model_slot,
    use_main_model_for_all,
)
from sevn.config.workspace_config import TelegramQuickActionsConfig, WorkspaceConfig
from sevn.gateway.commands.shortcuts_store import list_visible_shortcuts
from sevn.gateway.config_io.workspace_config_io import load_raw_sevn_json
from sevn.gateway.menu.menu_branding import (
    SEVN_BOT_ROOT_TILE_LABEL,
    config_sevn_bot_section_title,
)
from sevn.gateway.menu.social_media_manager_menu import (
    build_social_media_manager_keyboard_rows,
    social_media_manager_menu_caption,
)
from sevn.onboarding.seed import resolve_agent_display_name
from sevn.second_brain.paths import display_scope_root_relative, effective_scope, resolve_scope_root

_SECRET_REF_PATTERN = re.compile(r"\$\{SECRET:([^}]+)\}")


class MenuToolSurface(Protocol):
    """Minimal tool-set shape for menu About/diagnostics copy."""

    skill_descriptions: Mapping[str, str]
    native: Sequence[object]


@dataclass(frozen=True)
class _EmptyMenuToolSurface:
    """Empty :class:`MenuToolSurface` used when no session tool set is bound."""

    skill_descriptions: Mapping[str, str] = field(default_factory=dict)
    native: Sequence[object] = field(default_factory=tuple)


_EMPTY_TOOL_SURFACE = cast("MenuToolSurface", _EmptyMenuToolSurface())

MenuSection = Literal["root", "identity", "quick", "workspace", "diagnostics"]

ConfigSection = Literal[
    "root",
    "session",
    "agents",
    "models",
    "voice",
    "channels",
    "secrets",
    "skills",
    "skills:social_media_manager",
    "tools",
    "code",
    "security",
    "rlm",
    "self_improve",
    "second_brain",
    "subagents",
    "subagents_running",
    "codemode",
    "integrations",
    "dashboard",
    "shortcuts",
    "notifications",
    "advanced",
    "logs",
    "help",
    "sevn_bot",
    "my_sevn_bot",
]

_CONFIG_SECTIONS: frozenset[str] = frozenset(
    {
        "session",
        "agents",
        "models",
        "voice",
        "channels",
        "secrets",
        "skills",
        "skills:social_media_manager",
        "tools",
        "code",
        "security",
        "rlm",
        "self_improve",
        "second_brain",
        "subagents",
        "subagents_running",
        "codemode",
        "integrations",
        "dashboard",
        "shortcuts",
        "notifications",
        "advanced",
        "logs",
        "help",
        "sevn_bot",
        "my_sevn_bot",
    },
)


@dataclass(frozen=True)
class ConfigMenuRefreshContext:
    """Telegram coordinates for in-place ``/config`` menu re-render."""

    chat_id: int
    message_id: int
    topic_id: int | None
    section: ConfigSection
    models_picker_slot: str | None = None
    models_picker_page: int = 0


@dataclass(frozen=True)
class ConfigMenuNavFrame:
    """One screen in the ``/config`` navigation stack (Wave TMF-10)."""

    section: ConfigSection
    models_picker_slot: str | None = None
    models_picker_page: int = 0


@dataclass
class _ConfigMenuNavState:
    """Per-message ``/config`` back-stack (parents only + current screen)."""

    stack: list[ConfigMenuNavFrame]
    current: ConfigMenuNavFrame


def config_menu_nav_key(chat_id: int, message_id: int) -> tuple[int, int]:
    """Return the dict key for one Telegram ``/config`` host message.

    Args:
        chat_id (int): Telegram chat id.
        message_id (int): Host message id.

    Returns:
        tuple[int, int]: ``(chat_id, message_id)``.

    Examples:
        >>> config_menu_nav_key(42, 99)
        (42, 99)
    """
    return (chat_id, message_id)


def get_config_menu_nav(
    router: ChannelRouter, chat_id: int, message_id: int
) -> _ConfigMenuNavState:
    """Load or create navigation state for one ``/config`` message.

    Args:
        router (ChannelRouter): Gateway router holding ``_config_menu_nav``.
        chat_id (int): Telegram chat id.
        message_id (int): Host message id.

    Returns:
        _ConfigMenuNavState: Stack + current frame (defaults to root).

    Examples:
        >>> from sevn.gateway.channel_router import ChannelRouter
        >>> r = ChannelRouter.__new__(ChannelRouter)
        >>> r._config_menu_nav = {}
        >>> get_config_menu_nav(r, 1, 2).current.section
        'root'
    """
    key = config_menu_nav_key(chat_id, message_id)
    state = router._config_menu_nav.get(key)
    if state is None:
        state = _ConfigMenuNavState(stack=[], current=ConfigMenuNavFrame(section="root"))
        router._config_menu_nav[key] = state
    return cast("_ConfigMenuNavState", state)


def config_menu_nav_go(
    router: ChannelRouter,
    chat_id: int,
    message_id: int,
    target: ConfigMenuNavFrame,
) -> ConfigMenuNavFrame:
    """Push *current* onto the stack and navigate to *target*.

    Args:
        router (ChannelRouter): Gateway router.
        chat_id (int): Telegram chat id.
        message_id (int): Host message id.
        target (ConfigMenuNavFrame): Destination screen.

    Returns:
        ConfigMenuNavFrame: The new current frame.

    Examples:
        >>> from sevn.gateway.channel_router import ChannelRouter
        >>> r = ChannelRouter.__new__(ChannelRouter)
        >>> r._config_menu_nav = {}
        >>> f = config_menu_nav_go(r, 1, 2, ConfigMenuNavFrame(section="voice"))
        >>> f.section
        'voice'
    """
    state = get_config_menu_nav(router, chat_id, message_id)
    if state.current != target:
        state.stack.append(state.current)
        state.current = target
    return state.current


def config_menu_nav_push_current(
    router: ChannelRouter,
    chat_id: int,
    message_id: int,
) -> None:
    """Push *current* onto the stack without changing the active frame (overlay screens).

    Args:
        router (ChannelRouter): Gateway router.
        chat_id (int): Telegram chat id.
        message_id (int): Host message id.

    Examples:
        >>> from sevn.gateway.channel_router import ChannelRouter
        >>> r = ChannelRouter.__new__(ChannelRouter)
        >>> r._config_menu_nav = {}
        >>> get_config_menu_nav(r, 1, 2).current.section
        'root'
        >>> config_menu_nav_push_current(r, 1, 2)
        >>> len(get_config_menu_nav(r, 1, 2).stack)
        1
    """
    state = get_config_menu_nav(router, chat_id, message_id)
    state.stack.append(state.current)


def config_menu_nav_pop(
    router: ChannelRouter,
    chat_id: int,
    message_id: int,
) -> ConfigMenuNavFrame:
    """Pop one parent frame and make it current (or root when stack empty).

    Args:
        router (ChannelRouter): Gateway router.
        chat_id (int): Telegram chat id.
        message_id (int): Host message id.

    Returns:
        ConfigMenuNavFrame: Frame to render after Back.

    Examples:
        >>> from sevn.gateway.channel_router import ChannelRouter
        >>> r = ChannelRouter.__new__(ChannelRouter)
        >>> r._config_menu_nav = {}
        >>> _ = config_menu_nav_go(r, 1, 2, ConfigMenuNavFrame(section="voice"))
        >>> config_menu_nav_pop(r, 1, 2).section
        'root'
    """
    state = get_config_menu_nav(router, chat_id, message_id)
    if state.stack:
        state.current = state.stack.pop()
    else:
        state.current = ConfigMenuNavFrame(section="root")
    return state.current


def config_menu_nav_home(
    router: ChannelRouter,
    chat_id: int,
    message_id: int,
) -> ConfigMenuNavFrame:
    """Clear the stack and return to the root tile screen.

    Args:
        router (ChannelRouter): Gateway router.
        chat_id (int): Telegram chat id.
        message_id (int): Host message id.

    Returns:
        ConfigMenuNavFrame: Root frame.

    Examples:
        >>> from sevn.gateway.channel_router import ChannelRouter
        >>> r = ChannelRouter.__new__(ChannelRouter)
        >>> r._config_menu_nav = {}
        >>> _ = config_menu_nav_go(r, 1, 2, ConfigMenuNavFrame(section="voice"))
        >>> config_menu_nav_home(r, 1, 2).section
        'root'
    """
    state = get_config_menu_nav(router, chat_id, message_id)
    state.stack.clear()
    state.current = ConfigMenuNavFrame(section="root")
    return state.current


def config_menu_nav_clear(router: ChannelRouter, chat_id: int, message_id: int) -> None:
    """Drop navigation state when the ``/config`` message is closed.

    Args:
        router (ChannelRouter): Gateway router.
        chat_id (int): Telegram chat id.
        message_id (int): Host message id.

    Examples:
        >>> from sevn.gateway.channel_router import ChannelRouter
        >>> r = ChannelRouter.__new__(ChannelRouter)
        >>> r._config_menu_nav = {}
        >>> _ = get_config_menu_nav(r, 1, 2)
        >>> config_menu_nav_clear(r, 1, 2)
        >>> r._config_menu_nav
        {}
    """
    router._config_menu_nav.pop(config_menu_nav_key(chat_id, message_id), None)


_SHORTCUTS_MENU_LIMIT = 8
_SKILLS_MENU_LIMIT = 6
_TOOLS_PLUGIN_MENU_LIMIT = 6
_INTEGRATIONS_MENU_LIMIT = 8
MODELS_PICKER_PAGE_SIZE = 5

_MODEL_PICKER_SLOT_LABELS: dict[str, str] = {
    "triager": "Triager",
    "tier_b": "Tier B",
    "tier_cd": "Tier C/D",
}

_CONFIG_ROOT_TILES: tuple[tuple[str, str, str], ...] = (
    ("📦 Session", "session", "cfg:section:session"),
    ("🤖 Agents", "agents", "cfg:section:agents"),
    ("🧠 Models", "models", "cfg:section:models"),
    ("🎙 Voice", "voice", "cfg:section:voice"),
    ("🔌 Channels", "channels", "cfg:section:channels"),
    ("🔐 Secrets", "secrets", "cfg:section:secrets"),
    ("🧩 Skills", "skills", "cfg:section:skills"),
    ("🛠 Tools", "tools", "cfg:section:tools"),
    ("💻 Code", "code", "cfg:section:code"),
    ("🛡 Security", "security", "cfg:section:security"),
    ("🌐 Integrations", "integrations", "cfg:section:integrations"),
    ("📊 Dashboard", "dashboard", "cfg:section:dashboard"),
    ("⌨️ Shortcuts", "shortcuts", "cfg:section:shortcuts"),
    ("🔔 Notifications", "notifications", "cfg:section:notifications"),
    ("⚙️ Advanced", "advanced", "cfg:section:advanced"),
    ("📜 Logs", "logs", "cfg:section:logs"),
    ("❓ Commands", "help", "cfg:section:help"),
    (SEVN_BOT_ROOT_TILE_LABEL, "sevn_bot", "cfg:section:sevn_bot"),
    ("🤖 My sevn bot", "my_sevn_bot", "cfg:section:my_sevn_bot"),
)

_MENU_SECTIONS: frozenset[str] = frozenset({"identity", "quick", "workspace", "diagnostics"})


def web_ui_url_from_workspace(workspace: WorkspaceConfig) -> str | None:
    """Return ``web_ui.url`` when present on the workspace document.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        str | None: Absolute Web UI URL, or ``None`` when unset.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> web_ui_url_from_workspace(WorkspaceConfig.minimal()) is None
        True
        >>> web_ui_url_from_workspace(
        ...     WorkspaceConfig.minimal(web_ui={"url": "https://app.example/"}),
        ... )
        'https://app.example/'
    """
    extra = workspace.model_extra or {}
    block = extra.get("web_ui")
    if isinstance(block, dict):
        raw = block.get("url")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def infer_budget_regime(model_id: str) -> BudgetRegime:
    """Heuristically map a catalog model id to a budget regime label.

    Args:
        model_id (str): Resolved workspace catalog model id.

    Returns:
        BudgetRegime: Best-effort regime for diagnostics display.

    Examples:
        >>> infer_budget_regime("ollama/llama3")
        <BudgetRegime.FREE_LOCAL: 'FREE_LOCAL'>
        >>> infer_budget_regime("minimax/MiniMax-M2.7")
        <BudgetRegime.PER_TOKEN: 'PER_TOKEN'>
    """
    mid = model_id.strip().lower()
    if not mid:
        return BudgetRegime.PER_TOKEN
    if mid.startswith(("ollama/", "lmstudio/", "local/")) or "local" in mid:
        return BudgetRegime.FREE_LOCAL
    if "subscription" in mid or mid.startswith("anthropic/claude-opus"):
        return BudgetRegime.SUBSCRIPTION
    return BudgetRegime.PER_TOKEN


def _menu_chrome(*, include_back: bool = True) -> list[list[dict[str, Any]]]:
    """Return Back / Home / Close navigation row(s) for menu screens.

    Args:
        include_back (bool): When ``False``, omit the Back button (root screen).

    Returns:
        list[list[dict[str, Any]]]: One inline-keyboard row of callback buttons.

    Examples:
        >>> row = _menu_chrome()[0]
        >>> row[0]["callback_data"]
        'nav:back'
    """
    row: list[dict[str, Any]] = []
    if include_back:
        row.append({"text": "⬅ Back", "callback_data": "nav:back"})
    row.append({"text": "🏠 Home", "callback_data": "menu:home"})
    row.append({"text": "❌ Close", "callback_data": "menu:close"})
    return [row]  # one inline-keyboard row


def build_menu_keyboard(
    workspace: WorkspaceConfig,
    *,
    tool_set: MenuToolSurface,
    section: MenuSection = "root",
) -> dict[str, Any]:
    """Build Telegram ``InlineKeyboardMarkup`` for ``/menu`` navigation.

    Sections follow ``plan/telegram-commands-design.md``: Identity/About, Quick
    actions, Workspace, Diagnostics.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        tool_set (MenuToolSurface): Session tool surface (skill counts for About).
        section (MenuSection): Active screen; ``root`` shows the four tiles.

    Returns:
        dict[str, Any]: ``reply_markup``-shaped dict for outbound metadata.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> kb = build_menu_keyboard(
        ...     WorkspaceConfig.minimal(),
        ...     tool_set=_EMPTY_TOOL_SURFACE,
        ... )
        >>> kb["inline_keyboard"][0][0]["callback_data"]
        'menu:section:identity'
    """
    if section == "root":
        rows: list[list[dict[str, Any]]] = [
            [
                {"text": "🪪 Identity/About", "callback_data": "menu:section:identity"},
                {"text": "⚡ Quick actions", "callback_data": "menu:section:quick"},
            ],
            [
                {"text": "🗂 Workspace", "callback_data": "menu:section:workspace"},
                {"text": "🔧 Diagnostics", "callback_data": "menu:section:diagnostics"},
            ],
            [{"text": "⚙️ Open /config", "callback_data": "menu:open_config"}],
        ]
        rows.extend(_menu_chrome(include_back=False))
        return {"inline_keyboard": rows}
    if section == "identity":
        return {"inline_keyboard": _menu_chrome()}
    if section == "quick":
        rows = [
            [
                {"text": "📦 /new", "callback_data": "menu:cmd:new"},
                {"text": "❓ /help", "callback_data": "menu:cmd:help"},
            ],
            [
                {"text": "🎙 /voice", "callback_data": "menu:cmd:voice"},
                {"text": "🧠 /model", "callback_data": "menu:cmd:model"},
            ],
            [
                {"text": "📊 /status", "callback_data": "menu:cmd:status"},
                {"text": "⏹ /stop", "callback_data": "menu:cmd:stop"},
            ],
        ]
        rows.extend(_menu_chrome())
        return {"inline_keyboard": rows}
    if section == "workspace":
        url = web_ui_url_from_workspace(workspace)
        rows_ws: list[list[dict[str, Any]]] = []
        if url:
            rows_ws.append([{"text": "🌐 Open Web UI", "url": url}])
        rows_ws.extend(_menu_chrome())
        return {"inline_keyboard": rows_ws}
    if section == "diagnostics":
        rows = [
            [{"text": "📊 /status", "callback_data": "menu:cmd:status"}],
        ]
        rows.extend(_menu_chrome())
        return {"inline_keyboard": rows}
    rows = [_menu_chrome()[0]]
    return {"inline_keyboard": rows}


def menu_message_text(
    workspace: WorkspaceConfig,
    *,
    tool_set: MenuToolSurface,
    section: MenuSection = "root",
) -> str:
    """Return the menu message body for a screen.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        tool_set (MenuToolSurface): Session tool surface.
        section (MenuSection): Active screen id.

    Returns:
        str: Plain-text caption edited in place with the keyboard.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> menu_message_text(
        ...     WorkspaceConfig.minimal(),
        ...     tool_set=_EMPTY_TOOL_SURFACE,
        ...     section="root",
        ... )
        'sevn — menu'
    """
    if section == "root":
        return "sevn — menu"
    if section == "identity":
        skill_n = len(tool_set.skill_descriptions)
        native_n = len(tool_set.native)
        return (
            "Identity / About\n\n"
            f"Skills indexed: {skill_n}\n"
            f"Native tools: {native_n}\n"
            "Persona files: IDENTITY.md, SOUL.md, USER.md"
        )
    if section == "quick":
        return "Quick actions\n\nTap a command or type it in chat."
    if section == "workspace":
        url = web_ui_url_from_workspace(workspace)
        if url:
            return f"Workspace\n\nWeb UI: {url}"
        return "Workspace\n\nWeb UI URL is not configured in this workspace."
    model_id = resolve_model_slot(workspace, ModelSlot.tier_b)
    regime = infer_budget_regime(model_id)
    return f"Diagnostics\n\nTier B model: {model_id}\nBudget regime: {regime.value}"


def parse_menu_callback_data(data: str) -> tuple[str, str | None] | None:
    """Parse ``menu:*`` and ``nav:*`` callback payloads.

    Args:
        data (str): Raw Telegram ``callback_data``.

    Returns:
        tuple[str, str | None] | None: ``(kind, value)`` where ``kind`` is one of
        ``home``, ``close``, ``back``, ``section``, ``cmd``; ``value`` is set for
        ``section`` and ``cmd`` kinds.

    Examples:
        >>> parse_menu_callback_data("menu:section:quick")
        ('section', 'quick')
        >>> parse_menu_callback_data("nav:back")
        ('back', None)
        >>> parse_menu_callback_data("qa:1:up") is None
        True
    """
    raw = data.strip()
    if raw == "menu:home":
        return ("home", None)
    if raw == "menu:close":
        return ("close", None)
    if raw == "menu:open_config":
        return ("open_config", None)
    if raw == "nav:back":
        return ("back", None)
    if raw.startswith("menu:section:"):
        name = raw.removeprefix("menu:section:").strip().lower()
        if name in _MENU_SECTIONS:
            return ("section", name)
        return None
    if raw.startswith("menu:cmd:"):
        cmd = raw.removeprefix("menu:cmd:").strip().lower()
        if cmd in {"new", "help", "voice", "model", "stop", "status"}:
            return ("cmd", cmd)
        return None
    if raw.startswith(("menu:", "nav:")):
        return None
    return None


def menu_callback_matches(msg: object) -> bool:
    """Return whether ``msg`` is a menu navigation callback or ``/menu`` slash.

    Args:
        msg (object): Duck-typed inbound message with ``text`` and ``metadata``.

    Returns:
        bool: ``True`` for ``menu:*``, ``nav:*``, or bare ``/menu``.

    Examples:
        >>> class _M:
        ...     text = "/menu"
        ...     metadata: dict = {}
        >>> menu_callback_matches(_M())
        True
    """
    text = getattr(msg, "text", "") or ""
    if isinstance(text, str):
        t = text.strip()
        if t == "/menu" or t.startswith("/menu "):
            return True
    md = getattr(msg, "metadata", None)
    if not isinstance(md, dict):
        return False
    raw = md.get("callback_data")
    if not isinstance(raw, str):
        raw = text if isinstance(text, str) else ""
    if not isinstance(raw, str):
        return False
    stripped = raw.strip()
    if parse_menu_callback_data(stripped) is not None:
        return True
    return stripped.startswith(("menu:", "nav:"))


def _quick_actions_config(workspace: WorkspaceConfig) -> TelegramQuickActionsConfig:
    """Return Telegram QA bar visibility flags (defaults all on when unset).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        TelegramQuickActionsConfig: Effective quick-action visibility.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> qa = _quick_actions_config(WorkspaceConfig.minimal())
        >>> qa.show_regen
        True
    """
    channels = workspace.channels
    if channels is not None and channels.telegram is not None:
        qa = channels.telegram.quick_actions
        if qa is not None:
            return qa
    return TelegramQuickActionsConfig()


def _gateway_queue_mode(workspace: WorkspaceConfig) -> str:
    """Return effective ``gateway.queue_mode`` (defaults to ``cancel``).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        str: ``cancel``, ``steer``, or ``multi``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _gateway_queue_mode(WorkspaceConfig.minimal())
        'cancel'
    """
    if workspace.gateway is not None and workspace.gateway.queue_mode is not None:
        return str(workspace.gateway.queue_mode)
    return "cancel"


def _next_queue_mode(current: str) -> str:
    """Return the next queue mode in the cancel → steer → multi cycle.

    Args:
        current (str): Active ``gateway.queue_mode``.

    Returns:
        str: Next mode in ``_QUEUE_MODE_CYCLE``.

    Examples:
        >>> _next_queue_mode("cancel")
        'steer'
        >>> _next_queue_mode("multi")
        'cancel'
    """
    try:
        idx = _QUEUE_MODE_CYCLE.index(current)
    except ValueError:
        idx = 0
    return _QUEUE_MODE_CYCLE[(idx + 1) % len(_QUEUE_MODE_CYCLE)]


def _config_bool_toggle_button(
    label: str,
    path: str,
    *,
    enabled: bool,
) -> dict[str, Any]:
    """Build a ``cfg:toggle:`` button with on/off label state.

    Args:
        label (str): Short button title.
        path (str): Dot path under ``sevn.json``.
        enabled (bool): Current flag value.

    Returns:
        dict[str, Any]: Inline keyboard button dict.

    Examples:
        >>> btn = _config_bool_toggle_button("Regen", "channels.telegram.quick_actions.show_regen", enabled=True)
        >>> btn["callback_data"]
        'cfg:toggle:channels.telegram.quick_actions.show_regen:false'
        >>> '✅' in btn["text"]
        True
    """
    next_val = "false" if enabled else "true"
    state = "✅" if enabled else "off"
    return {
        "text": f"{label} {state}",
        "callback_data": f"cfg:toggle:{path}:{next_val}",
    }


def _build_session_keyboard_rows(workspace: WorkspaceConfig) -> list[list[dict[str, Any]]]:
    """Build Session section toggles for QA bar buttons and queue mode.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_session_keyboard_rows(WorkspaceConfig.minimal())
        >>> rows[0][0]["callback_data"].startswith("cfg:toggle:channels.telegram.quick_actions.")
        True
    """
    qa = _quick_actions_config(workspace)
    specs: tuple[tuple[str, str, bool], ...] = (
        ("Regen", "show_regen", qa.show_regen),
        ("👍 Up", "show_thumbs_up", qa.show_thumbs_up),
        ("👎 Down", "show_thumbs_down", qa.show_thumbs_down),
        ("Share", "show_share", qa.show_share),
        ("Feedback", "show_feedback", qa.show_feedback),
    )
    rows: list[list[dict[str, Any]]] = []
    pair: list[dict[str, Any]] = []
    for label, qa_field, enabled in specs:
        pair.append(
            _config_bool_toggle_button(
                label,
                f"channels.telegram.quick_actions.{qa_field}",
                enabled=enabled,
            ),
        )
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    current = _gateway_queue_mode(workspace)
    nxt = _next_queue_mode(current)
    rows.append(
        [
            {
                "text": f"Queue: {current} (-> {nxt})",
                "callback_data": f"cfg:toggle:gateway.queue_mode:{nxt}",
            },
        ],
    )
    return rows


def _voice_tts_mode(workspace: WorkspaceConfig) -> str:
    """Return effective ``voice.tts_mode`` (defaults to ``off``).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        str: ``off``, ``all``, or ``when_asked``.

    Examples:
        >>> from sevn.config.workspace_config import VoiceConfig, WorkspaceConfig
        >>> _voice_tts_mode(WorkspaceConfig.minimal(voice=VoiceConfig(tts_mode="all")))
        'all'
    """
    if workspace.voice is not None and workspace.voice.tts_mode is not None:
        return str(workspace.voice.tts_mode)
    return "off"


def _security_heuristic_only(workspace: WorkspaceConfig) -> bool:
    """Return whether the inbound scanner runs heuristic-only mode.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        bool: ``True`` when ``security.scanner.heuristic_only`` is set.

    Examples:
        >>> from sevn.config.workspace_config import (
        ...     SecurityScannerSubConfig,
        ...     SecurityWorkspaceConfig,
        ...     WorkspaceConfig,
        ... )
        >>> ws = WorkspaceConfig.minimal(
        ...     security=SecurityWorkspaceConfig(
        ...         scanner=SecurityScannerSubConfig(heuristic_only=True),
        ...     ),
        ... )
        >>> _security_heuristic_only(ws)
        True
    """
    if workspace.security is not None and workspace.security.scanner is not None:
        return bool(workspace.security.scanner.heuristic_only)
    return False


def _build_voice_keyboard_rows(workspace: WorkspaceConfig) -> list[list[dict[str, Any]]]:
    """Build Voice section TTS mode buttons with active-state labels.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_voice_keyboard_rows(WorkspaceConfig.minimal())
        >>> rows[0][0]["callback_data"]
        'cfg:voice:mode:off'
    """
    mode = _voice_tts_mode(workspace)
    rows: list[list[dict[str, Any]]] = []
    for candidate in ("off", "all", "when_asked"):
        label = f"TTS: {candidate}"
        if mode == candidate:
            label = f"{label} ✅"
        rows.append([{"text": label, "callback_data": f"cfg:voice:mode:{candidate}"}])
    rows.append(
        [{"text": f"STT: {_voice_stt_active(workspace)} 🔁", "callback_data": "cfg:voice:stt:next"}]
    )
    return rows


def _voice_stt_active(workspace: WorkspaceConfig) -> str:
    """Return the primary (index-0) speech-to-text provider tag.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        str: First configured ``voice.stt_providers`` tag, or the first
        :data:`DEFAULT_VOICE_STT_PROVIDERS` entry when unset.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _voice_stt_active(WorkspaceConfig.minimal())
        'whisper_cpp'
    """
    configured = workspace.voice.stt_providers if workspace.voice else None
    if configured:
        return configured[0]
    return DEFAULT_VOICE_STT_PROVIDERS[0]


def _owner_scanner_overrides(workspace: WorkspaceConfig) -> tuple[bool, bool, bool]:
    """Resolve owner-chat LLM-guard kill-switches.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        tuple[bool, bool, bool]: ``(disable_text, disable_links, disable_documents)``
        toggles from ``channels.telegram.owner_scanner_overrides``; ``(False, False, False)``
        when the subtree is absent.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _owner_scanner_overrides(WorkspaceConfig.minimal())
        (False, False, False)
    """
    tg = workspace.channels.telegram if workspace.channels is not None else None
    ovr = tg.owner_scanner_overrides if tg is not None else None
    if ovr is None:
        return (False, False, False)
    return (
        bool(ovr.disable_text),
        bool(ovr.disable_links),
        bool(ovr.disable_documents),
    )


def _build_security_keyboard_rows(workspace: WorkspaceConfig) -> list[list[dict[str, Any]]]:
    """Build Security section toggles for scanner heuristic-only mode and owner overrides.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_security_keyboard_rows(WorkspaceConfig.minimal())
        >>> rows[0][0]["callback_data"].startswith("cfg:toggle:security.scanner.heuristic_only:")
        True
        >>> any(
        ...     "owner_scanner_overrides.disable_text" in (b.get("callback_data") or "")
        ...     for row in rows for b in row
        ... )
        True
    """
    enabled = _security_heuristic_only(workspace)
    dt, dl, dd = _owner_scanner_overrides(workspace)
    rows: list[list[dict[str, Any]]] = [
        [
            _config_bool_toggle_button(
                "Heuristic-only",
                "security.scanner.heuristic_only",
                enabled=enabled,
            ),
        ],
        [
            _config_bool_toggle_button(
                "Skip guard on my text",
                "channels.telegram.owner_scanner_overrides.disable_text",
                enabled=dt,
            ),
        ],
        [
            _config_bool_toggle_button(
                "Skip guard on my links",
                "channels.telegram.owner_scanner_overrides.disable_links",
                enabled=dl,
            ),
        ],
        [
            _config_bool_toggle_button(
                "Skip guard on my documents",
                "channels.telegram.owner_scanner_overrides.disable_documents",
                enabled=dd,
            ),
        ],
    ]
    url = _mission_control_url(workspace, fragment="security")
    if url:
        rows.append([{"text": "🌐 Open Security tab", "url": url}])
    return rows


_NOTIFY_POLICY_CYCLE: tuple[str, ...] = ("all", "errors", "none")
_DM_POLICY_CYCLE: tuple[str, ...] = ("open", "pairing", "allowlist", "disabled")
_RLM_C_D_BACKEND_CYCLE: tuple[str, ...] = ("dspy", "lambda_rlm")


def _telegram_reply_keyboard_enabled(workspace: WorkspaceConfig) -> bool:
    """Return effective ``channels.telegram.reply_keyboard.enabled``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        bool: ``True`` when the persistent reply keyboard is enabled (default).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _telegram_reply_keyboard_enabled(WorkspaceConfig.minimal())
        True
    """
    channels = workspace.channels
    if channels is not None and channels.telegram is not None:
        rk = channels.telegram.reply_keyboard
        if rk is not None:
            return bool(rk.enabled)
    return True


def _telegram_show_routing(workspace: WorkspaceConfig) -> bool:
    """Return effective ``channels.telegram.show_routing``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        bool: ``True`` when routing footer is shown on Telegram replies.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _telegram_show_routing(WorkspaceConfig.minimal())
        False
    """
    channels = workspace.channels
    if channels is not None and channels.telegram is not None:
        return bool(channels.telegram.show_routing)
    return False


def _telegram_dm_policy(workspace: WorkspaceConfig) -> str:
    """Return configured DM policy string (defaults to ``open``).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        str: Lowercase policy label for display.

    Examples:
        >>> from sevn.config.workspace_config import TelegramChannelConfig, WorkspaceConfig
        >>> from sevn.config.workspace_config import ChannelsWorkspaceSectionConfig
        >>> ws = WorkspaceConfig.minimal(
        ...     channels=ChannelsWorkspaceSectionConfig(
        ...         telegram=TelegramChannelConfig(dm_policy="PAIRING"),
        ...     ),
        ... )
        >>> _telegram_dm_policy(ws)
        'pairing'
    """
    channels = workspace.channels
    if channels is not None and channels.telegram is not None:
        raw = channels.telegram.dm_policy
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower()
    return "open"


def _telegram_mode(workspace: WorkspaceConfig) -> str:
    """Return Telegram adapter mode (``poll`` or ``webhook``).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        str: Effective mode label.

    Examples:
        >>> from sevn.config.workspace_config import TelegramChannelConfig, WorkspaceConfig
        >>> from sevn.config.workspace_config import ChannelsWorkspaceSectionConfig
        >>> ws = WorkspaceConfig.minimal(
        ...     channels=ChannelsWorkspaceSectionConfig(
        ...         telegram=TelegramChannelConfig(mode="webhook"),
        ...     ),
        ... )
        >>> _telegram_mode(ws)
        'webhook'
    """
    channels = workspace.channels
    if channels is not None and channels.telegram is not None:
        raw = channels.telegram.mode
        if isinstance(raw, str) and raw.strip():
            mode = raw.strip().lower()
            if mode == "webhook":
                return "webhook"
    return "poll"


def _telegram_notify_policy(workspace: WorkspaceConfig) -> str:
    """Return ``channels.telegram.telegram_notify_policy`` when set.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        str: Policy label (defaults to ``all``).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _telegram_notify_policy(WorkspaceConfig.minimal())
        'all'
    """
    channels = workspace.channels
    if channels is not None and channels.telegram is not None:
        extra = channels.telegram.model_extra or {}
        raw = extra.get("telegram_notify_policy")
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower()
    return "all"


def _gateway_auto_resume_b(workspace: WorkspaceConfig) -> bool:
    """Return effective ``gateway.restart.auto_resume_b``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        bool: Tier-B auto-resume flag.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _gateway_auto_resume_b(WorkspaceConfig.minimal()) == DEFAULT_GATEWAY_AUTO_RESUME_B
        True
    """
    if workspace.gateway is not None and workspace.gateway.restart is not None:
        return bool(workspace.gateway.restart.auto_resume_b)
    return DEFAULT_GATEWAY_AUTO_RESUME_B


def _tracing_redaction_enabled(workspace: WorkspaceConfig) -> bool:
    """Return effective ``tracing.redaction.enabled``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        bool: Whether trace redaction wraps sinks.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _tracing_redaction_enabled(WorkspaceConfig.minimal()) == DEFAULT_TRACE_REDACTION_ENABLED
        True
    """
    if workspace.tracing is not None and workspace.tracing.redaction is not None:
        return bool(workspace.tracing.redaction.enabled)
    return DEFAULT_TRACE_REDACTION_ENABLED


def _logfire_export_enabled(workspace: WorkspaceConfig) -> bool:
    """Return whether a ``logfire`` sink is configured in ``tracing.sinks[]``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        bool: True when Logfire export is enabled in config.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _logfire_export_enabled(WorkspaceConfig.minimal())
        False
    """
    return logfire_export_status(workspace).enabled


def _webchat_tts_inline_enabled(workspace: WorkspaceConfig) -> bool:
    """Return effective ``channels.webchat.tts_inline`` (defaults to ``True``).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        bool: ``True`` when webchat emits inline audio frames alongside text.

    Examples:
        >>> from sevn.config.workspace_config import (
        ...     ChannelsWorkspaceSectionConfig,
        ...     WebChatChannelConfig,
        ...     WorkspaceConfig,
        ... )
        >>> ws = WorkspaceConfig.minimal(
        ...     channels=ChannelsWorkspaceSectionConfig(
        ...         webchat=WebChatChannelConfig(tts_inline=False),
        ...     ),
        ... )
        >>> _webchat_tts_inline_enabled(ws)
        False
    """
    channels = workspace.channels
    if channels is not None and channels.webchat is not None:
        return bool(channels.webchat.tts_inline)
    from sevn.config.defaults import DEFAULT_WEBCHAT_TTS_INLINE

    return bool(DEFAULT_WEBCHAT_TTS_INLINE)


def _build_dm_policy_cycle_row(workspace: WorkspaceConfig) -> list[dict[str, Any]]:
    """Build one inline row cycling ``channels.telegram.dm_policy``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[dict[str, Any]]: Single-button row for DM policy cycle.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> row = _build_dm_policy_cycle_row(WorkspaceConfig.minimal())
        >>> row[0]["callback_data"].startswith("cfg:toggle:channels.telegram.dm_policy:")
        True
    """
    current = _telegram_dm_policy(workspace)
    try:
        idx = _DM_POLICY_CYCLE.index(current)
    except ValueError:
        idx = 0
    nxt = _DM_POLICY_CYCLE[(idx + 1) % len(_DM_POLICY_CYCLE)]
    return [
        {
            "text": f"DM policy: {current} (→{nxt})",
            "callback_data": f"cfg:toggle:channels.telegram.dm_policy:{nxt}",
        },
    ]


def _build_channels_keyboard_rows(workspace: WorkspaceConfig) -> list[list[dict[str, Any]]]:
    """Build Channels section toggles for reply keyboard, routing, and DM policy.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_channels_keyboard_rows(WorkspaceConfig.minimal())
        >>> rows[0][0]["callback_data"].startswith("cfg:toggle:channels.telegram.reply_keyboard.enabled:")
        True
    """
    rk = _telegram_reply_keyboard_enabled(workspace)
    routing = _telegram_show_routing(workspace)
    rows: list[list[dict[str, Any]]] = [
        [
            _config_bool_toggle_button(
                "Reply keyboard",
                "channels.telegram.reply_keyboard.enabled",
                enabled=rk,
            ),
        ],
        [
            _config_bool_toggle_button(
                "Show routing",
                "channels.telegram.show_routing",
                enabled=routing,
            ),
        ],
        _build_dm_policy_cycle_row(workspace),
    ]
    if _schema_has_config_path("channels.webchat.tts_inline"):
        wc_tts = _webchat_tts_inline_enabled(workspace)
        rows.append(
            [
                _config_bool_toggle_button(
                    "Webchat TTS inline",
                    "channels.webchat.tts_inline",
                    enabled=wc_tts,
                ),
            ],
        )
    return rows


def _build_notifications_keyboard_rows(workspace: WorkspaceConfig) -> list[list[dict[str, Any]]]:
    """Build Notifications section cycle button for ``telegram_notify_policy``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_notifications_keyboard_rows(WorkspaceConfig.minimal())
        >>> rows[0][0]["callback_data"].startswith(
        ...     "cfg:toggle:channels.telegram.telegram_notify_policy:",
        ... )
        True
    """
    current = _telegram_notify_policy(workspace)
    try:
        idx = _NOTIFY_POLICY_CYCLE.index(current)
    except ValueError:
        idx = 0
    nxt = _NOTIFY_POLICY_CYCLE[(idx + 1) % len(_NOTIFY_POLICY_CYCLE)]
    return [
        [
            {
                "text": f"Notify policy: {current} (→{nxt})",
                "callback_data": f"cfg:toggle:channels.telegram.telegram_notify_policy:{nxt}",
            },
        ],
    ]


_ADVANCED_SECTION_TILES: tuple[tuple[str, str], ...] = (
    ("🧭 RLM", "rlm"),
    ("📈 Self-Improve", "self_improve"),
    ("📚 Second Brain", "second_brain"),
    ("🤖 Sub-agents", "subagents"),
    ("🧪 CodeMode", "codemode"),
)

_SUBAGENT_ROLES: tuple[str, ...] = ("triager", "tier_b", "tier_c", "tier_d")
_QUEUE_MODE_CYCLE: tuple[str, ...] = ("cancel", "steer", "multi")


def _build_advanced_keyboard_rows(
    workspace: WorkspaceConfig,
    *,
    is_owner: bool = False,
) -> list[list[dict[str, Any]]]:
    """Build Advanced section toggles, nested section links, and Mission Control.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        is_owner (bool): When ``True``, render gateway/proxy restart buttons.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_advanced_keyboard_rows(WorkspaceConfig.minimal())
        >>> rows[0][0]["callback_data"].startswith("cfg:toggle:gateway.restart.auto_resume_b:")
        True
        >>> any(btn["callback_data"] == "cfg:section:codemode" for row in rows for btn in row)
        True
    """
    _ = is_owner
    auto_resume = _gateway_auto_resume_b(workspace)
    redaction = _tracing_redaction_enabled(workspace)
    rows: list[list[dict[str, Any]]] = [
        [
            _config_bool_toggle_button(
                "Auto-resume tier B",
                "gateway.restart.auto_resume_b",
                enabled=auto_resume,
            ),
        ],
        [
            _config_bool_toggle_button(
                "Trace redaction",
                "tracing.redaction.enabled",
                enabled=redaction,
            ),
        ],
    ]
    pair_row: list[dict[str, Any]] = []
    for label, sid in _ADVANCED_SECTION_TILES:
        pair_row.append({"text": label, "callback_data": f"cfg:section:{sid}"})
        if len(pair_row) == 2:
            rows.append(pair_row)
            pair_row = []
    if pair_row:
        rows.append(pair_row)
    url = web_ui_url_from_workspace(workspace)
    if url:
        rows.append([{"text": "🌐 Open Mission Control", "url": url}])
    return rows


def _build_codemode_keyboard_rows(workspace: WorkspaceConfig) -> list[list[dict[str, Any]]]:
    """Build CodeMode section toggle for tier-B ``run_code`` composites (W8).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_codemode_keyboard_rows(WorkspaceConfig.minimal())
        >>> any(
        ...     btn["callback_data"].startswith("cfg:toggle:agent.codemode.enabled:")
        ...     for row in rows for btn in row
        ... )
        True
    """
    rows: list[list[dict[str, Any]]] = []
    if _schema_has_config_path("agent.codemode.enabled"):
        rows.append(
            [
                _config_bool_toggle_button(
                    "CodeMode",
                    "agent.codemode.enabled",
                    enabled=codemode_enabled(workspace),
                ),
            ],
        )
    return rows


def _build_sevn_bot_keyboard_rows(workspace: WorkspaceConfig) -> list[list[dict[str, Any]]]:
    """Build sevn.bot upstream section rows (sync, bugs, features).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_sevn_bot_keyboard_rows(WorkspaceConfig.minimal())
        >>> rows[0][0]["callback_data"]
        'act:sevn_bot:sync'
    """
    _ = workspace
    return [
        [{"text": "🔄 Sync (latest)", "callback_data": "act:sevn_bot:sync"}],
        [
            {"text": "🐛 Bugs", "callback_data": "act:sevn_bot:bugs"},
            {"text": "✨ Features", "callback_data": "act:sevn_bot:features"},
        ],
    ]


def _build_my_sevn_bot_keyboard_rows(
    workspace: WorkspaceConfig,
    *,
    is_owner: bool = False,
) -> list[list[dict[str, Any]]]:
    """Build My Sevn.bot operator rows (restart, deployment id).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        is_owner (bool): When ``True``, render gateway/proxy restart buttons.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_my_sevn_bot_keyboard_rows(WorkspaceConfig.minimal(), is_owner=True)
        >>> rows[-1][0]["callback_data"]
        'cfg:logs:deployment_id'
    """
    _ = workspace
    rows: list[list[dict[str, Any]]] = []
    if is_owner:
        rows.append([{"text": "🔄 Restart gateway", "callback_data": "act:gateway:restart"}])
        rows.append([{"text": "🔄 Restart proxy", "callback_data": "act:proxy:restart"}])
    rows.append([{"text": "🆔 Deployment id", "callback_data": "cfg:logs:deployment_id"}])
    return rows


def _build_logs_keyboard_rows(workspace: WorkspaceConfig) -> list[list[dict[str, Any]]]:
    """Build Logs section action rows for ``/config`` (`specs/18-channel-telegram.md` §4.7).

    The keyboard offers tail/grep/traces actions plus a redaction toggle and a
    deployment id button. All callbacks use the ``cfg:logs:`` namespace per the
    spec (not ``cfg:diag:``); :func:`gate_config_keyboard_rows` is applied by
    :func:`build_config_menu_keyboard` and locks every action with a 🚧 prefix
    until the corresponding ``C20.*`` registry rows are added to
    ``menu_readiness._READY_SPEC_IDS`` (Wave TE-9).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_logs_keyboard_rows(WorkspaceConfig.minimal())
        >>> rows[0][0]["callback_data"]
        'cfg:logs:tail:gateway:0'
        >>> rows[-1][0]["callback_data"].startswith("cfg:logs:")
        True
    """
    redaction = _tracing_redaction_enabled(workspace)
    logfire = _logfire_export_enabled(workspace)
    return [
        [
            {"text": "📄 Tail gateway", "callback_data": "cfg:logs:tail:gateway:0"},
            {"text": "📄 Tail proxy", "callback_data": "cfg:logs:tail:proxy:0"},
        ],
        [
            {"text": "🔍 Grep logs", "callback_data": "form:logs:grep"},
        ],
        [
            {"text": "🧵 Recent traces", "callback_data": "cfg:logs:traces:0"},
            {"text": "🔎 Trace by id", "callback_data": "form:logs:span_id"},
        ],
        [
            {
                "text": f"Logfire export: {'on' if logfire else 'off'} (toggle)",
                "callback_data": "cfg:logs:toggle_logfire",
            },
        ],
        [
            {"text": "🔑 Set Logfire token", "callback_data": "form:logs:logfire_token"},
        ],
        [
            {
                "text": f"Trace redaction: {'on' if redaction else 'off'} (toggle)",
                "callback_data": "cfg:logs:toggle_redaction",
            },
        ],
    ]


def build_service_restart_confirm_keyboard(
    service: Literal["gateway", "proxy"],
) -> list[list[dict[str, Any]]]:
    """Build Confirm/Cancel rows for a two-step service restart prompt.

    Args:
        service (Literal["gateway", "proxy"]): Which unit is being restarted.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> rows = build_service_restart_confirm_keyboard("gateway")
        >>> rows[0][0]["callback_data"]
        'act:gateway:restart:confirm'
        >>> rows[0][1]["callback_data"]
        'act:gateway:restart:cancel'
    """
    return [
        [
            {
                "text": "✅ Confirm restart",
                "callback_data": f"act:{service}:restart:confirm",
            },
            {
                "text": "Cancel",
                "callback_data": f"act:{service}:restart:cancel",
            },
        ],
    ]


def service_restart_confirm_message(service: Literal["gateway", "proxy"]) -> str:
    """Return caption text for the restart confirmation screen.

    Args:
        service (Literal["gateway", "proxy"]): Which unit is being restarted.

    Returns:
        str: Human-readable confirmation prompt.

    Examples:
        >>> "Restart gateway" in service_restart_confirm_message("gateway")
        True
        >>> "Restart proxy" in service_restart_confirm_message("proxy")
        True
    """
    label = "gateway" if service == "gateway" else "proxy"
    if service == "gateway":
        detail = (
            "Telegram will disconnect briefly. When the proxy unit is installed, "
            "it restarts together with the gateway."
        )
    else:
        detail = "Outbound provider traffic may pause while the proxy restarts."
    return f"My sevn bot\n\nRestart {label}?\n{detail}\nTap Confirm to proceed."


def _build_models_keyboard_rows(workspace: WorkspaceConfig) -> list[list[dict[str, Any]]]:
    """Build Models section toggles, slot pickers, swap, and Mission Control link.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_models_keyboard_rows(WorkspaceConfig.minimal())
        >>> rows[0][0]["callback_data"].startswith("cfg:toggle:providers.use_main_model_for_all:")
        True
        >>> any(btn.get("callback_data") == "cfg:models:swap" for row in rows for btn in row)
        True
    """
    enabled = use_main_model_for_all(workspace)
    rows: list[list[dict[str, Any]]] = [
        [
            _config_bool_toggle_button(
                "Unified model",
                "providers.use_main_model_for_all",
                enabled=enabled,
            ),
        ],
    ]
    picker_row: list[dict[str, Any]] = []
    for slot_key in model_picker_slot_keys():
        label = _MODEL_PICKER_SLOT_LABELS.get(slot_key, slot_key)
        picker_row.append(
            {
                "text": f"Pick {label}",
                "callback_data": f"cfg:models:page:{slot_key}:0",
            },
        )
    if picker_row:
        rows.append(picker_row)
    rows.append([{"text": "↔ Swap last model", "callback_data": "cfg:models:swap"}])
    url = _mission_control_url(workspace, fragment="models")
    if url:
        rows.append([{"text": "🌐 Open Models tab", "url": url}])
    return rows


def _short_model_label(model_id: str, *, max_len: int = 28) -> str:
    """Truncate a catalog model id for Telegram button labels.

    Args:
        model_id (str): Full catalog model id.
        max_len (int): Maximum label length.

    Returns:
        str: Truncated label with ellipsis when needed.

    Examples:
        >>> _short_model_label("openai/gpt-4o-mini")
        'openai/gpt-4o-mini'
        >>> len(_short_model_label("x" * 40)) <= 28
        True
    """
    mid = model_id.strip()
    if len(mid) <= max_len:
        return mid
    return mid[: max_len - 1] + "…"


def _resolved_model_for_picker_slot(workspace: WorkspaceConfig, slot_key: str) -> str:
    """Return the active model id for a picker slot key.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        slot_key (str): Picker key (``triager``, ``tier_b``, ``tier_cd``).

    Returns:
        str: Resolved model id for display/selection markers.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> ws = WorkspaceConfig.minimal(
        ...     providers={"tier_default": {"triager": "test/triager"}},
        ... )
        >>> _resolved_model_for_picker_slot(ws, "triager")
        'test/triager'
    """
    slots = model_picker_slots_for_key(slot_key)
    if not slots:
        return ""
    return resolve_model_slot(workspace, slots[0])


def _build_models_picker_keyboard_rows(
    workspace: WorkspaceConfig,
    slot_key: str,
    page: int,
) -> list[list[dict[str, Any]]]:
    """Build paginated model picker rows for one slot.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        slot_key (str): Picker key (``triager``, ``tier_b``, ``tier_cd``).
        page (int): Zero-based page index.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> ws = WorkspaceConfig.minimal(
        ...     providers={
        ...         "models": {"openai/gpt-4o-mini": {}},
        ...         "tier_default": {"triager": "openai/gpt-4o-mini"},
        ...     },
        ... )
        >>> rows = _build_models_picker_keyboard_rows(ws, "triager", 0)
        >>> rows[0][0]["callback_data"].startswith("cfg:models:pick:triager:")
        True
    """
    catalog = list_catalog_model_ids(workspace)
    if not catalog:
        return [[{"text": "⬅ Models", "callback_data": "cfg:section:models"}]]
    page_size = MODELS_PICKER_PAGE_SIZE
    total_pages = max(1, (len(catalog) + page_size - 1) // page_size)
    safe_page = max(0, min(page, total_pages - 1))
    start = safe_page * page_size
    end = min(start + page_size, len(catalog))
    current = _resolved_model_for_picker_slot(workspace, slot_key)
    rows: list[list[dict[str, Any]]] = []
    for idx in range(start, end):
        model_id = catalog[idx]
        mark = " ✅" if model_id == current else ""
        rows.append(
            [
                {
                    "text": f"{_short_model_label(model_id)}{mark}",
                    "callback_data": f"cfg:models:pick:{slot_key}:{idx}",
                },
            ],
        )
    nav: list[dict[str, Any]] = []
    if safe_page > 0:
        nav.append(
            {
                "text": "◀ Prev",
                "callback_data": f"cfg:models:page:{slot_key}:{safe_page - 1}",
            },
        )
    if safe_page + 1 < total_pages:
        nav.append(
            {
                "text": "▶ Next",
                "callback_data": f"cfg:models:page:{slot_key}:{safe_page + 1}",
            },
        )
    if nav:
        rows.append(nav)
    rows.append([{"text": "⬅ Models", "callback_data": "cfg:section:models"}])
    return rows


def _build_dashboard_keyboard_rows(workspace: WorkspaceConfig) -> list[list[dict[str, Any]]]:
    """Build Dashboard section action buttons (pin refresh + Mission Control URL).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_dashboard_keyboard_rows(WorkspaceConfig.minimal())
        >>> rows[0][0]["callback_data"]
        'cfg:dashboard:create_pin'
    """
    rows: list[list[dict[str, Any]]] = [
        [{"text": "📌 Create/update pin", "callback_data": "cfg:dashboard:create_pin"}],
        [{"text": "🔄 Refresh pin", "callback_data": "cfg:dashboard:refresh_pin"}],
        [{"text": "📤 Unpin", "callback_data": "cfg:dashboard:unpin"}],
    ]
    url = web_ui_url_from_workspace(workspace)
    if url:
        rows.append([{"text": "🌐 Open Mission Control", "url": url}])
    return rows


def _build_shortcuts_keyboard_rows(
    content_root: Path,
    *,
    user_id: str,
    is_owner: bool = True,
) -> list[list[dict[str, Any]]]:
    """Build Shortcuts section list rows with per-row delete and Add form launcher.

    Args:
        content_root (Path): Workspace content root for ``shortcuts.json``.
        user_id (str): Telegram user id string.
        is_owner (bool): Whether the user is workspace owner.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> rows = _build_shortcuts_keyboard_rows(
        ...     Path(tempfile.mkdtemp()),
        ...     user_id="1",
        ... )
        >>> rows[-1][0]["callback_data"]
        'form:shortcut_add'
    """
    rows: list[list[dict[str, Any]]] = []
    for row in list_visible_shortcuts(content_root, user_id=user_id, is_owner=is_owner)[
        :_SHORTCUTS_MENU_LIMIT
    ]:
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        rows.append(
            [{"text": f"🗑 /{name}", "callback_data": f"act:shortcut_delete:{name}"}],
        )
    rows.append([{"text": "+ Add shortcut", "callback_data": "form:shortcut_add"}])
    return rows


def _build_help_keyboard_rows() -> list[list[dict[str, Any]]]:
    """Help section has no action rows — catalog lives in the caption (``menu_readiness``).

    Returns:
        list[list[dict[str, Any]]]: Empty list; chrome added by ``build_config_menu_keyboard``.

    Examples:
        >>> _build_help_keyboard_rows()
        []
    """
    return []


@lru_cache(maxsize=1)
def _workspace_json_schema() -> dict[str, Any]:
    """Load ``infra/sevn.schema.json`` once for menu toggle gating.

    Returns:
        dict[str, Any]: Parsed workspace JSON Schema root, or ``{}`` when unavailable.

    Examples:
        >>> doc = _workspace_json_schema()
        >>> isinstance(doc, dict)
        True
    """
    from sevn.cli.workspace_schema import load_workspace_json_schema

    try:
        return load_workspace_json_schema()
    except (FileNotFoundError, OSError, ValueError):
        return {}


def _schema_has_config_path(dotted: str) -> bool:
    """Return whether ``dotted`` is declared in the workspace schema tree.

    Args:
        dotted (str): Dot path under ``sevn.json``.

    Returns:
        bool: ``True`` when the path is schema-declared.

    Examples:
        >>> _schema_has_config_path("code_understanding.code_review_graph.enabled")
        True
        >>> _schema_has_config_path("rlm.enabled")
        False
    """
    from sevn.cli.workspace_schema import dotted_path_in_schema

    return dotted_path_in_schema(_workspace_json_schema(), dotted)


def _schema_node_for_path(dotted: str) -> dict[str, Any] | None:
    """Return the JSON Schema node at ``dotted`` when every segment is declared.

    Args:
        dotted (str): Dot path under ``sevn.json``.

    Returns:
        dict[str, Any] | None: Schema object at the path, or ``None``.

    Examples:
        >>> node = _schema_node_for_path("skills")
        >>> isinstance(node, dict)
        True
    """
    parts = [p for p in dotted.split(".") if p]
    if not parts:
        return None
    node: Any = _workspace_json_schema()
    for key in parts:
        if not isinstance(node, dict):
            return None
        props = node.get("properties")
        if not isinstance(props, dict) or key not in props:
            return None
        node = props[key]
    return node if isinstance(node, dict) else None


def _schema_parent_allows_child_enabled(parent: str) -> bool:
    """Return whether children under ``parent`` may declare an ``enabled`` boolean.

    Args:
        parent (str): Dot path to a schema object (e.g. ``skills``, ``tools``).

    Returns:
        bool: ``True`` when ``additionalProperties`` allows per-child ``enabled``.

    Examples:
        >>> _schema_parent_allows_child_enabled("skills")
        True
        >>> _schema_parent_allows_child_enabled("tools")
        True
    """
    node = _schema_node_for_path(parent)
    if not isinstance(node, dict):
        return False
    ap = node.get("additionalProperties")
    if ap is True:
        return True
    if isinstance(ap, dict):
        props = ap.get("properties")
        if isinstance(props, dict) and "enabled" in props:
            return True
    return False


def _schema_has_skill_enabled_toggle(skill_key: str) -> bool:
    """Return whether ``skills.<skill_key>.enabled`` is a writable config path.

    Args:
        skill_key (str): Snake-case skill id under ``skills``.

    Returns:
        bool: ``True`` when toggles may be rendered for the skill.

    Examples:
        >>> _schema_has_skill_enabled_toggle("computer_use")
        True
    """
    if _schema_has_config_path(f"skills.{skill_key}.enabled"):
        return True
    return _schema_parent_allows_child_enabled("skills")


def _schema_has_tool_plugin_enabled_toggle(plugin_id: str) -> bool:
    """Return whether ``tools.<plugin_id>.enabled`` is a writable config path.

    Args:
        plugin_id (str): Plugin prefix from the ``sevn.tools`` entry-point group.

    Returns:
        bool: ``True`` when toggles may be rendered for the plugin.

    Examples:
        >>> _schema_has_tool_plugin_enabled_toggle("canvas")
        True
    """
    if _schema_has_config_path(f"tools.{plugin_id}.enabled"):
        return True
    return _schema_parent_allows_child_enabled("tools")


def _schema_has_integration_enabled_toggle(integration_id: str) -> bool:
    """Return whether ``integration.<id>.enabled`` is schema-declared.

    Args:
        integration_id (str): Integration id from workspace or secret refs.

    Returns:
        bool: ``True`` when per-id integration toggles may be rendered.

    Examples:
        >>> _schema_has_integration_enabled_toggle("cursor")
        False
    """
    return _schema_has_config_path(f"integration.{integration_id}.enabled")


def _skill_json_key(skill_id: str) -> str:
    """Map a skill registry id to its ``sevn.json`` skills block key.

    Args:
        skill_id (str): Skill id from the registry index.

    Returns:
        str: Snake-case key under ``skills``.

    Examples:
        >>> _skill_json_key("computer-use")
        'computer_use'
    """
    return skill_id.replace("-", "_")


def _short_menu_label(name: str, *, max_len: int = 14) -> str:
    """Truncate a button label for Telegram inline keyboard width.

    Args:
        name (str): Raw skill, plugin, or integration id.
        max_len (int): Maximum visible characters.

    Returns:
        str: Display label.

    Examples:
        >>> _short_menu_label("computer_use")
        'computer use'
    """
    compact = name.replace("_", " ").replace("-", " ").strip()
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 1] + "…"


def _OPT_IN_DEFAULT_FALSE_SKILL_KEYS() -> frozenset[str]:
    """Return skill config keys that default to disabled when ``enabled`` is unset.

    Returns:
        frozenset[str]: Snake-case keys for opt-in bundled skills.

    Examples:
        >>> "computer_use" in _OPT_IN_DEFAULT_FALSE_SKILL_KEYS()
        True
        >>> "cua_agent" in _OPT_IN_DEFAULT_FALSE_SKILL_KEYS()
        True
        >>> "lume" in _OPT_IN_DEFAULT_FALSE_SKILL_KEYS()
        True
    """
    return frozenset(
        {"computer_use", "cua_agent", "lume", "openwiki", "cursor_cloud", "social_media_manager"}
    )


def _skill_enabled(workspace: WorkspaceConfig, skill_key: str) -> bool:
    """Read ``skills.<skill_key>.enabled`` (defaults to enabled when unset).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        skill_key (str): Snake-case skill id.

    Returns:
        bool: Effective enabled flag.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _skill_enabled(WorkspaceConfig.minimal(), "computer_use")
        False
        >>> _skill_enabled(WorkspaceConfig.minimal(), "cua_agent")
        False
        >>> _skill_enabled(WorkspaceConfig.minimal(), "lume")
        False
        >>> _skill_enabled(WorkspaceConfig.minimal(), "openwiki")
        False
        >>> _skill_enabled(WorkspaceConfig.minimal(), "lcm")
        True
    """
    opt_in_default_false = _OPT_IN_DEFAULT_FALSE_SKILL_KEYS()
    skills = workspace.skills
    if not isinstance(skills, dict):
        return skill_key not in opt_in_default_false
    block = skills.get(skill_key)
    if isinstance(block, dict) and "enabled" in block:
        return bool(block["enabled"])
    return skill_key not in opt_in_default_false


def _tool_plugin_enabled(workspace: WorkspaceConfig, plugin_id: str) -> bool:
    """Read ``tools.<plugin_id>.enabled`` (defaults to enabled when unset).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        plugin_id (str): Entry-point prefix under ``sevn.tools``.

    Returns:
        bool: Effective enabled flag.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _tool_plugin_enabled(WorkspaceConfig.minimal(), "canvas")
        True
    """
    tools = workspace.tools
    if not isinstance(tools, dict):
        return True
    block = tools.get(plugin_id)
    if isinstance(block, dict) and "enabled" in block:
        return bool(block["enabled"])
    return True


def _integration_enabled(
    workspace: WorkspaceConfig,
    integration_id: str,
    *,
    raw_doc: dict[str, Any] | None,
) -> bool:
    """Read ``integration.<id>.enabled`` from workspace or raw ``sevn.json``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        integration_id (str): Integration id.
        raw_doc (dict[str, Any] | None): Optional raw document.

    Returns:
        bool: Effective enabled flag (defaults to ``False`` when unset).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _integration_enabled(WorkspaceConfig.minimal(), "cursor", raw_doc=None)
        False
    """
    from sevn.onboarding.web_app import _get_nested

    path = f"integration.{integration_id}.enabled"
    if raw_doc is not None:
        val = _get_nested(raw_doc, path)
        if isinstance(val, bool):
            return val
    extra = workspace.model_extra or {}
    block = extra.get("integration")
    if isinstance(block, dict):
        entry = block.get(integration_id)
        if isinstance(entry, dict) and "enabled" in entry:
            return bool(entry["enabled"])
    return False


def _list_tool_plugin_prefixes() -> tuple[str, ...]:
    """List unique plugin prefixes from the ``sevn.tools`` entry-point group.

    Returns:
        tuple[str, ...]: Sorted plugin ids (first segment of entry-point names).

    Examples:
        >>> prefixes = _list_tool_plugin_prefixes()
        >>> isinstance(prefixes, tuple)
        True
    """
    from importlib.metadata import entry_points

    from sevn.tools.registry import _PACKAGED_TOOLS_ENTRY_SKIP

    try:
        eps = entry_points(group="sevn.tools")
    except TypeError:
        eps = entry_points().select(group="sevn.tools")
    seen: dict[str, None] = {}
    for ep in eps or ():
        if ep.name in _PACKAGED_TOOLS_ENTRY_SKIP:
            continue
        prefix = ep.name.split(".", maxsplit=1)[0]
        seen.setdefault(prefix, None)
    return tuple(sorted(seen))


_MC_FRAGMENT_TO_TAB_SLUG: dict[str, str] = {
    "security": "security",
    "models": "providers-llms",
    "identity": "agent-config",
    "skills": "skills",
    "tools": "tools-permissions",
    "rlm": "rlm-training",
    "traces": "traces",
    "second_brain": "second-brain",
    "integrations": "tunnels-infra",
    "code": "code-understanding",
}


def _mission_control_url(
    workspace: WorkspaceConfig,
    *,
    fragment: str | None = None,
) -> str | None:
    """Resolve Mission Control URL with optional tab path segment.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        fragment (str | None): Legacy fragment id mapped to ``/mission/{slug}`` path routes.

    Returns:
        str | None: Absolute URL when ``web_ui.url`` is configured.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _mission_control_url(WorkspaceConfig.minimal()) is None
        True
        >>> _mission_control_url(
        ...     WorkspaceConfig.minimal(web_ui={"url": "https://app.example/"}),
        ...     fragment="traces",
        ... )
        'https://app.example/mission/traces'
    """
    base = web_ui_url_from_workspace(workspace)
    if not base:
        return None
    base = base.rstrip("/")
    if fragment:
        slug = _MC_FRAGMENT_TO_TAB_SLUG.get(fragment, fragment.replace("_", "-"))
        return f"{base}/mission/{slug}"
    return base


def _config_menu_tool_surface(
    workspace: WorkspaceConfig,
    content_root: Path | None,
) -> MenuToolSurface:
    """Best-effort registry snapshot for Skills/Tools diagnostics copy.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        content_root (Path | None): Workspace content root.

    Returns:
        MenuToolSurface: Session registry snapshot or empty surface.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> surf = _config_menu_tool_surface(WorkspaceConfig.minimal(), None)
        >>> len(surf.skill_descriptions)
        0
    """
    if content_root is None:
        return _EMPTY_TOOL_SURFACE
    from sevn.skills.errors import SkillExecutionError
    from sevn.tools.registry import build_session_registry

    try:
        _, tool_set = build_session_registry(
            workspace_config=workspace,
            workspace_root=content_root,
        )
    except (OSError, SkillExecutionError, ValueError):
        return _EMPTY_TOOL_SURFACE
    return cast("MenuToolSurface", tool_set)


def _agent_display_name(
    workspace: WorkspaceConfig,
    content_root: Path | None,
) -> str:
    """Resolve agent display name from ``sevn.json`` and optional ``IDENTITY.md``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        content_root (Path | None): Workspace content root.

    Returns:
        str: Operator-facing agent name.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _agent_display_name(WorkspaceConfig.minimal(), None)
        'Sevn'
    """
    name = resolve_agent_display_name(workspace.model_dump(mode="json"))
    if content_root is None:
        return name
    identity = content_root / "IDENTITY.md"
    if not identity.is_file():
        return name
    for line in identity.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("Name:"):
            parsed = stripped.removeprefix("Name:").strip()
            if parsed and not parsed.startswith("(") and parsed != "{{AGENT_NAME}}":
                return parsed
    return name


def _lambda_rlm_enabled(workspace: WorkspaceConfig) -> bool:
    """Return ``executors.tier_cd.lambda_rlm.enabled`` (defaults false).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        bool: Opt-in λ-RLM gate value.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _lambda_rlm_enabled(WorkspaceConfig.minimal())
        False
    """
    executors = workspace.executors
    if executors is not None and executors.tier_cd is not None:
        block = executors.tier_cd.lambda_rlm
        if block is not None:
            return bool(block.enabled)
    return DEFAULT_TIER_CD_LAMBDA_RLM_ENABLED


def _rlm_c_d_backend(workspace: WorkspaceConfig) -> str:
    """Return effective ``rlm.c_d_backend``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        str: ``dspy`` or ``lambda_rlm``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _rlm_c_d_backend(WorkspaceConfig.minimal())
        'dspy'
    """
    if workspace.rlm is not None and workspace.rlm.c_d_backend is not None:
        return str(workspace.rlm.c_d_backend)
    return DEFAULT_RLM_C_D_BACKEND


def _rlm_repl_lifetime(workspace: WorkspaceConfig) -> str:
    """Return effective ``rlm.repl_lifetime``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        str: REPL lifetime mode.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _rlm_repl_lifetime(WorkspaceConfig.minimal())
        'per_turn'
    """
    if workspace.rlm is not None and workspace.rlm.repl_lifetime is not None:
        return str(workspace.rlm.repl_lifetime)
    return DEFAULT_RLM_REPL_LIFETIME


def _triager_tier_b_caps(workspace: WorkspaceConfig) -> tuple[int, int]:
    """Return Triager tier-B tool and skill caps.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        tuple[int, int]: ``(tool_cap, skill_cap)``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _triager_tier_b_caps(WorkspaceConfig.minimal())
        (5, 7)
    """
    triager = workspace.triager
    if triager is not None:
        return triager.tier_b_tool_cap, triager.tier_b_skill_cap
    return DEFAULT_TRIAGER_TIER_B_TOOL_CAP, DEFAULT_TRIAGER_TIER_B_SKILL_CAP


def _mycode_enabled(workspace: WorkspaceConfig) -> bool:
    """Return ``code_understanding.mycode.enabled``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        bool: MYCODE layer toggle.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _mycode_enabled(WorkspaceConfig.minimal())
        True
    """
    cu = workspace.code_understanding
    if cu is not None:
        return bool(cu.mycode.enabled)
    return True


def _code_review_graph_enabled(workspace: WorkspaceConfig) -> bool:
    """Return ``code_understanding.code_review_graph.enabled``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        bool: Code review graph toggle.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _code_review_graph_enabled(WorkspaceConfig.minimal())
        False
    """
    cu = workspace.code_understanding
    if cu is not None:
        return bool(cu.code_review_graph.enabled)
    return False


def _build_agents_keyboard_rows(workspace: WorkspaceConfig) -> list[list[dict[str, Any]]]:
    """Build Agents section display-name form and dashboard links (no Advanced fallback).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_agents_keyboard_rows(WorkspaceConfig.minimal())
        >>> rows[0][0]["callback_data"]
        'form:agent:display_name'
    """
    rows: list[list[dict[str, Any]]] = [
        [{"text": "✏️ Edit display name", "callback_data": "form:agent:display_name"}],
    ]
    persona_url = _mission_control_url(workspace)
    if persona_url:
        rows.append([{"text": "✏️ Edit persona", "url": persona_url}])
    identity_url = _mission_control_url(workspace, fragment="identity")
    if identity_url:
        rows.append([{"text": "📄 Open IDENTITY.md", "url": identity_url}])
    return rows


def _build_skills_keyboard_rows(
    workspace: WorkspaceConfig,
    content_root: Path | None = None,
) -> list[list[dict[str, Any]]]:
    """Build Skills section URL, schema-gated skill toggles, and optional refresh.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        content_root (Path | None): Workspace content root for registry snapshot.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _build_skills_keyboard_rows(WorkspaceConfig.minimal())
        [[{'text': '📱 Social Media Manager', 'callback_data': 'cfg:section:skills:social_media_manager'}]]
    """
    rows: list[list[dict[str, Any]]] = []
    url = _mission_control_url(workspace, fragment="skills")
    if url:
        rows.append([{"text": "🌐 Open Skills tab", "url": url}])
    if _schema_parent_allows_child_enabled("skills"):
        surface = _config_menu_tool_surface(workspace, content_root)
        for skill_id in sorted(surface.skill_descriptions)[:_SKILLS_MENU_LIMIT]:
            skill_key = _skill_json_key(skill_id)
            if not _schema_has_skill_enabled_toggle(skill_key):
                continue
            rows.append(
                [
                    _config_bool_toggle_button(
                        _short_menu_label(skill_id),
                        f"skills.{skill_key}.enabled",
                        enabled=_skill_enabled(workspace, skill_key),
                    ),
                ],
            )
    if content_root is not None:
        rows.append([{"text": "🔄 Refresh index", "callback_data": "cfg:skills:refresh"}])
    if _schema_has_config_path("skills.social_media_manager"):
        rows.append(
            [
                {
                    "text": "📱 Social Media Manager",
                    "callback_data": "cfg:section:skills:social_media_manager",
                },
            ],
        )
    return rows


def _build_tools_keyboard_rows(
    workspace: WorkspaceConfig,
    content_root: Path | None = None,
) -> list[list[dict[str, Any]]]:
    """Build Tools section URL, plugin toggles, and MCP dashboard link when configured.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        content_root (Path | None): Unused; reserved for future registry hooks.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _build_tools_keyboard_rows(WorkspaceConfig.minimal())
        []
    """
    _ = content_root
    rows: list[list[dict[str, Any]]] = []
    url = _mission_control_url(workspace, fragment="tools")
    if url:
        rows.append([{"text": "🌐 Open Tools tab", "url": url}])
        rows.append([{"text": "🔌 MCP servers", "url": url}])
    if _schema_parent_allows_child_enabled("tools"):
        for plugin_id in _list_tool_plugin_prefixes()[:_TOOLS_PLUGIN_MENU_LIMIT]:
            if not _schema_has_tool_plugin_enabled_toggle(plugin_id):
                continue
            rows.append(
                [
                    _config_bool_toggle_button(
                        _short_menu_label(plugin_id),
                        f"tools.{plugin_id}.enabled",
                        enabled=_tool_plugin_enabled(workspace, plugin_id),
                    ),
                ],
            )
    return rows


def _rlm_lambda_tool_allowlist(workspace: WorkspaceConfig) -> list[str]:
    """Return ``rlm.lambda_tool_allowlist`` entries when configured.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[str]: Allowlist tool names (may be empty).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _rlm_lambda_tool_allowlist(WorkspaceConfig.minimal())
        []
    """
    if workspace.rlm is None:
        return []
    return [str(x) for x in workspace.rlm.lambda_tool_allowlist if str(x).strip()]


def _rlm_c_d_backend_cycle_options(workspace: WorkspaceConfig) -> tuple[str, ...]:
    """Return menu-valid ``rlm.c_d_backend`` values for cycling.

    ``lambda_rlm`` is offered only when λ-RLM is enabled and the tool allowlist is
    non-empty (``specs/21-executor-tier-cd.md`` §5).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        tuple[str, ...]: Ordered cycle values (length 1 ⇒ omit cycle button).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _rlm_c_d_backend_cycle_options(WorkspaceConfig.minimal())
        ('dspy',)
    """
    if not _schema_has_config_path("rlm.c_d_backend"):
        return ()
    if not _lambda_rlm_enabled(workspace):
        return ("dspy",)
    if _rlm_lambda_tool_allowlist(workspace):
        return _RLM_C_D_BACKEND_CYCLE
    return ("dspy",)


def _build_rlm_c_d_backend_cycle_row(workspace: WorkspaceConfig) -> list[dict[str, Any]] | None:
    """Build one inline row cycling ``rlm.c_d_backend`` when multiple values are valid.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[dict[str, Any]] | None: Single-button row, or ``None`` when cycle is N/A.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _build_rlm_c_d_backend_cycle_row(WorkspaceConfig.minimal()) is None
        True
    """
    options = _rlm_c_d_backend_cycle_options(workspace)
    if len(options) <= 1:
        return None
    current = _rlm_c_d_backend(workspace)
    try:
        idx = options.index(current)
    except ValueError:
        idx = 0
    nxt = options[(idx + 1) % len(options)]
    return [
        {
            "text": f"C/D backend: {current} (→{nxt})",
            "callback_data": f"cfg:toggle:rlm.c_d_backend:{nxt}",
        },
    ]


def _build_rlm_keyboard_rows(workspace: WorkspaceConfig) -> list[list[dict[str, Any]]]:
    """Build RLM section schema-gated toggles.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_rlm_keyboard_rows(WorkspaceConfig.minimal())
        >>> rows[0][0]["callback_data"].startswith("cfg:toggle:executors.tier_cd.lambda_rlm.enabled:")
        True
    """
    rows: list[list[dict[str, Any]]] = []
    if _schema_has_config_path("executors.tier_cd.lambda_rlm.enabled"):
        rows.append(
            [
                _config_bool_toggle_button(
                    "λ-RLM",
                    "executors.tier_cd.lambda_rlm.enabled",
                    enabled=_lambda_rlm_enabled(workspace),
                ),
            ],
        )
    cycle_row = _build_rlm_c_d_backend_cycle_row(workspace)
    if cycle_row is not None:
        rows.append(cycle_row)
    url = _mission_control_url(workspace, fragment="rlm")
    if url:
        rows.append([{"text": "🌐 Open RLM tab", "url": url}])
    return rows


def _raw_sevn_doc(content_root: Path | None) -> dict[str, Any] | None:
    """Load ``sevn.json`` from *content_root* when present.

    Args:
        content_root (Path | None): Workspace content root.

    Returns:
        dict[str, Any] | None: Parsed document or ``None`` when unavailable.

    Examples:
        >>> _raw_sevn_doc(None) is None
        True
    """
    if content_root is None:
        return None
    sevn_json = content_root / "sevn.json"
    if not sevn_json.is_file():
        return None
    try:
        return load_raw_sevn_json(sevn_json)
    except (OSError, json.JSONDecodeError):
        return None


def _collect_secret_ref_logical_keys(node: object, *, keys: set[str]) -> None:
    """Walk a JSON tree and collect ``${SECRET:…}`` logical keys into *keys*.

    Args:
        node (object): JSON subtree.
        keys (set[str]): Accumulator for logical secret keys (mutated in place).

    Returns:
        None: Mutates *keys* only.

    Examples:
        >>> acc: set[str] = set()
        >>> _collect_secret_ref_logical_keys("${SECRET:keychain:telegram.bot_token}", keys=acc)
        >>> "telegram.bot_token" in acc
        True
    """
    if isinstance(node, str):
        for match in _SECRET_REF_PATTERN.finditer(node):
            inner = match.group(1)
            if ":" in inner:
                _, logical = inner.split(":", 1)
                logical_key = logical.strip()
                if logical_key:
                    keys.add(logical_key)
        return
    if isinstance(node, dict):
        for value in node.values():
            _collect_secret_ref_logical_keys(value, keys=keys)
        return
    if isinstance(node, list):
        for item in node:
            _collect_secret_ref_logical_keys(item, keys=keys)


def _list_secret_ref_keys(doc: dict[str, Any] | None) -> list[str]:
    """Return sorted unique ``${SECRET:…}`` logical keys in *doc*.

    Args:
        doc (dict[str, Any] | None): Workspace JSON document.

    Returns:
        list[str]: Distinct logical secret keys (no values).

    Examples:
        >>> _list_secret_ref_keys({"x": "${SECRET:k:alpha}"})
        ['alpha']
    """
    if doc is None:
        return []
    keys: set[str] = set()
    _collect_secret_ref_logical_keys(doc, keys=keys)
    return sorted(keys)


def _count_secret_refs(doc: dict[str, Any] | None) -> int:
    """Return the number of unique ``${SECRET:…}`` logical keys in *doc*.

    Args:
        doc (dict[str, Any] | None): Workspace JSON document.

    Returns:
        int: Count of distinct secret reference logical keys (no values).

    Examples:
        >>> _count_secret_refs({"channels": {"telegram": {"bot_token_ref": "${SECRET:k:a}"}}})
        1
    """
    if doc is None:
        return 0
    keys: set[str] = set()
    _collect_secret_ref_logical_keys(doc, keys=keys)
    return len(keys)


def _self_improve_enabled(workspace: WorkspaceConfig) -> bool:
    """Return effective ``self_improve.enabled``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        bool: Self-improve loop toggle.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _self_improve_enabled(WorkspaceConfig.minimal()) == DEFAULT_SELF_IMPROVE_ENABLED
        True
    """
    si = workspace.self_improve
    if si is not None:
        return bool(si.enabled)
    return DEFAULT_SELF_IMPROVE_ENABLED


def _second_brain_enabled(workspace: WorkspaceConfig) -> bool:
    """Return effective ``second_brain.enabled``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        bool: Second Brain toggle.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _second_brain_enabled(WorkspaceConfig.minimal()) == DEFAULT_SECOND_BRAIN_ENABLED
        True
    """
    sb = workspace.second_brain
    if sb is not None:
        return bool(sb.enabled)
    return DEFAULT_SECOND_BRAIN_ENABLED


def _second_brain_ingest_mode(workspace: WorkspaceConfig) -> str:
    """Return ``second_brain.ingest_batch_cron`` for display.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        str: Ingest schedule label.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _second_brain_ingest_mode(WorkspaceConfig.minimal())
        'weekly'
    """
    sb = workspace.second_brain
    if sb is not None and sb.ingest_batch_cron:
        return str(sb.ingest_batch_cron)
    return "weekly"


def _second_brain_vault_display(content_root: Path, workspace: WorkspaceConfig) -> str:
    """Return workspace-relative vault path for Second Brain captions.

    Args:
        content_root (Path): Workspace content root.
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        str: Resolved vault path or legacy default label.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _second_brain_vault_display(Path("/tmp"), WorkspaceConfig.minimal()).startswith("second_brain/users/")
        True
    """
    sb = workspace.second_brain
    scope = effective_scope(None, sb)
    scope_root = resolve_scope_root(content_root, sb, scope)
    return display_scope_root_relative(content_root, scope_root)


def _configured_integration_ids(
    workspace: WorkspaceConfig,
    *,
    raw_doc: dict[str, Any] | None = None,
) -> list[str]:
    """List configured integration ids (names only, no secret values).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        raw_doc (dict[str, Any] | None): Optional raw ``sevn.json`` for ref scan.

    Returns:
        list[str]: Sorted integration ids.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _configured_integration_ids(WorkspaceConfig.minimal())
        []
    """
    ids: set[str] = set()
    extra = workspace.model_extra or {}
    block = extra.get("integration")
    if isinstance(block, dict):
        for key in block:
            stripped = str(key).strip()
            if stripped:
                ids.add(stripped)
    skills = workspace.skills
    if isinstance(skills, dict):
        cursor = skills.get("cursor_cloud")
        if isinstance(cursor, dict) and cursor.get("enabled"):
            ids.add("cursor")
    if raw_doc is not None:
        secret_keys: set[str] = set()
        _collect_secret_ref_logical_keys(raw_doc, keys=secret_keys)
        for key in secret_keys:
            if key.startswith("integration."):
                part = key.removeprefix("integration.").split(".", 1)[0]
                if part:
                    ids.add(part)
    return sorted(ids)


def _build_secrets_keyboard_rows() -> list[list[dict[str, Any]]]:
    """Build Secrets section form launcher (no secret values).

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> rows = _build_secrets_keyboard_rows()
        >>> rows[0][0]["callback_data"]
        'form:secret_wizard'
    """
    return [[{"text": "+ Add secret", "callback_data": "form:secret_wizard"}]]


def _build_self_improve_keyboard_rows(workspace: WorkspaceConfig) -> list[list[dict[str, Any]]]:
    """Build Self-Improve section ``self_improve.enabled`` toggle.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_self_improve_keyboard_rows(WorkspaceConfig.minimal())
        >>> rows[0][0]["callback_data"].startswith("cfg:toggle:self_improve.enabled:")
        True
    """
    enabled = _self_improve_enabled(workspace)
    rows: list[list[dict[str, Any]]] = [
        [
            _config_bool_toggle_button(
                "Self-improve",
                "self_improve.enabled",
                enabled=enabled,
            ),
        ],
    ]
    url = _mission_control_url(workspace, fragment="traces")
    if url:
        rows.append([{"text": "📈 View jobs / Traces", "url": url}])
    return rows


def _build_second_brain_keyboard_rows(workspace: WorkspaceConfig) -> list[list[dict[str, Any]]]:
    """Build Second Brain section ``second_brain.enabled`` toggle.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_second_brain_keyboard_rows(WorkspaceConfig.minimal())
        >>> rows[0][0]["callback_data"].startswith("cfg:toggle:second_brain.enabled:")
        True
    """
    enabled = _second_brain_enabled(workspace)
    rows: list[list[dict[str, Any]]] = [
        [
            _config_bool_toggle_button(
                "Second Brain",
                "second_brain.enabled",
                enabled=enabled,
            ),
        ],
        [
            {"text": "📁 Set vault path", "callback_data": "form:second_brain_vault_path"},
            {"text": "🗂️ Browse folders", "callback_data": "form:second_brain_vault_browse"},
        ],
    ]
    url = _mission_control_url(workspace, fragment="second_brain")
    if url:
        rows.append([{"text": "🌐 Open Second Brain tab", "url": url}])
    return rows


def _subagents_enabled(workspace: WorkspaceConfig) -> bool:
    """Return whether the sub-agent supervisor is enabled (D2).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        bool: ``subagents.enabled`` (default ``True``).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _subagents_enabled(WorkspaceConfig.minimal())
        True
    """
    cfg = workspace.subagents
    if cfg is None:
        return True
    return bool(cfg.enabled)


def _subagents_role_label(role: str) -> str:
    """Map internal role id to a short menu label.

    Args:
        role (str): ``triager`` / ``tier_b`` / ``tier_c`` / ``tier_d``.

    Returns:
        str: Human-readable label.

    Examples:
        >>> _subagents_role_label("tier_b")
        'Tier B'
    """
    labels = {
        "triager": "Triager",
        "tier_b": "Tier B",
        "tier_c": "Tier C",
        "tier_d": "Tier D",
    }
    return labels.get(role, role.replace("_", " ").title())


def _build_subagents_keyboard_rows(
    workspace: WorkspaceConfig,
    *,
    level1_count: int = 0,
    level2_count: int = 0,
) -> list[list[dict[str, Any]]]:
    """Build Sub-agents section toggles, limit forms, queue cycle, and Running link.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        level1_count (int): Live level-1 running count from the registry.
        level2_count (int): Live level-2 running count from the registry.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_subagents_keyboard_rows(WorkspaceConfig.minimal())
        >>> rows[0][0]["callback_data"].startswith("cfg:toggle:subagents.enabled:")
        True
    """
    enabled = _subagents_enabled(workspace)
    rows: list[list[dict[str, Any]]] = [
        [
            _config_bool_toggle_button(
                "Sub-agents",
                "subagents.enabled",
                enabled=enabled,
            ),
        ],
        [
            {
                "text": f"Running L1:{level1_count} L2:{level2_count}",
                "callback_data": "cfg:section:subagents_running",
            },
        ],
        [
            {
                "text": "Global override",
                "callback_data": "form:subagents_max_override",
            },
        ],
    ]
    mode = _gateway_queue_mode(workspace)
    nxt = _next_queue_mode(mode)
    rows.append(
        [
            {
                "text": f"Queue: {mode} (-> {nxt})",
                "callback_data": f"cfg:toggle:gateway.queue_mode:{nxt}",
            },
        ],
    )
    pair: list[dict[str, Any]] = []
    for role in _SUBAGENT_ROLES:
        pair.append(
            {
                "text": f"Limits {_subagents_role_label(role)}",
                "callback_data": f"form:subagents_limits:{role}",
            },
        )
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    url = _mission_control_url(workspace, fragment="subagents")
    if url:
        rows.append([{"text": "🌐 Open Sub-agents panel", "url": url}])
    return rows


def _build_subagents_running_keyboard_rows(
    running_rows: tuple[dict[str, Any], ...],
    *,
    is_owner: bool,
) -> list[list[dict[str, Any]]]:
    """Build Running submenu kill buttons (owner-only) for active sub-agent runs.

    Args:
        running_rows (tuple[dict[str, Any], ...]): Serialized running rows (id/role/level).
        is_owner (bool): When ``False``, omit kill buttons.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> rows = _build_subagents_running_keyboard_rows(
        ...     ({"id": "a1", "role": "tier_b", "level": 1, "task_summary": "x"},),
        ...     is_owner=True,
        ... )
        >>> rows[0][0]["callback_data"]
        'act:subagents:kill:a1'
    """
    rows: list[list[dict[str, Any]]] = []
    if running_rows and is_owner:
        for row in running_rows[:8]:
            run_id = str(row.get("id", "")).strip()
            if not run_id:
                continue
            role = str(row.get("role", "?"))
            level = row.get("level", "?")
            rows.append(
                [
                    {
                        "text": f"Kill {run_id} L{level} {role}",
                        "callback_data": f"act:subagents:kill:{run_id}",
                    },
                ],
            )
        rows.append(
            [
                {
                    "text": "Kill all L1",
                    "callback_data": "act:subagents:kill_all",
                },
            ],
        )
    rows.append([{"text": "⬅ Sub-agents", "callback_data": "cfg:section:subagents"}])
    return rows


def _build_integrations_keyboard_rows(
    workspace: WorkspaceConfig,
    content_root: Path | None = None,
) -> list[list[dict[str, Any]]]:
    """Build Integrations URL, schema-gated per-id toggles, and refresh list.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        content_root (Path | None): Workspace content root for id discovery.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_integrations_keyboard_rows(WorkspaceConfig.minimal())
        >>> rows[0][0]["callback_data"]
        'cfg:integrations:refresh'
    """
    rows: list[list[dict[str, Any]]] = []
    url = _mission_control_url(workspace, fragment="integrations")
    if url:
        rows.append([{"text": "+ Add integration", "url": url}])
    raw_doc = _raw_sevn_doc(content_root)
    for integration_id in _configured_integration_ids(workspace, raw_doc=raw_doc)[
        :_INTEGRATIONS_MENU_LIMIT
    ]:
        if not _schema_has_integration_enabled_toggle(integration_id):
            continue
        path = f"integration.{integration_id}.enabled"
        rows.append(
            [
                _config_bool_toggle_button(
                    _short_menu_label(integration_id),
                    path,
                    enabled=_integration_enabled(
                        workspace,
                        integration_id,
                        raw_doc=raw_doc,
                    ),
                ),
            ],
        )
    rows.append([{"text": "🔄 Refresh list", "callback_data": "cfg:integrations:refresh"}])
    return rows


def _build_code_keyboard_rows(workspace: WorkspaceConfig) -> list[list[dict[str, Any]]]:
    """Build Code section schema-gated layer toggles.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = _build_code_keyboard_rows(WorkspaceConfig.minimal())
        >>> any(
        ...     btn["callback_data"].startswith("cfg:toggle:code_understanding.code_review_graph.enabled:")
        ...     for row in rows for btn in row
        ... )
        True
    """
    rows: list[list[dict[str, Any]]] = []
    if _schema_has_config_path("code_understanding.mycode.enabled"):
        rows.append(
            [
                _config_bool_toggle_button(
                    "MYCODE",
                    "code_understanding.mycode.enabled",
                    enabled=_mycode_enabled(workspace),
                ),
            ],
        )
    if _schema_has_config_path("code_understanding.code_review_graph.enabled"):
        rows.append(
            [
                _config_bool_toggle_button(
                    "Review graph",
                    "code_understanding.code_review_graph.enabled",
                    enabled=_code_review_graph_enabled(workspace),
                ),
            ],
        )
    url = _mission_control_url(workspace, fragment="code")
    if url:
        rows.append([{"text": "🌐 Open Code tab", "url": url}])
    return rows


def _config_chrome(*, include_back: bool = True) -> list[list[dict[str, Any]]]:
    """Return Help / Back / Home / Close rows for ``/config`` screens.

    Args:
        include_back (bool): When ``False``, omit the Back button (root screen).

    Returns:
        list[list[dict[str, Any]]]: One inline-keyboard row of callback buttons.

    Examples:
        >>> _config_chrome()[0][0]["callback_data"]
        'cfg:nav:back'
    """
    row: list[dict[str, Any]] = []
    if include_back:
        row.append({"text": "⬅ Back", "callback_data": "cfg:nav:back"})
    row.append({"text": "❓ Help", "callback_data": "cfg:nav:help"})
    row.append({"text": "🏠 Home", "callback_data": "cfg:nav:home"})
    row.append({"text": "❌ Close", "callback_data": "cfg:nav:close"})
    return [row]


async def subagent_menu_snapshot_from_router(
    router: ChannelRouter | None,
) -> tuple[int, int, tuple[dict[str, Any], ...]]:
    """Fetch live sub-agent counts and running rows for Telegram menu captions.

    Args:
        router (ChannelRouter | None): Gateway router (may lack supervisor when unwired).

    Returns:
        tuple[int, int, tuple[dict[str, Any], ...]]: ``(level1_count, level2_count, running_rows)``.

    Examples:
        >>> import asyncio
        >>> asyncio.run(subagent_menu_snapshot_from_router(None))
        (0, 0, ())
    """
    if router is None:
        return 0, 0, ()
    supervisor = getattr(router, "_subagent_supervisor", None)
    if supervisor is None:
        return 0, 0, ()
    from sevn.gateway.mission.mission_subagents_snapshot import _serialize_subagent_run

    counts_map = await supervisor.registry.counts()
    level1 = sum(count for (level, _role), count in counts_map.items() if level == 1)
    level2 = sum(count for (level, _role), count in counts_map.items() if level == 2)
    runs = await supervisor.registry.running()
    rows = tuple(
        _serialize_subagent_run(run)
        for run in sorted(runs, key=lambda row: (row.level, row.role, row.id))
    )
    return level1, level2, rows


def build_config_menu_keyboard(
    workspace: WorkspaceConfig,
    *,
    section: ConfigSection = "root",
    content_root: Path | None = None,
    user_id: str | None = None,
    is_owner: bool = True,
    models_picker_slot: str | None = None,
    models_picker_page: int = 0,
    subagent_level1_count: int = 0,
    subagent_level2_count: int = 0,
    subagent_running_rows: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    """Build the 18-tile ``/config`` inline keyboard (`plan/telegram-commands-design.md` §5.1).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        section (ConfigSection): Active screen; ``root`` shows the 18 tiles.
        content_root (Path | None): Workspace content root (required for Shortcuts rows).
        user_id (str | None): Telegram user id for shortcut visibility filtering.
        is_owner (bool): Whether the user is workspace owner.
        models_picker_slot (str | None): When set on ``models`` section, show paginated picker.
        models_picker_page (int): Zero-based picker page index.
        subagent_level1_count (int): Live L1 count for ``subagents`` section caption/button.
        subagent_level2_count (int): Live L2 count for ``subagents`` section caption/button.
        subagent_running_rows (tuple[dict[str, Any], ...]): Serialized running rows for kill UI.

    Returns:
        dict[str, Any]: ``reply_markup``-shaped dict for outbound metadata.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> kb = build_config_menu_keyboard(WorkspaceConfig.minimal())
        >>> kb["inline_keyboard"][0][0]["callback_data"].startswith("cfg:section:")
        True
    """
    if section == "root":
        rows: list[list[dict[str, Any]]] = []
        pair_row: list[dict[str, Any]] = []
        for label, _sid, cb in _CONFIG_ROOT_TILES:
            pair_row.append({"text": label, "callback_data": cb})
            if len(pair_row) == 2:
                rows.append(pair_row)
                pair_row = []
        if pair_row:
            rows.append(pair_row)
        rows.extend(_config_chrome(include_back=False))
        return {"inline_keyboard": rows}
    if section == "session":
        rows_sec = _build_session_keyboard_rows(workspace)
    elif section == "help":
        rows_sec = _build_help_keyboard_rows()
    elif section == "voice":
        rows_sec = _build_voice_keyboard_rows(workspace)
    elif section == "security":
        rows_sec = _build_security_keyboard_rows(workspace)
    elif section == "models":
        if models_picker_slot and model_picker_slots_for_key(models_picker_slot):
            rows_sec = _build_models_picker_keyboard_rows(
                workspace,
                models_picker_slot,
                models_picker_page,
            )
        else:
            rows_sec = _build_models_keyboard_rows(workspace)
    elif section == "dashboard":
        rows_sec = _build_dashboard_keyboard_rows(workspace)
    elif section == "channels":
        rows_sec = _build_channels_keyboard_rows(workspace)
    elif section == "notifications":
        rows_sec = _build_notifications_keyboard_rows(workspace)
    elif section == "advanced":
        rows_sec = _build_advanced_keyboard_rows(workspace, is_owner=is_owner)
    elif section == "codemode":
        rows_sec = _build_codemode_keyboard_rows(workspace)
    elif section == "logs":
        rows_sec = _build_logs_keyboard_rows(workspace)
    elif section == "shortcuts":
        if content_root is not None:
            rows_sec = _build_shortcuts_keyboard_rows(
                content_root,
                user_id=user_id or "",
                is_owner=is_owner,
            )
        else:
            rows_sec = [[{"text": "+ Add shortcut", "callback_data": "form:shortcut_add"}]]
    elif section == "agents":
        rows_sec = _build_agents_keyboard_rows(workspace)
    elif section == "skills":
        rows_sec = _build_skills_keyboard_rows(workspace, content_root)
    elif section == "skills:social_media_manager":
        rows_sec = build_social_media_manager_keyboard_rows(workspace, content_root)
    elif section == "tools":
        rows_sec = _build_tools_keyboard_rows(workspace, content_root)
    elif section == "rlm":
        rows_sec = _build_rlm_keyboard_rows(workspace)
    elif section == "code":
        rows_sec = _build_code_keyboard_rows(workspace)
    elif section == "secrets":
        rows_sec = _build_secrets_keyboard_rows()
    elif section == "self_improve":
        rows_sec = _build_self_improve_keyboard_rows(workspace)
    elif section == "second_brain":
        rows_sec = _build_second_brain_keyboard_rows(workspace)
    elif section == "subagents":
        rows_sec = _build_subagents_keyboard_rows(
            workspace,
            level1_count=subagent_level1_count,
            level2_count=subagent_level2_count,
        )
    elif section == "subagents_running":
        rows_sec = _build_subagents_running_keyboard_rows(
            subagent_running_rows,
            is_owner=is_owner,
        )
    elif section == "integrations":
        rows_sec = _build_integrations_keyboard_rows(workspace, content_root)
    elif section == "sevn_bot":
        rows_sec = _build_sevn_bot_keyboard_rows(workspace)
    elif section == "my_sevn_bot":
        rows_sec = _build_my_sevn_bot_keyboard_rows(workspace, is_owner=is_owner)
    else:
        rows_sec = [[{"text": "Coming soon", "callback_data": f"cfg:section:{section}"}]]
    rows_sec.extend(_config_chrome())
    return {"inline_keyboard": rows_sec}


def _apply_operator_readiness_gate(markup: dict[str, Any]) -> dict[str, Any]:
    """Lock non-Ready section buttons; keep nav chrome row intact.

    Args:
        markup (dict[str, Any]): ``reply_markup`` dict from ``build_config_menu_keyboard``.

    Returns:
        dict[str, Any]: Gated markup for live Telegram render.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> raw = build_config_menu_keyboard(WorkspaceConfig.minimal(), section="session")
        >>> gated = _apply_operator_readiness_gate(raw)
        >>> "inline_keyboard" in gated
        True
    """
    from sevn.gateway.menu.menu_readiness import gate_config_keyboard_rows

    rows = markup.get("inline_keyboard")
    if not isinstance(rows, list) or len(rows) < 2:
        return markup
    chrome = rows[-1:]
    body = rows[:-1]
    return {"inline_keyboard": gate_config_keyboard_rows(body) + chrome}


async def refresh_config_menu_message(
    adapter: Any,
    ctx: ConfigMenuRefreshContext,
    workspace: WorkspaceConfig,
    *,
    section: ConfigSection | None = None,
    content_root: Path | None = None,
    user_id: str | None = None,
    is_owner: bool = True,
    models_picker_slot: str | None = None,
    models_picker_page: int | None = None,
    router: ChannelRouter | None = None,
) -> bool:
    """Re-edit the originating ``/config`` message caption and keyboard.

    Args:
        adapter (object): Channel adapter exposing Telegram edit helpers.
        ctx (ConfigMenuRefreshContext): Source message coordinates.
        workspace (WorkspaceConfig): Parsed workspace settings (post-mutation).
        section (ConfigSection | None): Override ``ctx.section`` when set.
        content_root (Path | None): Workspace content root for Shortcuts section rows.
        user_id (str | None): Telegram user id for shortcut visibility filtering.
        is_owner (bool): Whether the user is workspace owner.
        models_picker_slot (str | None): Override picker slot from ``ctx`` when set.
        models_picker_page (int | None): Override picker page from ``ctx`` when set.
        router (ChannelRouter | None): Gateway router for live sub-agent snapshot rows.

    Returns:
        bool: ``True`` when the edit API call succeeds.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(refresh_config_menu_message)
        True
    """
    active = section if section is not None else ctx.section
    picker_slot = models_picker_slot if models_picker_slot is not None else ctx.models_picker_slot
    picker_page = models_picker_page if models_picker_page is not None else ctx.models_picker_page
    l1_count = 0
    l2_count = 0
    running_rows: tuple[dict[str, Any], ...] = ()
    if active in {"subagents", "subagents_running"}:
        l1_count, l2_count, running_rows = await subagent_menu_snapshot_from_router(router)
    return await _edit_menu_message(
        adapter,
        chat_id=ctx.chat_id,
        message_id=ctx.message_id,
        text=config_menu_message_text(
            workspace,
            section=active,
            content_root=content_root,
            user_id=user_id,
            is_owner=is_owner,
            models_picker_slot=picker_slot,
            models_picker_page=picker_page,
            subagent_level1_count=l1_count,
            subagent_level2_count=l2_count,
            subagent_running_rows=running_rows,
        ),
        reply_markup=_apply_operator_readiness_gate(
            build_config_menu_keyboard(
                workspace,
                section=active,
                content_root=content_root,
                user_id=user_id,
                is_owner=is_owner,
                models_picker_slot=picker_slot,
                models_picker_page=picker_page,
                subagent_level1_count=l1_count,
                subagent_level2_count=l2_count,
                subagent_running_rows=running_rows,
            ),
        ),
        message_thread_id=ctx.topic_id,
    )


def config_menu_message_text(
    workspace: WorkspaceConfig,
    *,
    section: ConfigSection = "root",
    content_root: Path | None = None,
    user_id: str | None = None,
    is_owner: bool = True,
    models_picker_slot: str | None = None,
    models_picker_page: int = 0,
    subagent_level1_count: int = 0,
    subagent_level2_count: int = 0,
    subagent_running_rows: tuple[dict[str, Any], ...] = (),
) -> str:
    """Return caption text for a ``/config`` screen.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        section (ConfigSection): Active screen id.
        content_root (Path | None): Workspace content root for Shortcuts list copy.
        user_id (str | None): Telegram user id for shortcut visibility filtering.
        is_owner (bool): Whether the user is workspace owner.
        models_picker_slot (str | None): Active model picker slot when in picker view.
        models_picker_page (int): Zero-based picker page index.
        subagent_level1_count (int): Live L1 count for sub-agents captions.
        subagent_level2_count (int): Live L2 count for sub-agents captions.
        subagent_running_rows (tuple[dict[str, Any], ...]): Running rows for kill UI.

    Returns:
        str: Plain-text caption edited in place with the keyboard.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> config_menu_message_text(WorkspaceConfig.minimal(), section="root")
        'sevn — /config'
    """
    if section == "root":
        return "sevn — /config"
    if section == "voice":
        return (
            f"Voice\n\nGlobal TTS mode: {_voice_tts_mode(workspace)}\n"
            f"Active STT provider: {_voice_stt_active(workspace)}\n"
            "Per-chat override: /voice on|off|when_asked|reset"
        )
    if section == "models":
        if models_picker_slot and model_picker_slots_for_key(models_picker_slot):
            label = _MODEL_PICKER_SLOT_LABELS.get(models_picker_slot, models_picker_slot)
            catalog = list_catalog_model_ids(workspace)
            page_size = MODELS_PICKER_PAGE_SIZE
            total_pages = max(1, (len(catalog) + page_size - 1) // page_size)
            safe_page = max(0, min(models_picker_page, total_pages - 1))
            current = _resolved_model_for_picker_slot(workspace, models_picker_slot)
            lines = [
                "Models",
                "",
                f"Pick {label}",
                f"Current: {current or 'unset'}",
            ]
            if catalog:
                lines.append(f"Page {safe_page + 1}/{total_pages}")
            else:
                lines.append("No models in catalog.")
            return "\n".join(lines)
        unified = use_main_model_for_all(workspace)
        triager = resolve_model_slot(workspace, ModelSlot.triager)
        tier_b = resolve_model_slot(workspace, ModelSlot.tier_b)
        tier_c = resolve_model_slot(workspace, ModelSlot.tier_c)
        tier_d = resolve_model_slot(workspace, ModelSlot.tier_d)
        lines = [
            "Models",
            "",
            f"Unified model: {'on' if unified else 'off'}",
            f"Triager: {triager}",
            f"Tier B: {tier_b}",
        ]
        if not unified:
            lines.append(f"Tier C: {tier_c}")
            lines.append(f"Tier D: {tier_d}")
        return "\n".join(lines)
    if section == "security":
        heuristic = _security_heuristic_only(workspace)
        lines = [
            "Security",
            "",
            f"Heuristic-only scanner: {'on' if heuristic else 'off'}",
        ]
        url = web_ui_url_from_workspace(workspace)
        if url:
            lines.append(f"Mission Control: {url}#security")
        else:
            lines.append("Configure web_ui.url for Mission Control Security tab.")
        return "\n".join(lines)
    if section == "session":
        qa = _quick_actions_config(workspace)
        mode = _gateway_queue_mode(workspace)
        return (
            "Session\n\n"
            "Quick-action bar on final Telegram replies and per-session queue policy.\n\n"
            f"Queue mode: {mode}\n"
            f"Regen: {'on' if qa.show_regen else 'off'}\n"
            f"Thumbs up: {'on' if qa.show_thumbs_up else 'off'}\n"
            f"Thumbs down: {'on' if qa.show_thumbs_down else 'off'}\n"
            f"Share: {'on' if qa.show_share else 'off'}\n"
            f"Feedback: {'on' if qa.show_feedback else 'off'}"
        )
    if section == "help":
        from sevn.gateway.menu.menu_readiness import config_menu_help_catalog_text

        return config_menu_help_catalog_text()
    if section == "dashboard":
        url = web_ui_url_from_workspace(workspace)
        lines = [
            "Dashboard",
            "",
            "Pinned dashboard message for this chat/topic.",
            "Refresh pin re-renders the pinned caption and keyboard.",
        ]
        if url:
            lines.append(f"Mission Control: {url}")
        return "\n".join(lines)
    if section == "shortcuts":
        if content_root is not None:
            names = [
                str(row.get("name", ""))
                for row in list_visible_shortcuts(
                    content_root,
                    user_id=user_id or "",
                    is_owner=is_owner,
                )[:_SHORTCUTS_MENU_LIMIT]
            ]
            if names:
                listed = "\n".join(f"/{n}" for n in names)
                return f"Shortcuts\n\nVisible commands ({len(names)}):\n{listed}"
        return "Shortcuts\n\nNo custom shortcuts yet. Tap Add to create one."
    if section == "agents":
        name = _agent_display_name(workspace, content_root)
        lines = [
            "Agents",
            "",
            f"Display name: {name}",
            "Persona files: IDENTITY.md, SOUL.md, USER.md",
        ]
        url = web_ui_url_from_workspace(workspace)
        if url:
            lines.append(f"Edit persona in Mission Control: {url}")
        else:
            lines.append("Configure persona files in workspace (IDENTITY.md, SOUL.md, USER.md).")
        lines.append("Tap Edit display name to change the bot name in sevn.json.")
        return "\n".join(lines)
    if section == "skills":
        tool_surface = _config_menu_tool_surface(workspace, content_root)
        skill_n = len(tool_surface.skill_descriptions)
        lines = [
            "Skills",
            "",
            f"Indexed skills: {skill_n}",
        ]
        url = web_ui_url_from_workspace(workspace)
        if url:
            lines.append(f"Manage skills in Mission Control: {url}#skills")
        else:
            lines.append("Configure bundled skills in sevn.json (skills.*.enabled).")
        if not _schema_parent_allows_child_enabled("skills") and not url:
            lines.append("No skill toggles in menu — set web_ui.url or extend the schema.")
        return "\n".join(lines)
    if section == "skills:social_media_manager":
        return social_media_manager_menu_caption(workspace, content_root)
    if section == "tools":
        tool_surface = _config_menu_tool_surface(workspace, content_root)
        native_n = len(tool_surface.native)
        lines = [
            "Tools",
            "",
            f"Native tools in registry: {native_n}",
        ]
        url = web_ui_url_from_workspace(workspace)
        if url:
            lines.append(f"Manage tools in Mission Control: {url}#tools")
            lines.append("MCP server toggles: use Mission Control Tools tab.")
        else:
            lines.append("Configure tool plugins in sevn.json (tools.*.enabled).")
            lines.append("MCP servers: configure web_ui.url for Mission Control links.")
        return "\n".join(lines)
    if section == "rlm":
        tool_cap, skill_cap = _triager_tier_b_caps(workspace)
        backend = _rlm_c_d_backend(workspace)
        lambda_on = _lambda_rlm_enabled(workspace)
        lines = [
            "RLM",
            "",
            f"C/D backend: {backend}",
            f"λ-RLM opt-in: {'on' if lambda_on else 'off'}",
            f"REPL lifetime: {_rlm_repl_lifetime(workspace)}",
            f"Default complexity caps — tools: {tool_cap}, skills: {skill_cap}",
        ]
        url = web_ui_url_from_workspace(workspace)
        if url:
            lines.append(f"Mission Control: {url}#rlm")
        else:
            lines.append("Configure web_ui.url for Mission Control RLM tab.")
        if (
            _lambda_rlm_enabled(workspace)
            and not _rlm_lambda_tool_allowlist(workspace)
            and _schema_has_config_path("rlm.c_d_backend")
        ):
            lines.append("C/D backend cycle needs rlm.lambda_tool_allowlist before λ-RLM.")
        return "\n".join(lines)
    if section == "code":
        mycode = _mycode_enabled(workspace)
        review = _code_review_graph_enabled(workspace)
        lines = [
            "Code",
            "",
            f"MYCODE scan: {'on' if mycode else 'off'}",
            f"Code review graph: {'on' if review else 'off'}",
        ]
        url = web_ui_url_from_workspace(workspace)
        if url:
            lines.append(f"Mission Control: {url}#code")
        else:
            lines.append("Configure web_ui.url for Mission Control Code tab.")
        return "\n".join(lines)
    if section == "channels":
        rk = _telegram_reply_keyboard_enabled(workspace)
        routing = _telegram_show_routing(workspace)
        wc_tts = _webchat_tts_inline_enabled(workspace)
        lines = [
            "Channels",
            "",
            f"DM policy: {_telegram_dm_policy(workspace)}",
            f"Telegram mode: {_telegram_mode(workspace)} (read-only)",
            f"Reply keyboard: {'on' if rk else 'off'}",
            f"Show routing footer: {'on' if routing else 'off'}",
            f"Webchat TTS inline: {'on' if wc_tts else 'off'}",
        ]
        if not _schema_has_config_path("channels.webchat.tts_inline"):
            lines.append("Webchat TTS inline is caption-only (no schema toggle path).")
        return "\n".join(lines)
    if section == "notifications":
        policy = _telegram_notify_policy(workspace)
        return (
            f"Notifications\n\nTelegram notify policy: {policy}\nTap to cycle all → errors → none."
        )
    if section == "advanced":
        auto_resume = _gateway_auto_resume_b(workspace)
        redaction = _tracing_redaction_enabled(workspace)
        lines = [
            "Advanced",
            "",
            f"Auto-resume tier B on restart: {'on' if auto_resume else 'off'}",
            f"Trace redaction: {'on' if redaction else 'off'}",
            "",
            "Nested sections: RLM, Self-Improve, Second Brain, Sub-agents, CodeMode.",
        ]
        url = web_ui_url_from_workspace(workspace)
        if url:
            lines.append(f"Full config validation: {url}")
        else:
            lines.append("Configure web_ui.url for Mission Control deep links.")
        return "\n".join(lines)
    if section == "codemode":
        enabled = codemode_enabled(workspace)
        lines = [
            "CodeMode",
            "",
            f"Tier-B CodeMode: {'on' if enabled else 'off'}",
            "When on, triager-listed tools may run inside Monty run_code composites.",
            "Default off — flat pydantic-ai tool calls when disabled.",
        ]
        if enabled:
            lines.append(
                "Sandbox path skips permission hook; enable only for trusted workloads.",
            )
        return "\n".join(lines)
    if section == "sevn_bot":
        return (
            f"{config_sevn_bot_section_title()}\n\n"
            "Upstream sevn.bot checkout: sync from GitHub, list bug/feature evolution issues."
        )
    if section == "my_sevn_bot":
        lines = [
            "My sevn bot",
            "",
            "This gateway instance: deployment id and owner service restarts.",
        ]
        if is_owner:
            lines.append("Restart gateway or proxy below (two-step confirm).")
        else:
            lines.append("Restart actions are owner-only.")
        return "\n".join(lines)
    if section == "logs":
        from sevn.gateway.webapp.webapp_qa import (
            resolve_webapp_public_base,
            webapp_https_disabled_notice,
        )

        redaction = _tracing_redaction_enabled(workspace)
        logfire = _logfire_export_enabled(workspace)
        lines = [
            "Logs",
            "",
            "Owner-only operator diagnostics (mirrors /logs + /traces).",
            "",
            "Tail service logs, browse recent traces, grep by pattern,",
            "configure Logfire export, or flip trace redaction.",
            "",
            f"Logfire export: {'on' if logfire else 'off'}",
            f"Trace redaction: {'on' if redaction else 'off'}",
        ]
        webapp_notice = webapp_https_disabled_notice(resolve_webapp_public_base(workspace))
        if webapp_notice is not None:
            lines.extend(["", webapp_notice])
        return "\n".join(lines)
    if section == "secrets":
        raw_doc = _raw_sevn_doc(content_root)
        ref_keys = _list_secret_ref_keys(raw_doc)
        lines = [
            "Secrets",
            "",
            f"Configured secret refs: {len(ref_keys)}",
        ]
        if ref_keys:
            lines.append("Referenced keys:")
            for key in ref_keys[:20]:
                lines.append(f"• {key}")
            if len(ref_keys) > 20:
                lines.append(f"… and {len(ref_keys) - 20} more")
        lines.append("Values are never shown in Telegram. Tap Add to open the secret wizard.")
        return "\n".join(lines)
    if section == "self_improve":
        enabled = _self_improve_enabled(workspace)
        preset = "A"
        if workspace.self_improve is not None:
            preset = str(workspace.self_improve.preset)
        lines = [
            "Self-Improve",
            "",
            f"Enabled: {'on' if enabled else 'off'}",
            f"Preset: {preset}",
        ]
        url = web_ui_url_from_workspace(workspace)
        if url:
            lines.append(f"Jobs and traces: {url}#traces")
        else:
            lines.append("Configure web_ui.url for Mission Control traces.")
        return "\n".join(lines)
    if section == "second_brain":
        enabled = _second_brain_enabled(workspace)
        ingest = _second_brain_ingest_mode(workspace)
        lines = [
            "Second Brain",
            "",
            f"Enabled: {'on' if enabled else 'off'}",
            f"Ingest schedule: {ingest}",
        ]
        if content_root is not None:
            lines.append(f"Vault: {_second_brain_vault_display(content_root, workspace)}")
        url = web_ui_url_from_workspace(workspace)
        if url:
            lines.append(f"Mission Control: {url}#second_brain")
        else:
            lines.append("Configure web_ui.url for Mission Control Second Brain tab.")
        if not _schema_has_config_path("second_brain.ingest_batch_cron"):
            lines.append("Ingest schedule is caption-only (not in workspace schema).")
        return "\n".join(lines)
    if section == "subagents":
        from sevn.config.sections.subagents import SubAgentsWorkspaceConfig, resolve_limits

        cfg = workspace.subagents or SubAgentsWorkspaceConfig()
        lines = [
            "Sub-agents",
            "",
            f"Enabled: {'on' if _subagents_enabled(workspace) else 'off'}",
            f"Running: L1={subagent_level1_count} L2={subagent_level2_count}",
            f"Queue mode: {_gateway_queue_mode(workspace)}",
            f"Defaults: L1={cfg.max_level1_default} L2={cfg.max_level2_default}",
            f"Global override: {cfg.max_override!r}",
            "",
            "Per-role effective limits:",
        ]
        for role in _SUBAGENT_ROLES:
            l1, l2 = resolve_limits(cfg, role)
            lines.append(f"  {_subagents_role_label(role)}: L1={l1} L2={l2}")
        url = web_ui_url_from_workspace(workspace)
        if url:
            lines.append(f"Mission Control: {url}#subagents")
        return "\n".join(lines)
    if section == "subagents_running":
        lines = [
            "Sub-agents — Running",
            "",
            f"Active runs: {len(subagent_running_rows)} (L1={subagent_level1_count} L2={subagent_level2_count})",
        ]
        if subagent_running_rows:
            for row in subagent_running_rows[:8]:
                lines.append(
                    f"• {row.get('id')} L{row.get('level')} {row.get('role')} "
                    f"— {row.get('task_summary', '')!r}",
                )
        else:
            lines.append("No active sub-agent runs.")
        if not is_owner:
            lines.append("Kill controls are owner-only.")
        return "\n".join(lines)
    if section == "integrations":
        raw_doc = _raw_sevn_doc(content_root)
        ids = _configured_integration_ids(workspace, raw_doc=raw_doc)
        lines = ["Integrations", ""]
        if ids:
            lines.append("Configured:")
            lines.extend(f"• {iid}" for iid in ids)
        else:
            lines.append("No integrations configured yet.")
        url = _mission_control_url(workspace, fragment="integrations")
        if url:
            lines.append(f"Manage in Mission Control: {url}")
        else:
            lines.append("Configure web_ui.url for Mission Control deep links.")
        if not any(_schema_has_integration_enabled_toggle(iid) for iid in ids):
            lines.append(
                "Per-integration toggles appear when integration.<id>.enabled is in schema."
            )
        return "\n".join(lines)
    title = section.replace("_", " ").title()
    return f"{title}\n\nTap an action to mutate workspace config."


def parse_models_callback_data(data: str) -> tuple[str, str, int] | None:
    """Parse ``cfg:models:*`` picker navigation and selection callbacks.

    Args:
        data (str): Raw Telegram ``callback_data``.

    Returns:
        tuple[str, str, int] | None: ``(kind, slot_key, page_or_index)`` where
        *kind* is ``page``, ``pick``, or ``swap``.

    Examples:
        >>> parse_models_callback_data("cfg:models:page:tier_b:1")
        ('page', 'tier_b', 1)
        >>> parse_models_callback_data("cfg:models:pick:triager:0")
        ('pick', 'triager', 0)
        >>> parse_models_callback_data("cfg:models:swap")
        ('swap', '', 0)
    """
    raw = data.strip()
    if raw == "cfg:models:swap":
        return ("swap", "", 0)
    if raw.startswith("cfg:models:page:"):
        rest = raw.removeprefix("cfg:models:page:")
        if ":" not in rest:
            return None
        slot_key, page_raw = rest.rsplit(":", 1)
        if not page_raw.isdigit() or model_picker_slots_for_key(slot_key) is None:
            return None
        return ("page", slot_key, int(page_raw))
    if raw.startswith("cfg:models:pick:"):
        rest = raw.removeprefix("cfg:models:pick:")
        if ":" not in rest:
            return None
        slot_key, idx_raw = rest.rsplit(":", 1)
        if not idx_raw.isdigit() or model_picker_slots_for_key(slot_key) is None:
            return None
        return ("pick", slot_key, int(idx_raw))
    return None


def parse_config_callback_data(data: str) -> tuple[str, str | None] | None:
    """Parse ``cfg:nav:*`` and ``cfg:section:*`` navigation callbacks.

    Args:
        data (str): Raw Telegram ``callback_data``.

    Returns:
        tuple[str, str | None] | None: ``(kind, value)`` for navigation callbacks.

    Examples:
        >>> parse_config_callback_data("cfg:section:voice")
        ('section', 'voice')
        >>> parse_config_callback_data("cfg:voice:mode:off") is None
        True
    """
    raw = data.strip()
    if raw == "cfg:nav:home":
        return ("home", None)
    if raw == "cfg:nav:close":
        return ("close", None)
    if raw == "cfg:nav:back":
        return ("back", None)
    if raw == "cfg:nav:help":
        return ("help", None)
    if raw.startswith("cfg:disabled:"):
        return ("disabled", raw.removeprefix("cfg:disabled:").strip() or "unknown")
    if raw.startswith("cfg:section:"):
        name = raw.removeprefix("cfg:section:").strip().lower()
        if name in _CONFIG_SECTIONS:
            return ("section", name)
    if raw.startswith("cfg:help:cmd:"):
        cmd = raw.removeprefix("cfg:help:cmd:").strip().lower()
        if cmd in {"help", "menu", "new", "voice", "model", "config", "stop", "status"}:
            return ("cmd", cmd)
    return None


def config_callback_matches(msg: object) -> bool:
    """Return whether *msg* is a ``/config`` menu callback or slash command.

    Args:
        msg (object): Duck-typed inbound message with ``text`` and ``metadata``.

    Returns:
        bool: ``True`` for ``/config`` or ``cfg:*`` navigation callbacks.

    Examples:
        >>> class _M:
        ...     text = "/config"
        ...     metadata: dict = {}
        >>> config_callback_matches(_M())
        True
    """
    text = getattr(msg, "text", "") or ""
    if isinstance(text, str):
        t = text.strip()
        if t == "/config" or t.startswith("/config "):
            return True
    md = getattr(msg, "metadata", None)
    if not isinstance(md, dict):
        return False
    raw = md.get("callback_data")
    if not isinstance(raw, str):
        return False
    if parse_config_callback_data(raw.strip()) is not None:
        return True
    return raw.startswith("cfg:")


class ConfigMenuHandler:
    """Handle ``/config`` slash and ``cfg:nav:*`` / ``cfg:section:*`` navigation."""

    def __init__(
        self,
        workspace: WorkspaceConfig,
        router: ChannelRouter,
        *,
        command_invoker: Any | None = None,
    ) -> None:
        """Bind workspace + router for ``/config`` render and Telegram edits.

        Args:
            workspace (WorkspaceConfig): Parsed workspace settings.
            router (ChannelRouter): Gateway router (adapter lookup + sessions).
            command_invoker (object | None): Optional :class:`MenuCommandInvoker`.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ConfigMenuHandler.__init__)
            True
        """
        self._workspace = workspace
        self._router = router
        self._command_invoker = command_invoker

    def matches(self, msg: IncomingMessage) -> bool:
        """Return whether *msg* is a ``/config`` navigation callback.

        Args:
            msg (IncomingMessage): Inbound callback envelope.

        Returns:
            bool: ``True`` for ``cfg:nav:*`` / ``cfg:section:*`` callback data.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> h = ConfigMenuHandler.__new__(ConfigMenuHandler)
            >>> h.matches(
            ...     IncomingMessage(
            ...         channel="telegram", user_id="1", text="",
            ...         metadata={"callback_data": "cfg:section:voice"},
            ...     ),
            ... )
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        raw = md.get("callback_data")
        if not isinstance(raw, str):
            return False
        stripped = raw.strip()
        if parse_config_callback_data(stripped) is not None:
            return True
        parsed = parse_models_callback_data(stripped)
        return parsed is not None and parsed[0] == "page"

    def matches_slash(self, msg: IncomingMessage) -> bool:
        """Return whether *msg* is the ``/config`` slash command.

        Args:
            msg (IncomingMessage): Inbound message envelope.

        Returns:
            bool: ``True`` for ``/config``.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> h = ConfigMenuHandler.__new__(ConfigMenuHandler)
            >>> h.matches_slash(
            ...     IncomingMessage(channel="telegram", user_id="1", text="/config"),
            ... )
            True
        """
        text = (msg.text or "").strip()
        return text == "/config" or text.startswith("/config ")

    async def handle_slash(self, msg: IncomingMessage, *, session_id: str) -> None:
        """Open a new ``/config`` message with the root inline keyboard.

        Args:
            msg (IncomingMessage): Inbound ``/config`` message.
            session_id (str): Owning gateway session id.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ConfigMenuHandler.handle_slash)
            True
        """
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return
        workspace = self._router._workspace
        content_root = getattr(self._router, "_content_root", None)
        is_owner = self._router._resolve_owner_flag(msg)
        out_meta = _telegram_routing_metadata(msg)
        out_meta["inline_keyboard"] = build_config_menu_keyboard(
            workspace,
            section="root",
            content_root=content_root,
            user_id=msg.user_id,
            is_owner=is_owner,
        )
        from sevn.gateway.channel_router import OutgoingMessage

        await adapter.send(
            OutgoingMessage(
                channel=msg.channel,
                user_id=msg.user_id,
                text=config_menu_message_text(
                    workspace,
                    section="root",
                    content_root=content_root,
                    user_id=msg.user_id,
                    is_owner=is_owner,
                ),
                session_id=session_id,
                metadata=out_meta,
            ),
        )

    async def handle(self, msg: IncomingMessage, *, session_id: str) -> None:
        """Answer the callback and edit the source ``/config`` message in place.

        Args:
            msg (IncomingMessage): Inbound ``/config`` callback envelope.
            session_id (str): Owning gateway session id.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ConfigMenuHandler.handle)
            True
        """
        _ = session_id
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        raw = md.get("callback_data")
        if not isinstance(raw, str):
            return
        stripped = raw.strip()
        models_parsed = parse_models_callback_data(stripped)
        if models_parsed is not None and models_parsed[0] == "page":
            adapter = self._router._adapters.get(msg.channel)
            if adapter is None:
                return
            cq_id = md.get("callback_query_id")
            cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
            if cq_str:
                await _answer_callback_query(adapter, callback_query_id=cq_str)
            chat_raw = md.get("chat_id")
            message_raw = md.get("message_id")
            if (
                not isinstance(chat_raw, int)
                or not isinstance(message_raw, int)
                or message_raw <= 0
            ):
                return
            thread_id = _telegram_api_thread_id(md)
            _kind, slot_key, page = models_parsed
            target = ConfigMenuNavFrame(
                section="models",
                models_picker_slot=slot_key,
                models_picker_page=page,
            )
            config_menu_nav_go(self._router, chat_raw, message_raw, target)
            await self._render_config_nav_frame(
                msg,
                target,
                adapter=adapter,
                chat_id=chat_raw,
                message_id=message_raw,
                message_thread_id=thread_id,
            )
            return
        parsed = parse_config_callback_data(stripped)
        if parsed is None:
            return
        kind, value = parsed
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return
        cq_id = md.get("callback_query_id")
        cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
        if kind == "disabled":
            if cq_str:
                await _answer_callback_query(
                    adapter,
                    callback_query_id=cq_str,
                    text="Not active yet — see /config → Help for status.",
                )
            return
        if kind == "help":
            if cq_str:
                await _answer_callback_query(adapter, callback_query_id=cq_str)
            chat_raw = md.get("chat_id")
            message_raw = md.get("message_id")
            if not isinstance(chat_raw, int) or not isinstance(message_raw, int):
                return
            nav = get_config_menu_nav(self._router, chat_raw, message_raw)
            frame = nav.current
            workspace = self._router._workspace
            content_root = getattr(self._router, "_content_root", None)
            is_owner = self._router._resolve_owner_flag(msg)
            markup = build_config_menu_keyboard(
                workspace,
                section=frame.section,
                content_root=content_root,
                user_id=msg.user_id,
                is_owner=is_owner,
                models_picker_slot=frame.models_picker_slot,
                models_picker_page=frame.models_picker_page,
            )
            from sevn.gateway.menu.menu_readiness import config_menu_level_help_text

            help_text = config_menu_level_help_text(
                frame.section,
                markup=markup,
                is_owner=is_owner,
            )
            await self._send_level_help(msg, session_id=session_id, text=help_text)
            return
        if kind == "cmd" and value is not None:
            invoker = self._command_invoker
            if invoker is not None:
                await invoker.invoke(msg, session_id=session_id, command=value)
            elif cq_str:
                await _answer_callback_query(
                    adapter,
                    callback_query_id=cq_str,
                    text=f"Type /{value} in chat",
                )
            return
        if kind == "section" and value in _CONFIG_SECTIONS:
            from sevn.gateway.commands.menu_command_invoke import is_dashboard_pin_message

            if is_dashboard_pin_message(self._router, msg):
                if cq_str:
                    await _answer_callback_query(adapter, callback_query_id=cq_str)
                await self._open_config_at_section(
                    msg,
                    session_id=session_id,
                    section=value,  # type: ignore[arg-type]
                )
                return
        if cq_str:
            await _answer_callback_query(adapter, callback_query_id=cq_str)
        chat_raw = md.get("chat_id")
        message_raw = md.get("message_id")
        if not isinstance(chat_raw, int) or not isinstance(message_raw, int) or message_raw <= 0:
            return
        thread_id = _telegram_api_thread_id(md)
        if kind == "close":
            config_menu_nav_clear(self._router, chat_raw, message_raw)
            edit_markup = getattr(adapter, "edit_reply_markup", None)
            if callable(edit_markup):
                await cast("Any", edit_markup)(
                    chat_id=chat_raw,
                    message_id=message_raw,
                    reply_markup={"inline_keyboard": []},
                    message_thread_id=thread_id,
                )
            return
        if kind == "home":
            frame = config_menu_nav_home(self._router, chat_raw, message_raw)
        elif kind == "back":
            frame = config_menu_nav_pop(self._router, chat_raw, message_raw)
        elif kind == "section" and value in _CONFIG_SECTIONS:
            frame = ConfigMenuNavFrame(section=value)  # type: ignore[arg-type]
            config_menu_nav_go(self._router, chat_raw, message_raw, frame)
        else:
            return
        await self._render_config_nav_frame(
            msg,
            frame,
            adapter=adapter,
            chat_id=chat_raw,
            message_id=message_raw,
            message_thread_id=thread_id,
        )

    async def _send_level_help(
        self,
        msg: IncomingMessage,
        *,
        session_id: str,
        text: str,
    ) -> None:
        """Send per-level ``/config`` help as a new chat message.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            session_id (str): Owning gateway session id.
            text (str): Plain-text help body.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ConfigMenuHandler._send_level_help)
            True
        """
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return
        from sevn.gateway.channel_router import OutgoingMessage

        out_meta = _telegram_routing_metadata(msg)
        await adapter.send(
            OutgoingMessage(
                channel=msg.channel,
                user_id=msg.user_id,
                text=text,
                session_id=session_id,
                metadata=out_meta,
            ),
        )

    async def _render_config_nav_frame(
        self,
        msg: IncomingMessage,
        frame: ConfigMenuNavFrame,
        *,
        adapter: Any,
        chat_id: int,
        message_id: int,
        message_thread_id: int | None,
    ) -> None:
        """Edit the host ``/config`` message to *frame* (caption + keyboard).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            frame (ConfigMenuNavFrame): Target navigation frame.
            adapter (object): Telegram channel adapter.
            chat_id (int): Telegram chat id.
            message_id (int): Host message id.
            message_thread_id (int | None): Forum topic id when set.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ConfigMenuHandler._render_config_nav_frame)
            True
        """
        workspace = self._router._workspace
        content_root = getattr(self._router, "_content_root", None)
        is_owner = self._router._resolve_owner_flag(msg)
        l1_count = 0
        l2_count = 0
        running_rows: tuple[dict[str, Any], ...] = ()
        if frame.section in {"subagents", "subagents_running"}:
            l1_count, l2_count, running_rows = await subagent_menu_snapshot_from_router(
                self._router,
            )
        await _edit_menu_message(
            adapter,
            chat_id=chat_id,
            message_id=message_id,
            text=config_menu_message_text(
                workspace,
                section=frame.section,
                content_root=content_root,
                user_id=msg.user_id,
                is_owner=is_owner,
                models_picker_slot=frame.models_picker_slot,
                models_picker_page=frame.models_picker_page,
                subagent_level1_count=l1_count,
                subagent_level2_count=l2_count,
                subagent_running_rows=running_rows,
            ),
            reply_markup=_apply_operator_readiness_gate(
                build_config_menu_keyboard(
                    workspace,
                    section=frame.section,
                    content_root=content_root,
                    user_id=msg.user_id,
                    is_owner=is_owner,
                    models_picker_slot=frame.models_picker_slot,
                    models_picker_page=frame.models_picker_page,
                    subagent_level1_count=l1_count,
                    subagent_level2_count=l2_count,
                    subagent_running_rows=running_rows,
                ),
            ),
            message_thread_id=message_thread_id,
        )

    async def _open_config_at_section(
        self,
        msg: IncomingMessage,
        *,
        session_id: str,
        section: ConfigSection,
    ) -> None:
        """Open a new ``/config`` message at *section* (used from pin keyboard F6).

        Args:
            msg (IncomingMessage): Inbound callback envelope (pin message context).
            session_id (str): Owning gateway session id.
            section (ConfigSection): Target ``/config`` section id.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ConfigMenuHandler._open_config_at_section)
            True
        """
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return
        workspace = self._router._workspace
        content_root = getattr(self._router, "_content_root", None)
        is_owner = self._router._resolve_owner_flag(msg)
        out_meta = _telegram_routing_metadata(msg)
        out_meta["inline_keyboard"] = _apply_operator_readiness_gate(
            build_config_menu_keyboard(
                workspace,
                section=section,
                content_root=content_root,
                user_id=msg.user_id,
                is_owner=is_owner,
            ),
        )
        from sevn.gateway.channel_router import OutgoingMessage

        await adapter.send(
            OutgoingMessage(
                channel=msg.channel,
                user_id=msg.user_id,
                text=config_menu_message_text(
                    workspace,
                    section=section,
                    content_root=content_root,
                    user_id=msg.user_id,
                    is_owner=is_owner,
                ),
                session_id=session_id,
                metadata=out_meta,
            ),
        )


class MenuCallbackHandler:
    """Handle ``menu:*`` / ``nav:*`` callbacks with edit-in-place keyboards."""

    def __init__(
        self,
        workspace: WorkspaceConfig,
        router: ChannelRouter,
        *,
        tool_set: MenuToolSurface | None = None,
        command_invoker: Any | None = None,
    ) -> None:
        """Bind workspace + router for menu render and Telegram edits.

        Args:
            workspace (WorkspaceConfig): Parsed workspace settings.
            router (ChannelRouter): Gateway router (adapter lookup + sessions).
            tool_set (MenuToolSurface | None): Optional tool surface for About/diagnostics.
            command_invoker (object | None): Optional :class:`MenuCommandInvoker`.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(MenuCallbackHandler.__init__)
            True
        """
        self._workspace = workspace
        self._router = router
        self._tool_set: MenuToolSurface = tool_set if tool_set is not None else _EMPTY_TOOL_SURFACE
        self._command_invoker = command_invoker

    def matches(self, msg: IncomingMessage) -> bool:
        """Return whether ``msg`` is a menu callback (not bare ``/menu``).

        Args:
            msg (IncomingMessage): Inbound callback envelope.

        Returns:
            bool: ``True`` for ``menu:*`` / ``nav:*`` callback data.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> h = MenuCallbackHandler.__new__(MenuCallbackHandler)
            >>> h.matches(
            ...     IncomingMessage(
            ...         channel="telegram",
            ...         user_id="1",
            ...         text="menu:home",
            ...         metadata={"callback_data": "menu:home"},
            ...     ),
            ... )
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        raw = md.get("callback_data")
        if not isinstance(raw, str):
            raw = msg.text or ""
        if not isinstance(raw, str):
            return False
        return parse_menu_callback_data(raw.strip()) is not None

    def matches_slash(self, msg: IncomingMessage) -> bool:
        """Return whether ``msg`` is the ``/menu`` slash command.

        Args:
            msg (IncomingMessage): Inbound message envelope.

        Returns:
            bool: ``True`` for ``/menu``.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> h = MenuCallbackHandler.__new__(MenuCallbackHandler)
            >>> h.matches_slash(
            ...     IncomingMessage(channel="telegram", user_id="1", text="/menu"),
            ... )
            True
        """
        text = (msg.text or "").strip()
        return text == "/menu" or text.startswith("/menu ")

    async def handle_slash(
        self,
        msg: IncomingMessage,
        *,
        session_id: str,
    ) -> None:
        """Open a new menu message with the root inline keyboard.

        Args:
            msg (IncomingMessage): Inbound ``/menu`` message.
            session_id (str): Owning gateway session id.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuCallbackHandler.handle_slash)
            True
        """
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return
        out_meta = _telegram_routing_metadata(msg)
        out_meta["inline_keyboard"] = build_menu_keyboard(
            self._workspace,
            tool_set=self._tool_set,
            section="root",
        )
        from sevn.gateway.channel_router import OutgoingMessage

        await adapter.send(
            OutgoingMessage(
                channel=msg.channel,
                user_id=msg.user_id,
                text=menu_message_text(self._workspace, tool_set=self._tool_set, section="root"),
                session_id=session_id,
                metadata=out_meta,
            ),
        )

    async def handle(
        self,
        msg: IncomingMessage,
        *,
        session_id: str,
    ) -> None:
        """Answer the callback and edit the source menu message in place.

        Args:
            msg (IncomingMessage): Inbound menu callback envelope.
            session_id (str): Owning gateway session id.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuCallbackHandler.handle)
            True
        """
        _ = session_id
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        raw = md.get("callback_data")
        if not isinstance(raw, str):
            raw = msg.text or ""
        parsed = parse_menu_callback_data(str(raw).strip()) if isinstance(raw, str) else None
        if parsed is None:
            return
        kind, value = parsed
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return
        cq_id = md.get("callback_query_id")
        cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
        if kind == "cmd" and value is not None:
            invoker = self._command_invoker
            if invoker is not None:
                await invoker.invoke(msg, session_id=session_id, command=value)
            elif cq_str:
                await _answer_callback_query(
                    adapter,
                    callback_query_id=cq_str,
                    text=f"Type /{value} in chat",
                )
            return
        if cq_str:
            await _answer_callback_query(adapter, callback_query_id=cq_str)
        chat_raw = md.get("chat_id")
        message_raw = md.get("message_id")
        if not isinstance(chat_raw, int) or not isinstance(message_raw, int) or message_raw <= 0:
            return
        thread_id = _telegram_api_thread_id(md)
        if kind == "close":
            edit_markup = getattr(adapter, "edit_reply_markup", None)
            if callable(edit_markup):
                await cast("Any", edit_markup)(
                    chat_id=chat_raw,
                    message_id=message_raw,
                    reply_markup={"inline_keyboard": []},
                    message_thread_id=thread_id,
                )
            return
        if kind == "open_config":
            workspace = self._router._workspace
            content_root = getattr(self._router, "_content_root", None)
            is_owner = self._router._resolve_owner_flag(msg)
            await _edit_menu_message(
                adapter,
                chat_id=chat_raw,
                message_id=message_raw,
                text=config_menu_message_text(
                    workspace,
                    section="root",
                    content_root=content_root,
                    user_id=msg.user_id,
                    is_owner=is_owner,
                ),
                reply_markup=build_config_menu_keyboard(
                    workspace,
                    section="root",
                    content_root=content_root,
                    user_id=msg.user_id,
                    is_owner=is_owner,
                ),
                message_thread_id=thread_id,
            )
            return
        section: MenuSection = "root"
        if kind == "section" and value in {"identity", "quick", "workspace", "diagnostics"}:
            section = value  # type: ignore[assignment]
        await _edit_menu_message(
            adapter,
            chat_id=chat_raw,
            message_id=message_raw,
            text=menu_message_text(self._workspace, tool_set=self._tool_set, section=section),
            reply_markup=build_menu_keyboard(
                self._workspace,
                tool_set=self._tool_set,
                section=section,
            ),
            message_thread_id=thread_id,
        )


def _telegram_routing_metadata(msg: IncomingMessage) -> dict[str, Any]:
    """Copy Telegram routing keys from inbound metadata.

    Args:
        msg (IncomingMessage): Inbound adapter envelope.

    Returns:
        dict[str, Any]: Subset safe to forward on outbound sends.

    Examples:
        >>> from sevn.gateway.channel_router import IncomingMessage
        >>> _telegram_routing_metadata(
        ...     IncomingMessage(
        ...         channel="telegram",
        ...         user_id="1",
        ...         text="/menu",
        ...         metadata={"chat_id": 9},
        ...     ),
        ... )["chat_id"]
        9
    """
    md = msg.metadata if isinstance(msg.metadata, dict) else {}
    out: dict[str, Any] = {}
    for key in ("chat_id", "topic_id", "telegram_thread_id", "message_id", "reply_to_message_id"):
        if key in md:
            out[key] = md[key]
    return out


def _telegram_api_thread_id(md: dict[str, Any]) -> int | None:
    """Resolve Bot API ``message_thread_id`` from inbound metadata.

    Args:
        md (dict[str, Any]): Telegram routing metadata.

    Returns:
        int | None: Thread id for edits, including General-topic ``1``.

    Examples:
        >>> _telegram_api_thread_id({"telegram_thread_id": 1})
        1
        >>> _telegram_api_thread_id({"topic_id": 5})
        5
    """
    raw = md.get("telegram_thread_id")
    if isinstance(raw, int):
        return raw
    topic = md.get("topic_id")
    if isinstance(topic, int):
        return topic
    return None


async def _answer_callback_query(
    adapter: Any,
    *,
    callback_query_id: str,
    text: str | None = None,
) -> bool:
    """Invoke Telegram ``answerCallbackQuery`` when the adapter supports it.

    Args:
        adapter (object): Channel adapter (``TelegramAdapter`` in production).
        callback_query_id (str): Telegram callback query id.
        text (str | None): Optional toast body.

    Returns:
        bool: ``True`` when the API reports success.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_answer_callback_query)
        True
    """
    if not callback_query_id.strip():
        return False
    answer_fn = getattr(adapter, "answer_callback_query", None)
    if callable(answer_fn):
        return bool(
            await cast("Callable[..., Awaitable[Any]]", answer_fn)(
                callback_query_id=callback_query_id,
                text=text,
            ),
        )
    api = getattr(adapter, "_api", None)
    if not callable(api):
        return False
    body: dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        body["text"] = text
        body["show_alert"] = False
    res = await cast("Callable[..., Awaitable[Any]]", api)("answerCallbackQuery", body)
    return bool(res.get("ok"))


async def _edit_menu_message(
    adapter: Any,
    *,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: dict[str, Any],
    message_thread_id: int | None = None,
) -> bool:
    """Edit menu caption + keyboard via ``editMessageText`` / ``editMessageReplyMarkup``.

    Args:
        adapter (object): Channel adapter exposing Bot API helpers.
        chat_id (int): Destination chat id.
        message_id (int): Menu message id to edit.
        text (str): Updated plain-text body.
        reply_markup (dict[str, Any]): Inline keyboard markup dict.
        message_thread_id (int | None): Optional forum topic id.

    Returns:
        bool: ``True`` when an edit API call succeeds.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_edit_menu_message)
        True
    """
    if message_id <= 0:
        return False
    edit_text = getattr(adapter, "edit_message_text", None)
    if callable(edit_text):
        return bool(
            await cast("Callable[..., Awaitable[Any]]", edit_text)(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                message_thread_id=message_thread_id,
            ),
        )
    api = getattr(adapter, "_api", None)
    if callable(api):
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "reply_markup": reply_markup,
        }
        if message_thread_id is not None:
            body["message_thread_id"] = message_thread_id
        res = await cast("Callable[..., Awaitable[Any]]", api)("editMessageText", body)
        if res.get("ok"):
            return True
    edit_markup = getattr(adapter, "edit_reply_markup", None)
    if callable(edit_markup):
        return bool(
            await cast("Callable[..., Awaitable[Any]]", edit_markup)(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=reply_markup,
                message_thread_id=message_thread_id,
            ),
        )
    return False


def build_chat_menu_webapp_request(workspace: WorkspaceConfig) -> dict[str, Any]:
    """Build ``setChatMenuButton`` JSON for the rich artifact viewer (M2 / D12).

    Delegates to :func:`sevn.gateway.webapp.webapp_viewer.build_chat_menu_webapp_request`.

    Args:
        workspace (WorkspaceConfig): Active workspace document.

    Returns:
        dict[str, Any]: Bot API body with ``MenuButtonWebApp`` or ``MenuButtonDefault``.

    Examples:
        >>> body = build_chat_menu_webapp_request(
        ...     __import__(
        ...         "sevn.config.workspace_config",
        ...         fromlist=["WorkspaceConfig"],
        ...     ).WorkspaceConfig.minimal(workspace_root="."),
        ... )
        >>> body["menu_button"]["type"]
        'default'
    """
    from sevn.gateway.webapp.webapp_viewer import build_chat_menu_webapp_request as _build

    return _build(workspace)


async def sync_telegram_chat_menu_button(
    api_call: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    workspace: WorkspaceConfig,
) -> None:
    """Push or reset the Telegram chat menu Web App button (D12).

    Delegates to :func:`sevn.gateway.webapp.webapp_viewer.sync_telegram_chat_menu_button`.

    Args:
        api_call (Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]):
            Async Bot API caller ``(method, body) -> response``.
        workspace (WorkspaceConfig): Active workspace document.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(sync_telegram_chat_menu_button)
        True
    """
    from sevn.gateway.webapp.webapp_viewer import sync_telegram_chat_menu_button as _sync

    await _sync(api_call, workspace)


__all__ = [
    "ConfigMenuHandler",
    "ConfigMenuNavFrame",
    "ConfigMenuRefreshContext",
    "ConfigSection",
    "MenuCallbackHandler",
    "MenuToolSurface",
    "build_chat_menu_webapp_request",
    "build_config_menu_keyboard",
    "build_menu_keyboard",
    "config_callback_matches",
    "config_menu_message_text",
    "config_menu_nav_clear",
    "config_menu_nav_go",
    "config_menu_nav_home",
    "config_menu_nav_pop",
    "config_menu_nav_push_current",
    "get_config_menu_nav",
    "infer_budget_regime",
    "menu_callback_matches",
    "menu_message_text",
    "parse_config_callback_data",
    "parse_menu_callback_data",
    "parse_models_callback_data",
    "refresh_config_menu_message",
    "subagent_menu_snapshot_from_router",
    "sync_telegram_chat_menu_button",
    "web_ui_url_from_workspace",
]
