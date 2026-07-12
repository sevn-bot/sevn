"""Owner-only evolution slash commands (`specs/35-bot-evolution.md` §2.9).

Module: sevn.gateway.commands.evolution_commands
Depends: sevn.evolution.issues, sevn.evolution.pipeline_common,
    sevn.evolution.pipeline_runner

Exports:
    EvolutionCommandHandler — ``/issue``, ``/fix``, ``/feature`` owner commands.

Private:
    _command_arg — parse first argument after a slash command prefix.
    _parse_live_flag — detect ``--live`` in command text.
    _parse_executor_flag — extract ``--executor=<value>`` from command text.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Literal

from sevn.evolution.issues import get_issue, list_issues
from sevn.evolution.pipeline_common import PipelineBlockedError
from sevn.evolution.pipeline_runner import run_pipeline

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.evolution.events import EvolutionIssueEventFanoutFn
    from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
    from sevn.workspace.layout import WorkspaceLayout


class EvolutionCommandHandler:
    """Handle ``/issue``, ``/fix``, and ``/feature`` before the LLM pipeline."""

    def __init__(
        self,
        *,
        workspace: WorkspaceConfig,
        layout: WorkspaceLayout,
        router: ChannelRouter,
        conn: sqlite3.Connection,
        fanout: EvolutionIssueEventFanoutFn | None = None,
    ) -> None:
        """Bind workspace context for evolution commands.

        Args:
            workspace (WorkspaceConfig): Parsed workspace config.
            layout (WorkspaceLayout): Resolved layout.
            router (ChannelRouter): Channel router for owner checks.
            conn (sqlite3.Connection): Workspace SQLite for cloud routing.
            fanout (EvolutionIssueEventFanoutFn | None): Optional pipeline event fan-out.

        Examples:
            >>> EvolutionCommandHandler.__name__
            'EvolutionCommandHandler'
        """
        self._workspace = workspace
        self._layout = layout
        self._router = router
        self._conn = conn
        self._fanout = fanout

    def matches_slash(self, msg: IncomingMessage) -> bool:
        """Return whether *msg* is an evolution owner slash command.

        Args:
            msg (IncomingMessage): Inbound message.

        Returns:
            bool: ``True`` for ``/issue``, ``/fix``, or ``/feature``.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> h = EvolutionCommandHandler.__new__(EvolutionCommandHandler)
            >>> h.matches_slash(
            ...     IncomingMessage(channel="telegram", user_id="1", text="/fix abc"),
            ... )
            True
        """
        text = (msg.text or "").strip().lower()
        return text.startswith(("/issue", "/fix", "/feature"))

    async def handle(self, msg: IncomingMessage, *, session_id: str) -> str | None:
        """Dispatch one evolution slash command.

        Args:
            msg (IncomingMessage): Inbound slash command.
            session_id (str): Active gateway session id.

        Returns:
            str | None: User-visible status line.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(EvolutionCommandHandler.handle)
            True
        """
        if not self._router._resolve_owner_flag(msg):
            return "Evolution commands are owner-only."
        text = (msg.text or "").strip()
        lowered = text.lower()
        if lowered.startswith("/issue"):
            return self._handle_issue(text)
        if lowered.startswith("/fix"):
            return await self._handle_fix(text, session_id=session_id)
        if lowered.startswith("/feature"):
            return await self._handle_feature(text, session_id=session_id)
        return None

    def _handle_issue(self, text: str) -> str:
        """Show one issue or a short list.

        Args:
            text (str): Raw message text.

        Returns:
            str: Status summary.

        Examples:
            >>> EvolutionCommandHandler._handle_issue.__name__
            '_handle_issue'
        """
        parts = text.split(None, 1)
        if len(parts) < 2 or not parts[1].strip():
            rows = list_issues(self._layout, limit=5)
            if not rows:
                return "No evolution issues filed yet."
            lines = [f"- `{row.id}` [{row.kind}] {row.title} ({row.state})" for row in rows]
            return "Recent issues:\n" + "\n".join(lines)
        issue_id = parts[1].strip().split()[0]
        issue = get_issue(self._layout, issue_id)
        if issue is None:
            return f"Issue `{issue_id}` not found."
        stage = issue.pipeline_stage or issue.state
        approval = f" approval={issue.approval_id}" if issue.approval_id else ""
        return (
            f"Issue `{issue.id}` [{issue.kind}] {issue.title}\n"
            f"state={issue.state} stage={stage}{approval}"
        )

    async def _handle_fix(self, text: str, *, session_id: str) -> str:
        """Run the bug pipeline for one issue id.

        Supports ``--live`` (all dry-run flags false) and
        ``--executor=local|cloud|chat`` (``cloud`` maps to ``cursor_cloud``).

        Args:
            text (str): Raw ``/fix`` message.
            session_id (str): Gateway session id.

        Returns:
            str: Outcome message.

        Examples:
            >>> EvolutionCommandHandler._handle_fix.__name__
            '_handle_fix'
        """
        live = _parse_live_flag(text)
        executor = _parse_executor_flag(text)
        issue_id = _command_arg(text, "/fix")
        if not issue_id:
            return "Usage: /fix <issue-id> [--live] [--executor=local|cloud|chat]"
        dry: bool | None = False if live else None
        try:
            issue = await run_pipeline(
                self._conn,
                self._workspace,
                self._layout,
                issue_id,
                executor=executor,
                session_key=session_id,
                fanout=self._fanout,
                ci_dry_run=dry,
                promotion_dry_run=dry,
                spec_kit_dry_run=dry,
            )
        except PipelineBlockedError as exc:
            return str(exc)
        except Exception as exc:
            return f"Bug pipeline failed: {exc}"
        live_note = " (live)" if live else ""
        exec_note = f" executor={executor}" if executor else ""
        return f"Bug pipeline for `{issue.id}` finished with state={issue.state}{live_note}{exec_note}."

    async def _handle_feature(self, text: str, *, session_id: str) -> str:
        """Run the feature pipeline for one issue id.

        Supports ``--live`` (all dry-run flags false) and
        ``--executor=local|cloud|chat`` (``cloud`` maps to ``cursor_cloud``).

        Args:
            text (str): Raw ``/feature`` message.
            session_id (str): Gateway session id.

        Returns:
            str: Outcome message.

        Examples:
            >>> EvolutionCommandHandler._handle_feature.__name__
            '_handle_feature'
        """
        live = _parse_live_flag(text)
        executor = _parse_executor_flag(text)
        issue_id = _command_arg(text, "/feature")
        if not issue_id:
            return "Usage: /feature <issue-id> [--live] [--executor=local|cloud|chat]"
        dry: bool | None = False if live else None
        try:
            issue = await run_pipeline(
                self._conn,
                self._workspace,
                self._layout,
                issue_id,
                executor=executor,
                session_key=session_id,
                fanout=self._fanout,
                ci_dry_run=dry,
                promotion_dry_run=dry,
                spec_kit_dry_run=dry,
            )
        except PipelineBlockedError as exc:
            return str(exc)
        except Exception as exc:
            return f"Feature pipeline failed: {exc}"
        live_note = " (live)" if live else ""
        exec_note = f" executor={executor}" if executor else ""
        return f"Feature pipeline for `{issue.id}` finished with state={issue.state}{live_note}{exec_note}."


def _command_arg(text: str, prefix: str) -> str:
    """Return the first non-flag argument after a slash command prefix.

    Args:
        text (str): Raw message.
        prefix (str): Command prefix such as ``/fix``.

    Returns:
        str: Issue id or empty string.

    Examples:
        >>> _command_arg("/fix abc123 extra", "/fix")
        'abc123'
        >>> _command_arg("/fix", "/fix")
        ''
        >>> _command_arg("/fix abc123 --live", "/fix")
        'abc123'
    """
    raw = text.strip()
    if not raw.lower().startswith(prefix):
        return ""
    rest = raw[len(prefix) :].strip()
    if not rest:
        return ""
    for token in rest.split():
        if not token.startswith("--"):
            return token
    return ""


def _parse_live_flag(text: str) -> bool:
    r"""Return ``True`` when ``--live`` appears anywhere in ``text``.

    Args:
        text (str): Raw command text.

    Returns:
        bool: ``True`` when ``--live`` is present.

    Examples:
        >>> _parse_live_flag("/fix abc123 --live")
        True
        >>> _parse_live_flag("/fix abc123")
        False
    """
    return "--live" in text.split()


def _parse_executor_flag(
    text: str,
) -> Literal["local", "cursor_cloud", "chat"] | None:
    r"""Return the executor override from ``--executor=<value>`` in ``text``.

    Maps the shorthand ``cloud`` to ``cursor_cloud`` so operators can type
    ``--executor=cloud`` instead of the full provider name.  Returns ``None``
    when no ``--executor`` token is present or the value is unrecognised.

    Args:
        text (str): Raw command text.

    Returns:
        Literal["local", "cursor_cloud", "chat"] | None: Normalised executor
            string, or ``None`` when absent.

    Examples:
        >>> _parse_executor_flag("/fix abc --executor=local")
        'local'
        >>> _parse_executor_flag("/fix abc --executor=cloud")
        'cursor_cloud'
        >>> _parse_executor_flag("/fix abc --executor=chat")
        'chat'
        >>> _parse_executor_flag("/fix abc") is None
        True
    """
    _EXECUTOR_MAP: dict[str, str] = {"cloud": "cursor_cloud"}
    _VALID: frozenset[str] = frozenset({"local", "cursor_cloud", "chat"})
    for token in text.split():
        if token.startswith("--executor="):
            raw = token[len("--executor=") :]
            normalised = _EXECUTOR_MAP.get(raw, raw)
            if normalised in _VALID:
                return normalised  # type: ignore[return-value]
    return None


__all__ = ["EvolutionCommandHandler"]
