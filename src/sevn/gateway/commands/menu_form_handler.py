"""Multi-step Telegram form flows for shortcuts and secrets (TMF Wave 3).

Module: sevn.gateway.commands.menu_form_handler
Depends: json, re, secrets, sqlite3, sevn.gateway.dispatcher.dispatcher_state,
    sevn.gateway.commands.shortcuts_store, sevn.security.secrets.factory

Exports:
    parse_form_callback — parse ``form:shortcut_add`` / ``form:secret_wizard``.
    MenuFormHandler — start wizards on callback; advance on chat text replies.

Examples:
    >>> from sevn.gateway.commands.menu_form_handler import parse_form_callback
    >>> parse_form_callback("form:shortcut_add")
    'shortcut_add'
"""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.commands.shortcuts_store import (
    add_shortcut,
    republish_set_my_commands,
    validate_shortcut_name,
)
from sevn.gateway.config_io.workspace_config_io import mutate_sevn_json
from sevn.gateway.dispatcher.dispatcher_state import (
    dispatcher_state_ttl_for_kind,
    insert_dispatcher_state,
)
from sevn.gateway.menu.menu import (
    ConfigMenuRefreshContext,
    ConfigSection,
    refresh_config_menu_message,
)
from sevn.integrations.twexapi.config import TWEXAPI_SECRET_ALIAS
from sevn.onboarding.web_app import _get_nested, _set_nested
from sevn.security.secrets.factory import secrets_chain_from_workspace

if TYPE_CHECKING:
    from sevn.gateway.channel_router import ChannelRouter, IncomingMessage

FORM_TARGETS: frozenset[str] = frozenset(
    {
        "shortcut_add",
        "secret_wizard",
        "agent_display_name",
        "logs_grep",
        "logs_span_id",
        "logs_logfire_token",
        "second_brain_vault_path",
        "second_brain_vault_browse",
        "subagents_max_override",
    },
)
_SECRET_ALIAS_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


def parse_form_callback(data: str) -> str | None:
    """Parse a supported ``form:*`` callback suffix.

    Args:
        data (str): Raw Telegram ``callback_data``.

    Returns:
        str | None: Form target id when supported.

    Examples:
    >>> parse_form_callback("form:shortcut_add")
    'shortcut_add'
    >>> parse_form_callback("form:logs:grep")
    'logs_grep'
    >>> parse_form_callback("form:logs:span_id")
    'logs_span_id'
    >>> parse_form_callback("form:unknown") is None
    True
    """
    raw = data.strip()
    if not raw.startswith("form:"):
        return None
    if raw == "form:agent:display_name":
        return "agent_display_name"
    if raw == "form:logs:grep":
        return "logs_grep"
    if raw == "form:logs:span_id":
        return "logs_span_id"
    if raw == "form:logs:logfire_token":
        return "logs_logfire_token"
    if raw.startswith("form:secret_wizard:"):
        alias = raw.removeprefix("form:secret_wizard:").strip()
        if alias and _SECRET_ALIAS_RE.match(alias):
            return f"secret_wizard:{alias}"
    if raw.startswith("form:sb_browse:"):
        return "second_brain_vault_browse"
    if raw.startswith("form:subagents_limits:"):
        return raw.removeprefix("form:")
    target = raw.removeprefix("form:").strip()
    return target if target in FORM_TARGETS else None


