"""Polymorphic ``cfg:*`` / shortcut action dispatch (`plan/telegram-commands-design.md` §4.5).

Module: sevn.gateway.commands.menu_action_router
Depends: json, sqlite3, sevn.gateway.dispatcher.dispatcher_state, sevn.gateway.commands.dispatcher_kinds,
    sevn.gateway.commands.shortcuts_store, sevn.gateway.config_io.workspace_config_io

Exports:
    MenuActionRouter — sibling to :class:`sevn.gateway.menu.menu.MenuCallbackHandler` nav.
    infer_config_section_from_callback — map action callbacks to ``/config`` sections.
    parse_action_callback — parse action callback namespaces.
Examples:
    >>> parse_action_callback("cfg:voice:mode:off")
    ('toggle', 'voice.tts_mode', 'off')
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import json
import secrets
import sqlite3
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from loguru import logger

from sevn.agent.tracing.logfire_config import (
    apply_logfire_export_to_sevn_doc,
    logfire_export_status_from_doc,
)
from sevn.agent.tracing.redaction_config import (
    apply_trace_redaction_to_sevn_doc,
    effective_trace_redaction_enabled_from_doc,
)
from sevn.cli.daemon_control import _mutate_gateway_with_proxy
from sevn.cli.operator_lock import OperatorLockHeld, operator_lock
from sevn.cli.service_manager import (
    ServiceManagerError,
    control_unit,
    propagate_daemon_proxy_env,
    propagate_daemon_secret_env,
    unit_file_exists,
)
from sevn.cli.workspace import sevn_home_dir
from sevn.config.defaults import DEFAULT_VOICE_LOCAL_TTS_ENGINE, DEFAULT_VOICE_STT_PROVIDERS
from sevn.config.model_resolution import (
    ModelSlot,
    apply_model_to_picker_slot,
    list_catalog_model_ids,
    resolve_model_slot,
)
from sevn.config.version_id import effective_version_id
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.commands.shortcuts_store import (
    delete_shortcut,
    find_shortcut,
    republish_set_my_commands,
)
from sevn.gateway.config_io.workspace_config_io import load_raw_sevn_json, mutate_sevn_json
from sevn.gateway.dispatcher.dispatcher_state import (
    dispatcher_state_ttl_for_kind,
    insert_dispatcher_state,
)
from sevn.gateway.menu.menu import (
    ConfigMenuNavFrame,
    ConfigMenuRefreshContext,
    ConfigSection,
    _config_chrome,
    _edit_menu_message,
    _telegram_api_thread_id,
    _voice_tts_mode,
    build_service_restart_confirm_keyboard,
    build_tunnel_on_confirm_keyboard,
    config_menu_nav_pop,
    config_menu_nav_push_current,
    get_config_menu_nav,
    is_registered_config_menu_host,
    parse_config_callback_data,
    parse_models_callback_data,
    refresh_config_menu_message,
    service_restart_confirm_message,
    tunnel_on_confirm_message,
)
from sevn.gateway.subagents.surfaces import (
    STOP_L1_PICKER_COPY,
    build_stop_l1_keyboard,
    subagent_menu_snapshot_from_router,
)
from sevn.onboarding.web_app import _get_nested, _set_nested
from sevn.voice.backends import KNOWN_LOCAL_TTS_ENGINES

if TYPE_CHECKING:
    from sevn.gateway.channel_router import ChannelRouter, IncomingMessage

ActionKind = Literal["toggle", "cycle", "prompt", "skill", "action", "scene", "form"]

_SECTION_TOGGLES: dict[str, tuple[str, Any, Any]] = {
    "voice:mode:off": ("voice.tts_mode", "off", "off"),
    "voice:mode:all": ("voice.tts_mode", "all", "all"),
    "voice:mode:when_asked": ("voice.tts_mode", "when_asked", "when_asked"),
}

_CFG_ACTION_KEYS: frozenset[str] = frozenset(
    {
        "dashboard:refresh_pin",
        "dashboard:create_pin",
        "dashboard:unpin",
        "shortcuts:list",
        "skills:refresh",
        "skills:sync",
        "integrations:refresh",
        "models:swap",
    }
)

_HOST_SHELL_COMMANDS: dict[str, str] = {
    "onboard": "sevn onboard --web",
    "completion": "sevn completion install",
    "shell-history": "sevn shell-history install",
    "gateway-token": "sevn gateway set-gateway-token",
    "dashboard-password": "sevn dashboard set-login-password",
    "store-passphrase": "sevn secrets store-passphrase",
    "uninstall": "sevn unboard",
}

_DEV_SHELL_COMMANDS: dict[str, str] = {
    "readme": "sevn readme check|generate|update|scaffold|index|curate|fingerprint",
    "about-docs": "sevn about-docs check|generate|index|extract|context|schema|migrate",
    "gui-migrate": "sevn gui migrate",
}

# Mutating or cross-session actions gated to workspace owner (Thermos: align W7a/W7c with W7d/W7e).
_OWNER_ONLY_ACTION_TARGETS: frozenset[str] = frozenset(
    {
        "skills:sync",
        "second_brain:setup",
        "second_brain:reindex",
        "dreaming:undo",
        "dreaming:reconcile_cron",
        "openui:install",
        "openui:setup",
        "sessions:list",
    }
)

_CALLBACK_SECTION_PREFIXES: tuple[tuple[str, ConfigSection], ...] = (
    ("voice:", "chat_voice"),
    ("security:", "access_guard"),
    ("dashboard:", "health_pin"),
    ("shortcuts:", "chat_shortcuts"),
    ("sessions:", "chat_sessions"),
    ("channels:", "chat_channels"),
    ("agent:", "agent"),
    ("self_improve:", "agent_lab"),
    ("skills:", "skills"),
    ("tools:", "skills_tools"),
    ("memory:", "memory"),
    ("dreaming:", "memory_dreaming"),
    ("openui:", "memory_openwiki"),
    ("second_brain:", "memory_sb"),
    ("integrations:", "skills_integrations"),
    ("logs:", "health"),
)

_CONFIG_PATH_SECTION: dict[str, ConfigSection] = {
    "voice": "chat_voice",
    "security": "access_guard",
    "webchat": "chat_channels",
    "providers": "agent",
    "channels": "chat_channels",
    "gateway": "chat",
    "executors": "agent_lab",
    "rlm": "agent_lab",
    "code_understanding": "memory_code",
    "code_review_graph": "memory_code",
    "self_improve": "agent_lab",
    "second_brain": "memory_sb",
    "subagents": "agent_subagents",
    "skills": "skills",
    "tools": "skills_tools",
    "integration": "skills_integrations",
    "agent": "agent_identity",
}


def _tts_pipeline_engine(tts: Any) -> str | None:
    """Return a TTS backend ``.engine`` when present, or ``None``.

    Prefers the first backend that exposes a non-empty ``engine`` attribute so a
    reordered ``tts_providers`` list (e.g. ``edge_tts`` first) does not miss the
    local ``text_to_voice`` pipeline engine.

    Args:
        tts (Any): :class:`~sevn.voice.tts.TextToSpeechPipeline` or substitute.

    Returns:
        str | None: Normalised local TTS engine tag when present.

    Examples:
        >>> _tts_pipeline_engine(None) is None
        True
    """
    backends = getattr(tts, "_backends", None) or getattr(tts, "backends", None)
    if not backends:
        return None
    for backend in backends:
        engine = getattr(backend, "engine", None)
        if engine:
            return str(engine).strip().casefold()
    return None


def infer_config_section_from_callback(data: str) -> ConfigSection:
    """Map an action callback to the active ``/config`` section for refresh.

    Args:
        data (str): Raw Telegram ``callback_data``.

    Returns:
        ConfigSection: Best-effort section id for caption rebuild.

    Examples:
        >>> infer_config_section_from_callback("cfg:voice:mode:all")
        'chat_voice'
        >>> infer_config_section_from_callback("cfg:toggle:providers.use_main_model_for_all:false")
        'agent'
        >>> infer_config_section_from_callback(
        ...     "cfg:toggle:security.scanner.heuristic_only:true",
        ... )
        'access_guard'
        >>> infer_config_section_from_callback(
        ...     "cfg:toggle:executors.tier_cd.lambda_rlm.enabled:true",
        ... )
        'agent_lab'
        >>> infer_config_section_from_callback(
        ...     "cfg:toggle:code_understanding.mycode.enabled:false",
        ... )
        'memory_code'
        >>> infer_config_section_from_callback("cfg:models:pick:tier_b:0")
        'agent'
        >>> infer_config_section_from_callback("act:gateway:restart")
        'deployment'
        >>> infer_config_section_from_callback("act:tunnel:on")
        'deployment'
        >>> infer_config_section_from_callback("act:sevn_bot:sync")
        'help'
        >>> infer_config_section_from_callback("cfg:logs:toggle_redaction")
        'health_tracing'
    """
    raw = data.strip()
    if raw.startswith("act:secrets:"):
        return "access_secrets"
    if raw.startswith("act:pairing:"):
        return "access_pairing"
    if raw.startswith("act:providers:"):
        return "access_providers"
    if raw in {"act:doctor:run", "act:usage:show"}:
        return "health"
    if raw.startswith("act:turn_bundles:"):
        return "health_bundles"
    if raw == "act:tracing:config":
        return "health_tracing"
    if raw.startswith("act:services:"):
        return "deployment_services"
    if raw.startswith("act:config:"):
        return "deployment_config"
    if raw.startswith("act:guides:"):
        return "help_guides"
    if raw.startswith("act:help:"):
        return "help"
    if raw.startswith("act:update:"):
        return "deployment_update"
    if raw.startswith("act:deploy:"):
        return "deployment_deploy"
    if raw.startswith("form:config:"):
        return "deployment_config"
    if raw.startswith("form:tunnel:"):
        return "deployment_tunnel"
    if raw.startswith("form:migrate:"):
        return "deployment_update"
    if raw.startswith("form:deploy:"):
        return "deployment_deploy"
    if raw.startswith("form:guides:"):
        return "help_guides"
    if raw.startswith("cfg:logs:"):
        if "toggle_redaction" in raw or "logfire" in raw or "logfire_token" in raw:
            return "health_tracing"
        return "health"
    if raw.startswith("cfg:models:"):
        return "agent"
    if raw.startswith(("act:gateway:", "act:proxy:")):
        return "deployment"
    if raw.startswith("act:tunnel:"):
        if raw in {"act:tunnel:status", "act:tunnel:start", "act:tunnel:stop"}:
            return "deployment_tunnel"
        return "deployment"
    if raw.startswith("act:sevn_bot:"):
        return "help"
    if raw.startswith("act:discogs:"):
        return "skills:discogs:setup"
    if raw.startswith("cfg:cycle:"):
        path = raw.removeprefix("cfg:cycle:").rsplit(":", 1)[0]
        if path.startswith("skills.social_media_manager"):
            return "skills:social_media_manager"
        if path.startswith("skills.discogs"):
            return "skills:discogs"
        top = path.split(".", 1)[0]
        return _CONFIG_PATH_SECTION.get(top, "root")
    if raw.startswith("cfg:toggle:"):
        path = raw.removeprefix("cfg:toggle:").split(":", 1)[0]
        if path.startswith("skills.social_media_manager"):
            return "skills:social_media_manager"
        if path.startswith("skills.discogs"):
            if path.endswith(".enabled") and path.count(".") == 3:
                return "skills:discogs"
            return "skills:discogs"
        if path.startswith("agent.codemode"):
            return "agent_lab"
        if path.startswith("subagents"):
            return "agent_subagents"
        if "quick_actions" in path:
            return "chat_qa"
        if path.startswith("gateway.queue_mode"):
            return "chat"
        if path.startswith("gateway.restart"):
            return "deployment"
        if path.startswith("channels.telegram.dm_policy"):
            return "access_pairing"
        if path.startswith("tracing."):
            return "health_tracing"
        if "telegram_notify_policy" in path:
            return "chat"
        if path.startswith("channels.telegram."):
            return "chat_channels"
        top = path.split(".", 1)[0]
        return _CONFIG_PATH_SECTION.get(top, "root")
    if raw.startswith("cfg:"):
        key = raw.removeprefix("cfg:")
        for prefix, section in _CALLBACK_SECTION_PREFIXES:
            if key.startswith(prefix):
                return section
    if raw.startswith("act:"):
        key = raw.removeprefix("act:")
        for prefix, section in _CALLBACK_SECTION_PREFIXES:
            if key.startswith(prefix):
                return section
    return "root"


def parse_action_callback(data: str) -> tuple[ActionKind, str, str | None] | None:
    """Parse ``cfg:*``, ``short:*``, ``act:*``, ``scene:*``, ``form:*`` callbacks.

    Args:
        data (str): Raw Telegram ``callback_data``.

    Returns:
        tuple[ActionKind, str, str | None] | None: ``(kind, target, value)``.

    Examples:
        >>> parse_action_callback("cfg:voice:mode:off")
        ('toggle', 'voice.tts_mode', 'off')
        >>> parse_action_callback("cfg:voice:stt:next")
        ('action', 'voice:stt:next', None)
        >>> parse_action_callback("cfg:voice:engine:next")
        ('action', 'voice:engine:next', None)
        >>> parse_action_callback("cfg:dashboard:refresh_pin")
        ('action', 'dashboard:refresh_pin', None)
        >>> parse_action_callback("cfg:dashboard:create_pin")
        ('action', 'dashboard:create_pin', None)
        >>> parse_action_callback("cfg:models:swap")
        ('action', 'models:swap', None)
        >>> parse_action_callback("cfg:models:pick:tier_b:2")
        ('action', 'models:pick:tier_b:2', None)
        >>> parse_action_callback("act:shortcut_delete:standup")
        ('action', 'shortcut_delete:standup', None)
        >>> parse_action_callback("act:gateway:restart:confirm")
        ('action', 'gateway:restart:confirm', None)
        >>> parse_action_callback("cfg:logs:tail:gateway:0")
        ('action', 'logs:tail:gateway:0', None)
        >>> parse_action_callback("cfg:logs:toggle_redaction")
        ('action', 'logs:toggle_redaction', None)
        >>> parse_action_callback("cfg:logs:deployment_id")
        ('action', 'logs:deployment_id', None)
    """
    raw = data.strip()
    models_parsed = parse_models_callback_data(raw)
    if models_parsed is not None:
        kind, slot_key, idx = models_parsed
        if kind == "swap":
            return ("action", "models:swap", None)
        if kind == "pick":
            return ("action", f"models:pick:{slot_key}:{idx}", None)
    if raw.startswith("cfg:cycle:"):
        rest = raw.removeprefix("cfg:cycle:")
        if ":" in rest:
            path, val = rest.rsplit(":", 1)
            return ("cycle", path, val)
        return None
    if raw.startswith("cfg:toggle:"):
        rest = raw.removeprefix("cfg:toggle:")
        if ":" in rest:
            path, val = rest.split(":", 1)
            return ("toggle", path, val)
        return None
    if raw.startswith("cfg:logs:"):
        rest = raw.removeprefix("cfg:logs:")
        return ("action", f"logs:{rest}", None)
    if raw.startswith("cfg:"):
        if parse_config_callback_data(raw) is not None:
            return None
        key = raw.removeprefix("cfg:")
        if key in _SECTION_TOGGLES:
            path, val, _ = _SECTION_TOGGLES[key]
            return ("toggle", path, str(val))
        if key in _CFG_ACTION_KEYS:
            return ("action", key, None)
        if key.startswith("voice:stt:"):
            return ("action", key, None)
        if key.startswith("voice:engine:"):
            return ("action", key, None)
        if key.endswith((":off", ":on")):
            parts = key.rsplit(":", 1)
            return ("toggle", parts[0].replace(":", "."), parts[1])
        return None
    if raw.startswith("short:run:"):
        return ("prompt", raw.removeprefix("short:run:"), None)
    if raw.startswith("act:"):
        return ("action", raw.removeprefix("act:"), None)
    if raw.startswith("scene:apply:"):
        return ("scene", raw.removeprefix("scene:apply:"), None)
    if raw.startswith("form:"):
        return ("form", raw.removeprefix("form:"), None)
    return None


class MenuActionRouter:
    """Dispatch config mutations and shortcut actions (not nav chrome)."""

    def __init__(
        self,
        *,
        workspace: WorkspaceConfig,
        router: ChannelRouter,
        conn: sqlite3.Connection,
        content_root: Path,
        sevn_json_path: Path,
    ) -> None:
        """Bind workspace, router, DB, and config paths.

        Args:
            workspace (WorkspaceConfig): Parsed workspace settings.
            router (ChannelRouter): Gateway router.
            conn (sqlite3.Connection): Open gateway DB handle.
            content_root (Path): Workspace content root.
            sevn_json_path (Path): Path to ``sevn.json``.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(MenuActionRouter.__init__)
            True
        """
        self._workspace = workspace
        self._router = router
        self._conn = conn
        self._content_root = content_root.expanduser().resolve()
        self._sevn_json = sevn_json_path

    def matches(self, msg: IncomingMessage) -> bool:
        """Return whether *msg* is an action callback we own.

        Args:
            msg (IncomingMessage): Inbound callback envelope.

        Returns:
            bool: ``True`` for ``cfg:*`` / ``short:*`` / ``act:*`` / ``scene:*`` / ``form:*``.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> r = MenuActionRouter.__new__(MenuActionRouter)
            >>> r.matches(
            ...     IncomingMessage(
            ...         channel="telegram", user_id="1", text="",
            ...         metadata={"callback_data": "cfg:voice:mode:off"},
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
        parsed = parse_action_callback(raw.strip())
        return parsed is not None and parsed[0] != "form"

    async def handle(self, msg: IncomingMessage, *, session_id: str) -> str | None:
        """Execute the action and return optional toast text.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            session_id (str): Active gateway session id.

        Returns:
            str | None: Toast or confirmation text.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter.handle)
            True
        """
        _ = session_id
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        raw = md.get("callback_data")
        if not isinstance(raw, str):
            raw = msg.text or ""
        parsed = parse_action_callback(str(raw).strip()) if isinstance(raw, str) else None
        if parsed is None or parsed[0] == "form":
            return None
        from sevn.gateway.menu.menu_readiness import READINESS_LOCKED_TOAST, readiness_for_callback

        if readiness_for_callback(str(raw).strip()) != "Ready":
            toast = READINESS_LOCKED_TOAST
            answered = await self._refresh_config_menu_after_action(msg, raw, toast=toast)
            return None if answered else toast
        kind, target, value = parsed
        if kind == "cycle":
            if value is None:
                return None
            from sevn.integrations.social_media.cycle_validation import (
                validate_config_cycle_mutation,
            )

            if not validate_config_cycle_mutation(target, value):
                toast = "Invalid cycle value."
                answered = await self._refresh_config_menu_after_action(msg, raw, toast=toast)
                return None if answered else toast
            mutate_sevn_json(self._sevn_json, lambda d: _set_nested(d, target, value))
            self._reload_workspace()
            toast = "✅ Updated."
            answered = await self._refresh_config_menu_after_action(msg, raw, toast=toast)
            return None if answered else toast
        if kind == "toggle":
            if value is None:
                return None
            if target == "tracing.redaction.enabled" and value in {"true", "false"}:
                enabled = value == "true"
                mutate_sevn_json(
                    self._sevn_json,
                    lambda d: apply_trace_redaction_to_sevn_doc(d, enabled=enabled),
                )
                self._reload_workspace()
                toast = f"Trace redaction: {'on' if enabled else 'off'}"
            else:
                parsed_val: Any = value
                if value in {"true", "false"}:
                    parsed_val = value == "true"

                def _apply_toggle(doc: dict[str, Any]) -> None:
                    _set_nested(doc, target, parsed_val)
                    if target == "second_brain.layout" and parsed_val == "para":
                        sb_obj = doc.get("second_brain")
                        if isinstance(sb_obj, dict) and "para" not in sb_obj:
                            from sevn.config.sections.features import SecondBrainParaConfig

                            sb_obj["para"] = SecondBrainParaConfig().model_dump()
                    if target == "executors.tier_cd.lambda_rlm.enabled" and parsed_val is True:
                        raw_allowlist = _get_nested(doc, "rlm.lambda_tool_allowlist")
                        if isinstance(raw_allowlist, list) and any(
                            str(x).strip() for x in raw_allowlist
                        ):
                            _set_nested(doc, "rlm.c_d_backend", "lambda_rlm")
                    elif target == "rlm.c_d_backend" and parsed_val == "dspy":
                        _set_nested(doc, "executors.tier_cd.lambda_rlm.enabled", False)

                mutate_sevn_json(self._sevn_json, _apply_toggle)
                self._reload_workspace()
                if target == "second_brain.layout":
                    from sevn.config.loader import load_workspace
                    from sevn.second_brain.bootstrap import ensure_second_brain_scope_layout
                    from sevn.second_brain.paths import effective_scope, resolve_scope_root

                    cfg, _lay = load_workspace(sevn_json=self._sevn_json)
                    sb_cfg = cfg.second_brain
                    if sb_cfg is not None:
                        scope = effective_scope(None, sb_cfg)
                        scope_root = resolve_scope_root(self._content_root, sb_cfg, scope)
                        ensure_second_brain_scope_layout(scope_root, cfg=cfg)
                toast = "✅ Updated."
            answered = await self._refresh_config_menu_after_action(msg, raw, toast=toast)
            return None if answered else toast
        if kind == "prompt":
            row = find_shortcut(self._content_root, target)
            if row is None:
                return f"Unknown shortcut {target!r}."
            template = row.get("payload", {})
            if isinstance(template, dict):
                text = str(template.get("template") or template.get("text") or f"/{target}")
            else:
                text = f"/{target}"
            return text
        if kind == "action":
            if target in _OWNER_ONLY_ACTION_TARGETS and not self._router._resolve_owner_flag(msg):
                await self._answer_owner_only(msg)
                return None
            if target == "dashboard:refresh_pin":
                return await self._handle_dashboard_refresh_pin(msg, raw)
            if target == "dashboard:create_pin":
                return await self._handle_dashboard_create_pin(msg, raw, session_id=session_id)
            if target == "dashboard:unpin":
                return await self._handle_dashboard_unpin(msg, raw)
            if target == "shortcuts:list":
                return await self._handle_shortcuts_list(msg, raw, session_id=session_id)
            if target == "voice:status":
                return await self._handle_voice_status(msg, raw)
            if target == "voice:show":
                return await self._handle_voice_show(msg, raw)
            if target == "channels:status":
                return await self._handle_channels_status(msg, raw)
            if target == "channels:config":
                return await self._handle_channels_config(msg, raw)
            if target == "sessions:list":
                return await self._handle_sessions_list(msg, raw, session_id=session_id)
            if target == "agent:status":
                return await self._handle_agent_status(msg, raw)
            if target == "agent:config":
                return await self._handle_agent_config(msg, raw)
            if target == "agent:sampling:show":
                return await self._handle_agent_sampling_show(msg, raw)
            if target == "self_improve:doctor":
                return await self._handle_self_improve_doctor(msg, raw)
            if target == "self_improve:replay_sampler":
                return await self._handle_self_improve_replay_sampler(msg, raw)
            if target == "skills:list":
                return await self._handle_skills_list(msg, raw)
            if target == "skills:sync":
                return await self._handle_skills_sync(msg, raw)
            if target == "skills:security-scan":
                return await self._handle_skills_security_scan(msg, raw)
            if target == "tools:health":
                return await self._handle_tools_health(msg, raw)
            if target == "memory:search":
                return await self._handle_memory_search(msg, raw, session_id=session_id)
            if target == "memory:index":
                return await self._handle_memory_index(msg, raw)
            if target == "second_brain:reindex":
                return await self._handle_second_brain_reindex(msg, raw)
            if target == "second_brain:setup":
                return await self._handle_second_brain_setup(msg, raw)
            if target == "dreaming:status":
                return await self._handle_dreaming_status(msg, raw)
            if target == "dreaming:undo":
                return await self._handle_dreaming_undo(msg, raw)
            if target == "dreaming:reconcile_cron":
                return await self._handle_dreaming_reconcile_cron(msg, raw)
            if target == "openui:install":
                return await self._handle_openui_install(msg, raw)
            if target == "openui:setup":
                return await self._handle_openui_setup(msg, raw, session_id=session_id)
            if target.startswith("secrets:"):
                return await self._handle_secrets_action(msg, raw, target)
            if target.startswith("pairing:"):
                return await self._handle_pairing_action(msg, raw, target)
            if target.startswith("providers:"):
                return await self._handle_providers_action(msg, raw, target)
            if target == "doctor:run":
                return await self._handle_doctor_run(msg, raw)
            if target == "usage:show":
                return await self._handle_usage_show(msg, raw)
            if target.startswith("turn_bundles:"):
                return await self._handle_turn_bundles_action(msg, raw, target)
            if target == "tracing:config":
                return await self._handle_tracing_config(msg, raw)
            if target.startswith("services:"):
                return await self._handle_services_action(msg, raw, target)
            if target.startswith("config:"):
                return await self._handle_config_action(msg, raw, target)
            if target.startswith("guides:"):
                return await self._handle_guides_action(msg, raw, target)
            if target.startswith("help:"):
                return await self._handle_help_action(msg, raw, target)
            if target.startswith("update:"):
                return await self._handle_update_action(msg, raw, target)
            if target.startswith("deploy:"):
                return await self._handle_deploy_action(msg, raw, target)
            if target == "integrations:status":
                return await self._handle_integrations_status(msg, raw)
            if target.startswith("host:"):
                return await self._handle_host_action(msg, raw, target)
            if target.startswith("dev:"):
                return await self._handle_dev_action(msg, raw, target)
            if target in {"skills:refresh", "integrations:refresh"}:
                answered = await self._refresh_config_menu_after_action(
                    msg,
                    raw,
                    toast="Refreshed.",
                )
                return None if answered else "Refreshed."
            if target.startswith("shortcut_delete:"):
                return await self._handle_shortcut_delete(msg, raw, target)
            if target.startswith("voice:stt:"):
                return await self._handle_voice_stt_cycle(msg, raw, target)
            if target.startswith("voice:engine:"):
                return await self._handle_voice_engine_cycle(msg, raw, target)
            if target == "models:swap":
                return await self._handle_models_swap(msg, raw)
            if target.startswith("models:pick:"):
                return await self._handle_models_pick(msg, raw, target)
            if target.startswith("logs:"):
                return await self._handle_logs_action(msg, raw, target)
            if target.startswith("sevn_bot:"):
                return await self._handle_sevn_bot_action(msg, raw, target)
            if target.startswith("tunnel:"):
                return await self._handle_tunnel_action(msg, raw, target)
            if target == "discogs:whoami":
                return await self._handle_discogs_whoami(msg, raw)
            if target.startswith("subagents:kill:"):
                return await self._handle_subagents_kill(msg, raw, target)
            if target == "subagents:kill_all":
                return await self._handle_subagents_kill_all(msg, raw)
            restart_handled = await self._handle_service_restart_action(
                msg,
                raw,
                target,
                session_id=session_id,
            )
            if restart_handled is not None:
                return restart_handled
        if kind in {"skill", "action", "scene"}:
            token = f"ds:{secrets.token_hex(8)}"
            payload = json.dumps(
                {"v": 1, "kind": kind, "target": target, "value": value},
                separators=(",", ":"),
            )
            chat_raw = md.get("chat_id")
            topic_raw = md.get("topic_id")
            user_raw = msg.user_id
            insert_dispatcher_state(
                self._conn,
                token=token,
                kind=kind,
                user_id=int(user_raw) if str(user_raw).isdigit() else 0,
                chat_id=int(chat_raw) if isinstance(chat_raw, int) else 0,
                topic_id=int(topic_raw) if isinstance(topic_raw, int) else None,
                payload_json=payload,
                ttl_seconds=dispatcher_state_ttl_for_kind(kind, self._workspace),
            )
            return f"Queued {kind} handler ({target})."
        return None

    async def handle_shortcut_crud_reply(
        self,
        *,
        content_root: Path,
        router: ChannelRouter,
    ) -> None:
        """Republish Telegram commands after shortcut store mutation.

        Args:
            content_root (Path): Workspace content root.
            router (ChannelRouter): Gateway router.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter.handle_shortcut_crud_reply)
            True
        """
        _ = content_root
        await republish_set_my_commands(router)

    def _reload_workspace(self) -> None:
        """Reload parsed workspace config after ``sevn.json`` mutation.

        Delegates to :meth:`ChannelRouter.apply_workspace` so ``_queue_mode``,
        scanner, voice runtime, adapter flags, and handler ``_workspace`` refs
        stay in sync (`specs/17-gateway.md` §2.9).

        Examples:
            >>> import inspect
            >>> inspect.isfunction(MenuActionRouter._reload_workspace)
            True
        """
        from sevn.config.loader import load_workspace

        ws, _ = load_workspace(sevn_json=self._sevn_json)
        self._router.apply_workspace(ws)

    async def _refresh_config_menu_after_action(
        self,
        msg: IncomingMessage,
        callback_data: str,
        *,
        toast: str | None,
    ) -> bool:
        """Re-edit the source ``/config`` message and answer the callback toast.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            toast (str | None): Optional toast body for ``answerCallbackQuery``.

        Returns:
            bool: ``True`` when ``answerCallbackQuery`` was invoked.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._refresh_config_menu_after_action)
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        message_raw = md.get("message_id")
        if not isinstance(chat_raw, int) or not isinstance(message_raw, int) or message_raw <= 0:
            return False
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return False
        thread_id = _telegram_api_thread_id(md)
        nav = get_config_menu_nav(self._router, chat_raw, message_raw)
        frame = nav.current
        section: ConfigSection = frame.section
        if section == "root":
            section = infer_config_section_from_callback(callback_data)
        ctx = ConfigMenuRefreshContext(
            chat_id=chat_raw,
            message_id=message_raw,
            topic_id=thread_id,
            section=section,
            models_picker_slot=frame.models_picker_slot,
            models_picker_page=frame.models_picker_page,
        )
        await refresh_config_menu_message(
            adapter,
            ctx,
            self._workspace,
            content_root=self._content_root,
            user_id=msg.user_id,
            is_owner=self._router._resolve_owner_flag(msg),
            router=self._router,
        )
        cq_id = md.get("callback_query_id")
        cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
        if cq_str:
            await _answer_callback(adapter, callback_query_id=cq_str, text=toast)
            return True
        return False

    async def _send_identity_message(
        self,
        msg: IncomingMessage,
        *,
        label: str,
        value: str,
    ) -> None:
        """Post a read-only ``cfg:logs:*`` identity value as a persistent chat message.

        Unlike an ``answerCallbackQuery`` toast (which appears then disappears),
        the value is sent as a normal chat message wrapped in a ``<code>`` span,
        so it stays in the chat and operators can tap-to-copy it. A short toast
        acks the button press when the adapter can answer inline.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            label (str): Human label (e.g. ``Version id``).
            value (str): Identity value to show and copy.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._send_identity_message)
            True
        """
        text = f"{html.escape(label)}:\n<code>{html.escape(value)}</code>"
        await self._send_logs_chunks(msg, [text])
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        cq_id = md.get("callback_query_id")
        cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
        adapter = self._router._adapters.get(msg.channel)
        if adapter is not None and cq_str:
            await _answer_callback(
                adapter,
                callback_query_id=cq_str,
                text=f"{label} sent to chat",
            )

    async def _refresh_stop_picker_after_kill(
        self,
        msg: IncomingMessage,
        *,
        toast: str | None,
    ) -> bool:
        """Re-edit a slash ``/stop`` picker message after a kill callback.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            toast (str | None): Optional toast for ``answerCallbackQuery``.

        Returns:
            bool: ``True`` when callback query was answered or message edited.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._refresh_stop_picker_after_kill)
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        message_raw = md.get("message_id")
        if not isinstance(chat_raw, int) or not isinstance(message_raw, int) or message_raw <= 0:
            return False
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return False
        thread_id = _telegram_api_thread_id(md)
        level1_count, _, rows = await subagent_menu_snapshot_from_router(self._router)
        is_owner = self._router._resolve_owner_flag(msg)
        if level1_count >= 1 and is_owner:
            text = STOP_L1_PICKER_COPY
            markup = build_stop_l1_keyboard(rows, is_owner=True)
        else:
            text = "Stopped."
            markup = {"inline_keyboard": []}
        await _edit_menu_message(
            adapter,
            chat_id=chat_raw,
            message_id=message_raw,
            text=text,
            reply_markup=markup,
            message_thread_id=thread_id,
        )
        cq_id = md.get("callback_query_id")
        cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
        if cq_str:
            await _answer_callback(adapter, callback_query_id=cq_str, text=toast)
            return True
        return False

    async def _after_subagent_kill(
        self,
        msg: IncomingMessage,
        callback_data: str,
        *,
        toast: str,
    ) -> str | None:
        """Refresh config or slash ``/stop`` host after a kill callback.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            toast (str): Kill result toast text.

        Returns:
            str | None: Residual toast when refresh did not answer inline.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._after_subagent_kill)
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        message_raw = md.get("message_id")
        if (
            isinstance(chat_raw, int)
            and isinstance(message_raw, int)
            and message_raw > 0
            and is_registered_config_menu_host(self._router, chat_raw, message_raw)
        ):
            answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
            return None if answered else toast
        answered = await self._refresh_stop_picker_after_kill(msg, toast=toast)
        return None if answered else toast

    def _dashboard_pin_context(
        self,
        msg: IncomingMessage,
    ) -> tuple[int, int | None] | None:
        """Extract chat/topic ids from a dashboard action callback.

        Args:
            msg (IncomingMessage): Inbound callback envelope.

        Returns:
            tuple[int, int | None] | None: ``(chat_id, topic_id)`` when present.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> r = MenuActionRouter.__new__(MenuActionRouter)
            >>> r._dashboard_pin_context(
            ...     IncomingMessage(
            ...         channel="telegram", user_id="1", text="",
            ...         metadata={"chat_id": 42},
            ...     ),
            ... )
            (42, None)
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        if not isinstance(chat_raw, int):
            return None
        return chat_raw, _telegram_api_thread_id(md)

    async def _handle_dashboard_refresh_pin(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Schedule a debounced pinned-dashboard re-render for the current topic.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Toast text when refresh could not be scheduled.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_dashboard_refresh_pin)
            True
        """
        _ = callback_data
        ctx = self._dashboard_pin_context(msg)
        if ctx is None:
            return "Missing chat context."
        chat_raw, topic_id = ctx
        from sevn.gateway.dashboard.dashboard_pin import (
            DashboardPinPublisher,
            default_pin_keyboard,
            default_pin_text,
            lookup_dashboard_pin_message_id,
        )

        pin_message_id = lookup_dashboard_pin_message_id(
            self._router,
            chat_id=chat_raw,
            topic_id=topic_id,
        )
        if pin_message_id is None:
            return "No pinned dashboard in this topic."
        publisher = getattr(self._router, "_dashboard_pin_publisher", None)
        if publisher is None:
            publisher = DashboardPinPublisher()
            self._router._dashboard_pin_publisher = publisher
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return "Channel unavailable."
        model_id = resolve_model_slot(self._workspace, ModelSlot.tier_b)
        voice_mode = _voice_tts_mode(self._workspace)

        async def edit_fn(**kwargs: object) -> bool:
            edit_text = getattr(adapter, "edit_message_text", None)
            if not callable(edit_text):
                return False
            return bool(await cast("Callable[..., Awaitable[Any]]", edit_text)(**kwargs))

        await publisher.schedule_render(
            chat_id=chat_raw,
            topic_id=topic_id,
            message_id=pin_message_id,
            text=default_pin_text(model_id=model_id, voice_mode=voice_mode),
            reply_markup=default_pin_keyboard(),
            edit_fn=edit_fn,
        )
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        cq_id = md.get("callback_query_id")
        cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
        if cq_str:
            await _answer_callback(
                adapter,
                callback_query_id=cq_str,
                text="Pin refresh scheduled.",
            )
        return None

    async def _handle_dashboard_create_pin(
        self,
        msg: IncomingMessage,
        callback_data: str,
        *,
        session_id: str,
    ) -> str | None:
        """Create or update the pinned dashboard message for the current topic.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            session_id (str): Active gateway session id.

        Returns:
            str | None: Toast text when create/update could not complete.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_dashboard_create_pin)
            True
        """
        ctx = self._dashboard_pin_context(msg)
        if ctx is None:
            return "Missing chat context."
        chat_raw, topic_id = ctx
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return "Channel unavailable."
        from sevn.gateway.channel_router import OutgoingMessage, _telegram_reply_metadata
        from sevn.gateway.dashboard.dashboard_pin import (
            default_pin_keyboard,
            default_pin_text,
            lookup_dashboard_pin_message_id,
            register_dashboard_pin,
            render_dashboard_pin,
        )

        model_id = resolve_model_slot(self._workspace, ModelSlot.tier_b)
        voice_mode = _voice_tts_mode(self._workspace)
        existing_id = lookup_dashboard_pin_message_id(
            self._router,
            chat_id=chat_raw,
            topic_id=topic_id,
        )
        toast = "Pin updated."
        pin_message_id: int | None = existing_id
        if pin_message_id is None:
            out_meta = dict(_telegram_reply_metadata(msg))
            out_meta["inline_keyboard"] = default_pin_keyboard()
            if topic_id is not None:
                out_meta["topic_id"] = topic_id
            out_ids = await adapter.send(
                OutgoingMessage(
                    channel=msg.channel,
                    user_id=msg.user_id,
                    text=default_pin_text(model_id=model_id, voice_mode=voice_mode),
                    session_id=session_id,
                    metadata=out_meta,
                ),
            )
            if not out_ids or out_ids == ["0"]:
                return "Could not create pin."
            try:
                pin_message_id = int(out_ids[0])
            except ValueError:
                return "Could not create pin."
            register_dashboard_pin(
                self._router,
                chat_id=chat_raw,
                topic_id=topic_id,
                message_id=pin_message_id,
            )
            toast = "Pin created."
        else:
            rendered = await render_dashboard_pin(
                adapter,
                chat_id=chat_raw,
                topic_id=topic_id,
                message_id=pin_message_id,
                model_id=model_id,
                voice_mode=voice_mode,
            )
            if not rendered:
                return "Could not update pin."
        pinned = await _pin_chat_message(
            adapter,
            chat_id=chat_raw,
            message_id=pin_message_id,
            topic_id=topic_id,
        )
        if not pinned:
            return "Pin message ready but could not pin in chat."
        answered = await self._refresh_config_menu_after_action(
            msg,
            callback_data,
            toast=toast,
        )
        return None if answered else toast

    async def _handle_dashboard_unpin(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Unpin the dashboard message and drop it from the in-memory registry.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Toast text when unpin could not complete.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_dashboard_unpin)
            True
        """
        ctx = self._dashboard_pin_context(msg)
        if ctx is None:
            return "Missing chat context."
        chat_raw, topic_id = ctx
        from sevn.gateway.dashboard.dashboard_pin import unregister_dashboard_pin

        pin_message_id = unregister_dashboard_pin(
            self._router,
            chat_id=chat_raw,
            topic_id=topic_id,
        )
        if pin_message_id is None:
            return "No pinned dashboard in this topic."
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return "Channel unavailable."
        unpinned = await _unpin_chat_message(
            adapter,
            chat_id=chat_raw,
            message_id=pin_message_id,
            topic_id=topic_id,
        )
        if not unpinned:
            return "Could not unpin dashboard message."
        answered = await self._refresh_config_menu_after_action(
            msg,
            callback_data,
            toast="Unpinned.",
        )
        return None if answered else "Unpinned."

    async def _handle_shortcut_delete(
        self,
        msg: IncomingMessage,
        callback_data: str,
        target: str,
    ) -> str | None:
        """Delete one shortcut, republish ``setMyCommands``, and refresh the menu.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target (``shortcut_delete:<name>``).

        Returns:
            str | None: Toast text when delete failed or refresh was skipped.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_shortcut_delete)
            True
        """
        name = target.removeprefix("shortcut_delete:").strip().lower()
        if not name:
            return "Unknown shortcut."
        if not delete_shortcut(self._content_root, name):
            return f"Shortcut {name!r} not found."
        await republish_set_my_commands(self._router)
        answered = await self._refresh_config_menu_after_action(
            msg,
            callback_data,
            toast="Deleted.",
        )
        return None if answered else "Deleted."

    async def _handle_shortcuts_list(
        self,
        msg: IncomingMessage,
        callback_data: str,
        *,
        session_id: str,
    ) -> str | None:
        """Post visible workspace shortcuts as a chat message.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            session_id (str): Active gateway session id (unused).

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_shortcuts_list)
            True
        """
        _ = session_id
        from sevn.gateway.commands.shortcuts_store import list_visible_shortcuts
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram

        is_owner = self._router._resolve_owner_flag(msg)
        rows = list_visible_shortcuts(
            self._content_root,
            user_id=str(msg.user_id),
            is_owner=is_owner,
        )
        if not rows:
            body = "No shortcuts."
        else:
            names = [str(row.get("name", "")).strip() for row in rows if row.get("name")]
            body = "Shortcuts:\n" + "\n".join(f"/{name}" for name in names if name)
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Shortcuts sent")
        return None

    async def _handle_voice_show(self, msg: IncomingMessage, callback_data: str) -> str | None:
        """Post local ``sevn.json`` voice settings (``sevn voice show`` parity).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_voice_show)
            True
        """
        _ = callback_data
        from sevn.cli.commands.voice_cmd import _format_voice_settings, _voice_settings_snapshot
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram

        body = _format_voice_settings(_voice_settings_snapshot(self._workspace))
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Voice settings sent")
        return None

    async def _handle_voice_status(self, msg: IncomingMessage, callback_data: str) -> str | None:
        """Probe configured STT/TTS backends and post health summary.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_voice_status)
            True
        """
        _ = callback_data
        from sevn.cli.commands.voice_cmd import _format_voice_status
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.ui.dashboard.api.system import _probe_voice_backend
        from sevn.voice.backends import build_stt_backend, build_tts_backend
        from sevn.voice.factory import voice_runtime_settings

        voice_settings = voice_runtime_settings(self._workspace)
        rows: list[dict[str, object]] = []
        for tag in voice_settings.stt_providers:
            rows.append(await _probe_voice_backend("stt", tag, build_stt_backend))
        for tag in voice_settings.tts_providers:
            rows.append(await _probe_voice_backend("tts", tag, build_tts_backend))
        normalized = [
            {
                "provider_id": row.get("provider_id"),
                "status": "ok" if row.get("ok") else "warn",
                "detail": row.get("detail") or "",
            }
            for row in rows
        ]
        body = _format_voice_status(normalized)
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Voice probe sent")
        return None

    def _mission_runtime_channel_map(self) -> dict[str, Any]:
        """Return live channel health from gateway mission state when wired.

        Returns:
            dict[str, Any]: Channel name to runtime health mapping.

        Examples:
            >>> router = MenuActionRouter.__new__(MenuActionRouter)
            >>> router._router = type("_R", (), {"_mission_control_state": None})()
            >>> router._mission_runtime_channel_map()
            {}
        """
        state = getattr(self._router, "_mission_control_state", None)
        if state is None or not callable(getattr(state, "get_status", None)):
            return {}
        status = state.get_status()
        channels = status.get("channels")
        return channels if isinstance(channels, dict) else {}

    async def _handle_channels_status(self, msg: IncomingMessage, callback_data: str) -> str | None:
        """Post runtime channel health (``sevn channels status`` parity).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_channels_status)
            True
        """
        _ = callback_data
        from sevn.cli.commands.channels_cmd import _format_channels_status
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.ui.dashboard.api.channels import (
            _channel_enabled_flags,
            _merge_channel_rows,
            _session_counts_by_channel,
        )

        enabled = _channel_enabled_flags(self._workspace)
        runtime = self._mission_runtime_channel_map()
        sessions = _session_counts_by_channel(self._conn)
        channels = _merge_channel_rows(enabled=enabled, runtime=runtime, sessions=sessions)
        body = _format_channels_status({"channels": channels})
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Channel status sent")
        return None

    async def _handle_channels_config(self, msg: IncomingMessage, callback_data: str) -> str | None:
        """Post editable channel toggles (``sevn channels config`` parity).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_channels_config)
            True
        """
        _ = callback_data
        from sevn.cli.commands.channels_cmd import _format_channels_config
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.ui.dashboard.api.channels import _channels_config_payload

        body = _format_channels_config(_channels_config_payload(self._workspace))
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Channel config sent")
        return None

    async def _handle_sessions_list(
        self,
        msg: IncomingMessage,
        callback_data: str,
        *,
        session_id: str,
    ) -> str | None:
        """Post visibility-scoped gateway sessions (``sevn sessions list`` parity).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            session_id (str): Active gateway session id for visibility filter.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_sessions_list)
            True
        """
        _ = callback_data
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.gateway.session.sessions_query import list_sessions

        items = list_sessions(
            self._conn,
            caller_session_id=session_id or None,
            limit=50,
        )
        if not items:
            body = "No sessions."
        else:
            lines = [
                f"{it.get('session_id', '?')}\t{it.get('channel', '?')}\t{it.get('updated_at', '')}"
                for it in items
            ]
            body = "\n".join(lines)
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Sessions sent")
        return None

    async def _handle_agent_status(self, msg: IncomingMessage, callback_data: str) -> str | None:
        """Post active gateway run snapshots (``sevn agent status`` parity).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_agent_status)
            True
        """
        _ = callback_data
        from sevn.cli.commands.agent_cmd import _format_run_snapshots
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.ui.dashboard.query import list_active_run_snapshots

        body_dict = list_active_run_snapshots(self._conn, limit=50)
        body = _format_run_snapshots(body_dict)
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Active runs sent")
        return None

    async def _handle_agent_config(self, msg: IncomingMessage, callback_data: str) -> str | None:
        """Post resolved model slots (``sevn agent config`` / ``sevn models show`` parity).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_agent_config)
            True
        """
        _ = callback_data
        from sevn.cli.commands.agent_cmd import _format_agent_config
        from sevn.config.model_resolution import (
            resolve_main_model_id,
            resolve_model_slot,
            use_main_model_for_all,
        )
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.ui.dashboard.api.agent import _AGENT_CONFIG_SLOTS, _model_warnings

        workspace = self._workspace
        unified = use_main_model_for_all(workspace)
        try:
            main_model = resolve_main_model_id(workspace)
        except Exception as exc:
            return f"Could not resolve main model: {exc}"
        slots: list[dict[str, object]] = []
        for key, slot in _AGENT_CONFIG_SLOTS:
            try:
                resolved = resolve_model_slot(workspace, slot)
            except Exception:
                resolved = main_model
            slots.append(
                {"slot": key, "resolved": resolved, "editable": not unified or key == "triager"},
            )
        body = _format_agent_config(
            {
                "use_main_model_for_all": unified,
                "main_model": main_model,
                "slots": slots,
                "warnings": _model_warnings(workspace),
            },
        )
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Resolved slots sent")
        return None

    async def _handle_agent_sampling_show(
        self, msg: IncomingMessage, callback_data: str
    ) -> str | None:
        """Post workspace LLM sampling params (``sevn models params`` parity).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_agent_sampling_show)
            True
        """
        _ = callback_data
        from sevn.cli.commands.models_cmd import _format_llm_params
        from sevn.config.llm_params import LLM_PARAMS_FILENAME, load_or_create_llm_params_doc
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram

        path = self._content_root / LLM_PARAMS_FILENAME
        source = "workspace" if path.is_file() else "builtin"
        body = _format_llm_params(
            {
                "source": source,
                "path": str(path),
                "doc": load_or_create_llm_params_doc(self._content_root),
                "restart_required": True,
            },
        )
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Sampling params sent")
        return None

    async def _handle_self_improve_doctor(
        self, msg: IncomingMessage, callback_data: str
    ) -> str | None:
        """Post self-improve config posture (``sevn improve doctor`` parity).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_self_improve_doctor)
            True
        """
        _ = callback_data
        import os

        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.self_improve.effective import effective_self_improve_enabled

        ws = self._workspace
        si = ws.self_improve
        hub_repo = (si.hub.repo or "").strip() if si and si.hub else ""
        preset = si.preset if si else "A"
        hub_ok = True
        if si and si.enabled and preset in ("B", "C"):
            hub_ok = bool(hub_repo)
        payload = {
            "effective_enabled": effective_self_improve_enabled(ws),
            "config_enabled": bool(si and si.enabled),
            "preset": preset,
            "hub_repo_configured": hub_ok,
            "hub_repo_non_empty": bool(hub_repo),
            "env_disable_self_improve": os.environ.get("SEVN_DISABLE_SELF_IMPROVE", "").strip()
            == "1",
        }
        body = "\n".join(f"{key}: {payload[key]}" for key in sorted(payload))
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Improve doctor sent")
        return None

    async def _handle_self_improve_replay_sampler(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Replay the bundled sampler fixture (``sevn improve replay-sampler`` parity).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_self_improve_replay_sampler)
            True
        """
        _ = callback_data
        if not self._router._resolve_owner_flag(msg):
            return "Owner only."
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.self_improve.sampler import ShortlistCandidate, allocate_shortlist

        cands = [
            ShortlistCandidate(
                turn_id="exp-a",
                bucket="explicit_feedback",
                channel="web",
                intent=None,
                complexity_tier=None,
                score=0.0,
                signals=None,
            ),
            ShortlistCandidate(
                turn_id="ctrl-b",
                bucket="control_random_sample",
                channel="telegram",
                intent=None,
                complexity_tier=None,
                score=0.0,
                signals=None,
            ),
        ]
        selected, diagnostics = allocate_shortlist(
            candidates=cands,
            max_candidates=12,
            explicit_feedback_floor_pct=0.25,
            per_channel_pct_max=0.6,
            per_intent_pct_max=0.6,
            per_tier_pct_max=0.6,
            per_channel_pct_min=None,
        )
        body = (
            f"shortlist_turn_ids: {[c.turn_id for c in selected]}\n"
            f"count: {len(selected)}\n"
            f"diagnostics: {diagnostics}"
        )
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Replay sampler sent")
        return None

    async def _handle_skills_list(self, msg: IncomingMessage, callback_data: str) -> str | None:
        """Post workspace skills inventory (``sevn skills list`` parity).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_skills_list)
            True
        """
        _ = callback_data
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.skills.manager import SkillsManager
        from sevn.ui.dashboard.api.agent import _serialize_skill_inventory
        from sevn.workspace.layout import WorkspaceLayout

        layout = WorkspaceLayout.from_config(self._sevn_json, self._workspace)
        manager = SkillsManager.shared(
            layout.content_root,
            layout=layout,
            config=self._workspace,
        )
        skills = _serialize_skill_inventory(manager)
        lines = [f"skills: {len(skills)}"]
        for row in skills[:50]:
            name = row.get("id") or row.get("name") or "?"
            lines.append(f"  {name}")
        body = "\n".join(lines)
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Skills list sent")
        return None

    async def _handle_skills_sync(self, msg: IncomingMessage, callback_data: str) -> str | None:
        """Append missing starter rows to ``skills/INDEX.md`` (``sevn skills sync --additive``).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_skills_sync)
            True
        """
        _ = callback_data
        from sevn.cli.commands.skills_cmd import _resolve_workspace_index, _sync_additive
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram

        target = _resolve_workspace_index(self._content_root)
        added, total = _sync_additive(target)
        rel = (
            target.relative_to(self._content_root)
            if self._content_root in target.parents
            else target
        )
        body = f"skills sync: appended {added} row(s); starter has {total} (target: {rel})"
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Skills index synced")
        return None

    async def _handle_skills_security_scan(
        self, msg: IncomingMessage, callback_data: str
    ) -> str | None:
        """Run SkillSpector over workspace user/generated skill dirs.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Error toast text, or ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_skills_security_scan)
            True
        """
        _ = callback_data
        from sevn.cli.commands.skills_cmd import _collect_security_scan_paths
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.skills.security_scan import (
            DEFAULT_FAIL_SEVERITIES,
            normalize_skill_path,
            resolve_skillspector_command,
            scan_skill_path,
            write_workspace_scan_summary,
        )

        if resolve_skillspector_command() is None:
            return "SkillSpector CLI not found — install with: uv sync --extra skillspector"
        try:
            targets = _collect_security_scan_paths(
                self._content_root,
                scan_path=None,
                all_user=True,
                all_generated=True,
            )
        except Exception as exc:
            return str(exc)
        lines: list[str] = []
        total_findings = 0
        high_critical = 0
        rel_paths: list[str] = []
        exit_code = 0
        for target in targets:
            result = scan_skill_path(target, fail_severities=DEFAULT_FAIL_SEVERITIES)
            rel = normalize_skill_path(target, repo_root=self._content_root)
            rel_paths.append(rel)
            if result.error:
                lines.append(f"{rel}: scan error — {result.error}")
                exit_code = 1
                continue
            total_findings += len(result.issues)
            high_critical += len(result.issues_at_or_above(DEFAULT_FAIL_SEVERITIES))
            if result.issues:
                lines.append(f"{rel}: {len(result.issues)} HIGH/CRITICAL finding(s)")
                exit_code = 1
            else:
                lines.append(f"{rel}: ok")
        write_workspace_scan_summary(
            self._content_root,
            scanned_paths=rel_paths,
            total_findings=total_findings,
            high_critical=high_critical,
        )
        body = "No skill directories to scan." if not lines else "\n".join(lines)
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(
            msg,
            "Scan complete" if exit_code == 0 else "Scan found issues",
        )
        return None

    async def _handle_tools_health(self, msg: IncomingMessage, callback_data: str) -> str | None:
        """Post chronic tool/skill failure rows (``sevn tools health`` parity).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_tools_health)
            True
        """
        _ = callback_data
        from sevn.cli.commands.tools_cmd import _format_tools_health
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.ui.dashboard.api.agent import _workspace_id
        from sevn.ui.dashboard.services.tool_skill_health import ToolSkillHealthService
        from sevn.workspace.layout import WorkspaceLayout

        layout = WorkspaceLayout.from_config(self._sevn_json, self._workspace)
        svc = ToolSkillHealthService(workspace_id=_workspace_id(self._workspace, layout))
        rows = svc.list_rows(self._conn, source="telegram")
        body = _format_tools_health({"rows": rows, "count": len(rows)})
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Tool health sent")
        return None

    async def _handle_memory_search(
        self,
        msg: IncomingMessage,
        callback_data: str,
        *,
        session_id: str,
    ) -> str | None:
        """Browse or search federated memory layers (``memory_search`` tool parity).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            session_id (str): Active gateway session id for SQLite scope.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_memory_search)
            True
        """
        _ = callback_data
        import json

        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.tools.memory_tools import federated_memory_search

        sid = session_id.strip() or str(msg.metadata.get("session_id") or "telegram:menu")
        hits, truncated = federated_memory_search(
            self._content_root,
            self._conn,
            query="",
            session_id=sid,
            source="all",
            limit=10,
        )
        body = json.dumps({"hits": hits, "truncated": truncated}, indent=2)
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Memory search sent")
        return None

    async def _handle_memory_index(self, msg: IncomingMessage, callback_data: str) -> str | None:
        """Report memory index CLI posture (``sevn memory index`` is not implemented yet).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_memory_index)
            True
        """
        _ = callback_data
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram

        body = "`sevn memory index` is not implemented yet."
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Memory index")
        return None

    async def _handle_second_brain_reindex(
        self, msg: IncomingMessage, callback_data: str
    ) -> str | None:
        """Build or refresh the Witchcraft semantic index (``sevn second-brain reindex``).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Precondition error text, or ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_second_brain_reindex)
            True
        """
        _ = callback_data
        from sevn.cli.commands.second_brain_cmd import _run_reindex
        from sevn.cli.errors import CliPreconditionError
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram

        try:
            _run_reindex(self._workspace, self._content_root)
        except CliPreconditionError as exc:
            return str(exc)
        body = "Witchcraft index built for resolved vault content roots."
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Reindex complete")
        return None

    async def _handle_second_brain_setup(
        self, msg: IncomingMessage, callback_data: str
    ) -> str | None:
        """Enable Second Brain and bootstrap vault layout (``sevn second-brain setup``).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Error toast text, or ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_second_brain_setup)
            True
        """
        _ = callback_data
        from sevn.cli.commands.second_brain_cmd import _resolve_setup_layout
        from sevn.config.sections.features import SecondBrainParaConfig
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.second_brain.bootstrap import ensure_second_brain_scope_layout
        from sevn.second_brain.paths import effective_scope, resolve_scope_root

        layout_name = _resolve_setup_layout(
            "auto", content_root=self._content_root, vault_norm=None
        )

        def _apply(doc: dict[str, Any]) -> None:
            _set_nested(doc, "second_brain.enabled", True)
            _set_nested(doc, "second_brain.layout", layout_name)
            if layout_name == "para":
                sb_obj = doc.setdefault("second_brain", {})
                if isinstance(sb_obj, dict) and "para" not in sb_obj:
                    sb_obj["para"] = SecondBrainParaConfig().model_dump()

        mutate_sevn_json(self._sevn_json, _apply)
        self._reload_workspace()
        sb_cfg = self._workspace.second_brain
        if sb_cfg is None:
            return "second_brain config missing after setup"
        scope = effective_scope(None, sb_cfg)
        scope_root = resolve_scope_root(self._content_root, sb_cfg, scope)
        try:
            created = ensure_second_brain_scope_layout(
                scope_root,
                cfg=self._workspace,
                copy_model=True,
            )
        except Exception as exc:
            return str(exc)
        body = (
            f"Second Brain enabled (layout: {layout_name}).\n"
            f"Created: {', '.join(created) if created else 'none'}"
        )
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Second Brain bootstrapped")
        return None

    async def _handle_dreaming_status(self, msg: IncomingMessage, callback_data: str) -> str | None:
        """Summarize Dreaming toggles (``sevn memory status`` parity).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_dreaming_status)
            True
        """
        _ = callback_data
        import json

        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.memory.dreaming.scheduler import effective_dreaming

        dreaming = effective_dreaming(self._workspace)
        body = json.dumps(
            {
                "dreaming_enabled": dreaming.enabled,
                "promotion_mode": dreaming.promotion_mode,
                "cron": dreaming.cron,
                "threshold": dreaming.threshold,
                "max_promotions_per_run": dreaming.max_promotions_per_run,
            },
            indent=2,
        )
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Dreaming status sent")
        return None

    async def _handle_dreaming_undo(self, msg: IncomingMessage, callback_data: str) -> str | None:
        """Undo the last auto Dreaming batch (``sevn memory rem-backfill --rollback``).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_dreaming_undo)
            True
        """
        _ = callback_data
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.memory.dreaming.rollback import rollback_last_auto_batch

        rollback_last_auto_batch(self._content_root)
        body = "rollback complete"
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Dreaming rollback complete")
        return None

    async def _handle_dreaming_reconcile_cron(
        self, msg: IncomingMessage, callback_data: str
    ) -> str | None:
        """Rewrite the Dreaming cron row (``sevn memory reconcile-cron``).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_dreaming_reconcile_cron)
            True
        """
        _ = callback_data
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.memory.dreaming.scheduler import reconcile_dreaming_cron_job

        reconcile_dreaming_cron_job(self._conn, self._workspace)
        body = "dreaming cron row reconciled"
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Cron reconciled")
        return None

    async def _handle_openui_install(self, msg: IncomingMessage, callback_data: str) -> str | None:
        """Install the upstream OpenWiki npm CLI (``sevn openwiki install``).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Error text, or ``None`` after refresh/toast.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_openui_install)
            True
        """
        _ = callback_data
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.skills.openwiki_install import openwiki_cli_installed, run_openwiki_install

        code, detail = run_openwiki_install(skip_if_installed=True)
        if code != 0:
            return detail or "OpenWiki install failed"
        installed = openwiki_cli_installed()
        body = detail or f"openwiki CLI {'installed' if installed else 'install finished'}"
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        answered = await self._refresh_config_menu_after_action(
            msg,
            callback_data,
            toast="OpenWiki installed.",
        )
        return None if answered else body

    async def _handle_openui_setup(
        self,
        msg: IncomingMessage,
        callback_data: str,
        *,
        session_id: str = "",
    ) -> str | None:
        """Install OpenWiki CLI then start the LLM key form (``sevn openwiki setup``).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            session_id (str): Active gateway session id for the configure wizard.

        Returns:
            str | None: Install error text, or ``None`` after starting the form.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_openui_setup)
            True
        """
        _ = callback_data
        from sevn.gateway.channel_router import IncomingMessage
        from sevn.gateway.commands.menu_form_handler import MenuFormHandler
        from sevn.skills.openwiki_install import openwiki_cli_installed, run_openwiki_install

        code, detail = run_openwiki_install(skip_if_installed=True)
        if code != 0:
            return detail or "OpenWiki install failed"
        if not openwiki_cli_installed():
            return detail or "OpenWiki install did not place openwiki on PATH"
        md = dict(msg.metadata) if isinstance(msg.metadata, dict) else {}
        md["callback_data"] = "form:openui:configure"
        form_msg = IncomingMessage(
            channel=msg.channel,
            user_id=msg.user_id,
            text=msg.text,
            metadata=md,
        )
        handler = MenuFormHandler(
            workspace=self._workspace,
            router=self._router,
            conn=self._conn,
            content_root=self._content_root,
            sevn_json_path=self._sevn_json,
        )
        await handler.handle(form_msg, session_id=session_id)
        return None

    @staticmethod
    def reject_unknown_callback_suffix(family_prefix: str, suffix: str) -> str:
        """Return explicit error toast for unrecognised callback suffixes (D15).

        Args:
            family_prefix (str): Callback family prefix (e.g. ``act:secrets:``).
            suffix (str): Unrecognised suffix segment.

        Returns:
            str: Operator-facing error toast text.

        Examples:
            >>> MenuActionRouter.reject_unknown_callback_suffix("act:secrets:", "nope")
            "Unknown act:secrets: action: 'nope'."
        """
        return f"Unknown {family_prefix} action: {suffix!r}."

    async def _load_secrets_entries(self) -> list[dict[str, str]]:
        """List logical secret aliases with fingerprints from the encrypted store.

        Returns:
            list[dict[str, str]]: Rows with ``alias`` and ``fingerprint_sha256_hex``.

        Raises:
            RuntimeError: When the store cannot be opened.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._load_secrets_entries)
            True
        """
        from sevn.secrets.fingerprint import fingerprint_sha256_hex
        from sevn.secrets.migrate import encrypted_file_backend_for_workspace
        from sevn.security.secrets.errors import SecretsStoreCorruptError

        try:
            backend = encrypted_file_backend_for_workspace(self._content_root, self._workspace)
            enc_map = await backend.load_decrypted_map()
        except (ValueError, SecretsStoreCorruptError) as exc:
            msg = f"Secrets store unavailable: {exc}"
            raise RuntimeError(msg) from exc
        return [
            {"alias": key, "fingerprint_sha256_hex": fingerprint_sha256_hex(enc_map[key])}
            for key in sorted(enc_map)
        ]

    async def _handle_secrets_action(
        self,
        msg: IncomingMessage,
        callback_data: str,
        target: str,
    ) -> str | None:
        """Dispatch Access > Secrets ``act:secrets:*`` rows (W7d).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target after ``act:``.

        Returns:
            str | None: Toast when the action could not proceed; ``None`` when handled.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_secrets_action)
            True
        """
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        if target == "secrets:list":
            return await self._handle_secrets_list(msg, callback_data)
        if target == "secrets:check-unlock":
            return await self._handle_secrets_check_unlock(msg, callback_data)
        if target == "secrets:rm:confirm":
            return await self._handle_secrets_rm_confirm(msg, callback_data)
        if target == "secrets:rm:cancel":
            return await self._handle_secrets_rm_cancel(msg, callback_data)
        if target == "secrets:export-secrets":
            return await self._handle_secrets_export_prompt(msg, callback_data)
        if target == "secrets:export-secrets:confirm":
            return await self._handle_secrets_export_confirm(msg, callback_data)
        if target == "secrets:export-secrets:cancel":
            return await self._handle_secrets_export_cancel(msg, callback_data)
        toast = self.reject_unknown_callback_suffix("act:secrets:", target.removeprefix("secrets:"))
        answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
        return None if answered else toast

    async def _handle_secrets_list(self, msg: IncomingMessage, callback_data: str) -> str | None:
        """Post alias + fingerprint listing (never secret values).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Error toast when listing failed.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_secrets_list)
            True
        """
        _ = callback_data
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram

        try:
            rows = await self._load_secrets_entries()
        except RuntimeError as exc:
            return str(exc)
        if not rows:
            body = "No logical secrets stored yet."
        else:
            lines = [
                "alias\tfingerprint_sha256_hex",
                *(f"{r['alias']}\t{r['fingerprint_sha256_hex']}" for r in rows),
            ]
            body = "\n".join(lines)
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Secrets list sent")
        return None

    async def _handle_secrets_check_unlock(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Report encrypted-store unlock key reachability.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_secrets_check_unlock)
            True
        """
        _ = callback_data
        import os

        from sevn.config.workspace_config import effective_encrypted_file_key_source
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.security.secrets.passphrase_prime import (
            keychain_has_unlock_secret,
            unlock_env_var_for,
        )

        key_source = effective_encrypted_file_key_source(self._workspace.secrets_backend)
        var = unlock_env_var_for(key_source)
        in_env = bool(os.environ.get(var, "").strip())
        in_keychain = bool(await keychain_has_unlock_secret(key_source=key_source))
        reachable = in_env or in_keychain
        body = (
            f"key_source={key_source} var={var} in_env={in_env} "
            f"in_keychain={in_keychain} reachable={reachable}"
        )
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Unlock status sent")
        return None

    async def _edit_secrets_rm_confirm(
        self,
        msg: IncomingMessage,
        *,
        alias: str,
        fingerprint: str,
    ) -> bool:
        """Edit the ``/config`` message to the remove-secret confirmation screen.

        Args:
            msg (IncomingMessage): Inbound callback or chat envelope.
            alias (str): Logical secret alias pending deletion.
            fingerprint (str): SHA-256 hex fingerprint for confirmation copy.

        Returns:
            bool: ``True`` when the confirm screen was shown.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._edit_secrets_rm_confirm)
            True
        """
        from sevn.gateway.menu.confirm_gates import (
            build_confirm_gate_keyboard,
            confirm_gate_message,
        )
        from sevn.gateway.menu.menu import _config_chrome

        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        message_raw = md.get("message_id")
        if not isinstance(chat_raw, int) or not isinstance(message_raw, int):
            return False
        topic_raw = md.get("topic_id")
        insert_dispatcher_state(
            self._conn,
            token=f"ds:{secrets.token_hex(8)}",
            kind="secrets_rm",
            user_id=int(msg.user_id) if str(msg.user_id).isdigit() else 0,
            chat_id=chat_raw,
            topic_id=topic_raw if isinstance(topic_raw, int) else None,
            payload_json=json.dumps(
                {"v": 1, "alias": alias, "fingerprint_sha256_hex": fingerprint},
                separators=(",", ":"),
            ),
            ttl_seconds=600,
        )
        config_menu_nav_push_current(self._router, chat_raw, message_raw)
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return False
        thread_id = _telegram_api_thread_id(md)
        rows = build_confirm_gate_keyboard("secrets:rm")
        rows.extend(_config_chrome())
        edit_text = getattr(adapter, "edit_message_text", None)
        if not callable(edit_text):
            return False
        caption = confirm_gate_message(
            title="Remove secret",
            detail=(
                f"Delete logical secret `{alias}`?\n"
                f"fingerprint={fingerprint}\n"
                "This cannot be undone."
            ),
        )
        body: dict[str, Any] = {
            "chat_id": chat_raw,
            "message_id": message_raw,
            "text": caption,
            "reply_markup": {"inline_keyboard": rows},
        }
        if thread_id is not None:
            body["message_thread_id"] = thread_id
        return bool(await cast("Callable[..., Awaitable[Any]]", edit_text)(**body))

    async def _handle_secrets_rm_confirm(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Delete one logical secret after two-step confirm (W7d).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Toast when deletion failed.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_secrets_rm_confirm)
            True
        """
        _ = callback_data
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        user_raw = msg.user_id
        user_id = int(user_raw) if str(user_raw).isdigit() else 0
        pending = self._find_pending_secrets_rm(
            chat_id=int(chat_raw) if isinstance(chat_raw, int) else 0,
            user_id=user_id,
        )
        if pending is None:
            return "No pending secret removal — start again from Remove secret."
        alias = str(pending.get("alias", "")).strip()
        fingerprint = str(pending.get("fingerprint_sha256_hex", "")).strip()
        if not alias or not fingerprint:
            return "Pending removal payload invalid."
        from sevn.secrets.fingerprint import fingerprint_sha256_hex
        from sevn.secrets.migrate import encrypted_file_backend_for_workspace
        from sevn.security.secrets.errors import SecretsStoreCorruptError

        try:
            backend = encrypted_file_backend_for_workspace(self._content_root, self._workspace)
            existing = await backend.get(alias)
        except (ValueError, SecretsStoreCorruptError) as exc:
            return f"Could not delete secret: {exc}"
        if existing is None:
            return f"Secret {alias!r} not found."
        if fingerprint_sha256_hex(existing) != fingerprint:
            return "Fingerprint mismatch — list aliases and try again."
        await backend.delete(alias)
        self._clear_pending_secrets_rm(
            chat_id=int(chat_raw) if isinstance(chat_raw, int) else 0,
            user_id=user_id,
        )
        toast = f"Deleted {alias!r}."
        if isinstance(chat_raw, int) and isinstance(md.get("message_id"), int):
            get_config_menu_nav(
                self._router, chat_raw, md["message_id"]
            ).current = ConfigMenuNavFrame(
                section="access_secrets",
            )
        answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
        return None if answered else toast

    async def _handle_secrets_rm_cancel(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Return to Access > Secrets after cancelling remove-secret confirm.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Toast when refresh was skipped.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_secrets_rm_cancel)
            True
        """
        _ = callback_data
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        user_raw = msg.user_id
        if isinstance(chat_raw, int):
            self._clear_pending_secrets_rm(
                chat_id=chat_raw,
                user_id=int(user_raw) if str(user_raw).isdigit() else 0,
            )
        if isinstance(chat_raw, int) and isinstance(md.get("message_id"), int):
            get_config_menu_nav(
                self._router, chat_raw, md["message_id"]
            ).current = ConfigMenuNavFrame(
                section="access_secrets",
            )
        answered = await self._refresh_config_menu_after_action(
            msg, callback_data, toast="Cancelled."
        )
        return None if answered else "Cancelled."

    async def _handle_host_action(
        self,
        msg: IncomingMessage,
        callback_data: str,
        target: str,
    ) -> str | None:
        """Post copy-paste host-only command cards (D17, W8).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target after ``act:``.

        Returns:
            str | None: Toast when the card could not be sent.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_host_action)
            True
        """
        _ = callback_data
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        suffix = target.removeprefix("host:")
        command = _HOST_SHELL_COMMANDS.get(suffix)
        if command is None:
            toast = self.reject_unknown_callback_suffix("act:host:", suffix)
            answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
            return None if answered else toast
        from sevn.gateway.menu.host_command_cards import render_host_command_card

        card = await render_host_command_card(
            command,
            why="Run this in your shell — the gateway cannot execute it here.",
        )
        await self._send_logs_chunks(msg, [card])
        await self._answer_chat_action(msg, "Command card sent")
        return None

    async def _handle_dev_action(
        self,
        msg: IncomingMessage,
        callback_data: str,
        target: str,
    ) -> str | None:
        """Post repo-only developer copy-paste cards (W8).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target after ``act:``.

        Returns:
            str | None: Toast when the card could not be sent.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_dev_action)
            True
        """
        _ = callback_data
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        from sevn.config.sevn_repo import resolve_sevn_checkout_for_workspace
        from sevn.gateway.menu.host_command_cards import (
            has_bound_source_checkout,
            render_host_command_card,
        )

        if not has_bound_source_checkout(self._workspace, self._content_root):
            return "No sevn.bot checkout — set my_sevn.repo_path in sevn.json."
        suffix = target.removeprefix("dev:")
        command = _DEV_SHELL_COMMANDS.get(suffix)
        if command is None:
            toast = self.reject_unknown_callback_suffix("act:dev:", suffix)
            answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
            return None if answered else toast
        checkout = resolve_sevn_checkout_for_workspace(
            self._workspace,
            content_root=self._content_root,
        )
        why = "Run this inside your sevn.bot git checkout — the gateway cannot execute it here."
        if checkout is not None:
            why = f"{why}\nCheckout: {checkout}"
        card = await render_host_command_card(command, why=why)
        await self._send_logs_chunks(msg, [card])
        await self._answer_chat_action(msg, "Developer command card sent")
        return None

    async def _handle_integrations_status(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """List per-integration enabled/config posture (W8).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Error toast when listing failed.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_integrations_status)
            True
        """
        _ = callback_data
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.gateway.menu.menu import (
            _configured_integration_ids,
            _integration_enabled,
            _raw_sevn_doc,
            _schema_has_integration_enabled_toggle,
        )

        raw_doc = _raw_sevn_doc(self._content_root)
        ids = _configured_integration_ids(self._workspace, raw_doc=raw_doc)
        if not ids:
            body = "No integrations configured yet."
        else:
            lines = ["Integration status", ""]
            for integration_id in ids:
                enabled = _integration_enabled(
                    self._workspace,
                    integration_id,
                    raw_doc=raw_doc,
                )
                toggle = (
                    "schema toggle"
                    if _schema_has_integration_enabled_toggle(integration_id)
                    else "no schema toggle"
                )
                lines.append(f"• {integration_id}: enabled={'on' if enabled else 'off'} ({toggle})")
            body = "\n".join(lines)
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Integration status sent")
        return None

    async def _edit_secrets_export_confirm(self, msg: IncomingMessage) -> bool:
        """Edit the menu message to the export-secrets confirmation screen (W8).

        Args:
            msg (IncomingMessage): Inbound callback envelope.

        Returns:
            bool: ``True`` when the confirm screen was shown.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._edit_secrets_export_confirm)
            True
        """
        from sevn.gateway.menu.confirm_gates import (
            build_confirm_gate_keyboard,
            confirm_gate_message,
        )
        from sevn.gateway.menu.menu import _config_chrome

        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        message_raw = md.get("message_id")
        if not isinstance(chat_raw, int) or not isinstance(message_raw, int):
            return False
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return False
        thread_id = _telegram_api_thread_id(md)
        rows = build_confirm_gate_keyboard("secrets:export-secrets")
        rows.extend(_config_chrome())
        edit_text = getattr(adapter, "edit_message_text", None)
        if not callable(edit_text):
            return False
        caption = confirm_gate_message(
            title="Export .env bundle",
            detail=(
                "Writes a plaintext `.env` bundle with decrypted secrets.\n"
                "Store it safely — anyone with the file can recover your secrets."
            ),
        )
        body: dict[str, Any] = {
            "chat_id": chat_raw,
            "message_id": message_raw,
            "text": caption,
            "reply_markup": {"inline_keyboard": rows},
        }
        if thread_id is not None:
            body["message_thread_id"] = thread_id
        config_menu_nav_push_current(self._router, chat_raw, message_raw)
        user_raw = msg.user_id
        insert_dispatcher_state(
            self._conn,
            token=f"ds:{secrets.token_hex(8)}",
            kind="secrets_export",
            user_id=int(user_raw) if str(user_raw).isdigit() else 0,
            chat_id=chat_raw,
            topic_id=thread_id,
            payload_json=json.dumps({"v": 1}, separators=(",", ":")),
            ttl_seconds=600,
        )
        return bool(await cast("Callable[..., Awaitable[Any]]", edit_text)(**body))

    async def _handle_secrets_export_prompt(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Show two-step confirm before exporting secrets (W8).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Toast when confirm could not be shown.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_secrets_export_prompt)
            True
        """
        _ = callback_data
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        if await self._edit_secrets_export_confirm(msg):
            await self._answer_chat_action(msg, "Confirm export")
            return None
        return "Could not show export confirm."

    async def _handle_secrets_export_confirm(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Export decrypted secrets to a bundle file and deliver via Telegram (W8).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Error toast when export failed.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_secrets_export_confirm)
            True
        """
        _ = callback_data
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        user_raw = msg.user_id
        pending = self._find_pending_secrets_export(
            chat_id=int(chat_raw) if isinstance(chat_raw, int) else 0,
            user_id=int(user_raw) if str(user_raw).isdigit() else 0,
        )
        if pending is None:
            return "No pending export — start again from Export .env bundle."
        from sevn.gateway.channel_router import OutgoingMessage, _telegram_reply_metadata
        from sevn.onboarding.export_bundle import ExportBundleError, run_export_secrets
        from sevn.tools.outbound import _attachment_kind, _guess_mime

        export_dir = self._content_root / ".sevn" / "telegram-exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        out_path = export_dir / "secrets-export.env"
        try:
            result = await run_export_secrets(
                workspace_root=self._content_root,
                to_file=out_path,
                force=True,
            )
        except ExportBundleError as exc:
            return str(exc)
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return "Channel unavailable."
        attachment_meta: dict[str, Any] = {
            "attachment_path": str(result.path),
            "attachment_filename": result.path.name,
            "attachment_mime": _guess_mime(result.path),
            "attachment_kind": _attachment_kind(result.path),
        }
        attachment_meta.update(_telegram_reply_metadata(msg))
        summary = (
            f"Exported {result.secret_count} secret(s) for {result.bot_name!r}.\n"
            "Plaintext bundle attached — store it safely."
        )
        if result.git_unignored_warning:
            summary += "\nWarning: export path is not git-ignored."
        self._clear_pending_secrets_export(
            chat_id=int(chat_raw) if isinstance(chat_raw, int) else 0,
            user_id=int(user_raw) if str(user_raw).isdigit() else 0,
        )
        await adapter.send(
            OutgoingMessage(
                channel=msg.channel,
                user_id=msg.user_id,
                text=summary,
                metadata=attachment_meta,
            ),
        )
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        if isinstance(chat_raw, int) and isinstance(md.get("message_id"), int):
            get_config_menu_nav(
                self._router, chat_raw, md["message_id"]
            ).current = ConfigMenuNavFrame(section="access_secrets")
        answered = await self._refresh_config_menu_after_action(
            msg,
            callback_data,
            toast="Export sent.",
        )
        return None if answered else "Export sent."

    async def _handle_secrets_export_cancel(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Return to Access > Secrets after cancelling export confirm (W8).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Toast when refresh was skipped.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_secrets_export_cancel)
            True
        """
        _ = callback_data
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        user_raw = msg.user_id
        if isinstance(chat_raw, int):
            self._clear_pending_secrets_export(
                chat_id=chat_raw,
                user_id=int(user_raw) if str(user_raw).isdigit() else 0,
            )
        if isinstance(chat_raw, int) and isinstance(md.get("message_id"), int):
            get_config_menu_nav(
                self._router, chat_raw, md["message_id"]
            ).current = ConfigMenuNavFrame(section="access_secrets")
        answered = await self._refresh_config_menu_after_action(
            msg, callback_data, toast="Cancelled."
        )
        return None if answered else "Cancelled."

    def _find_pending_secrets_rm(self, *, chat_id: int, user_id: int) -> dict[str, Any] | None:
        """Return the newest pending secrets-rm payload for one chat and user.

        Args:
            chat_id (int): Telegram chat id.
            user_id (int): Telegram user id that started the confirm flow.

        Returns:
            dict[str, Any] | None: Parsed payload or ``None``.

        Examples:
            >>> MenuActionRouter._find_pending_secrets_rm.__name__
            '_find_pending_secrets_rm'
        """
        row = self._conn.execute(
            """
            SELECT payload_json FROM dispatcher_state
            WHERE kind = 'secrets_rm' AND chat_id = ? AND user_id = ?
            ORDER BY rowid DESC LIMIT 1
            """,
            (chat_id, user_id),
        ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row[0]))
        except (TypeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _clear_pending_secrets_rm(self, *, chat_id: int, user_id: int) -> None:
        """Drop pending secrets-rm dispatcher rows for one chat and user.

        Args:
            chat_id (int): Telegram chat id.
            user_id (int): Telegram user id that started the confirm flow.

        Examples:
            >>> MenuActionRouter._clear_pending_secrets_rm.__name__
            '_clear_pending_secrets_rm'
        """
        self._conn.execute(
            "DELETE FROM dispatcher_state WHERE kind = 'secrets_rm' AND chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        self._conn.commit()

    def _find_pending_secrets_export(self, *, chat_id: int, user_id: int) -> dict[str, Any] | None:
        """Return the newest pending secrets-export payload for one chat and user.

        Args:
            chat_id (int): Telegram chat id.
            user_id (int): Telegram user id that started the confirm flow.

        Returns:
            dict[str, Any] | None: Parsed payload or ``None``.

        Examples:
            >>> MenuActionRouter._find_pending_secrets_export.__name__
            '_find_pending_secrets_export'
        """
        row = self._conn.execute(
            """
            SELECT payload_json FROM dispatcher_state
            WHERE kind = 'secrets_export' AND chat_id = ? AND user_id = ?
            ORDER BY rowid DESC LIMIT 1
            """,
            (chat_id, user_id),
        ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row[0]))
        except (TypeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _clear_pending_secrets_export(self, *, chat_id: int, user_id: int) -> None:
        """Drop pending secrets-export dispatcher rows for one chat and user.

        Args:
            chat_id (int): Telegram chat id.
            user_id (int): Telegram user id that started the confirm flow.

        Examples:
            >>> MenuActionRouter._clear_pending_secrets_export.__name__
            '_clear_pending_secrets_export'
        """
        self._conn.execute(
            "DELETE FROM dispatcher_state WHERE kind = 'secrets_export' AND chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        self._conn.commit()

    async def _handle_pairing_action(
        self,
        msg: IncomingMessage,
        callback_data: str,
        target: str,
    ) -> str | None:
        """Dispatch Access > pairing ``act:pairing:*`` rows (W7d).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target after ``act:``.

        Returns:
            str | None: Toast when the action could not proceed.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_pairing_action)
            True
        """
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        if target == "pairing:pending":
            return await self._handle_pairing_pending(msg, callback_data)
        toast = self.reject_unknown_callback_suffix("act:pairing:", target.removeprefix("pairing:"))
        answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
        return None if answered else toast

    async def _handle_pairing_pending(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """List pending pairing requests without revealing plaintext codes.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_pairing_pending)
            True
        """
        _ = callback_data
        import json

        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.gateway.onboarding.pairing import PairingStore

        rows = PairingStore(self._content_root).list_pending()
        body = json.dumps({"pending": rows, "count": len(rows)}, indent=2)
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Pending pairing sent")
        return None

    async def _handle_providers_action(
        self,
        msg: IncomingMessage,
        callback_data: str,
        target: str,
    ) -> str | None:
        """Dispatch Access > Provider logins ``act:providers:*`` rows (W7d).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target after ``act:``.

        Returns:
            str | None: Toast when the action could not proceed.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_providers_action)
            True
        """
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        if target == "providers:oauth:status":
            return await self._handle_providers_oauth_status(msg, callback_data)
        toast = self.reject_unknown_callback_suffix(
            "act:providers:", target.removeprefix("providers:")
        )
        answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
        return None if answered else toast

    async def _handle_providers_oauth_status(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Post OAuth secret aliases and OpenAI credential summary.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Error toast when status could not be loaded.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_providers_oauth_status)
            True
        """
        _ = callback_data
        from sevn.cli.commands.providers_cmd import _format_oauth_status
        from sevn.cli.workspace import BoundWorkspace
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.security.oauth.credential import oauth_openai_secret_alias
        from sevn.security.oauth.login_flow import load_codex_oauth_credential_from_workspace
        from sevn.workspace.layout import WorkspaceLayout

        try:
            rows = await self._load_secrets_entries()
        except RuntimeError as exc:
            return str(exc)
        aliases = [str(r.get("alias", "")) for r in rows if r.get("alias")]
        openai_cred: dict[str, Any] | None = None
        if oauth_openai_secret_alias() in aliases:
            bw = BoundWorkspace(
                sevn_json_path=self._sevn_json,
                config=self._workspace,
                layout=WorkspaceLayout.from_config(self._sevn_json, self._workspace),
                raw=load_raw_sevn_json(self._sevn_json) or {},
            )
            openai_cred = load_codex_oauth_credential_from_workspace(bw)
        body = _format_oauth_status([], aliases, openai_oauth=openai_cred)
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "OAuth status sent")
        return None

    async def _handle_doctor_run(self, msg: IncomingMessage, callback_data: str) -> str | None:
        """Run ``sevn doctor`` probes and post the report (D19 pagination).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Error toast when doctor could not run.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_doctor_run)
            True
        """
        _ = callback_data
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        from sevn.cli.doctor.checks import CheckResult
        from sevn.cli.doctor.probes import DoctorRunOptions, run_doctor_probes
        from sevn.cli.workspace import BoundWorkspace
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.workspace.layout import WorkspaceLayout

        bw = BoundWorkspace(
            sevn_json_path=self._sevn_json,
            config=self._workspace,
            layout=WorkspaceLayout.from_config(self._sevn_json, self._workspace),
            raw=load_raw_sevn_json(self._sevn_json) or {},
        )
        result = CheckResult()
        run_doctor_probes(bw, result, options=DoctorRunOptions())
        lines: list[str] = []
        for section_name, checks in result.by_section():
            lines.append(section_name)
            for check in checks:
                mark = "ok" if check.ok and check.severity != "warn" else check.severity or "fail"
                detail = check.detail or ""
                if check.hint:
                    detail = f"{detail} — {check.hint}" if detail else check.hint
                lines.append(f"  [{mark}] {check.title}: {detail}")
        ok_count, warn_count, fail_count = result.counts()
        lines.append(f"{ok_count} ok · {warn_count} warn · {fail_count} fail")
        body = "\n".join(lines)
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Doctor sent")
        return None

    async def _handle_usage_show(self, msg: IncomingMessage, callback_data: str) -> str | None:
        """Post budget rollups from traces (``sevn usage show`` parity).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_usage_show)
            True
        """
        _ = callback_data
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        from sevn.cli.commands.usage_cmd import _format_usage
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.storage.paths import traces_sqlite_path
        from sevn.ui.dashboard.query.budget import budget_summary_from_traces
        from sevn.ui.dashboard.query.traces import ensure_trace_connection

        trace_path = traces_sqlite_path(self._content_root / ".sevn")
        if not trace_path.exists():
            body = _format_usage({})
        else:
            conn = ensure_trace_connection(trace_path)
            try:
                body = _format_usage(budget_summary_from_traces(conn))
            finally:
                conn.close()
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Usage sent")
        return None

    async def _handle_turn_bundles_action(
        self,
        msg: IncomingMessage,
        callback_data: str,
        target: str,
    ) -> str | None:
        """Dispatch Health > Turn bundles ``act:turn_bundles:*`` rows (W7d).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target after ``act:``.

        Returns:
            str | None: Toast when export failed.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_turn_bundles_action)
            True
        """
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        if target == "turn_bundles:export":
            return await self._handle_turn_bundles_export(msg, callback_data)
        toast = self.reject_unknown_callback_suffix(
            "act:turn_bundles:",
            target.removeprefix("turn_bundles:"),
        )
        answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
        return None if answered else toast

    async def _handle_turn_bundles_export(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Backfill or refresh turn JSONL bundles under ``.sevn/turns/``.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_turn_bundles_export)
            True
        """
        _ = callback_data
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.gateway.turn.turn_bundle import export_turn_bundles
        from sevn.storage.paths import traces_sqlite_path
        from sevn.ui.dashboard.query.traces import ensure_trace_connection

        trace_conn = None
        trace_path = traces_sqlite_path(self._content_root / ".sevn")
        if trace_path.exists():
            trace_conn = ensure_trace_connection(trace_path)
        try:
            written = export_turn_bundles(
                self._conn,
                trace_conn,
                content_root=self._content_root,
            )
        finally:
            if trace_conn is not None:
                trace_conn.close()
        body = f"Exported {len(written)} turn bundle(s)."
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Turn bundles exported")
        return None

    async def _handle_tracing_config(self, msg: IncomingMessage, callback_data: str) -> str | None:
        """Post Logfire / trace export configuration (``sevn config tracing`` parity).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Always ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_tracing_config)
            True
        """
        _ = callback_data
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        from sevn.agent.tracing.logfire_config import logfire_export_status_from_doc
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram

        doc = load_raw_sevn_json(self._sevn_json) or {}
        status = logfire_export_status_from_doc(doc)
        redaction = effective_trace_redaction_enabled_from_doc(doc)
        body = (
            f"logfire_enabled={status.enabled}\n"
            f"logfire_token_ref={status.token_ref or '(unset)'}\n"
            f"trace_redaction={'on' if redaction else 'off'}"
        )
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Tracing config sent")
        return None

    async def _handle_services_action(
        self,
        msg: IncomingMessage,
        callback_data: str,
        target: str,
    ) -> str | None:
        """Dispatch Deployment > Services ``act:services:*`` rows (W7e).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target (``services:<service>:<action>``).

        Returns:
            str | None: Error text, or ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_services_action)
            True
        """
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        suffix = target.removeprefix("services:")
        parts = suffix.split(":", 1)
        if len(parts) != 2:
            toast = self.reject_unknown_callback_suffix("act:services:", suffix)
            answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
            return None if answered else toast
        service_raw, action = parts
        if service_raw not in {"gateway", "proxy"} or action not in {
            "start",
            "stop",
            "status",
            "logs",
        }:
            toast = self.reject_unknown_callback_suffix("act:services:", suffix)
            answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
            return None if answered else toast
        service = cast("Literal['gateway', 'proxy']", service_raw)
        if action == "logs":
            return await self._handle_logs_tail(msg, f"tail:{service}:0")
        home = sevn_home_dir()
        try:
            sm_action = cast("Literal['start', 'stop', 'status']", action)
            if service == "gateway" and sm_action in {"start", "stop"}:
                gw_action = cast("Literal['start', 'stop']", sm_action)
                lines = await asyncio.to_thread(
                    _mutate_gateway_with_proxy,
                    home=Path.home(),
                    action=gw_action,
                )
                line = "\n".join(lines)
            else:
                line = await asyncio.to_thread(
                    control_unit, home=home, service=service, action=sm_action
                )
        except (OperatorLockHeld, ServiceManagerError) as exc:
            return str(exc)
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram

        await self._send_logs_chunks(msg, format_for_telegram(line, redaction=None))
        await self._answer_chat_action(msg, f"{service} {action} sent")
        return None

    async def _handle_config_action(
        self, msg: IncomingMessage, callback_data: str, target: str
    ) -> str | None:
        """Dispatch Deployment > Config file ``act:config:*`` rows (W7e).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target (``config:<suffix>``).

        Returns:
            str | None: Error text, or ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_config_action)
            True
        """
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        suffix = target.removeprefix("config:")
        if suffix == "show":
            import json as json_mod

            from sevn.gateway.diagnostics.diagnostics import format_for_telegram
            from sevn.ui.dashboard.api.ops import _redact_config_document

            doc = load_raw_sevn_json(self._sevn_json) or {}
            redacted = _redact_config_document(doc)
            body = json_mod.dumps(redacted, indent=2, sort_keys=True)
            await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
            await self._answer_chat_action(msg, "sevn.json sent (redacted)")
            return None
        if suffix == "validate":
            from sevn.config.workspace_config import parse_workspace_config
            from sevn.gateway.diagnostics.diagnostics import format_for_telegram
            from sevn.onboarding.live_validate import emit_openai_oauth_warnings
            from sevn.onboarding.validate import (
                emit_unused_provider_warnings,
                validate_workspace_document,
            )
            from sevn.security.secrets.factory import secrets_chain_from_workspace

            doc = load_raw_sevn_json(self._sevn_json) or {}
            try:
                validate_workspace_document(doc)
            except ValueError as exc:
                return str(exc)
            warnings: list[str] = []

            def _collect(msg_text: str) -> None:
                warnings.append(msg_text)

            emit_unused_provider_warnings(parse_workspace_config(doc), echo=_collect)
            chain = secrets_chain_from_workspace(
                self._content_root, self._workspace.secrets_backend
            )
            emit_openai_oauth_warnings(doc, echo=_collect, secrets_chain=chain)
            body = "sevn.json: valid" + (("\n\n" + "\n".join(warnings)) if warnings else "")
            await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
            await self._answer_chat_action(msg, "Validate sent")
            return None
        if suffix == "sections":
            from sevn.cli.config_paths import iter_config_sections
            from sevn.gateway.diagnostics.diagnostics import format_for_telegram

            lines = ["slug\tlabel", *(f"{s.slug}\t{s.label}" for s in iter_config_sections())]
            await self._send_logs_chunks(msg, format_for_telegram("\n".join(lines), redaction=None))
            await self._answer_chat_action(msg, "Sections sent")
            return None
        toast = self.reject_unknown_callback_suffix("act:config:", suffix)
        answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
        return None if answered else toast

    async def _handle_guides_action(
        self, msg: IncomingMessage, callback_data: str, target: str
    ) -> str | None:
        """Dispatch Help > Guides ``act:guides:*`` rows (W7e).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target (``guides:<suffix>``).

        Returns:
            str | None: Toast text, or ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_guides_action)
            True
        """
        suffix = target.removeprefix("guides:")
        if suffix != "list":
            toast = self.reject_unknown_callback_suffix("act:guides:", suffix)
            answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
            return None if answered else toast
        from sevn.cli.help.guide import list_guide_topics
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram

        topics = list_guide_topics()
        body = " · ".join(topics) if topics else "No bundled guides found."
        await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
        await self._answer_chat_action(msg, "Guides list sent")
        return None

    async def _handle_help_action(
        self, msg: IncomingMessage, callback_data: str, target: str
    ) -> str | None:
        """Dispatch Help ``act:help:*`` rows (W7e).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target (``help:<suffix>``).

        Returns:
            str | None: Toast text, or ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_help_action)
            True
        """
        suffix = target.removeprefix("help:")
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram

        if suffix == "slash":
            body = (
                "Slash shortcuts:\n"
                "/new /stop /status /model /voice /logs /traces /config /menu /help\n"
                "Owner: /platform /improve /file_issue /agents"
            )
            await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
            await self._answer_chat_action(msg, "Slash commands sent")
            return None
        if suffix == "version":
            from importlib.metadata import PackageNotFoundError
            from importlib.metadata import version as pkg_version

            try:
                cli_version = pkg_version("sevn")
            except PackageNotFoundError:
                cli_version = "0.0.0"
            await self._send_logs_chunks(
                msg, format_for_telegram(f"sevn CLI version: {cli_version}", redaction=None)
            )
            await self._answer_chat_action(msg, "Version sent")
            return None
        if suffix == "about":
            await self._send_logs_chunks(
                msg,
                format_for_telegram("https://about.sevn.bot", redaction=None),
            )
            await self._answer_chat_action(msg, "About link sent")
            return None
        toast = self.reject_unknown_callback_suffix("act:help:", suffix)
        answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
        return None if answered else toast

    async def _handle_update_action(
        self, msg: IncomingMessage, callback_data: str, target: str
    ) -> str | None:
        """Dispatch Deployment > Update ``act:update:*`` rows (W7e).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target (``update:<suffix>``).

        Returns:
            str | None: Error or toast text, or ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_update_action)
            True
        """
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        suffix = target.removeprefix("update:")
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram

        if suffix == "cli":
            from importlib.metadata import PackageNotFoundError
            from importlib.metadata import version as pkg_version

            try:
                current = pkg_version("sevn")
            except PackageNotFoundError:
                current = "0.0.0"
            body = f"installed: {current}\nuv tool upgrade sevn  # or: pip install -U sevn"
            await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
            await self._answer_chat_action(msg, "Update hint sent")
            return None
        if suffix == "schema":
            import json as json_mod

            from sevn.onboarding.migrate import describe_schema_upgrade
            from sevn.workspace.layout import WorkspaceLayout

            layout = WorkspaceLayout(self._sevn_json, self._content_root)
            plan = describe_schema_upgrade(layout.content_root)
            body = json_mod.dumps(plan, indent=2, sort_keys=True)
            body += "\nRun `sevn migrate` when an in-place schema upgrade is required."
            await self._send_logs_chunks(msg, format_for_telegram(body, redaction=None))
            await self._answer_chat_action(msg, "Schema posture sent")
            return None
        toast = self.reject_unknown_callback_suffix("act:update:", suffix)
        answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
        return None if answered else toast

    async def _handle_deploy_action(
        self, msg: IncomingMessage, callback_data: str, target: str
    ) -> str | None:
        """Dispatch Deployment > Deploy ``act:deploy:*`` confirm rows (W7e).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target (``deploy:<suffix>``).

        Returns:
            str | None: Error or toast text, or ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_deploy_action)
            True
        """
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        suffix = target.removeprefix("deploy:")
        if suffix == "remote:cancel":
            return await self._handle_deploy_remote_cancel(msg, callback_data)
        if suffix == "remote:confirm":
            return await self._handle_deploy_remote_confirm(msg, callback_data)
        toast = self.reject_unknown_callback_suffix("act:deploy:", suffix)
        answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
        return None if answered else toast

    async def _edit_deploy_remote_confirm(
        self, msg: IncomingMessage, *, host: str, bundle: str
    ) -> bool:
        """Show two-step remote deploy confirm keyboard (W7e).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            host (str): Inventory host id.
            bundle (str): Export bundle path.

        Returns:
            bool: ``True`` when the confirm keyboard was edited in place.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._edit_deploy_remote_confirm)
            True
        """
        from sevn.gateway.menu.confirm_gates import (
            build_confirm_gate_keyboard,
            confirm_gate_message,
        )
        from sevn.gateway.menu.menu import _config_chrome

        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        message_raw = md.get("message_id")
        if not isinstance(chat_raw, int) or not isinstance(message_raw, int):
            return False
        topic_raw = md.get("topic_id")
        insert_dispatcher_state(
            self._conn,
            token=f"ds:{secrets.token_hex(8)}",
            kind="deploy_remote",
            user_id=int(msg.user_id) if str(msg.user_id).isdigit() else 0,
            chat_id=chat_raw,
            topic_id=topic_raw if isinstance(topic_raw, int) else None,
            payload_json=json.dumps(
                {"v": 1, "host": host, "bundle": bundle}, separators=(",", ":")
            ),
            ttl_seconds=600,
        )
        config_menu_nav_push_current(self._router, chat_raw, message_raw)
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return False
        thread_id = _telegram_api_thread_id(md)
        rows = build_confirm_gate_keyboard("deploy:remote")
        rows.extend(_config_chrome())
        edit_text = getattr(adapter, "edit_message_text", None)
        if not callable(edit_text):
            return False
        caption = confirm_gate_message(
            title="Deploy to remote",
            detail=f"Deploy to host `{host}` from bundle `{bundle}`?\nThis mutates the remote install over SSH.",
        )
        body: dict[str, Any] = {
            "chat_id": chat_raw,
            "message_id": message_raw,
            "text": caption,
            "reply_markup": {"inline_keyboard": rows},
        }
        if thread_id is not None:
            body["message_thread_id"] = thread_id
        return bool(await cast("Callable[..., Awaitable[Any]]", edit_text)(**body))

    async def _handle_deploy_remote_confirm(
        self, msg: IncomingMessage, callback_data: str
    ) -> str | None:
        """Run remote deploy after operator confirms (W7e).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Error text, or ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_deploy_remote_confirm)
            True
        """
        _ = callback_data
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        from pathlib import Path

        from sevn.cli.commands.deploy_cmd import _run_deploy_command
        from sevn.deploy.remote import DeployMode
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram

        active = self._find_pending_deploy_remote(
            chat_id=int(chat_raw) if isinstance(chat_raw, int) else 0
        )
        if active is None:
            return "Deploy confirm expired — start again."
        host = str(active.get("host", "")).strip()
        bundle = str(active.get("bundle", "")).strip()
        if not host or not bundle:
            return "Pending deploy payload invalid."
        try:
            await asyncio.to_thread(
                _run_deploy_command,
                host=host,
                inventory=None,
                mode=DeployMode.DEPLOY,
                bundle=Path(bundle),
            )
        except Exception as exc:
            from typer import Exit

            if isinstance(exc, Exit):
                return f"Deploy failed (exit {exc.exit_code})."
            return f"Deploy failed: {exc}"
        self._clear_pending_deploy_remote(chat_id=int(chat_raw) if isinstance(chat_raw, int) else 0)
        await self._send_logs_chunks(
            msg, format_for_telegram(f"Deploy to {host} completed.", redaction=None)
        )
        await self._answer_chat_action(msg, "Deploy sent")
        return None

    async def _handle_deploy_remote_cancel(
        self, msg: IncomingMessage, callback_data: str
    ) -> str | None:
        """Cancel pending remote deploy confirm (W7e).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Toast text, or ``None`` when the config menu was edited in place.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_deploy_remote_cancel)
            True
        """
        _ = callback_data
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        if isinstance(chat_raw, int):
            self._clear_pending_deploy_remote(chat_id=chat_raw)
        answered = await self._refresh_config_menu_after_action(
            msg, callback_data, toast="Deploy cancelled."
        )
        return None if answered else "Deploy cancelled."

    def _find_pending_deploy_remote(self, *, chat_id: int) -> dict[str, Any] | None:
        """Return the newest pending remote-deploy payload for *chat_id*.

        Args:
            chat_id (int): Telegram chat id.

        Returns:
            dict[str, Any] | None: Parsed payload, or ``None``.

        Examples:
            >>> MenuActionRouter._find_pending_deploy_remote.__name__
            '_find_pending_deploy_remote'
        """
        row = self._conn.execute(
            "SELECT payload_json FROM dispatcher_state WHERE kind = 'deploy_remote' AND chat_id = ? ORDER BY rowid DESC LIMIT 1",
            (chat_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row[0]))
        except (TypeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _clear_pending_deploy_remote(self, *, chat_id: int) -> None:
        """Delete pending remote-deploy rows for *chat_id*.

        Args:
            chat_id (int): Telegram chat id.

        Examples:
            >>> MenuActionRouter._clear_pending_deploy_remote.__name__
            '_clear_pending_deploy_remote'
        """
        self._conn.execute(
            "DELETE FROM dispatcher_state WHERE kind = 'deploy_remote' AND chat_id = ?", (chat_id,)
        )
        self._conn.commit()

    async def _answer_chat_action(self, msg: IncomingMessage, text: str) -> None:
        """Acknowledge a read-only menu action with a short callback toast.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            text (str): Toast body.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._answer_chat_action)
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        cq_id = md.get("callback_query_id")
        cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
        adapter = self._router._adapters.get(msg.channel)
        if adapter is not None and cq_str:
            await _answer_callback(adapter, callback_query_id=cq_str, text=text)

    async def _handle_voice_stt_cycle(
        self,
        msg: IncomingMessage,
        callback_data: str,
        target: str,
    ) -> str | None:
        """Cycle the primary ``voice.stt_providers`` entry and persist the new order.

        Rotates through the union of the configured ``voice.stt_providers`` chain and
        :data:`DEFAULT_VOICE_STT_PROVIDERS`, promoting the next tag to index 0 (the
        provider :func:`sevn.voice.factory.build_stt_pipeline` tries first). A specific
        provider tag as the callback suffix (e.g. ``cfg:voice:stt:deepgram``) jumps
        directly to that provider instead of advancing one step.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target (``voice:stt:<suffix>``).

        Returns:
            str | None: Toast text, or ``None`` when the config menu was edited in place.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_voice_stt_cycle)
            True
        """
        suffix = target.removeprefix("voice:stt:").strip()
        configured = self._workspace.voice.stt_providers if self._workspace.voice else None
        chain = list(configured) if configured else list(DEFAULT_VOICE_STT_PROVIDERS)
        for provider in DEFAULT_VOICE_STT_PROVIDERS:
            if provider not in chain:
                chain.append(provider)
        active = chain[0]
        if suffix and suffix != "next" and suffix in chain:
            new_active = suffix
        else:
            idx = chain.index(active)
            new_active = chain[(idx + 1) % len(chain)]
        new_chain = [new_active, *(p for p in chain if p != new_active)]

        def _apply(doc: dict[str, Any]) -> None:
            _set_nested(doc, "voice.stt_providers", new_chain)

        mutate_sevn_json(self._sevn_json, _apply)
        self._reload_workspace()
        toast = f"STT provider: {new_active}"
        answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
        return None if answered else toast

    async def _handle_voice_engine_cycle(
        self,
        msg: IncomingMessage,
        callback_data: str,
        target: str,
    ) -> str | None:
        """Cycle ``voice.local_tts_engine`` between ``kokoro`` and ``supertonic``.

        Writes the next engine into ``sevn.json`` and reloads workspace settings so
        :meth:`ChannelRouter.apply_workspace` rebuilds the TTS pipeline with the new
        engine. A specific engine tag as the callback suffix (e.g.
        ``cfg:voice:engine:supertonic``) jumps directly to that engine.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target (``voice:engine:<suffix>``).

        Returns:
            str | None: Toast text, or ``None`` when the config menu was edited in place.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_voice_engine_cycle)
            True
        """
        suffix = target.removeprefix("voice:engine:").strip().casefold()
        engines = tuple(sorted(KNOWN_LOCAL_TTS_ENGINES))
        configured = (
            str(self._workspace.voice.local_tts_engine).strip().casefold()
            if self._workspace.voice and self._workspace.voice.local_tts_engine
            else DEFAULT_VOICE_LOCAL_TTS_ENGINE
        )
        active = configured if configured in engines else DEFAULT_VOICE_LOCAL_TTS_ENGINE
        if suffix and suffix != "next" and suffix in engines:
            new_active = suffix
        else:
            idx = engines.index(active)
            new_active = engines[(idx + 1) % len(engines)]

        def _apply(doc: dict[str, Any]) -> None:
            _set_nested(doc, "voice.local_tts_engine", new_active)

        mutate_sevn_json(self._sevn_json, _apply)
        self._reload_workspace()
        runtime_engine = _tts_pipeline_engine(getattr(self._router, "_tts", None))
        if runtime_engine != new_active:
            logger.warning(
                "voice TTS engine cycle wrote {!r} but pipeline .engine is {!r}",
                new_active,
                runtime_engine,
            )
            toast = f"TTS engine: {new_active} (pipeline still {runtime_engine or 'unset'})"
        else:
            toast = f"TTS engine: {new_active}"
        answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
        return None if answered else toast

    async def _handle_models_pick(
        self,
        msg: IncomingMessage,
        callback_data: str,
        target: str,
    ) -> str | None:
        """Persist a catalog model selection for one picker slot.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target (``models:pick:<slot>:<idx>``).

        Returns:
            str | None: Toast text when pick could not complete.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_models_pick)
            True
        """
        rest = target.removeprefix("models:pick:")
        if ":" not in rest:
            return "Unknown model slot."
        slot_key, idx_raw = rest.rsplit(":", 1)
        if not idx_raw.isdigit():
            return "Invalid model selection."
        catalog = list_catalog_model_ids(self._workspace)
        idx = int(idx_raw)
        if idx < 0 or idx >= len(catalog):
            return "Model not found."
        model_id = catalog[idx]

        def _apply(doc: dict[str, Any]) -> None:
            apply_model_to_picker_slot(doc, slot_key, model_id)

        mutate_sevn_json(self._sevn_json, _apply)
        self._reload_workspace()
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        message_raw = md.get("message_id")
        if isinstance(chat_raw, int) and isinstance(message_raw, int):
            get_config_menu_nav(self._router, chat_raw, message_raw).current = ConfigMenuNavFrame(
                section="agent",
            )
        toast = f"Model set to {model_id}."
        answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
        return None if answered else toast

    async def _handle_models_swap(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Swap tier-B model with ``providers.last_used_model`` (``/model toggle`` parity).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Toast text when swap could not complete.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_models_swap)
            True
        """
        current = resolve_model_slot(self._workspace, ModelSlot.tier_b)
        doc = load_raw_sevn_json(self._sevn_json)
        last = _get_nested(doc, "providers.last_used_model")
        target = str(last) if isinstance(last, str) and last.strip() else current

        def _swap(d: dict[str, Any]) -> None:
            _set_nested(d, "providers.last_used_model", current)
            _set_nested(d, "providers.tier_default.B", target)

        mutate_sevn_json(self._sevn_json, _swap)
        self._reload_workspace()
        toast = f"Model switched to {target}."
        answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
        return None if answered else toast

    async def _handle_subagents_kill(
        self,
        msg: IncomingMessage,
        callback_data: str,
        target: str,
    ) -> str | None:
        """Kill one tracked sub-agent run (owner-only, D13).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed target ``subagents:kill:<id>``.

        Returns:
            str | None: Toast when non-owner; ``None`` when handled via menu refresh.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_subagents_kill)
            True
        """
        _ = callback_data
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        run_id = target.removeprefix("subagents:kill:").strip()
        supervisor = getattr(self._router, "_subagent_supervisor", None)
        if supervisor is None:
            return "Sub-agent supervisor unavailable."
        run = await supervisor.registry.get(run_id)
        if run is None:
            return f"Unknown sub-agent {run_id!r}."
        killed = await supervisor.kill(run_id, cascade=True)
        toast = f"Killed {run_id}." if killed else f"Could not kill {run_id}."
        return await self._after_subagent_kill(msg, callback_data, toast=toast)

    async def _handle_subagents_kill_all(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Kill all active level-1 sub-agent runs (owner-only, D13).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Toast when non-owner; ``None`` when handled via menu refresh.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_subagents_kill_all)
            True
        """
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        supervisor = getattr(self._router, "_subagent_supervisor", None)
        if supervisor is None:
            return "Sub-agent supervisor unavailable."
        count = await supervisor.kill_all(role=None)
        toast = f"Killed {count} sub-agent run(s)."
        return await self._after_subagent_kill(msg, callback_data, toast=toast)

    def _tunnel_persistence_hint(self) -> str:
        """Return a caveat when the gateway daemon is absent (no host-restart survival).

        Autostart re-launches the tunnel on gateway boot; that only survives a host
        restart when the gateway itself is installed as a launchd/systemd daemon.

        Returns:
            str: Trailing hint text, or ``""`` when the gateway daemon is installed.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(MenuActionRouter._tunnel_persistence_hint)
            True
        """
        try:
            if unit_file_exists(home=Path.home(), service="gateway"):
                return ""
        except (OSError, ServiceManagerError):
            return ""
        return " Install the gateway daemon so it survives host restart."

    async def _handle_tunnel_lifecycle(
        self,
        msg: IncomingMessage,
        callback_data: str,
        target: str,
    ) -> str | None:
        """One-shot ``sevn tunnel status|start|stop`` (W7e).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target (``tunnel:<action>``).

        Returns:
            str | None: Error text, or ``None`` after posting to chat.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_tunnel_lifecycle)
            True
        """
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.infrastructure.tunnel_config import (
            prepare_tunnel_runtime_cfg,
            tunnel_cfg_from_disk,
        )
        from sevn.infrastructure.tunnel_manager import default_manager

        action = target.removeprefix("tunnel:")
        tunnel_cfg = tunnel_cfg_from_disk(self._workspace, sevn_json=self._sevn_json)
        try:
            if action == "status":
                status = default_manager.status(tunnel_cfg)
            elif action == "stop":
                status = await asyncio.to_thread(default_manager.stop, tunnel_cfg, confirm=True)
            else:
                gateway_port = self._workspace.gateway.port if self._workspace.gateway else None
                runtime_cfg = await prepare_tunnel_runtime_cfg(
                    tunnel_cfg,
                    gateway_port=gateway_port,
                    content_root=self._content_root,
                    secrets_backend=self._workspace.secrets_backend,
                )
                status = await asyncio.to_thread(default_manager.start, runtime_cfg, confirm=True)
        except (OSError, RuntimeError, ValueError) as exc:
            return f"Tunnel {action} failed: {exc}"
        state = "running" if status.healthy else "stopped"
        line = f"tunnel {action}: mode={status.mode} {state}"
        if status.pid:
            line += f" pid={status.pid}"
        url = status.mission_control_url or status.public_url
        if url:
            line += f" url={url}"
        if status.error:
            line += f"\n{status.error}"
        await self._send_logs_chunks(msg, format_for_telegram(line, redaction=None))
        answered = await self._refresh_config_menu_after_action(
            msg, callback_data, toast=f"Tunnel {action} sent"
        )
        return None if answered else f"Tunnel {action} sent"

    async def _handle_tunnel_action(
        self,
        msg: IncomingMessage,
        callback_data: str,
        target: str,
    ) -> str | None:
        """Turn the persistent tunnel on/off from the My sevn bot menu (owner-only).

        Turning *on* stands up a public URL to the gateway, so ``tunnel:on`` shows a
        two-step confirm first (like gateway/proxy restart); ``tunnel:on:confirm``
        stamps ``infrastructure.tunnel.autostart`` in ``sevn.json`` and starts the
        configured provider now (the gateway boot hook re-launches it after a host
        restart), and ``tunnel:on:cancel`` returns to the menu. ``tunnel:off`` stays
        one-tap — clearing the flag and stopping the provider only reduces exposure.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target (``tunnel:on``, ``tunnel:on:confirm``,
                ``tunnel:on:cancel`` or ``tunnel:off``).

        Returns:
            str | None: Toast text when refresh did not answer inline; ``None`` otherwise.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_tunnel_action)
            True
        """
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        if target in {"tunnel:status", "tunnel:start", "tunnel:stop"}:
            return await self._handle_tunnel_lifecycle(msg, callback_data, target)
        if target == "tunnel:on:cancel":
            return await self._handle_tunnel_on_cancel(msg, callback_data)
        # Enumerate the valid targets explicitly (like _handle_service_restart_action) so
        # an unexpected ``tunnel:*`` callback is a no-op rather than falling through to the
        # "stop" branch below and silently tearing down a live tunnel.
        if target not in {"tunnel:on", "tunnel:on:confirm", "tunnel:off"}:
            return None
        from sevn.infrastructure.tunnel_config import RUNNABLE_MODES, tunnel_cfg_from_disk
        from sevn.infrastructure.tunnel_manager import default_manager

        tunnel_cfg = tunnel_cfg_from_disk(self._workspace, sevn_json=self._sevn_json)
        mode = str(tunnel_cfg.get("mode") or "none")
        if mode not in RUNNABLE_MODES:
            # Stale-button guard: the toggle only renders for a runnable mode, but a
            # button left in an old message could still be tapped. Toast rather than
            # prompt/spawn for an impossible action.
            toast = "No tunnel configured — run `sevn tunnel setup` first."
            answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
            return None if answered else toast
        if target == "tunnel:on":
            return await self._edit_tunnel_on_confirm(msg, callback_data)
        turn_on = target == "tunnel:on:confirm"
        gateway_port = self._workspace.gateway.port if self._workspace.gateway else None
        if turn_on:
            from sevn.infrastructure.tunnel_autostart import start_configured_tunnel

            # Hold ``lifecycle_lock`` across the spawn *and* the ``autostart`` persist so a
            # concurrent Mission Control stop can't slip in between them and leave the
            # persisted flag out of sync with the live process. Start first; only persist
            # once the provider is confirmed healthy (a failed/unhealthy start persists
            # nothing, so a later gateway boot never retries a broken config).
            started_ok = False
            start_error: str | None = None
            tunnel_url: str | None = None
            async with default_manager.lifecycle_lock:
                try:
                    status = await start_configured_tunnel(
                        tunnel_config=tunnel_cfg,
                        gateway_port=gateway_port,
                        content_root=self._content_root,
                        secrets_backend=self._workspace.secrets_backend,
                        manager=default_manager,
                        lock_held=True,
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    start_error = f"Tunnel start failed: {exc}"
                else:
                    if status.healthy:
                        mutate_sevn_json(
                            self._sevn_json,
                            lambda d: _set_nested(d, "infrastructure.tunnel.autostart", True),
                        )
                        self._reload_workspace()
                        started_ok = True
                        tunnel_url = status.mission_control_url or status.public_url
                    else:
                        start_error = f"Tunnel start failed: {status.error or 'not healthy'}"
            if not started_ok:
                toast = start_error or "Tunnel start failed."
                answered = await self._refresh_config_menu_after_action(
                    msg, callback_data, toast=toast
                )
                return None if answered else toast
            toast = (
                "Tunnel on."
                + (f" {tunnel_url}" if tunnel_url else "")
                + self._tunnel_persistence_hint()
            )
        else:
            # Stop first, then clear ``autostart`` — both under ``lifecycle_lock`` so a
            # concurrent Mission Control start can't race the flag persist, and so a stale
            # "off" is never shown for a still-running provider. A failed stop leaves the
            # flag/button "on" (the provider may still be exposing the gateway).
            stop_error: str | None = None
            async with default_manager.lifecycle_lock:
                try:
                    await asyncio.to_thread(default_manager.stop, tunnel_cfg, confirm=True)
                except (OSError, RuntimeError, ValueError) as exc:
                    stop_error = f"Tunnel stop failed: {exc}"
                else:
                    mutate_sevn_json(
                        self._sevn_json,
                        lambda d: _set_nested(d, "infrastructure.tunnel.autostart", False),
                    )
                    self._reload_workspace()
            if stop_error is not None:
                answered = await self._refresh_config_menu_after_action(
                    msg, callback_data, toast=stop_error
                )
                return None if answered else stop_error
            toast = "Tunnel off."
        answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
        return None if answered else toast

    async def _edit_tunnel_on_confirm(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Edit the ``/config`` message to the "Turn tunnel on" confirmation screen.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Toast when the confirm screen could not be shown; ``None`` on success.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._edit_tunnel_on_confirm)
            True
        """
        _ = callback_data
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        message_raw = md.get("message_id")
        if not isinstance(chat_raw, int) or not isinstance(message_raw, int):
            return "Could not show tunnel confirm."
        config_menu_nav_push_current(self._router, chat_raw, message_raw)
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return "Could not show tunnel confirm."
        thread_id = _telegram_api_thread_id(md)
        rows = build_tunnel_on_confirm_keyboard()
        rows.extend(_config_chrome())
        edit_text = getattr(adapter, "edit_message_text", None)
        if not callable(edit_text):
            return "Could not show tunnel confirm."
        body: dict[str, Any] = {
            "chat_id": chat_raw,
            "message_id": message_raw,
            "text": tunnel_on_confirm_message(),
            "reply_markup": {"inline_keyboard": rows},
        }
        if thread_id is not None:
            body["message_thread_id"] = thread_id
        edited = bool(await cast("Callable[..., Awaitable[Any]]", edit_text)(**body))
        if not edited:
            return "Could not show tunnel confirm."
        cq_id = md.get("callback_query_id")
        cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
        if cq_str:
            await _answer_callback(adapter, callback_query_id=cq_str, text="Turn tunnel on?")
        return None

    async def _handle_tunnel_on_cancel(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Return the My sevn bot section after cancelling the tunnel-on prompt.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Toast when refresh was skipped; ``None`` when answered inline.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_tunnel_on_cancel)
            True
        """
        _ = callback_data
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        message_raw = md.get("message_id")
        if not isinstance(chat_raw, int) or not isinstance(message_raw, int):
            return "Cancelled."
        frame = config_menu_nav_pop(self._router, chat_raw, message_raw)
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return "Cancelled."
        thread_id = _telegram_api_thread_id(md)
        ctx = ConfigMenuRefreshContext(
            chat_id=chat_raw,
            message_id=message_raw,
            topic_id=thread_id,
            section=frame.section,
            models_picker_slot=frame.models_picker_slot,
            models_picker_page=frame.models_picker_page,
        )
        await refresh_config_menu_message(
            adapter,
            ctx,
            self._workspace,
            content_root=self._content_root,
            user_id=msg.user_id,
            is_owner=self._router._resolve_owner_flag(msg),
            router=self._router,
        )
        cq_id = md.get("callback_query_id")
        cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
        if cq_str:
            await _answer_callback(adapter, callback_query_id=cq_str, text="Cancelled.")
            return None
        return "Cancelled."

    async def _handle_service_restart_action(
        self,
        msg: IncomingMessage,
        callback_data: str,
        target: str,
        *,
        session_id: str,
    ) -> str | None:
        """Dispatch owner-only gateway/proxy restart prompts and confirmations.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target after ``act:`` prefix.
            session_id (str): Active gateway session id (for restart ack snapshot).

        Returns:
            str | None: Toast text when the action could not proceed; ``None`` when handled.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_service_restart_action)
            True
        """
        if target == "gateway:restart":
            return await self._handle_service_restart_prompt(msg, callback_data, service="gateway")
        if target == "gateway:restart:confirm":
            return await self._handle_service_restart_confirm(
                msg,
                callback_data,
                service="gateway",
                session_id=session_id,
            )
        if target == "gateway:restart:cancel":
            return await self._handle_service_restart_cancel(msg, callback_data, service="gateway")
        if target == "proxy:restart":
            return await self._handle_service_restart_prompt(msg, callback_data, service="proxy")
        if target == "proxy:restart:confirm":
            return await self._handle_service_restart_confirm(
                msg,
                callback_data,
                service="proxy",
                session_id=session_id,
            )
        if target == "proxy:restart:cancel":
            return await self._handle_service_restart_cancel(msg, callback_data, service="proxy")
        return None

    async def _handle_service_restart_prompt(
        self,
        msg: IncomingMessage,
        callback_data: str,
        *,
        service: Literal["gateway", "proxy"],
    ) -> str | None:
        """Show the two-step restart confirmation keyboard for one service.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            service (Literal["gateway", "proxy"]): Unit to restart.

        Returns:
            str | None: Toast when non-owner or edit failed.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_service_restart_prompt)
            True
        """
        _ = callback_data
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        message_raw = md.get("message_id")
        if isinstance(chat_raw, int) and isinstance(message_raw, int):
            config_menu_nav_push_current(self._router, chat_raw, message_raw)
        shown = await self._edit_service_restart_confirm(msg, service=service)
        if not shown:
            return "Could not show restart confirm."
        return None

    async def _handle_service_restart_confirm(
        self,
        msg: IncomingMessage,
        callback_data: str,
        *,
        service: Literal["gateway", "proxy"],
        session_id: str,
    ) -> str | None:
        """Execute a confirmed gateway or proxy restart via service manager.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            service (Literal["gateway", "proxy"]): Unit to restart.
            session_id (str): Active gateway session for conversation snapshot.

        Returns:
            str | None: Toast when non-owner or restart failed.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_service_restart_confirm)
            True
        """
        _ = callback_data
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        message_raw = md.get("message_id")
        topic_raw = md.get("topic_id")
        cq_id = md.get("callback_query_id")
        cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
        adapter = self._router._adapters.get(msg.channel)
        restart_label = "gateway" if service == "gateway" else "proxy"
        if adapter is not None and cq_str:
            await _answer_callback(
                adapter,
                callback_query_id=cq_str,
                text=f"Restarting {restart_label}…",
            )
        from sevn.gateway.runtime.gateway_restart_ack import (
            conversation_snapshot_for_session,
            has_pending_gateway_restart,
            recent_restart_ack_delivered,
            record_pending_gateway_restart,
        )
        from sevn.workspace.layout import WorkspaceLayout

        dot_sevn = WorkspaceLayout(self._sevn_json, self._content_root).dot_sevn
        if isinstance(chat_raw, int):
            if await asyncio.to_thread(recent_restart_ack_delivered, dot_sevn, chat_raw):
                if adapter is not None and cq_str:
                    await _answer_callback(
                        adapter,
                        callback_query_id=cq_str,
                        text="Gateway already restarted.",
                    )
                return None
            if await asyncio.to_thread(has_pending_gateway_restart, dot_sevn):
                if adapter is not None and cq_str:
                    await _answer_callback(
                        adapter,
                        callback_query_id=cq_str,
                        text="Restart already in progress.",
                    )
                return None
        # §14 one-shot invalidation (`PROBLEMS.md`). Strip the inline keyboard so
        # repeated clicks while the restart is in flight don't queue more restarts.
        # The owner dedup above catches *processed* repeats; this stops new ones
        # from being enqueued at the source.
        if adapter is not None and isinstance(chat_raw, int) and isinstance(message_raw, int):
            edit_markup = getattr(adapter, "edit_reply_markup", None)
            if callable(edit_markup):
                with contextlib.suppress(Exception):
                    await cast("Any", edit_markup)(
                        chat_id=chat_raw,
                        message_id=message_raw,
                        reply_markup={"inline_keyboard": []},
                        message_thread_id=(int(topic_raw) if isinstance(topic_raw, int) else None),
                    )
        if isinstance(chat_raw, int) and isinstance(message_raw, int):
            snapshot = await asyncio.to_thread(
                conversation_snapshot_for_session,
                self._conn,
                session_id,
            )
            topic_id = int(topic_raw) if isinstance(topic_raw, int) else None
            await asyncio.to_thread(
                record_pending_gateway_restart,
                dot_sevn,
                service=service,
                channel=msg.channel,
                user_id=msg.user_id,
                chat_id=chat_raw,
                message_id=message_raw,
                topic_id=topic_id,
                session_id=session_id,
                conversation_snapshot=snapshot,
            )
            if service == "gateway":
                restart_result = await asyncio.to_thread(_run_gateway_restart)
            else:
                restart_result = await asyncio.to_thread(_run_proxy_restart)
            # In production the process is killed before this line is reached, so
            # this second ack only fires for the failure / mock paths — handy for
            # surfacing ``Locked: …`` / ``Restart failed: …`` errors back to the
            # operator and for the unit tests that mock ``_run_*_restart`` to
            # return synchronously.
            if (
                adapter is not None
                and cq_str
                and isinstance(restart_result, str)
                and restart_result.strip()
            ):
                await _answer_callback(
                    adapter,
                    callback_query_id=cq_str,
                    text=restart_result,
                )
        return None

    async def _handle_service_restart_cancel(
        self,
        msg: IncomingMessage,
        callback_data: str,
        *,
        service: Literal["gateway", "proxy"],
    ) -> str | None:
        """Return the Advanced section after cancelling a restart prompt.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            service (Literal["gateway", "proxy"]): Unit whose prompt was cancelled.

        Returns:
            str | None: Toast when refresh was skipped.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_service_restart_cancel)
            True
        """
        _ = service
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        message_raw = md.get("message_id")
        if not isinstance(chat_raw, int) or not isinstance(message_raw, int):
            return "Cancelled."
        frame = config_menu_nav_pop(self._router, chat_raw, message_raw)
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return "Cancelled."
        thread_id = _telegram_api_thread_id(md)
        ctx = ConfigMenuRefreshContext(
            chat_id=chat_raw,
            message_id=message_raw,
            topic_id=thread_id,
            section=frame.section,
            models_picker_slot=frame.models_picker_slot,
            models_picker_page=frame.models_picker_page,
        )
        await refresh_config_menu_message(
            adapter,
            ctx,
            self._workspace,
            content_root=self._content_root,
            user_id=msg.user_id,
            is_owner=self._router._resolve_owner_flag(msg),
            router=self._router,
        )
        cq_id = md.get("callback_query_id")
        cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
        if cq_str:
            await _answer_callback(adapter, callback_query_id=cq_str, text="Cancelled.")
            return None
        return "Cancelled."

    async def _edit_service_restart_confirm(
        self,
        msg: IncomingMessage,
        *,
        service: Literal["gateway", "proxy"],
    ) -> bool:
        """Edit the source ``/config`` message to the restart confirmation screen.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            service (Literal["gateway", "proxy"]): Unit being restarted.

        Returns:
            bool: ``True`` when the edit and callback answer succeed.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._edit_service_restart_confirm)
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        message_raw = md.get("message_id")
        if not isinstance(chat_raw, int) or not isinstance(message_raw, int):
            return False
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return False
        thread_id = _telegram_api_thread_id(md)
        rows = build_service_restart_confirm_keyboard(service)
        rows.extend(_config_chrome())
        edit_text = getattr(adapter, "edit_message_text", None)
        if not callable(edit_text):
            return False
        body: dict[str, Any] = {
            "chat_id": chat_raw,
            "message_id": message_raw,
            "text": service_restart_confirm_message(service),
            "reply_markup": {"inline_keyboard": rows},
        }
        if thread_id is not None:
            body["message_thread_id"] = thread_id
        edited = bool(await cast("Callable[..., Awaitable[Any]]", edit_text)(**body))
        if not edited:
            return False
        cq_id = md.get("callback_query_id")
        cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
        if cq_str:
            await _answer_callback(
                adapter,
                callback_query_id=cq_str,
                text="Confirm restart?",
            )
        return True

    async def _handle_sevn_bot_action(
        self,
        msg: IncomingMessage,
        callback_data: str,
        target: str,
    ) -> str | None:
        """Dispatch ``act:sevn_bot:*`` upstream checkout actions.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed target after ``act:`` (``sevn_bot:…``).

        Returns:
            str | None: Toast or chat summary; ``None`` when answered via callback.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_sevn_bot_action)
            True
        """
        _ = callback_data
        suffix = target.removeprefix("sevn_bot:")
        if suffix == "sync":
            if not self._router._resolve_owner_flag(msg):
                await self._answer_owner_only(msg)
                return None
            from sevn.cli.repo_sync import RepoSyncError, sync_source_tree
            from sevn.config.sevn_repo import resolve_sevn_checkout_for_workspace

            checkout = resolve_sevn_checkout_for_workspace(
                self._workspace,
                content_root=self._content_root,
            )
            if checkout is None:
                return "No sevn.bot checkout — set my_sevn.repo_path in sevn.json."
            try:
                result = await asyncio.to_thread(
                    sync_source_tree,
                    repo_root=checkout,
                    latest=True,
                    dry_run=False,
                    restart_gateway=True,
                )
            except RepoSyncError as exc:
                return str(exc)
            return result.detail
        if suffix in {"bugs", "features"}:
            from sevn.evolution.issues import list_issues
            from sevn.workspace.layout import WorkspaceLayout

            layout = WorkspaceLayout(self._sevn_json, self._content_root)
            kind = "bug" if suffix == "bugs" else "feature"
            rows = [row for row in list_issues(layout, limit=20) if row.kind == kind]
            if not rows:
                return f"No {kind} issues filed yet."
            lines = [f"Recent {kind} issues:"]
            for row in rows[:8]:
                lines.append(f"- `{row.id}` {row.title} ({row.state})")
            return "\n".join(lines)
        return "Unknown sevn.bot action."

    async def _handle_discogs_whoami(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Run ``discogs-identity/whoami`` and report the authed username or auth error.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Toast with the smoke-test result.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_discogs_whoami)
            True
        """
        _ = callback_data
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        from sevn.skills.manager import SkillsManager
        from sevn.workspace.layout import WorkspaceLayout

        layout = WorkspaceLayout(self._sevn_json, self._content_root)
        manager = SkillsManager.shared(
            layout,
            config=self._workspace,
            layout=layout,
        )
        result = await manager.run_script("discogs-identity", "whoami.py")
        if result.get("ok"):
            data = result.get("data")
            username = data.get("username") if isinstance(data, dict) else None
            toast = f"Discogs connected as {username}" if username else "Discogs whoami succeeded."
        else:
            err = result.get("error")
            if isinstance(err, dict):
                toast = str(err.get("message") or err.get("code") or "Discogs auth failed.")
            else:
                toast = str(result.get("code") or "Discogs auth failed.")
        answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
        return None if answered else toast

    async def _handle_logs_action(
        self,
        msg: IncomingMessage,
        callback_data: str,
        target: str,
    ) -> str | None:
        """Dispatch a ``cfg:logs:*`` Logs section action (`specs/18-channel-telegram.md` §4.7).

        All actions except the deployment id button are owner-only and gated by
        :meth:`ChannelRouter._resolve_owner_flag`. Tail / traces output is sent
        as new ``<pre>``-wrapped chat messages (via
        :func:`sevn.gateway.diagnostics.format_for_telegram`); the redaction
        toggle writes ``tracing.redaction.enabled`` then calls
        :meth:`ChannelRouter.apply_workspace` via ``_reload_workspace``.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.
            target (str): Parsed action target after the ``cfg:`` prefix
                (always starts with ``logs:``).

        Returns:
            str | None: Toast text when the action could not proceed; ``None``
            when the adapter handled the response directly.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_logs_action)
            True
        """
        suffix = target.removeprefix("logs:")
        if suffix == "deployment_id":
            dep_id = getattr(self._router, "_deployment_id", None) or "unset"
            await self._send_identity_message(
                msg,
                label="Deployment id",
                value=str(dep_id),
            )
            return None
        if suffix == "version_id":
            vid = effective_version_id(
                sevn_json_path=self._sevn_json,
                repo_root=self._content_root,
                router_stash=getattr(self._router, "_version_id", None),
            )
            await self._send_identity_message(
                msg,
                label="Version id",
                value=vid,
            )
            return None
        if not self._router._resolve_owner_flag(msg):
            await self._answer_owner_only(msg)
            return None
        if suffix == "toggle_redaction":
            return await self._handle_logs_toggle_redaction(msg, callback_data)
        if suffix == "toggle_logfire":
            return await self._handle_logs_toggle_logfire(msg, callback_data)
        if suffix.startswith("tail:"):
            return await self._handle_logs_tail(msg, suffix)
        if suffix.startswith("traces:"):
            return await self._handle_logs_traces_recent(msg, suffix)
        return "Unknown logs action."

    async def _handle_logs_toggle_redaction(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Flip ``tracing.redaction.enabled`` then reload the workspace.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Toast when refresh failed.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_logs_toggle_redaction)
            True
        """
        doc = load_raw_sevn_json(self._sevn_json)
        current = effective_trace_redaction_enabled_from_doc(doc)
        new_value = not current

        mutate_sevn_json(
            self._sevn_json,
            lambda d: apply_trace_redaction_to_sevn_doc(d, enabled=new_value),
        )
        self._reload_workspace()
        toast = f"Trace redaction: {'on' if new_value else 'off'}"
        answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
        return None if answered else toast

    async def _handle_logs_toggle_logfire(
        self,
        msg: IncomingMessage,
        callback_data: str,
    ) -> str | None:
        """Flip Logfire export by adding/removing the ``logfire`` trace sink.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            callback_data (str): Raw ``callback_data`` string.

        Returns:
            str | None: Toast when refresh failed.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_logs_toggle_logfire)
            True
        """
        doc = load_raw_sevn_json(self._sevn_json)
        current = logfire_export_status_from_doc(doc).enabled
        new_value = not current

        mutate_sevn_json(
            self._sevn_json,
            lambda d: apply_logfire_export_to_sevn_doc(d, enabled=new_value, keep_local_sinks=True),
        )
        self._reload_workspace()
        toast = f"Logfire export: {'on' if new_value else 'off'} — restart gateway"
        answered = await self._refresh_config_menu_after_action(msg, callback_data, toast=toast)
        return None if answered else toast

    async def _handle_logs_tail(self, msg: IncomingMessage, suffix: str) -> str | None:
        """Tail one service log and send ``<pre>`` chunks to the chat.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            suffix (str): Action suffix after ``logs:`` (``tail:<service>:<page>``).

        Returns:
            str | None: Toast text when the tail could not be produced.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_logs_tail)
            True
        """
        from sevn.agent.tracing.sink_factory import trace_redaction_policy_for
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram, tail_service_log
        from sevn.workspace.layout import WorkspaceLayout

        parts = suffix.split(":")
        if len(parts) != 3:
            return "Bad tail callback."
        _, service, page_raw = parts
        if service not in ("gateway", "proxy") or not page_raw.isdigit():
            return "Bad tail callback."
        page = int(page_raw)
        lines = 50
        layout = WorkspaceLayout(self._sevn_json, self._content_root)
        try:
            tail = tail_service_log(service, lines, layout)
        except ValueError as exc:
            return f"Error: {exc}"
        policy = trace_redaction_policy_for(self._workspace)
        if not tail:
            chunks = [f"<pre>(no entries for {service})</pre>"]
        else:
            chunks = format_for_telegram(tail, redaction=policy)
        await self._send_logs_chunks(msg, chunks)
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        cq_id = md.get("callback_query_id")
        cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
        adapter = self._router._adapters.get(msg.channel)
        if adapter is not None and cq_str:
            await _answer_callback(
                adapter,
                callback_query_id=cq_str,
                text=f"Tail {service} (page {page})",
            )
        return None

    async def _handle_logs_traces_recent(
        self,
        msg: IncomingMessage,
        suffix: str,
    ) -> str | None:
        """Send the most-recent trace rows for the active page.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            suffix (str): Action suffix after ``logs:`` (``traces:<page>``).

        Returns:
            str | None: Toast text when traces could not be loaded.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._handle_logs_traces_recent)
            True
        """
        from sevn.agent.tracing.sink_factory import trace_redaction_policy_for
        from sevn.gateway.diagnostics.diagnostics import format_traces_for_telegram, recent_traces
        from sevn.workspace.layout import WorkspaceLayout

        parts = suffix.split(":")
        if len(parts) != 2 or not parts[1].isdigit():
            return "Bad traces callback."
        page = int(parts[1])
        layout = WorkspaceLayout(self._sevn_json, self._content_root)
        policy = trace_redaction_policy_for(self._workspace)
        spans = recent_traces(layout, limit=20, policy=policy)
        if not spans:
            chunks = ["<pre>(no traces yet)</pre>"]
        else:
            chunks = format_traces_for_telegram(spans, redaction=policy)
        await self._send_logs_chunks(msg, chunks)
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        cq_id = md.get("callback_query_id")
        cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
        adapter = self._router._adapters.get(msg.channel)
        if adapter is not None and cq_str:
            await _answer_callback(
                adapter,
                callback_query_id=cq_str,
                text=f"Recent traces (page {page})",
            )
        return None

    async def _send_logs_chunks(self, msg: IncomingMessage, chunks: list[str]) -> None:
        """Send pre-formatted ``<pre>`` chunks as new chat messages.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            chunks (list[str]): Output of ``format_for_telegram`` /
                ``format_traces_for_telegram``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._send_logs_chunks)
            True
        """
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return
        from sevn.gateway.channel_router import OutgoingMessage, _telegram_reply_metadata

        for chunk in chunks:
            metadata = dict(_telegram_reply_metadata(msg))
            metadata.setdefault("parse_mode", "HTML")
            await adapter.send(
                OutgoingMessage(
                    channel=msg.channel,
                    user_id=msg.user_id,
                    text=chunk,
                    metadata=metadata,
                ),
            )

    async def _answer_owner_only(self, msg: IncomingMessage) -> None:
        """Answer a callback query with the standard owner-only toast.

        Args:
            msg (IncomingMessage): Inbound callback envelope.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuActionRouter._answer_owner_only)
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        cq_id = md.get("callback_query_id")
        cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
        if not cq_str:
            return
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return
        await _answer_callback(adapter, callback_query_id=cq_str, text="Owner only.")


