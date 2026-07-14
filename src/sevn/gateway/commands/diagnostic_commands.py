"""Owner-only ``/logs`` and ``/traces`` slash commands (`specs/17-gateway.md` §2.9, §10.14 TE-3).

Module: sevn.gateway.commands.diagnostic_commands
Depends: sevn.agent.tracing.sink_factory, sevn.gateway.diagnostics.diagnostics

Exports:
    DiagnosticCommandHandler — owner-gated `/logs` / `/traces` slash dispatcher.

Examples:
    >>> from sevn.gateway.commands.diagnostic_commands import DiagnosticCommandHandler
    >>> DiagnosticCommandHandler.__name__
    'DiagnosticCommandHandler'
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sevn.agent.tracing.sink_factory import trace_redaction_policy_for
from sevn.gateway.diagnostics.diagnostics import (
    format_for_telegram,
    format_traces_for_telegram,
    get_span,
    recent_traces,
    tail_service_log,
)

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
    from sevn.workspace.layout import WorkspaceLayout

OWNER_ONLY_REFUSAL = "Diagnostic commands are owner-only."

DEFAULT_TAIL_LINES = 50
MAX_TAIL_LINES = 200
DEFAULT_TRACES_LIMIT = 20
MAX_TRACES_LIMIT = 100

USAGE_LOGS = (
    "Usage:\n  /logs tail <gateway|proxy> [N]\n  /logs grep <pattern> [N]   # not yet implemented"
)
USAGE_TRACES = "Usage:\n  /traces recent [N]\n  /traces span <span_id>"


class DiagnosticCommandHandler:
    """Handle ``/logs`` and ``/traces`` outside the agent turn."""

    def __init__(
        self,
        *,
        workspace: WorkspaceConfig,
        layout: WorkspaceLayout,
        router: ChannelRouter,
    ) -> None:
        """Bind workspace context for diagnostic commands.

        Args:
            workspace (WorkspaceConfig): Parsed workspace config (read for
                ``tracing.redaction``).
            layout (WorkspaceLayout): Resolved workspace layout (anchors log
                + trace paths).
            router (ChannelRouter): Channel router for owner checks.

        Examples:
            >>> DiagnosticCommandHandler.__name__
            'DiagnosticCommandHandler'
        """
        self._workspace = workspace
        self._layout = layout
        self._router = router

    def matches_slash(self, msg: IncomingMessage) -> bool:
        """Return whether ``msg`` is a ``/logs`` or ``/traces`` slash command.

        Args:
            msg (IncomingMessage): Inbound message.

        Returns:
            bool: ``True`` for ``/logs`` / ``/traces`` (bare or with args).

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> h = DiagnosticCommandHandler.__new__(DiagnosticCommandHandler)
            >>> h.matches_slash(
            ...     IncomingMessage(channel="telegram", user_id="1", text="/logs tail gateway"),
            ... )
            True
            >>> h.matches_slash(
            ...     IncomingMessage(channel="telegram", user_id="1", text="/traces"),
            ... )
            True
            >>> h.matches_slash(
            ...     IncomingMessage(channel="telegram", user_id="1", text="/help"),
            ... )
            False
        """
        text = (msg.text or "").strip().lower()
        if text in ("/logs", "/traces"):
            return True
        return text.startswith(("/logs ", "/traces "))

    async def handle(
        self,
        msg: IncomingMessage,
        *,
        session_id: str,
    ) -> list[str]:
        """Dispatch one diagnostic slash command and return chunked reply text.

        Owner check runs **before** any file or database read so non-owners
        never touch operator state. The returned chunks are pre-formatted as
        ``<pre>`` blocks (UTF-16 chunked); the caller delivers them via the
        channel adapter without an agent turn.

        Args:
            msg (IncomingMessage): Inbound slash command.
            session_id (str): Active gateway session id (unused; kept for the
                handler signature shared with other command handlers).

        Returns:
            list[str]: Reply chunks (always non-empty). A short refusal is
            returned (as a one-element list) for non-owners.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(DiagnosticCommandHandler.handle)
            True
        """
        _ = session_id
        if not self._router._resolve_owner_flag(msg):
            return [OWNER_ONLY_REFUSAL]
        text = (msg.text or "").strip()
        lowered = text.lower()
        if lowered == "/logs" or lowered.startswith("/logs "):
            return self._handle_logs(text)
        if lowered == "/traces" or lowered.startswith("/traces "):
            return self._handle_traces(text)
        return [OWNER_ONLY_REFUSAL]

    def _handle_logs(self, text: str) -> list[str]:
        """Dispatch ``/logs tail|grep`` subcommands.

        Args:
            text (str): Raw message body (leading ``/logs`` preserved).

        Returns:
            list[str]: Reply chunks (usage or ``<pre>``-wrapped tail output).

        Examples:
            >>> DiagnosticCommandHandler._handle_logs.__name__
            '_handle_logs'
        """
        parts = text.split()
        if len(parts) < 2:
            return [USAGE_LOGS]
        sub = parts[1].lower()
        if sub == "tail":
            return self._handle_logs_tail(parts[2:])
        if sub == "grep":
            return ["/logs grep is not implemented yet — use the dashboard for regex filtering."]
        return [USAGE_LOGS]

    def _handle_logs_tail(self, args: list[str]) -> list[str]:
        """Tail ``gateway`` or ``proxy`` logs and wrap them in ``<pre>`` chunks.

        Args:
            args (list[str]): Tokens after ``/logs tail`` (``<service> [N]``).

        Returns:
            list[str]: ``<pre>``-wrapped redacted tail chunks.

        Examples:
            >>> DiagnosticCommandHandler._handle_logs_tail.__name__
            '_handle_logs_tail'
        """
        if not args:
            return [USAGE_LOGS]
        service = args[0].strip().lower()
        if service not in ("gateway", "proxy"):
            return [USAGE_LOGS]
        lines = DEFAULT_TAIL_LINES
        if len(args) >= 2:
            try:
                lines = max(1, min(MAX_TAIL_LINES, int(args[1])))
            except ValueError:
                lines = DEFAULT_TAIL_LINES
        try:
            tail = tail_service_log(service, lines, self._layout)
        except ValueError as exc:
            return [f"Error: {exc}"]
        policy = trace_redaction_policy_for(self._workspace)
        if not tail:
            return [f"<pre>(no entries for {service})</pre>"]
        return format_for_telegram(tail, redaction=policy)

    def _handle_traces(self, text: str) -> list[str]:
        """Dispatch ``/traces recent|span`` subcommands.

        Args:
            text (str): Raw message body (leading ``/traces`` preserved).

        Returns:
            list[str]: Reply chunks (usage or formatted trace output).

        Examples:
            >>> DiagnosticCommandHandler._handle_traces.__name__
            '_handle_traces'
        """
        parts = text.split()
        if len(parts) < 2:
            return [USAGE_TRACES]
        sub = parts[1].lower()
        if sub == "recent":
            return self._handle_traces_recent(parts[2:])
        if sub == "span":
            return self._handle_traces_span(parts[2:])
        return [USAGE_TRACES]

    def _handle_traces_recent(self, args: list[str]) -> list[str]:
        """Return the most-recent trace rows formatted for Telegram.

        Args:
            args (list[str]): Tokens after ``/traces recent`` (``[N]``).

        Returns:
            list[str]: ``<pre>``-wrapped chunks.

        Examples:
            >>> DiagnosticCommandHandler._handle_traces_recent.__name__
            '_handle_traces_recent'
        """
        limit = DEFAULT_TRACES_LIMIT
        if args:
            try:
                limit = max(1, min(MAX_TRACES_LIMIT, int(args[0])))
            except ValueError:
                limit = DEFAULT_TRACES_LIMIT
        policy = trace_redaction_policy_for(self._workspace)
        spans = recent_traces(self._layout, limit=limit, policy=policy)
        if not spans:
            return ["<pre>(no traces yet)</pre>"]
        return format_traces_for_telegram(spans, redaction=policy)

    def _handle_traces_span(self, args: list[str]) -> list[str]:
        """Return one span tree by id.

        Args:
            args (list[str]): Tokens after ``/traces span`` (``<span_id>``).

        Returns:
            list[str]: ``<pre>``-wrapped chunks or a not-found message.

        Examples:
            >>> DiagnosticCommandHandler._handle_traces_span.__name__
            '_handle_traces_span'
        """
        if not args:
            return [USAGE_TRACES]
        span_id = args[0].strip()
        policy = trace_redaction_policy_for(self._workspace)
        span = get_span(self._layout, span_id, policy=policy)
        if span is None:
            return [f"Span `{span_id}` not found."]
        return format_traces_for_telegram([span], redaction=policy)


__all__ = ["OWNER_ONLY_REFUSAL", "DiagnosticCommandHandler"]