class MenuFormHandler:
    """Collect multi-step operator input for shortcut add and secret wizard flows."""

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
            >>> inspect.isfunction(MenuFormHandler.__init__)
            True
        """
        self._workspace = workspace
        self._router = router
        self._conn = conn
        self._content_root = content_root.expanduser().resolve()
        self._sevn_json = sevn_json_path

    def matches(self, msg: IncomingMessage) -> bool:
        """Return whether *msg* starts or continues a supported form flow.

        Args:
            msg (IncomingMessage): Inbound Telegram envelope.

        Returns:
            bool: ``True`` for ``form:*`` callbacks or active wizard text replies.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> h = MenuFormHandler.__new__(MenuFormHandler)
            >>> h.matches(
            ...     IncomingMessage(
            ...         channel="telegram",
            ...         user_id="1",
            ...         text="",
            ...         metadata={"callback_data": "form:shortcut_add"},
            ...     ),
            ... )
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        raw_cb = md.get("callback_data")
        if isinstance(raw_cb, str) and parse_form_callback(raw_cb.strip()):
            return True
        if isinstance(raw_cb, str) and raw_cb.strip().startswith("form:sb_browse:"):
            return True
        if isinstance(raw_cb, str) and raw_cb.strip().startswith("form:subagents_limits:"):
            return True
        text = (msg.text or "").strip()
        if not text or text.startswith("/"):
            return False
        if md.get("callback_data"):
            return False
        return self._find_active_form(msg) is not None

    async def handle(self, msg: IncomingMessage, *, session_id: str) -> None:
        """Start or advance a form wizard for *msg*.

        Args:
            msg (IncomingMessage): Inbound Telegram envelope.
            session_id (str): Active gateway session id.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler.handle)
            True
        """
        _ = session_id
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        raw_cb = md.get("callback_data")
        if isinstance(raw_cb, str) and raw_cb.strip().startswith("form:sb_browse:"):
            await self._handle_second_brain_browse_callback(msg, data=raw_cb.strip())
            return
        if isinstance(raw_cb, str) and parse_form_callback(raw_cb.strip()):
            await self._start_form(msg, target=parse_form_callback(raw_cb.strip()) or "")
            return
        await self._advance_form(msg)

    async def _start_form(self, msg: IncomingMessage, *, target: str) -> None:
        """Insert dispatcher state and prompt for the first wizard step.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            target (str): Parsed form target (``shortcut_add`` or ``secret_wizard``).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._start_form)
            True
        """
        if target == "secret_wizard" and not self._router._resolve_owner_flag(msg):
            await self._answer_callback(msg, text="Owner only.")
            return
        preset_alias: str | None = None
        if target.startswith("secret_wizard:"):
            preset_alias = target.removeprefix("secret_wizard:").strip()
            target = "secret_wizard"
        # ``logs_grep`` / ``logs_span_id`` are owner-only operator diagnostics
        # (`specs/18-channel-telegram.md` §4.7).
        if target in {
            "logs_grep",
            "logs_span_id",
            "logs_logfire_token",
        } and not self._router._resolve_owner_flag(msg):
            await self._answer_callback(msg, text="Owner only.")
            return
        if target in {
            "second_brain_vault_path",
            "second_brain_vault_browse",
        } and not self._router._resolve_owner_flag(msg):
            await self._answer_callback(msg, text="Owner only.")
            return
        await self._answer_callback(msg)
        self._consume_active_forms(msg)
        kind = "secret_wizard" if target == "secret_wizard" else "form"
        if target == "secret_wizard":
            section = (
                "skills:social_media_manager" if preset_alias == TWEXAPI_SECRET_ALIAS else "secrets"
            )
            step = "value" if preset_alias else "key"
        elif target == "agent_display_name":
            section = "agents"
            step = "name"
        elif target == "logs_grep":
            section = "logs"
            step = "pattern"
        elif target == "logs_span_id":
            section = "logs"
            step = "span_id"
        elif target == "logs_logfire_token":
            section = "logs"
            step = "token"
        elif target == "second_brain_vault_path":
            section = "second_brain"
            step = "path"
        elif target == "second_brain_vault_browse":
            section = "second_brain"
            step = "browse"
        elif target == "subagents_max_override":
            section = "subagents"
            step = "override"
        elif target.startswith("subagents_limits:"):
            section = "subagents"
            step = "l1"
        else:
            section = "shortcuts"
            step = "name"
        token = f"ds:{secrets.token_hex(8)}"
        payload_obj: dict[str, Any] = {
            "v": 1,
            "target": target,
            "step": step,
            "section": section,
            "user_id": str(msg.user_id),
        }
        if target.startswith("subagents_limits:"):
            payload_obj["role"] = target.removeprefix("subagents_limits:").strip()
        if preset_alias:
            payload_obj["alias"] = preset_alias
        payload = json.dumps(
            payload_obj,
            separators=(",", ":"),
        )
        chat_raw, topic_raw = self._chat_context(msg)
        insert_dispatcher_state(
            self._conn,
            token=token,
            kind=kind,
            user_id=self._user_id_int(msg.user_id),
            chat_id=chat_raw,
            topic_id=topic_raw,
            payload_json=payload,
            ttl_seconds=dispatcher_state_ttl_for_kind(kind, self._workspace),
        )
        if target == "secret_wizard":
            if preset_alias:
                prompt = f"Send the secret value for `{preset_alias}` (not shown again):"
            else:
                prompt = "Send the secret logical key (e.g. providers.openai.api_key):"
        elif target == "agent_display_name":
            prompt = "Send the new bot display name:"
        elif target == "logs_grep":
            prompt = "Send the grep pattern for service logs (gateway+proxy):"
        elif target == "logs_span_id":
            prompt = "Send the trace span id to look up:"
        elif target == "logs_logfire_token":
            prompt = "Send your Logfire write token (pylf_v1_… — not shown again):"
        elif target == "second_brain_vault_path":
            prompt = "Send the workspace-relative vault path (e.g. obsidian/alex_AI):"
        elif target == "second_brain_vault_browse":
            await self._send_second_brain_browse_keyboard(msg, token=token, browse_path=".")
            return
        elif target == "subagents_max_override":
            prompt = "Send global max_override (integer, or empty to clear):"
        elif target.startswith("subagents_limits:"):
            role = target.removeprefix("subagents_limits:").strip()
            prompt = f"Send max level-1 count for {role} (integer, empty clears override):"
        else:
            prompt = "Send the shortcut name (e.g. standup):"
        await self._send_chat(msg, prompt)

    async def _advance_form(self, msg: IncomingMessage) -> None:
        """Apply one text reply to the active wizard step.

        Args:
            msg (IncomingMessage): Inbound chat text envelope.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._advance_form)
            True
        """
        active = self._find_active_form(msg)
        if active is None:
            return
        token, _kind, payload = active
        target = str(payload.get("target", ""))
        step = str(payload.get("step", ""))
        text = (msg.text or "").strip()
        if text.lower() in {"cancel", "abort"}:
            self._consume_token(token)
            await self._send_chat(msg, "Form cancelled.")
            return
        if target == "shortcut_add":
            await self._advance_shortcut_add(
                msg, token=token, step=step, text=text, payload=payload
            )
            return
        if target == "secret_wizard":
            await self._advance_secret_wizard(
                msg, token=token, step=step, text=text, payload=payload
            )
            return
        if target == "agent_display_name":
            await self._advance_agent_display_name(
                msg, token=token, step=step, text=text, payload=payload
            )
            return
        if target == "second_brain_vault_path":
            await self._advance_second_brain_vault_path(
                msg, token=token, step=step, text=text, payload=payload
            )
            return
        if target == "logs_grep":
            await self._advance_logs_grep(msg, token=token, step=step, text=text, payload=payload)
            return
        if target == "logs_span_id":
            await self._advance_logs_span_id(
                msg, token=token, step=step, text=text, payload=payload
            )
            return
        if target == "logs_logfire_token":
            await self._advance_logs_logfire_token(
                msg, token=token, step=step, text=text, payload=payload
            )
            return
        if target == "subagents_max_override":
            await self._advance_subagents_max_override(
                msg, token=token, step=step, text=text, payload=payload
            )
            return
        if target.startswith("subagents_limits:"):
            await self._advance_subagents_role_limits(
                msg, token=token, step=step, text=text, payload=payload
            )

    async def _advance_subagents_max_override(
        self,
        msg: IncomingMessage,
        *,
        token: str,
        step: str,
        text: str,
        payload: dict[str, Any],
    ) -> None:
        """Persist ``subagents.max_override`` from operator numeric input.

        Args:
            msg (IncomingMessage): Inbound chat text envelope.
            token (str): Active dispatcher token.
            step (str): Wizard step id.
            text (str): Operator reply.
            payload (dict[str, Any]): Parsed wizard payload.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._advance_subagents_max_override)
            True
        """
        _ = step, payload
        value: int | None
        if not text.strip():
            value = None
        else:
            try:
                value = max(0, int(text.strip()))
            except ValueError:
                await self._send_chat(msg, "Send a non-negative integer or empty to clear.")
                return

        def _apply(doc: dict[str, Any]) -> None:
            _set_nested(doc, "subagents.max_override", value)

        mutate_sevn_json(self._sevn_json, _apply)
        mar = self._router._menu_action_router
        if mar is not None:
            mar._reload_workspace()
        self._workspace = self._router._workspace
        self._consume_token(token)
        await self._refresh_section(msg, section="subagents", toast="✅ Updated max_override.")

    async def _advance_subagents_role_limits(
        self,
        msg: IncomingMessage,
        *,
        token: str,
        step: str,
        text: str,
        payload: dict[str, Any],
    ) -> None:
        """Two-step wizard for per-role ``max_level1`` / ``max_level2`` overrides.

        Args:
            msg (IncomingMessage): Inbound chat text envelope.
            token (str): Active dispatcher token.
            step (str): ``l1`` or ``l2``.
            text (str): Operator reply.
            payload (dict[str, Any]): Parsed wizard payload including ``role``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._advance_subagents_role_limits)
            True
        """
        role = str(payload.get("role", "")).strip()
        if role not in {"triager", "tier_b", "tier_c", "tier_d"}:
            self._consume_token(token)
            await self._send_chat(msg, "Wizard expired — open Sub-agents again.")
            return
        if step == "l1":
            if text.strip():
                try:
                    payload["max_level1"] = max(0, int(text.strip()))
                except ValueError:
                    await self._send_chat(msg, "Send a non-negative integer or empty to clear.")
                    return
            else:
                payload["max_level1"] = None
            payload["step"] = "l2"
            self._update_payload(token, payload)
            await self._send_chat(
                msg, f"Send max level-2 count for {role} (integer, empty clears):"
            )
            return
        if step == "l2":
            max_l1 = payload.get("max_level1")
            max_l2: int | None
            if text.strip():
                try:
                    max_l2 = max(0, int(text.strip()))
                except ValueError:
                    await self._send_chat(msg, "Send a non-negative integer or empty to clear.")
                    return
            else:
                max_l2 = None

            def _apply(doc: dict[str, Any]) -> None:
                agents = _get_nested(doc, f"subagents.agents.{role}")
                block = dict(agents) if isinstance(agents, dict) else {}
                if max_l1 is not None:
                    block["max_level1"] = max_l1
                elif "max_level1" in block:
                    block.pop("max_level1", None)
                if max_l2 is not None:
                    block["max_level2"] = max_l2
                elif "max_level2" in block:
                    block.pop("max_level2", None)
                if block:
                    _set_nested(doc, f"subagents.agents.{role}", block)
                else:
                    agents_root = _get_nested(doc, "subagents.agents")
                    if isinstance(agents_root, dict):
                        agents_root.pop(role, None)

            mutate_sevn_json(self._sevn_json, _apply)
            mar = self._router._menu_action_router
            if mar is not None:
                mar._reload_workspace()
            self._workspace = self._router._workspace
            self._consume_token(token)
            await self._refresh_section(msg, section="subagents", toast="✅ Updated role limits.")

    async def _advance_logs_grep(
        self,
        msg: IncomingMessage,
        *,
        token: str,
        step: str,
        text: str,
        payload: dict[str, Any],
    ) -> None:
        """Handle the single-step ``form:logs:grep`` wizard (owner-only).

        Greps gateway and proxy service logs and replies with ``<pre>``-wrapped
        chunked output via :func:`sevn.gateway.diagnostics.format_for_telegram`.

        Args:
            msg (IncomingMessage): Inbound chat text envelope.
            token (str): Active ``dispatcher_state`` token.
            step (str): Current step id.
            text (str): Operator reply text (regex pattern).
            payload (dict[str, Any]): Parsed wizard payload.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._advance_logs_grep)
            True
        """
        import re

        from sevn.agent.tracing.sink_factory import trace_redaction_policy_for
        from sevn.gateway.diagnostics.diagnostics import format_for_telegram
        from sevn.tools.log_query import tail_log_lines
        from sevn.workspace.layout import WorkspaceLayout

        _ = step, payload
        pattern_text = text.strip()
        if not pattern_text:
            await self._send_chat(msg, "Pattern cannot be empty.")
            return
        try:
            compiled = re.compile(pattern_text)
        except re.error as exc:
            await self._send_chat(msg, f"Invalid regex: {exc}")
            return
        self._consume_token(token)
        layout = WorkspaceLayout(self._sevn_json, self._content_root)
        policy = trace_redaction_policy_for(self._workspace)
        matched: list[str] = []
        for service in ("gateway", "proxy"):
            path = layout.logs_dir / f"{service}.log"
            lines, _existed = tail_log_lines(path, lines=500, pattern=compiled)
            for line in lines:
                matched.append(f"[{service}] {line}")
        chunks = (
            format_for_telegram(matched, redaction=policy)
            if matched
            else ["<pre>(no matches)</pre>"]
        )
        await self._send_pre_chunks(msg, chunks)
        await self._refresh_section(msg, section="logs", toast=None)

    async def _advance_logs_span_id(
        self,
        msg: IncomingMessage,
        *,
        token: str,
        step: str,
        text: str,
        payload: dict[str, Any],
    ) -> None:
        """Handle the single-step ``form:logs:span_id`` wizard (owner-only).

        Args:
            msg (IncomingMessage): Inbound chat text envelope.
            token (str): Active ``dispatcher_state`` token.
            step (str): Current step id.
            text (str): Operator reply text (span id).
            payload (dict[str, Any]): Parsed wizard payload.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._advance_logs_span_id)
            True
        """
        from sevn.agent.tracing.sink_factory import trace_redaction_policy_for
        from sevn.gateway.diagnostics.diagnostics import format_traces_for_telegram, get_span
        from sevn.workspace.layout import WorkspaceLayout

        _ = step, payload
        span_id = text.strip()
        if not span_id:
            await self._send_chat(msg, "Span id cannot be empty.")
            return
        self._consume_token(token)
        layout = WorkspaceLayout(self._sevn_json, self._content_root)
        policy = trace_redaction_policy_for(self._workspace)
        span = get_span(layout, span_id, policy=policy)
        if span is None:
            chunks = [f"<pre>(span {span_id!r} not found)</pre>"]
        else:
            chunks = format_traces_for_telegram([span], redaction=policy)
        await self._send_pre_chunks(msg, chunks)
        await self._refresh_section(msg, section="logs", toast=None)

    async def _advance_logs_logfire_token(
        self,
        msg: IncomingMessage,
        *,
        token: str,
        step: str,
        text: str,
        payload: dict[str, Any],
    ) -> None:
        """Store a Logfire write token and enable the Logfire trace sink (owner-only).

        Args:
            msg (IncomingMessage): Inbound chat text envelope.
            token (str): Active ``dispatcher_state`` token.
            step (str): Current step id.
            text (str): Operator reply text (Logfire token).
            payload (dict[str, Any]): Parsed wizard payload.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._advance_logs_logfire_token)
            True
        """
        from sevn.agent.tracing.logfire_config import (
            LOGFIRE_SECRET_LOGICAL_KEY,
            apply_logfire_export_to_sevn_doc,
        )

        _ = step, payload
        if not self._router._resolve_owner_flag(msg):
            self._consume_token(token)
            await self._send_chat(msg, "Owner only.")
            return
        bearer = text.strip()
        if not bearer:
            await self._send_chat(msg, "Logfire token cannot be empty.")
            return
        chain = secrets_chain_from_workspace(
            self._content_root,
            self._workspace.secrets_backend,
        )
        try:
            await chain.set(LOGFIRE_SECRET_LOGICAL_KEY, bearer)
        except Exception as exc:
            await self._send_chat(msg, f"Could not store Logfire token: {exc}")
            return
        mutate_sevn_json(
            self._sevn_json,
            lambda d: apply_logfire_export_to_sevn_doc(d, enabled=True, keep_local_sinks=True),
        )
        self._consume_token(token)
        await self._refresh_section(msg, section="logs", toast=None)
        await self._send_chat(
            msg,
            "✅ Logfire token stored and export enabled. Restart the gateway to apply.",
        )

    async def _advance_shortcut_add(
        self,
        msg: IncomingMessage,
        *,
        token: str,
        step: str,
        text: str,
        payload: dict[str, Any],
    ) -> None:
        """Handle one ``shortcut_add`` wizard step.

        Args:
            msg (IncomingMessage): Inbound chat text envelope.
            token (str): Active ``dispatcher_state`` token.
            step (str): Current step id.
            text (str): Operator reply text.
            payload (dict[str, Any]): Parsed wizard payload.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._advance_shortcut_add)
            True
        """
        if step == "name":
            try:
                validate_shortcut_name(text)
            except ValueError as exc:
                await self._send_chat(msg, f"Invalid name: {exc}")
                return
            payload["step"] = "prompt"
            payload["name"] = text.strip().lower()
            self._update_payload(token, payload)
            await self._send_chat(msg, f"Send the prompt text for /{payload['name']}:")
            return
        if step == "prompt":
            name = str(payload.get("name", "")).strip().lower()
            if not name:
                self._consume_token(token)
                await self._send_chat(msg, "Wizard expired — start again from /config → Shortcuts.")
                return
            if not text:
                await self._send_chat(msg, "Prompt text cannot be empty.")
                return
            try:
                add_shortcut(
                    self._content_root,
                    {
                        "name": name,
                        "description": f"Shortcut {name}",
                        "type": "prompt",
                        "payload": {"template": text},
                        "visibility": True,
                        "auth": "PUBLIC",
                    },
                )
            except ValueError as exc:
                await self._send_chat(msg, f"Could not save shortcut: {exc}")
                return
            self._consume_token(token)
            await republish_set_my_commands(self._router)
            await self._refresh_section(msg, section="shortcuts", toast=None)
            await self._send_chat(
                msg, f"✅ Shortcut /{name} saved and published to the command menu."
            )

    async def _advance_agent_display_name(
        self,
        msg: IncomingMessage,
        *,
        token: str,
        step: str,
        text: str,
        payload: dict[str, Any],
    ) -> None:
        """Handle the single-step agent display name wizard.

        Args:
            msg (IncomingMessage): Inbound chat text envelope.
            token (str): Active ``dispatcher_state`` token.
            step (str): Current step id.
            text (str): Operator reply text.
            payload (dict[str, Any]): Parsed wizard payload.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._advance_agent_display_name)
            True
        """
        _ = step, payload
        if not text.strip():
            await self._send_chat(msg, "Display name cannot be empty.")
            return

        def _apply(doc: dict[str, Any]) -> None:
            _set_nested(doc, "agent.display_name", text.strip())

        mutate_sevn_json(self._sevn_json, _apply)
        mar = self._router._menu_action_router
        if mar is not None:
            mar._reload_workspace()
        self._workspace = self._router._workspace
        self._consume_token(token)
        await self._refresh_section(msg, section="agents", toast=None)
        await self._send_chat(msg, f"✅ Display name set to {text.strip()!r}.")

    async def _advance_second_brain_vault_path(
        self,
        msg: IncomingMessage,
        *,
        token: str,
        step: str,
        text: str,
        payload: dict[str, Any],
    ) -> None:
        """Handle the single-step Second Brain vault path wizard (owner-only).

        Args:
            msg (IncomingMessage): Inbound chat text envelope.
            token (str): Active ``dispatcher_state`` token.
            step (str): Current step id.
            text (str): Operator reply text.
            payload (dict[str, Any]): Parsed wizard payload.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._advance_second_brain_vault_path)
            True
        """
        _ = step, payload
        if not self._router._resolve_owner_flag(msg):
            self._consume_token(token)
            await self._send_chat(msg, "Owner only.")
            return
        try:
            await self._apply_second_brain_vault_path(text.strip())
        except ValueError as exc:
            await self._send_chat(msg, str(exc))
            return
        mar = self._router._menu_action_router
        if mar is not None:
            mar._reload_workspace()
        self._workspace = self._router._workspace
        self._consume_token(token)
        await self._refresh_section(msg, section="second_brain", toast=None)
        await self._send_chat(msg, f"✅ Vault path set to {text.strip()!r}.")

    async def _apply_second_brain_vault_path(self, rel_path: str) -> None:
        """Validate, persist, and bootstrap a Second Brain vault path.

        Args:
            rel_path (str): Workspace-relative vault directory.

        Raises:
            ValueError: When the path is invalid.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._apply_second_brain_vault_path)
            True
        """
        from sevn.config.sections.features import _normalise_vault_path
        from sevn.second_brain.bootstrap import ensure_second_brain_scope_layout
        from sevn.second_brain.paths import effective_scope, resolve_scope_root

        vault_norm = _normalise_vault_path(rel_path)

        def _apply(doc: dict[str, Any]) -> None:
            _set_nested(doc, "second_brain.enabled", True)
            _set_nested(doc, "second_brain.paths.vault", vault_norm)
            sb = doc.get("second_brain")
            if isinstance(sb, dict):
                paths = sb.get("paths")
                if isinstance(paths, dict):
                    paths.pop("wiki", None)

        mutate_sevn_json(self._sevn_json, _apply)
        from sevn.config.loader import load_workspace

        cfg, _layout = load_workspace(sevn_json=self._sevn_json)
        sb_cfg = cfg.second_brain
        scope = effective_scope(None, sb_cfg)
        scope_root = resolve_scope_root(self._content_root, sb_cfg, scope)
        ensure_second_brain_scope_layout(scope_root)

    async def _send_second_brain_browse_keyboard(
        self,
        msg: IncomingMessage,
        *,
        token: str,
        browse_path: str,
    ) -> None:
        """Send inline keyboard listing workspace subdirectories for vault browse.

        Args:
            msg (IncomingMessage): Inbound envelope.
            token (str): Active dispatcher token storing browse state.
            browse_path (str): Current browse cursor.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._send_second_brain_browse_keyboard)
            True
        """
        from sevn.second_brain.folder_picker import list_workspace_subdirs, normalise_browse_path

        try:
            rel = normalise_browse_path(browse_path)
        except Exception as exc:
            await self._send_chat(msg, f"Invalid browse path: {exc}")
            return
        rows_data = list_workspace_subdirs(self._content_root, rel)
        payload = {
            "v": 1,
            "target": "second_brain_vault_browse",
            "step": "browse",
            "section": "second_brain",
            "user_id": str(msg.user_id),
            "browse_path": rel,
            "entries": rows_data,
        }
        self._update_payload(token, payload)
        keyboard: list[list[dict[str, str]]] = []
        for entry in rows_data:
            idx = rows_data.index(entry)
            keyboard.append(
                [
                    {
                        "text": f"📂 {entry['name']}",
                        "callback_data": f"form:sb_browse:dir:{idx}",
                    }
                ]
            )
        nav_row: list[dict[str, str]] = [
            {"text": "✓ Select here", "callback_data": "form:sb_browse:select"},
            {"text": "✗ Cancel", "callback_data": "form:sb_browse:cancel"},
        ]
        if rel != ".":
            nav_row.insert(0, {"text": "⬆ Up", "callback_data": "form:sb_browse:up"})
        keyboard.append(nav_row)
        label = "workspace root" if rel == "." else rel
        await self._send_chat(
            msg,
            f"Browse vault folder ({label}):",
            reply_markup={"inline_keyboard": keyboard},
        )

    async def _handle_second_brain_browse_callback(
        self,
        msg: IncomingMessage,
        *,
        data: str,
    ) -> None:
        """Handle ``form:sb_browse:*`` navigation callbacks during vault browse.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            data (str): Raw callback_data string.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._handle_second_brain_browse_callback)
            True
        """
        if not self._router._resolve_owner_flag(msg):
            await self._answer_callback(msg, text="Owner only.")
            return
        active = self._find_active_form(msg)
        if active is None:
            await self._answer_callback(msg, text="Browse session expired.")
            return
        token, _kind, payload = active
        if payload.get("target") != "second_brain_vault_browse":
            await self._answer_callback(msg)
            return
        await self._answer_callback(msg)
        action = data.removeprefix("form:sb_browse:").strip()
        browse_path = str(payload.get("browse_path") or ".")
        entries = payload.get("entries")
        entry_rows = entries if isinstance(entries, list) else []
        if action == "cancel":
            self._consume_token(token)
            await self._send_chat(msg, "Vault browse cancelled.")
            return
        if action == "up":
            if browse_path == ".":
                await self._send_second_brain_browse_keyboard(msg, token=token, browse_path=".")
                return
            parent = browse_path.rsplit("/", 1)[0] if "/" in browse_path else "."
            await self._send_second_brain_browse_keyboard(msg, token=token, browse_path=parent)
            return
        if action == "select":
            if browse_path == ".":
                await self._send_chat(msg, "Select a subfolder or enter a path manually.")
                return
            try:
                await self._apply_second_brain_vault_path(browse_path)
            except ValueError as exc:
                await self._send_chat(msg, str(exc))
                return
            mar = self._router._menu_action_router
            if mar is not None:
                mar._reload_workspace()
            self._workspace = self._router._workspace
            self._consume_token(token)
            await self._refresh_section(msg, section="second_brain", toast=None)
            await self._send_chat(msg, f"✅ Vault path set to {browse_path!r}.")
            return
        if action.startswith("dir:"):
            try:
                idx = int(action.split(":", 1)[1])
            except ValueError:
                await self._send_chat(msg, "Invalid folder selection.")
                return
            if idx < 0 or idx >= len(entry_rows):
                await self._send_chat(msg, "Folder list changed — start browse again.")
                return
            row = entry_rows[idx]
            if not isinstance(row, dict):
                await self._send_chat(msg, "Invalid folder selection.")
                return
            nxt = str(row.get("relative") or "")
            await self._send_second_brain_browse_keyboard(msg, token=token, browse_path=nxt)
            return

    async def _advance_secret_wizard(
        self,
        msg: IncomingMessage,
        *,
        token: str,
        step: str,
        text: str,
        payload: dict[str, Any],
    ) -> None:
        """Handle one ``secret_wizard`` step (owner-only).

        Args:
            msg (IncomingMessage): Inbound chat text envelope.
            token (str): Active ``dispatcher_state`` token.
            step (str): Current step id.
            text (str): Operator reply text.
            payload (dict[str, Any]): Parsed wizard payload.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._advance_secret_wizard)
            True
        """
        if not self._router._resolve_owner_flag(msg):
            self._consume_token(token)
            await self._send_chat(msg, "Owner only.")
            return
        if step == "key":
            alias = text.strip()
            if not _SECRET_ALIAS_RE.match(alias):
                await self._send_chat(
                    msg,
                    "Invalid key — use letters, digits, dots, underscores, or hyphens.",
                )
                return
            payload["step"] = "value"
            payload["alias"] = alias
            self._update_payload(token, payload)
            await self._send_chat(msg, f"Send the secret value for `{alias}` (not shown again):")
            return
        if step == "value":
            alias = str(payload.get("alias", "")).strip()
            if not alias:
                self._consume_token(token)
                await self._send_chat(msg, "Wizard expired — start again from /config → Secrets.")
                return
            if not text:
                await self._send_chat(msg, "Secret value cannot be empty.")
                return
            chain = secrets_chain_from_workspace(
                self._content_root, self._workspace.secrets_backend
            )
            try:
                await chain.set(alias, text)
            except Exception as exc:
                await self._send_chat(msg, f"Could not store secret: {exc}")
                return
            self._consume_token(token)
            section = str(payload.get("section") or "secrets")
            await self._refresh_section(msg, section=section, toast=None)
            await self._send_chat(msg, f"✅ Secret `{alias}` stored.")

    def _find_active_form(
        self,
        msg: IncomingMessage,
    ) -> tuple[str, str, dict[str, Any]] | None:
        """Return the newest active wizard row for *msg*'s user and chat.

        Args:
            msg (IncomingMessage): Inbound envelope.

        Returns:
            tuple[str, str, dict[str, Any]] | None: ``(token, kind, payload)`` or ``None``.

        Examples:
            >>> h = MenuFormHandler.__new__(MenuFormHandler)
            >>> h._find_active_form.__name__
            '_find_active_form'
        """
        chat_raw, _topic_raw = self._chat_context(msg)
        now = int(time.time())
        rows = self._conn.execute(
            """
            SELECT token, kind, payload_json
            FROM dispatcher_state
            WHERE chat_id = ? AND kind IN ('form', 'secret_wizard')
              AND consumed = 0 AND expires_at > ?
            ORDER BY created_at DESC
            """,
            (chat_raw, now),
        ).fetchall()
        user_id = str(msg.user_id)
        for token, kind, payload_raw in rows:
            try:
                payload = json.loads(str(payload_raw))
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            if str(payload.get("user_id", "")) != user_id:
                continue
            return str(token), str(kind), payload
        return None

    def _consume_active_forms(self, msg: IncomingMessage) -> None:
        """Mark any in-flight wizard rows for *msg* as consumed.

        Args:
            msg (IncomingMessage): Inbound envelope.

        Examples:
            >>> h = MenuFormHandler.__new__(MenuFormHandler)
            >>> h._consume_active_forms.__name__
            '_consume_active_forms'
        """
        active = self._find_active_form(msg)
        if active is not None:
            self._consume_token(active[0])

    def _consume_token(self, token: str) -> None:
        """Mark one ``dispatcher_state`` row consumed.

        Args:
            token (str): Row primary key.

        Examples:
            >>> import sqlite3
            >>> from sevn.storage.migrate import apply_migrations
            >>> c = sqlite3.connect(":memory:")
            >>> apply_migrations(c)
            >>> h = MenuFormHandler.__new__(MenuFormHandler)
            >>> h._conn = c
            >>> h._consume_token("missing")
        """
        self._conn.execute(
            "UPDATE dispatcher_state SET consumed = 1 WHERE token = ?",
            (token.strip(),),
        )
        self._conn.commit()

    def _update_payload(self, token: str, payload: dict[str, Any]) -> None:
        """Replace the JSON payload for an active wizard row.

        Args:
            token (str): Row primary key.
            payload (dict[str, Any]): Updated wizard state.

        Examples:
            >>> h = MenuFormHandler.__new__(MenuFormHandler)
            >>> h._update_payload.__name__
            '_update_payload'
        """
        body = json.dumps(payload, separators=(",", ":"))
        self._conn.execute(
            "UPDATE dispatcher_state SET payload_json = ? WHERE token = ?",
            (body, token.strip()),
        )
        self._conn.commit()

    async def _refresh_section(
        self,
        msg: IncomingMessage,
        *,
        section: str,
        toast: str | None,
    ) -> None:
        """Re-edit the source ``/config`` message when callback metadata is present.

        Args:
            msg (IncomingMessage): Inbound envelope.
            section (str): Config section id to rebuild.
            toast (str | None): Optional callback toast text.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._refresh_section)
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        message_raw = md.get("message_id")
        if not isinstance(chat_raw, int) or not isinstance(message_raw, int):
            return
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return
        thread_raw = md.get("topic_id")
        thread_id = int(thread_raw) if isinstance(thread_raw, int) else None
        ctx = ConfigMenuRefreshContext(
            chat_id=chat_raw,
            message_id=message_raw,
            topic_id=thread_id,
            section=cast("ConfigSection", section),
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
        if cq_str and toast is not None:
            await self._answer_callback(msg, text=toast)

    async def _send_pre_chunks(self, msg: IncomingMessage, chunks: list[str]) -> None:
        """Send ``<pre>`` HTML chunks as new chat messages.

        Args:
            msg (IncomingMessage): Inbound envelope.
            chunks (list[str]): Pre-formatted HTML chunks.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._send_pre_chunks)
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

    async def _send_chat(
        self,
        msg: IncomingMessage,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        """Send a new chat message on *msg*'s channel.

        Args:
            msg (IncomingMessage): Inbound envelope.
            text (str): Outbound body.
            reply_markup (dict[str, Any] | None): Optional Telegram inline keyboard.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._send_chat)
            True
        """
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return
        from sevn.gateway.channel_router import OutgoingMessage, _telegram_reply_metadata

        metadata = dict(_telegram_reply_metadata(msg))
        if reply_markup is not None:
            metadata["reply_markup"] = reply_markup
        await adapter.send(
            OutgoingMessage(
                channel=msg.channel,
                user_id=msg.user_id,
                text=text,
                metadata=metadata,
            ),
        )

    async def _answer_callback(self, msg: IncomingMessage, *, text: str | None = None) -> None:
        """Acknowledge a Telegram callback query when present.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            text (str | None): Optional toast body.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuFormHandler._answer_callback)
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        cq_id = md.get("callback_query_id")
        if not isinstance(cq_id, str) or not cq_id.strip():
            return
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return
        answer_fn = getattr(adapter, "answer_callback_query", None)
        if callable(answer_fn):
            await cast("Callable[..., Awaitable[Any]]", answer_fn)(
                callback_query_id=cq_id.strip(),
                text=text,
            )

    @staticmethod
    def _user_id_int(user_id: str) -> int:
        """Coerce Telegram user id to int for ``dispatcher_state.user_id``.

        Args:
            user_id (str): Gateway user id string.

        Returns:
            int: Parsed id or ``0`` when non-numeric.

        Examples:
            >>> MenuFormHandler._user_id_int("42")
            42
            >>> MenuFormHandler._user_id_int("owner1")
            0
        """
        return int(user_id) if str(user_id).isdigit() else 0

    @staticmethod
    def _chat_context(msg: IncomingMessage) -> tuple[int, int | None]:
        """Extract chat and topic ids from message metadata.

        Args:
            msg (IncomingMessage): Inbound envelope.

        Returns:
            tuple[int, int | None]: ``(chat_id, topic_id)``.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> MenuFormHandler._chat_context(
            ...     IncomingMessage(
            ...         channel="telegram",
            ...         user_id="1",
            ...         text="",
            ...         metadata={"chat_id": 7, "topic_id": 3},
            ...     ),
            ... )
            (7, 3)
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        chat_raw = md.get("chat_id")
        chat_id = int(chat_raw) if isinstance(chat_raw, int) else 0
        topic_raw = md.get("topic_id")
        topic_id = int(topic_raw) if isinstance(topic_raw, int) else None
        return chat_id, topic_id


__all__ = ["FORM_TARGETS", "MenuFormHandler", "parse_form_callback"]
