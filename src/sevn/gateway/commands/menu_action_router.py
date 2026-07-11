"""Polymorphic ``cfg:*`` / shortcut action dispatch (`plan/telegram-commands-design.md` §4.5).

Module: sevn.gateway.commands.menu_action_router
Depends: json, sqlite3, sevn.gateway.dispatcher_state, sevn.gateway.commands.dispatcher_kinds,
    sevn.gateway.commands.shortcuts_store, sevn.gateway.workspace_config_io

Exports:
    MenuActionRouter — sibling to :class:`sevn.gateway.menu.MenuCallbackHandler` nav.
    infer_config_section_from_callback — map action callbacks to ``/config`` sections.
    parse_action_callback — parse action callback namespaces.
Examples:
    >>> parse_action_callback("cfg:voice:mode:off")
    ('toggle', 'voice.tts_mode', 'off')
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import sqlite3
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

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
from sevn.config.defaults import DEFAULT_VOICE_STT_PROVIDERS
from sevn.config.model_resolution import (
    ModelSlot,
    apply_model_to_picker_slot,
    list_catalog_model_ids,
    resolve_model_slot,
)
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.commands.shortcuts_store import (
    delete_shortcut,
    find_shortcut,
    republish_set_my_commands,
)
from sevn.gateway.dispatcher_state import dispatcher_state_ttl_for_kind, insert_dispatcher_state
from sevn.gateway.menu import (
    ConfigMenuNavFrame,
    ConfigMenuRefreshContext,
    ConfigSection,
    _config_chrome,
    _telegram_api_thread_id,
    _voice_tts_mode,
    build_service_restart_confirm_keyboard,
    config_menu_nav_pop,
    config_menu_nav_push_current,
    get_config_menu_nav,
    parse_config_callback_data,
    parse_models_callback_data,
    refresh_config_menu_message,
    service_restart_confirm_message,
)
from sevn.gateway.workspace_config_io import load_raw_sevn_json, mutate_sevn_json
from sevn.onboarding.web_app import _get_nested, _set_nested

if TYPE_CHECKING:
    from sevn.gateway.channel_router import ChannelRouter, IncomingMessage

ActionKind = Literal["toggle", "prompt", "skill", "action", "scene", "form"]

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
        "integrations:refresh",
        "models:swap",
    }
)

_CALLBACK_SECTION_PREFIXES: tuple[tuple[str, ConfigSection], ...] = (
    ("voice:", "voice"),
    ("security:", "security"),
    ("dashboard:", "dashboard"),
    ("shortcuts:", "shortcuts"),
    ("skills:", "skills"),
    ("integrations:", "integrations"),
    ("logs:", "logs"),
)

_CONFIG_PATH_SECTION: dict[str, ConfigSection] = {
    "voice": "voice",
    "security": "security",
    "webchat": "session",
    "providers": "models",
    "channels": "channels",
    "gateway": "session",
    "executors": "rlm",
    "rlm": "rlm",
    "code_understanding": "code",
    "code_review_graph": "code",
    "self_improve": "self_improve",
    "second_brain": "second_brain",
    "skills": "skills",
    "tools": "tools",
    "integration": "integrations",
    "agent": "agents",
}


def infer_config_section_from_callback(data: str) -> ConfigSection:
    """Map an action callback to the active ``/config`` section for refresh.

    Args:
        data (str): Raw Telegram ``callback_data``.

    Returns:
        ConfigSection: Best-effort section id for caption rebuild.

    Examples:
        >>> infer_config_section_from_callback("cfg:voice:mode:all")
        'voice'
        >>> infer_config_section_from_callback("cfg:toggle:providers.use_main_model_for_all:false")
        'models'
        >>> infer_config_section_from_callback(
        ...     "cfg:toggle:security.scanner.heuristic_only:true",
        ... )
        'security'
        >>> infer_config_section_from_callback(
        ...     "cfg:toggle:executors.tier_cd.lambda_rlm.enabled:true",
        ... )
        'rlm'
        >>> infer_config_section_from_callback(
        ...     "cfg:toggle:code_understanding.mycode.enabled:false",
        ... )
        'code'
        >>> infer_config_section_from_callback("cfg:models:pick:tier_b:0")
        'models'
        >>> infer_config_section_from_callback("act:gateway:restart")
        'my_sevn_bot'
        >>> infer_config_section_from_callback("act:sevn_bot:sync")
        'sevn_bot'
        >>> infer_config_section_from_callback("cfg:logs:toggle_redaction")
        'logs'
    """
    raw = data.strip()
    if raw.startswith("cfg:logs:"):
        return "logs"
    if raw.startswith("cfg:models:"):
        return "models"
    if raw.startswith(("act:gateway:", "act:proxy:")):
        return "my_sevn_bot"
    if raw.startswith("act:sevn_bot:"):
        return "sevn_bot"
    if raw.startswith("cfg:toggle:"):
        path = raw.removeprefix("cfg:toggle:").split(":", 1)[0]
        if path.startswith("agent.codemode"):
            return "codemode"
        if "quick_actions" in path or path.startswith("gateway.queue_mode"):
            return "session"
        if path.startswith("gateway.restart"):
            return "advanced"
        if path.startswith("tracing."):
            return "advanced"
        if "telegram_notify_policy" in path:
            return "notifications"
        if path.startswith("channels.telegram."):
            return "channels"
        top = path.split(".", 1)[0]
        return _CONFIG_PATH_SECTION.get(top, "root")
    if raw.startswith("cfg:"):
        key = raw.removeprefix("cfg:")
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
        kind, target, value = parsed
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
            if target == "dashboard:refresh_pin":
                return await self._handle_dashboard_refresh_pin(msg, raw)
            if target == "dashboard:create_pin":
                return await self._handle_dashboard_create_pin(msg, raw, session_id=session_id)
            if target == "dashboard:unpin":
                return await self._handle_dashboard_unpin(msg, raw)
            if target == "shortcuts:list":
                answered = await self._refresh_config_menu_after_action(
                    msg,
                    raw,
                    toast="Refreshed.",
                )
                return None if answered else "Refreshed."
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
            if target == "models:swap":
                return await self._handle_models_swap(msg, raw)
            if target.startswith("models:pick:"):
                return await self._handle_models_pick(msg, raw, target)
            if target.startswith("logs:"):
                return await self._handle_logs_action(msg, raw, target)
            if target.startswith("sevn_bot:"):
                return await self._handle_sevn_bot_action(msg, raw, target)
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
        )
        cq_id = md.get("callback_query_id")
        cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
        if cq_str:
            await _answer_callback(adapter, callback_query_id=cq_str, text=toast)
            return True
        return False

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
        from sevn.gateway.dashboard_pin import (
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
        from sevn.gateway.dashboard_pin import (
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
        from sevn.gateway.dashboard_pin import unregister_dashboard_pin

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
                section="models",
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
        from sevn.gateway.gateway_restart_ack import (
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
            toast = f"Deployment id: {dep_id}"
            md = msg.metadata if isinstance(msg.metadata, dict) else {}
            cq_id = md.get("callback_query_id")
            cq_str = cq_id.strip() if isinstance(cq_id, str) else ""
            adapter = self._router._adapters.get(msg.channel)
            if adapter is not None and cq_str:
                await _answer_callback(adapter, callback_query_id=cq_str, text=toast)
                return None
            return toast
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
        from sevn.gateway.diagnostics import format_for_telegram, tail_service_log
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
        from sevn.gateway.diagnostics import format_traces_for_telegram, recent_traces
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


async def _answer_callback(adapter: Any, *, callback_query_id: str, text: str | None) -> None:
    """Best-effort Telegram ``answerCallbackQuery`` helper.

    Args:
        adapter (object): Channel adapter exposing ``answer_callback_query``.
        callback_query_id (str): Telegram callback query id.
        text (str | None): Optional toast body.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_answer_callback)
        True
    """
    answer_fn = getattr(adapter, "answer_callback_query", None)
    if callable(answer_fn):
        await cast("Callable[..., Awaitable[Any]]", answer_fn)(
            callback_query_id=callback_query_id,
            text=text,
        )


__all__ = [
    "ActionKind",
    "MenuActionRouter",
    "infer_config_section_from_callback",
    "parse_action_callback",
]