def _run_gateway_restart() -> str:
    """Restart gateway (and paired proxy when installed) like ``sevn gateway restart``.

    Returns:
        str: Human-readable status for Telegram toast.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_run_gateway_restart)
        True
    """
    home = Path.home()
    try:
        with operator_lock(sevn_home_dir()):
            propagate_daemon_secret_env()
            propagate_daemon_proxy_env()
            lines = _mutate_gateway_with_proxy(home=home, action="restart")
    except OperatorLockHeld as exc:
        return f"Locked: {exc}"
    except ServiceManagerError as exc:
        return f"Restart failed: {exc}"
    return "; ".join(lines) if lines else "Gateway restart initiated."


def _run_proxy_restart() -> str:
    """Restart the proxy user unit when installed.

    Returns:
        str: Human-readable status for Telegram toast.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_run_proxy_restart)
        True
    """
    home = Path.home()
    if not unit_file_exists(home=home, service="proxy"):
        return "Proxy unit not installed."
    try:
        with operator_lock(sevn_home_dir()):
            propagate_daemon_secret_env()
            propagate_daemon_proxy_env()
            line = control_unit(home=home, service="proxy", action="restart")
    except OperatorLockHeld as exc:
        return f"Locked: {exc}"
    except ServiceManagerError as exc:
        return f"Restart failed: {exc}"
    return line or "Proxy restart initiated."


