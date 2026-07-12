"""Dedicated Telegram routing for bound Coding Agents (bypass Triager).

Module: sevn.gateway.coding_agent_router
Depends: sevn.agent.tracing.sink, sevn.coding_agents.registry, sevn.config.workspace_config,
    sevn.gateway.channel_router

Exports:
    CodingAgentRouter — match bindings and handle operator chat/commands.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import TYPE_CHECKING, Any

from loguru import logger

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.coding_agents.registry import match_telegram_binding
from sevn.config.sections.coding_agents import parse_coding_agents_section
from sevn.config.workspace_config import WorkspaceConfig

if TYPE_CHECKING:
    from sevn.gateway.channel_router import ChannelAdapter, IncomingMessage

_GOAL_RE = re.compile(r"^/goal(?:\s+(.+))?$", re.IGNORECASE | re.DOTALL)
_LOOP_RE = re.compile(r"^/loop(?:\s+(start|stop))?$", re.IGNORECASE)
_STATUS_RE = re.compile(r"^/(?:status|coding-status)(?:\s*)$", re.IGNORECASE)


class CodingAgentRouter:
    """Route bound Telegram topics directly to configured coding agents."""

    def __init__(
        self,
        *,
        workspace: WorkspaceConfig,
        trace: TraceSink,
    ) -> None:
        """Wire workspace config and trace sink for operator chat.

        Args:
            workspace (WorkspaceConfig): Parsed workspace configuration.
            trace (TraceSink): Gateway trace sink for coding-agent events.

        Examples:
            >>> from sevn.agent.tracing.sink import NullTraceSink
            >>> isinstance(
            ...     CodingAgentRouter(workspace=WorkspaceConfig.minimal(), trace=NullTraceSink()),
            ...     CodingAgentRouter,
            ... )
            True
        """
        self._workspace = workspace
        self._trace = trace
        self._loop_active: set[str] = set()

    @staticmethod
    def _chat_id(msg: IncomingMessage) -> str | None:
        """Extract Telegram chat id from inbound metadata.

        Args:
            msg (IncomingMessage): Normalised inbound envelope.

        Returns:
            str | None: Chat id string when present.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> CodingAgentRouter._chat_id(IncomingMessage(channel="telegram", user_id="1", text="hi", metadata={"chat_id": -100}))
            '-100'
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        raw = md.get("chat_id")
        if isinstance(raw, int):
            return str(raw)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return None

    @staticmethod
    def _topic_id(msg: IncomingMessage) -> int | None:
        """Extract normalised Telegram topic id from inbound metadata.

        Args:
            msg (IncomingMessage): Normalised inbound envelope.

        Returns:
            int | None: Topic id when routed through a forum thread.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> CodingAgentRouter._topic_id(IncomingMessage(channel="telegram", user_id="1", text="hi", metadata={"topic_id": 42}))
            42
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        raw = md.get("topic_id")
        if isinstance(raw, int):
            return raw
        return None

    def match_binding(self, msg: IncomingMessage) -> str | None:
        """Return configured agent id when ``msg`` matches a Telegram binding.

        Args:
            msg (IncomingMessage): Inbound channel envelope.

        Returns:
            str | None: Agent id or ``None`` when no binding matches.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> from sevn.agent.tracing.sink import NullTraceSink
            >>> r = CodingAgentRouter(workspace=WorkspaceConfig.minimal(), trace=NullTraceSink())
            >>> r.match_binding(IncomingMessage(channel="webchat", user_id="1", text="hi")) is None
            True
        """
        chat_id = self._chat_id(msg)
        if chat_id is None:
            return None
        return match_telegram_binding(
            self._workspace,
            channel=msg.channel,
            chat_id=chat_id,
            topic_id=self._topic_id(msg),
        )

    def _agent_config(self, agent_id: str) -> Any | None:
        """Load typed agent config row for ``agent_id``.

        Args:
            agent_id (str): Registry key under ``coding_agents.agents``.

        Returns:
            Any | None: Parsed agent config or ``None`` when missing.

        Examples:
            >>> from sevn.agent.tracing.sink import NullTraceSink
            >>> r = CodingAgentRouter(workspace=WorkspaceConfig.minimal(), trace=NullTraceSink())
            >>> r._agent_config("missing") is None
            True
        """
        extra = self._workspace.model_extra or {}
        section = parse_coding_agents_section(extra.get("coding_agents"))
        if section is None:
            return None
        return section.agents.get(agent_id)

    async def _emit(
        self,
        *,
        kind: str,
        session_id: str,
        turn_id: str,
        status: str,
        attrs: dict[str, Any] | None = None,
    ) -> None:
        """Emit a coding-agent trace row.

        Args:
            kind (str): Trace event kind.
            session_id (str): Gateway session id.
            turn_id (str): Correlation / turn id.
            status (str): Short status token.
            attrs (dict[str, Any] | None): Optional attribute bag.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CodingAgentRouter._emit)
            True
        """
        now = time.time_ns()
        await self._trace.emit(
            TraceEvent(
                kind=kind,
                span_id=uuid.uuid4().hex,
                parent_span_id=None,
                session_id=session_id,
                turn_id=turn_id,
                tier=None,
                ts_start_ns=now,
                ts_end_ns=now,
                status=status,
                attrs=dict(attrs or {}),
            ),
        )

    def _handle_alrca_command(self, agent_id: str, text: str) -> str | None:
        """Parse ALRCA slash commands for bound operator chat.

        Args:
            agent_id (str): Matched agent registry id.
            text (str): Inbound message body.

        Returns:
            str | None: Reply text when a command was handled, else ``None``.

        Examples:
            >>> from sevn.agent.tracing.sink import NullTraceSink
            >>> r = CodingAgentRouter(workspace=WorkspaceConfig.minimal(), trace=NullTraceSink())
            >>> r._handle_alrca_command("a", "/status").startswith("ALRCA")
            True
        """
        stripped = text.strip()
        if _STATUS_RE.match(stripped):
            loop = "running" if agent_id in self._loop_active else "stopped"
            agent = self._agent_config(agent_id)
            executor = getattr(agent, "executor", "cursor") if agent is not None else "cursor"
            return (
                f"ALRCA agent `{agent_id}` · executor `{executor}` · loop {loop}. "
                "Full goal/loop worker ships in CA3."
            )
        goal_match = _GOAL_RE.match(stripped)
        if goal_match:
            payload = (goal_match.group(1) or "").strip()
            if payload:
                return f"Goal capture for `{agent_id}` is queued (CA3). Received: {payload[:240]}"
            return (
                f"No active goal for `{agent_id}`. Use `/goal <description>` once CA3 ships, "
                "or configure goals under workspace/coding_agents/goals/."
            )
        loop_match = _LOOP_RE.match(stripped)
        if loop_match:
            action = (loop_match.group(1) or "").strip().lower()
            if action == "start":
                self._loop_active.add(agent_id)
                return f"ALRCA loop marked running for `{agent_id}` (stub until CA3 worker)."
            if action == "stop":
                self._loop_active.discard(agent_id)
                return f"ALRCA loop stopped for `{agent_id}`."
            state = "running" if agent_id in self._loop_active else "stopped"
            return f"ALRCA loop is {state} for `{agent_id}`. Use `/loop start` or `/loop stop`."
        return None

    def _handle_conversational(self, agent_id: str, text: str) -> str:
        """Return a conversational reply for non-command operator chat.

        Args:
            agent_id (str): Matched agent registry id.
            text (str): Operator message body.

        Returns:
            str: Agent-facing reply text.

        Examples:
            >>> from sevn.agent.tracing.sink import NullTraceSink
            >>> r = CodingAgentRouter(workspace=WorkspaceConfig.minimal(), trace=NullTraceSink())
            >>> "ALRCA" in r._handle_conversational("a", "hello")
            True
        """
        agent = self._agent_config(agent_id)
        if agent is not None and agent.type == "litellm_lap":
            lap_id = agent.lap_agent_id or "(unset lap_agent_id)"
            return (
                f"LAP passthrough for `{agent_id}` → `{lap_id}` (HTTP client ships in CA5). "
                f"You wrote: {text.strip()[:500]}"
            )
        return (
            f"ALRCA agent `{agent_id}` received your message. "
            "Long-running loop + executors ship in CA3/CA4. "
            f"Try `/status`, `/goal`, or `/loop start|stop`. "
            f"You wrote: {text.strip()[:500]}"
        )

    async def handle_operator_message(
        self,
        msg: IncomingMessage,
        *,
        agent_id: str,
        session_id: str,
        correlation_id: str,
        adapter: ChannelAdapter | None,
    ) -> None:
        """Handle bound-topic operator traffic without Triager dispatch.

        Args:
            msg (IncomingMessage): Inbound envelope.
            agent_id (str): Matched coding agent id.
            session_id (str): Gateway session id for the binding scope.
            correlation_id (str): Turn correlation id for traces.
            adapter (ChannelAdapter | None): Channel adapter for outbound send.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CodingAgentRouter.handle_operator_message)
            True
        """
        await self._emit(
            kind="coding_agent.operator_message",
            session_id=session_id,
            turn_id=correlation_id,
            status="started",
            attrs={"agent_id": agent_id, "channel": msg.channel},
        )
        agent = self._agent_config(agent_id)
        agent_type = agent.type if agent is not None else "alrca"
        reply: str | None = None
        if agent_type == "alrca":
            reply = self._handle_alrca_command(agent_id, msg.text)
        if reply is None:
            reply = self._handle_conversational(agent_id, msg.text)
        if adapter is not None:
            try:
                from sevn.gateway.channel_router import OutgoingMessage, _telegram_reply_metadata

                tg_meta = _telegram_reply_metadata(msg)
                out_meta = dict(tg_meta)
                mid = msg.metadata.get("message_id") if isinstance(msg.metadata, dict) else None
                if isinstance(mid, int):
                    out_meta["reply_to_message_id"] = mid
                await adapter.send(
                    OutgoingMessage(
                        channel=msg.channel,
                        user_id=msg.user_id,
                        text=reply,
                        session_id=session_id,
                        metadata=out_meta,
                    ),
                )
            except Exception:
                logger.exception(
                    "coding_agent_reply_failed agent_id={} channel={}",
                    agent_id,
                    msg.channel,
                )
        await self._emit(
            kind="coding_agent.operator_message",
            session_id=session_id,
            turn_id=correlation_id,
            status="completed",
            attrs={"agent_id": agent_id, "agent_type": agent_type},
        )


__all__ = ["CodingAgentRouter"]
