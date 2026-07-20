"""Option-B core slash command handlers (`plan/telegram-commands-design.md` §3).

Module: sevn.gateway.commands.core_commands
Depends: sevn.config.model_resolution, sevn.gateway.commands.ask_config,
    sevn.gateway.commands.shortcuts_store, sevn.gateway.config_io.workspace_config_io

Exports:
    CoreCommandHandler — ``/start`` … ``/model`` + deep-link handoffs.
    CoreCommandReply — slash reply with optional ``reply_markup`` (D9).
    core_command_outbound — split handler result for Telegram send path.
Examples:
    >>> from sevn.gateway.commands.core_commands import CoreCommandHandler
    >>> CoreCommandHandler.__name__
    'CoreCommandHandler'
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sevn.config.model_resolution import ModelSlot, resolve_model_slot
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.commands.ask_config import format_ask_config_reply, parse_ask_config_query
from sevn.gateway.commands.shortcuts_store import find_shortcut
from sevn.gateway.config_io.workspace_config_io import load_raw_sevn_json, mutate_sevn_json
from sevn.onboarding.web_app import _get_nested, _set_nested
from sevn.voice.factory import resolve_effective_tts_mode

if TYPE_CHECKING:
    from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
    from sevn.gateway.session_manager import SessionManager
    from sevn.workspace.layout import WorkspaceLayout


_START_WELCOME = (
    "Welcome to sevn.\n\n"
    "Core commands: /help /new /status /agents /stop /config /voice /model\n"
    "Open /config for the full menu."
)
_UNKNOWN_COMMAND = "Unknown command — try `/help`."
_STOP_L1_PICKER_COPY = "Select a level-1 agent to stop, or ALL to stop every L1 run."
_STOP_L1_OWNER_ONLY_COPY = "Running level-1 agents. Kill controls are owner-only."

# Kokoro voice codes look like ``bf_emma`` / ``af_heart`` / ``am_michael`` (2-letter
# lang+gender prefix, underscore, name). This never collides with the mode keywords
# (``on``/``off``/``all``/``when_asked``/``reset``/``toggle``) since none match the shape.
_VOICE_CODE_RE = re.compile(r"^[a-z]{2}_[a-z]+$")


@dataclass(frozen=True, slots=True)
class CoreCommandReply:
    """Slash handler result with optional Telegram inline keyboard (D9)."""

    text: str
    reply_markup: dict[str, Any] | None = None


def core_command_outbound(
    reply: str | CoreCommandReply,
) -> tuple[str, dict[str, Any] | None]:
    """Split a core handler result into outbound text and optional ``reply_markup``.

    Args:
        reply (str | CoreCommandReply): Plain text or structured slash reply.

    Returns:
        tuple[str, dict[str, Any] | None]: Send text and optional inline keyboard.

    Examples:
        >>> core_command_outbound("Stopped.")
        ('Stopped.', None)
        >>> core_command_outbound(CoreCommandReply("Pick", reply_markup={"inline_keyboard": []}))
        ('Pick', {'inline_keyboard': []})
    """
    if isinstance(reply, CoreCommandReply):
        return reply.text, reply.reply_markup
    return reply, None


def _voice_mode_label(workspace: WorkspaceConfig) -> str:
    """Return the configured TTS mode label for status copy.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        str: ``off`` when unset, otherwise ``voice.tts_mode``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig, VoiceConfig
        >>> _voice_mode_label(WorkspaceConfig.minimal(voice=VoiceConfig(tts_mode="all")))
        'all'
    """
    voice = workspace.voice
    if voice is None or voice.tts_mode is None:
        return "off"
    return str(voice.tts_mode)


class CoreCommandHandler:
    """Handle Option-B slash commands before the LLM pipeline."""

    def __init__(
        self,
        *,
        workspace: WorkspaceConfig,
        layout: WorkspaceLayout,
        router: ChannelRouter,
        sessions: SessionManager,
    ) -> None:
        """Bind workspace, layout, router, and session manager.

        Args:
            workspace (WorkspaceConfig): Parsed workspace settings.
            layout (WorkspaceLayout): Resolved filesystem layout.
            router (ChannelRouter): Gateway router (adapters + dispatch).
            sessions (SessionManager): Durable session facade.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(CoreCommandHandler.__init__)
            True
        """
        self._workspace = workspace
        self._layout = layout
        self._router = router
        self._sessions = sessions
        self._content_root = layout.content_root.expanduser().resolve()
        self._sevn_json = layout.sevn_json_path

    def matches_slash(self, msg: IncomingMessage) -> bool:
        """Return whether *msg* is a core slash command we handle.

        Args:
            msg (IncomingMessage): Inbound message.

        Returns:
            bool: ``True`` for Option-B commands (not ``/menu`` or ``/steer``).

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> h = CoreCommandHandler.__new__(CoreCommandHandler)
            >>> h.matches_slash(IncomingMessage(channel="telegram", user_id="1", text="/help"))
            True
        """
        text = (msg.text or "").strip()
        if not text.startswith("/"):
            return False
        cmd = text.split(maxsplit=1)[0].lower()
        if cmd in {
            "/start",
            "/help",
            "/new",
            "/status",
            "/agents",
            "/stop",
            "/config",
            "/voice",
            "/model",
            "/ask-config",
        }:
            return True
        name = cmd.lstrip("/")
        return find_shortcut(self._content_root, name) is not None

    async def handle(
        self,
        msg: IncomingMessage,
        *,
        session_id: str,
    ) -> str | CoreCommandReply | None:
        """Run the matching core command and return user-visible text.

        Args:
            msg (IncomingMessage): Inbound slash command.
            session_id (str): Active gateway session id.

        Returns:
            str | CoreCommandReply | None: Reply text (optionally with keyboard), or
                ``None`` when a submenu handler sends separately.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CoreCommandHandler.handle)
            True
        """
        text = (msg.text or "").strip()
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""
        if cmd == "/start":
            return await self._handle_start(msg, args=args)
        if cmd == "/help":
            return self._handle_help()
        if cmd == "/new":
            return await self._handle_new(session_id)
        if cmd == "/status":
            return self._handle_status(session_id)
        if cmd == "/agents":
            return await self._handle_agents()
        if cmd == "/stop":
            return await self._handle_stop(msg, session_id)
        if cmd == "/config":
            return None  # ConfigMenuHandler opens keyboard separately
        if cmd == "/voice":
            return self._handle_voice(args, session_id=session_id)
        if cmd == "/model":
            return self._handle_model(args)
        if cmd == "/ask-config":
            return self._handle_ask_config(args)
        if cmd.startswith("/"):
            name = cmd.lstrip("/")
            row = find_shortcut(self._content_root, name)
            if row is not None:
                stype = str(row.get("type", "prompt"))
                if stype == "prompt":
                    payload = row.get("payload", {})
                    if isinstance(payload, dict):
                        return str(payload.get("template") or payload.get("text") or f"/{name}")
                return f"Running shortcut /{name} ({stype})."
        return _UNKNOWN_COMMAND

    async def _handle_start(self, msg: IncomingMessage, *, args: str) -> str:
        """Handle ``/start`` including deep-link prefixes.

        Args:
            msg (IncomingMessage): Inbound message (may carry ``start_deep_link`` metadata).
            args (str): Unused trailing args after normalisation.

        Returns:
            str: Welcome or deep-link follow-up copy.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CoreCommandHandler._handle_start)
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        deep = md.get("start_deep_link")
        if isinstance(deep, str) and deep.strip():
            low = deep.strip().lower()
            if low.startswith("onb_"):
                return (
                    f"{_START_WELCOME}\n\n"
                    "Onboarding link received. Complete setup in the dashboard or "
                    "reply here to continue bootstrap."
                )
            if low.startswith("dash_"):
                url = _dashboard_url(self._workspace)
                if url:
                    return f"{_START_WELCOME}\n\nDashboard: {url}"
                return f"{_START_WELCOME}\n\nDashboard URL is not configured."
            if low.startswith("short_"):
                name = low.removeprefix("short_").strip()
                if msg.channel == "telegram":
                    chat_type = md.get("chat_type")
                    if chat_type not in {None, "private"} and md.get("chat_id"):
                        return f"{_START_WELCOME}\n\nShortcut deep links work in DM only."
                row = find_shortcut(self._content_root, name)
                if row is None:
                    return f"{_START_WELCOME}\n\nUnknown shortcut {name!r}."
                return f"{_START_WELCOME}\n\nRun /{name} to execute shortcut {name!r}."
        return _START_WELCOME

    def _handle_help(self) -> str:
        """Return the core command list for ``/help``.

        Returns:
            str: Plain-text help body.

        Examples:
            >>> CoreCommandHandler.__new__(CoreCommandHandler)._handle_help().startswith("Core")
            True
        """
        return (
            "Core commands:\n"
            "/start — welcome\n"
            "/help — this message\n"
            "/new — new session\n"
            "/status — session status\n"
            "/agents — running sub-agents\n"
            "/stop — stop L1 agents or cancel in-flight run\n"
            "/config — configuration menu\n"
            "/voice — voice settings\n"
            "/model — model settings\n"
            "/ask-config <topic> — find a setting"
        )

    async def _handle_new(self, session_id: str) -> str:
        """Cancel in-flight work and acknowledge a new session.

        Args:
            session_id (str): Active gateway session id.

        Returns:
            str: Confirmation copy.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CoreCommandHandler._handle_new)
            True
        """
        await self._sessions.cancel_active_dispatch(session_id)
        new_id = await self._sessions.rotate_session(
            session_id,
            content_root=self._content_root,
        )
        short = new_id[:8] if len(new_id) >= 8 else new_id
        return f"Started a new session ({short}…). Previous in-flight work was cancelled."

    async def _handle_stop(
        self,
        msg_or_session_id: IncomingMessage | str,
        session_id: str | None = None,
    ) -> str | CoreCommandReply:
        """Stop L1 sub-agents via inline picker, or cancel session dispatch (D7/D8).

        When at least one level-1 run is active, do not auto-kill: return a picker
        keyboard reusing Config→Sub-agents kill callbacks. When no L1 runs exist,
        preserve the session ``cancel_active_dispatch`` path and ``\"Stopped.\"`` copy.

        Args:
            msg_or_session_id (IncomingMessage | str): Inbound slash/menu message, or
                legacy unit-test call with session id only (no L1 picker path).
            session_id (str | None): Active gateway session id when the first arg is
                an :class:`IncomingMessage`.

        Returns:
            str | CoreCommandReply: Confirmation copy, or picker text with keyboard.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CoreCommandHandler._handle_stop)
            True
        """
        from sevn.gateway.channel_router import IncomingMessage
        from sevn.gateway.menu.menu import (
            build_stop_l1_keyboard,
            subagent_menu_snapshot_from_router,
        )

        if isinstance(msg_or_session_id, str):
            msg = IncomingMessage(channel="telegram", user_id="", text="/stop")
            sid = msg_or_session_id
        else:
            msg = msg_or_session_id
            if session_id is None:
                raise TypeError("session_id required when first argument is IncomingMessage")
            sid = session_id

        level1_count, _level2, rows = await subagent_menu_snapshot_from_router(self._router)
        if level1_count >= 1:
            is_owner = self._router._resolve_owner_flag(msg)
            markup = build_stop_l1_keyboard(rows, is_owner=is_owner)
            copy = _STOP_L1_PICKER_COPY if is_owner else _STOP_L1_OWNER_ONLY_COPY
            return CoreCommandReply(text=copy, reply_markup=markup)
        await self._sessions.cancel_active_dispatch(sid)
        return "Stopped."

    def _handle_status(self, session_id: str) -> str:
        """Return session, model, voice, and deployment-id status for ``/status``.

        Args:
            session_id (str): Active gateway session id.

        Returns:
            str: Multi-line status body. Includes a ``Deployment id:`` row when
                :attr:`ChannelRouter._deployment_id` has been populated by
                ``http_server.create_app`` (`specs/17-gateway.md` §10.14 TE-1).

        Examples:
            >>> import sqlite3
            >>> from sevn.config.workspace_config import WorkspaceConfig
            >>> from sevn.storage.migrate import apply_migrations
            >>> from sevn.gateway.session_manager import SessionManager
            >>> conn = sqlite3.connect(":memory:")
            >>> apply_migrations(conn)
            >>> h = CoreCommandHandler.__new__(CoreCommandHandler)
            >>> h._workspace = WorkspaceConfig.minimal(
            ...     providers={
            ...         "use_main_model_for_all": True,
            ...         "tier_default": {"triager": "minimax/MiniMax-M2.7"},
            ...     },
            ... )
            >>> h._sessions = SessionManager(conn)
            >>> h._router = type("_R", (), {"_deployment_id": "host-20260524000000-abcdef"})()
            >>> body = h._handle_status("s1")
            >>> "Session:" in body
            True
            >>> "Deployment id: host-20260524000000-abcdef" in body
            True
        """
        from sevn.gateway.session_manager import format_lcm_status_lines

        model_id = resolve_model_slot(self._workspace, ModelSlot.tier_b)
        voice_mode = _voice_mode_label(self._workspace)
        chat_override = self._sessions.get_tts_mode_override(session_id)
        effective = resolve_effective_tts_mode(
            global_mode=voice_mode,
            session_override=chat_override,
        )
        voice_line = f"Voice: {effective} (global: {voice_mode}"
        if chat_override:
            voice_line += f", chat: {chat_override}"
        voice_line += ")"
        lines = [
            f"Session: {session_id}",
            f"Model: {model_id}",
            voice_line,
        ]
        lines.extend(
            format_lcm_status_lines(
                self._sessions.connection,
                session_id,
                workspace=self._workspace,
            ),
        )
        deployment_id = getattr(self._router, "_deployment_id", None)
        if isinstance(deployment_id, str) and deployment_id.strip():
            lines.append(f"Deployment id: {deployment_id}")
        return "\n".join(lines)

    async def _handle_agents(self) -> str:
        """Return a rich inventory of running L1/L2 sub-agents for ``/agents`` (D6/D11).

        List visibility matches Config→Sub-agents Running: all users may read the
        inventory; kill controls remain owner-only elsewhere.

        Returns:
            str: Formatted inventory or empty-state copy.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CoreCommandHandler._handle_agents)
            True
        """
        from sevn.gateway.menu.menu import (
            format_running_agents_inventory,
            subagent_menu_snapshot_from_router,
        )

        _l1, _l2, rows = await subagent_menu_snapshot_from_router(self._router)
        return format_running_agents_inventory(rows)

    def _global_tts_voice_id(self) -> str | None:
        """Return the workspace ``voice.tts_voice_id`` when set.

        Returns:
            str | None: Configured Kokoro voice code, or ``None`` when unset.

        Examples:
            >>> from sevn.config.workspace_config import WorkspaceConfig
            >>> from sevn.config.sections.channels import VoiceConfig
            >>> h = CoreCommandHandler.__new__(CoreCommandHandler)
            >>> h._workspace = WorkspaceConfig.minimal(voice=VoiceConfig(tts_voice_id="bf_emma"))
            >>> h._global_tts_voice_id()
            'bf_emma'
        """
        voice = self._workspace.voice
        if voice is None or not voice.tts_voice_id:
            return None
        return str(voice.tts_voice_id)

    def _handle_voice(self, args: str, *, session_id: str) -> str:
        """Apply ``/voice`` subcommands per design §10a.2 (session override).

        Args:
            args (str): Trailing args after ``/voice``.
            session_id (str): Active gateway session id.

        Returns:
            str: User-visible result or picker hint.

        Examples:
            >>> from sevn.config.workspace_config import WorkspaceConfig
            >>> h = CoreCommandHandler.__new__(CoreCommandHandler)
            >>> h._workspace = WorkspaceConfig.minimal()
            >>> h._handle_voice("", session_id="s").startswith("Voice:")
            True
        """
        arg = args.strip().lower()
        if arg in {"", "picker"}:
            current = self._global_tts_voice_id() or "default (af_heart)"
            return (
                f"Voice: {current}. Use /voice on|off|when_asked|reset to control replies, "
                "or /voice <name> to pick a voice (e.g. bf_emma, af_heart, am_michael). "
                "See /voice voices for the full list."
            )
        if arg in {"voices", "list"}:
            current = self._global_tts_voice_id() or "af_heart (default)"
            return (
                f"Current voice: {current}. Set with /voice <name> — e.g. bf_emma (British "
                "female), af_heart (US female, warm), am_michael (US male), bf_isabella. "
                "Full catalogue: kokoro-tts skill `--list-voices`."
            )
        if _VOICE_CODE_RE.match(arg):
            mutate_sevn_json(
                self._sevn_json,
                lambda d: _set_nested(d, "voice.tts_voice_id", arg),
            )
            self._reload_workspace()
            return f"Voice set to {arg} (applies to all chats)."
        if arg in {"on", "all"}:
            self._sessions.set_tts_mode_override(session_id, "all")
            return "Voice mode for this chat set to all."
        if arg == "off":
            self._sessions.set_tts_mode_override(session_id, "off")
            return "Voice mode for this chat set to off."
        if arg == "when_asked":
            self._sessions.set_tts_mode_override(session_id, "when_asked")
            return "Voice mode for this chat set to when_asked."
        if arg == "reset":
            self._sessions.set_tts_mode_override(session_id, None)
            global_mode = _voice_mode_label(self._workspace)
            return f"Chat voice override cleared (using global: {global_mode})."
        if arg == "toggle":
            effective = resolve_effective_tts_mode(
                global_mode=_voice_mode_label(self._workspace),
                session_override=self._sessions.get_tts_mode_override(session_id),
            )
            nxt = "off" if effective == "all" else "all"
            self._sessions.set_tts_mode_override(session_id, nxt)
            return f"Voice mode for this chat toggled to {nxt}."
        return "Open /config > Voice or use /voice on|off|when_asked|reset."

    def _handle_model(self, args: str) -> str:
        """Apply ``/model`` subcommands per design §10a.2.

        Args:
            args (str): Trailing args after ``/model``.

        Returns:
            str: User-visible result or picker hint.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(CoreCommandHandler._handle_model)
            True
        """
        arg = args.strip()
        if not arg:
            model_id = resolve_model_slot(self._workspace, ModelSlot.tier_b)
            return f"Current model: {model_id}\nUse /model <name> or /model toggle."
        low = arg.lower()
        if low == "toggle":
            doc = load_raw_sevn_json(self._sevn_json)
            current = resolve_model_slot(self._workspace, ModelSlot.tier_b)
            last = _get_nested(doc, "providers.last_used_model")
            target = str(last) if isinstance(last, str) and last.strip() else current

            def _swap(d: dict[str, Any]) -> None:
                _set_nested(d, "providers.last_used_model", current)
                _set_nested(d, "providers.tier_default.B", target)

            mutate_sevn_json(self._sevn_json, _swap)
            self._reload_workspace()
            return f"Model switched to {target}."
        mutate_sevn_json(
            self._sevn_json,
            lambda d: _set_nested(d, "providers.tier_default.B", arg),
        )
        self._reload_workspace()
        return f"Model set to {arg}."

    def _handle_ask_config(self, args: str) -> str:
        """Resolve ``/ask-config`` queries against closed vocabulary.

        Args:
            args (str): Trailing free-text query.

        Returns:
            str: Suggested menu path or shortcut (never mutates config).

        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> h = CoreCommandHandler.__new__(CoreCommandHandler)
            >>> h._content_root = Path(tempfile.mkdtemp())
            >>> h._handle_ask_config("voice").startswith("Try")
            True
        """
        if not args.strip():
            return "Usage: /ask-config <topic> — e.g. voice, model, shortcuts"
        parsed = parse_ask_config_query(self._content_root, args)
        if parsed is None:
            return "No matching menu path or shortcut. Try /config or /help."
        kind, target = parsed
        return format_ask_config_reply(kind, target)

    def _reload_workspace(self) -> None:
        """Reload parsed workspace config after ``sevn.json`` mutation.

        Delegates the full refresh (queue mode, scanner, voice, Telegram
        adapter flags, and per-handler ``_workspace`` propagation) to
        :meth:`ChannelRouter.apply_workspace` (`specs/17-gateway.md` §2.9).

        Examples:
            >>> import inspect
            >>> inspect.isfunction(CoreCommandHandler._reload_workspace)
            True
        """
        from sevn.config.loader import load_workspace

        ws, _ = load_workspace(sevn_json=self._sevn_json)
        self._workspace = ws
        self._router.apply_workspace(ws)


def _dashboard_url(workspace: WorkspaceConfig) -> str | None:
    """Resolve dashboard or Web UI URL from workspace extras.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        str | None: Absolute URL when configured.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _dashboard_url(WorkspaceConfig.minimal()) is None
        True
    """
    extra = workspace.model_extra or {}
    dash = extra.get("dashboard")
    if isinstance(dash, dict):
        url = dash.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    web_ui = extra.get("web_ui")
    if isinstance(web_ui, dict):
        url = web_ui.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


__all__ = ["CoreCommandHandler", "CoreCommandReply", "core_command_outbound"]