async def _pin_chat_message(
    adapter: Any,
    *,
    chat_id: int,
    message_id: int,
    topic_id: int | None,
) -> bool:
    """Pin one Telegram message via adapter helper or Bot API fallback.

    Args:
        adapter (object): Channel adapter.
        chat_id (int): Destination chat id.
        message_id (int): Message id to pin.
        topic_id (int | None): Optional forum topic id.

    Returns:
        bool: ``True`` when pin succeeds.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_pin_chat_message)
        True
    """
    pin_fn = getattr(adapter, "pin_chat_message", None)
    if callable(pin_fn):
        return bool(
            await cast("Callable[..., Awaitable[Any]]", pin_fn)(
                chat_id=chat_id,
                message_id=message_id,
                message_thread_id=topic_id,
            ),
        )
    api = getattr(adapter, "_api", None)
    if not callable(api):
        return False
    body: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "disable_notification": True,
    }
    if topic_id is not None:
        body["message_thread_id"] = topic_id
    res = await cast("Callable[..., Awaitable[Any]]", api)("pinChatMessage", body)
    return bool(res.get("ok"))


async def _unpin_chat_message(
    adapter: Any,
    *,
    chat_id: int,
    message_id: int,
    topic_id: int | None,
) -> bool:
    """Unpin one Telegram message via adapter helper or Bot API fallback.

    Args:
        adapter (object): Channel adapter.
        chat_id (int): Destination chat id.
        message_id (int): Message id to unpin.
        topic_id (int | None): Optional forum topic id.

    Returns:
        bool: ``True`` when unpin succeeds.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_unpin_chat_message)
        True
    """
    unpin_fn = getattr(adapter, "unpin_chat_message", None)
    if callable(unpin_fn):
        return bool(
            await cast("Callable[..., Awaitable[Any]]", unpin_fn)(
                chat_id=chat_id,
                message_id=message_id,
                message_thread_id=topic_id,
            ),
        )
    api = getattr(adapter, "_api", None)
    if not callable(api):
        return False
    body: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
    }
    if topic_id is not None:
        body["message_thread_id"] = topic_id
    res = await cast("Callable[..., Awaitable[Any]]", api)("unpinChatMessage", body)
    return bool(res.get("ok"))


