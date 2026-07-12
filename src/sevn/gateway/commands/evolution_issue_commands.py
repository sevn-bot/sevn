"""Owner-only ``/file_issue`` slash command (`specs/35-bot-evolution.md` §2.9).

Module: sevn.gateway.commands.evolution_issue_commands
Depends: sevn.evolution.issues

Exports:
    FileIssueCommandHandler — file a bug/feature issue from chat without the LLM.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sevn.evolution.issues import create_issue, maybe_mirror_issue_to_github

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
    from sevn.workspace.layout import WorkspaceLayout

IssueKind = Literal["bug", "feature"]


class FileIssueCommandHandler:
    """Handle ``/file_issue`` before the LLM pipeline."""

    def __init__(
        self,
        *,
        workspace: WorkspaceConfig,
        layout: WorkspaceLayout,
        router: ChannelRouter,
    ) -> None:
        """Bind workspace context for issue filing.

        Args:
            workspace (WorkspaceConfig): Parsed workspace config.
            layout (WorkspaceLayout): Resolved layout.
            router (ChannelRouter): Channel router for owner checks.

        Examples:
            >>> FileIssueCommandHandler.__name__
            'FileIssueCommandHandler'
        """
        self._workspace = workspace
        self._layout = layout
        self._router = router

    def matches_slash(self, msg: IncomingMessage) -> bool:
        """Return whether *msg* is ``/file_issue``.

        Args:
            msg (IncomingMessage): Inbound message.

        Returns:
            bool: ``True`` for the file-issue slash command.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> h = FileIssueCommandHandler.__new__(FileIssueCommandHandler)
            >>> h.matches_slash(
            ...     IncomingMessage(channel="telegram", user_id="1", text="/file_issue"),
            ... )
            True
        """
        text = (msg.text or "").strip().lower()
        return text == "/file_issue" or text.startswith("/file_issue ")

    async def handle(self, msg: IncomingMessage, *, session_id: str) -> str | None:
        """Create one evolution issue for the owner.

        Args:
            msg (IncomingMessage): Inbound slash command.
            session_id (str): Active gateway session id.

        Returns:
            str | None: User-visible status line.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(FileIssueCommandHandler.handle)
            True
        """
        _ = session_id
        if not self._router._resolve_owner_flag(msg):
            return "Issue filing is owner-only."
        kind, title, body = _parse_file_issue_args(msg.text or "")
        if kind is None or not title:
            return (
                "Usage: /file_issue <bug|feature> <title>\n"
                "Optional body: add lines after the title on following messages is not supported; "
                "include details in the title or use Mission Control → Evolution → Issues."
            )
        issue = create_issue(
            self._layout,
            kind=kind,
            title=title,
            body=body,
            source="telegram",
            ws=self._workspace,
        )
        issue = await maybe_mirror_issue_to_github(self._layout, issue, self._workspace)
        gh = issue.github or {}
        gh_note = ""
        if gh.get("number") is not None:
            gh_note = f" GitHub #{gh['number']}."
        return f"Filed {issue.kind} issue `{issue.id}`: {issue.title}.{gh_note}"


def _parse_file_issue_args(text: str) -> tuple[IssueKind | None, str, str]:
    """Parse ``/file_issue <kind> <title>`` arguments.

    Args:
        text (str): Raw inbound message text.

    Returns:
        tuple[IssueKind | None, str, str]: Kind, title, and body (body always empty for slash).

    Examples:
        >>> _parse_file_issue_args("/file_issue bug Login fails on Safari")
        ('bug', 'Login fails on Safari', '')
        >>> _parse_file_issue_args("/file_issue")
        (None, '', '')
    """
    raw = text.strip()
    if not raw.lower().startswith("/file_issue"):
        return None, "", ""
    rest = raw[len("/file_issue") :].strip()
    if not rest:
        return None, "", ""
    parts = rest.split(None, 1)
    kind_raw = parts[0].lower()
    if kind_raw not in ("bug", "feature"):
        return None, "", ""
    title = parts[1].strip() if len(parts) > 1 else ""
    kind: IssueKind = "bug" if kind_raw == "bug" else "feature"
    return kind, title, ""


__all__ = ["FileIssueCommandHandler"]