async def _answer_callback(adapter: Any, *, callback_query_id: str, text: str | None) -> bool:
    """Best-effort Telegram ``answerCallbackQuery`` helper.

    Prefers production :meth:`TelegramAdapter.answer_callback`, then legacy
    ``answer_callback_query``, then raw ``_api("answerCallbackQuery", …)``.

    Args:
        adapter (object): Channel adapter (``TelegramAdapter`` in production).
        callback_query_id (str): Telegram callback query id.
        text (str | None): Optional toast body.

    Returns:
        bool: ``True`` when an answer path reports success.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_answer_callback)
        True
    """
    cq = callback_query_id.strip()
    if not cq:
        return False
    answer_fn = getattr(adapter, "answer_callback", None)
    if callable(answer_fn):
        try:
            result = await cast("Callable[..., Awaitable[Any]]", answer_fn)(
                cq,
                text=text or "",
            )
        except Exception:
            return False
        if isinstance(result, dict):
            return bool(result.get("ok"))
        return result is not False
    answer_query = getattr(adapter, "answer_callback_query", None)
    if callable(answer_query):
        try:
            return bool(
                await cast("Callable[..., Awaitable[Any]]", answer_query)(
                    callback_query_id=cq,
                    text=text,
                ),
            )
        except Exception:
            return False
    api = getattr(adapter, "_api", None)
    if not callable(api):
        return False
    body: dict[str, Any] = {"callback_query_id": cq}
    if text:
        body["text"] = text
        body["show_alert"] = False
    try:
        res = await cast("Callable[..., Awaitable[Any]]", api)("answerCallbackQuery", body)
    except Exception:
        return False
    return bool(res.get("ok")) if isinstance(res, dict) else bool(res)


__all__ = [
    "ActionKind",
    "MenuActionRouter",
    "infer_config_section_from_callback",
    "parse_action_callback",
]
