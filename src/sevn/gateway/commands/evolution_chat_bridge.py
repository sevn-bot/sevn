"""Natural-language evolution issue-fix bridge (`plan/full-loop-evolution-wave-plan.md` FL-4B).

Detects phrases like "fix issue #42", "fix evolution abc-1", "implement feature xyz" from
natural-language (no slash prefix) owner messages and drives the **chat executor track**:

  1. Resolve or import the evolution issue (FL-4B.1).
  2. If ``plan_approval.enabled``, the pipeline allocates a worktree, dispatches the plan
     via the existing PlanGate approval loop (FL-2), and blocks until the operator approves.
     On approval, ``run_pipeline(stage="implement", executor="chat")`` runs tier-B implement
     + CI + promote (FL-4B.2).
  3. If ``plan_approval`` is disabled (or the issue is already beyond the plan stage),
     ``run_pipeline(executor="chat")`` falls through immediately to implement + CI + promote.

**Layering note (FL-4B adaptation):** ``evolution/`` must not import ``gateway/``.
Gateway-coupled orchestration (PlanGate dispatch via ``_run_cd_dispatch``) therefore lives
here in the bridge, NOT inside ``evolution/pipeline_runner.py``.  ``pipeline_runner.py``
remains gateway-free; the bridge is the sole gateway→evolution choreographer for the chat
track.

Module: sevn.gateway.commands.evolution_chat_bridge
Depends: sevn.evolution.github_sync, sevn.evolution.pipeline_runner,
    sevn.evolution.issues, sevn.evolution.pipeline_common,
    sevn.agent.triager.routing_policy (for intent detection)

Exports:
    EvolutionChatBridge — natural-language "fix issue" pre-LLM interceptor.

Private:
    _parse_evolution_phrase — extract (kind, id_or_number) from a matched phrase.
    _is_github_number — True when the identifier looks like a bare GitHub number.
"""

from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING

from loguru import logger

from sevn.agent.triager.routing_policy import is_evolution_fix_intent_message
from sevn.evolution.issues import get_issue
from sevn.evolution.pipeline_common import PipelineBlockedError
from sevn.evolution.pipeline_runner import run_pipeline
from sevn.runtime.background_tasks import spawn_logged

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.evolution.events import EvolutionIssueEventFanoutFn
    from sevn.evolution.issues import EvolutionIssue
    from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
    from sevn.workspace.layout import WorkspaceLayout


# ---------------------------------------------------------------------------
# Phrase parsing helpers
# ---------------------------------------------------------------------------

# Captures (optional "github ") "issue #42" → group 1 = "42"
_ISSUE_NUMBER_RE: re.Pattern[str] = re.compile(
    r"\bfix\s+(?:github\s+)?issue\s+#?(\d+)\b",
    re.I,
)
# "fix evolution <id>" → group 1 = id
_EVOLUTION_ID_RE: re.Pattern[str] = re.compile(
    r"\bfix\s+evolution\s+(\S+)\b",
    re.I,
)
# "implement feature/issue <id-or-number>" → group 1 = id
_IMPLEMENT_RE: re.Pattern[str] = re.compile(
    r"\bimplement\s+(?:feature|issue)\s+#?(\S+)\b",
    re.I,
)
# "work on issue/bug/feature <id>" → group 1 = id
_WORK_ON_RE: re.Pattern[str] = re.compile(
    r"\bwork\s+on\s+(?:issue|bug|feature)\s+#?(\S+)\b",
    re.I,
)
# "implement #42" → group 1 = "42"
_IMPLEMENT_NUM_RE: re.Pattern[str] = re.compile(
    r"\bimplement\s+#(\d+)\b",
    re.I,
)


def _parse_evolution_phrase(text: str) -> str | None:
    """Extract the issue id or GitHub number string from a matched evolution phrase.

    Args:
        text (str): User message text.

    Returns:
        str | None: Extracted identifier (local id string or GitHub number string),
            or ``None`` when not parseable.

    Examples:
        >>> _parse_evolution_phrase("fix issue #42")
        '42'
        >>> _parse_evolution_phrase("fix evolution abc-123")
        'abc-123'
        >>> _parse_evolution_phrase("implement feature xyz-1")
        'xyz-1'
        >>> _parse_evolution_phrase("implement #99")
        '99'
        >>> _parse_evolution_phrase("hello") is None
        True
    """
    for pattern in (
        _ISSUE_NUMBER_RE,
        _EVOLUTION_ID_RE,
        _IMPLEMENT_RE,
        _WORK_ON_RE,
        _IMPLEMENT_NUM_RE,
    ):
        m = pattern.search(text)
        if m:
            return m.group(1)
    return None


def _is_github_number(identifier: str) -> bool:
    """Return True when the identifier looks like a bare GitHub issue number.

    Args:
        identifier (str): Parsed identifier from the phrase.

    Returns:
        bool: True for pure digit strings (e.g. "42").

    Examples:
        >>> _is_github_number("42")
        True
        >>> _is_github_number("abc-1")
        False
    """
    return identifier.isdigit()


# ---------------------------------------------------------------------------
# Bridge class
# ---------------------------------------------------------------------------


class EvolutionChatBridge:
    """Natural-language "fix issue" pre-LLM interceptor (FL-4B).

    Wired by ``build_agent_run_turn`` alongside :class:`EvolutionCommandHandler`; called
    from the ``_route_incoming_with_menu`` patch before the LLM turn is dispatched.  When
    matched, the bridge handles the turn entirely (no LLM needed) and returns a status
    string; the gateway sends it to the user and short-circuits the agent turn.

    The bridge is owner-only (same check as evolution slash commands).
    """

    def __init__(
        self,
        *,
        workspace: WorkspaceConfig,
        layout: WorkspaceLayout,
        router: ChannelRouter,
        conn: sqlite3.Connection,
        fanout: EvolutionIssueEventFanoutFn | None = None,
    ) -> None:
        """Bind gateway context.

        Args:
            workspace (WorkspaceConfig): Parsed workspace config.
            layout (WorkspaceLayout): Workspace filesystem layout.
            router (ChannelRouter): Channel router for owner checks.
            conn (sqlite3.Connection): Workspace SQLite.
            fanout (EvolutionIssueEventFanoutFn | None): Optional event fan-out.

        Examples:
            >>> EvolutionChatBridge.__name__
            'EvolutionChatBridge'
        """
        self._workspace = workspace
        self._layout = layout
        self._router = router
        self._conn = conn
        self._fanout = fanout

    def matches_nl(self, msg: IncomingMessage) -> bool:
        """Return True when *msg* is a natural-language evolution fix intent.

        Matches phrases like "fix issue #42", "fix evolution abc-1",
        "implement feature xyz".  Slash commands (``/fix``, ``/feature``) are
        handled by :class:`EvolutionCommandHandler` and are NOT matched here.

        Args:
            msg (IncomingMessage): Inbound message.

        Returns:
            bool: True for matched natural-language evolution-fix phrases.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> b = EvolutionChatBridge.__new__(EvolutionChatBridge)
            >>> b.matches_nl(IncomingMessage(channel="telegram", user_id="1", text="fix issue #42"))
            True
            >>> b.matches_nl(IncomingMessage(channel="telegram", user_id="1", text="/fix abc"))
            False
            >>> b.matches_nl(IncomingMessage(channel="telegram", user_id="1", text="hello"))
            False
        """
        text = (msg.text or "").strip()
        if text.startswith("/"):
            # Slash commands go to EvolutionCommandHandler.
            return False
        return is_evolution_fix_intent_message(text)

    async def handle(self, msg: IncomingMessage, *, session_id: str) -> str | None:
        """Handle one natural-language evolution fix request.

        Flow (FL-4B.1 / FL-4B.2):
        1. Owner check.
        2. Parse identifier → resolve local issue or import from GitHub.
        3. Fire-and-forget ``run_pipeline(executor="chat")`` so the gateway's
           poll loop does not block.
        4. Return a user-visible status line.

        When ``plan_approval.enabled``, ``run_pipeline`` will progress the issue
        through the allocation + plan stages, raise ``PipelineBlockedError`` at
        ``awaiting_approval`` (the operator approves via the existing PlanGate
        Telegram callback / MC button), and the resume caller (FL-2 wiring) calls
        ``run_pipeline(stage="implement")`` to complete the implement+CI+promote
        sequence.

        Args:
            msg (IncomingMessage): Inbound natural-language message.
            session_id (str): Gateway session id.

        Returns:
            str | None: User-visible status line, or ``None`` when the bridge
                decides not to handle this message (should not happen after
                ``matches_nl`` returns True).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(EvolutionChatBridge.handle)
            True
        """
        if not self._router._resolve_owner_flag(msg):
            return "Evolution commands are owner-only."

        text = (msg.text or "").strip()
        identifier = _parse_evolution_phrase(text)
        if not identifier:
            # matches_nl said True but we can't extract an id — fall through.
            return None

        # Step 1: resolve or import the issue.
        issue = await self._resolve_issue(identifier)
        if issue is None:
            return (
                f"Evolution issue `{identifier}` not found locally "
                "and could not be imported (no GitHub config or not a number)."
            )

        # Step 2: fire-and-forget run_pipeline(executor="chat").
        # The pipeline will allocate a worktree, run spec-kit/plan (blocking on
        # PlanGate when enabled), then implement + CI + promote.  We don't await
        # here so the operator gets an immediate ack and the poll loop stays free.
        spawn_logged(
            self._run_pipeline_safe(issue_id=issue.id, session_id=session_id),
            label="evolution_pipeline_resume",
            name=f"evolution-chat-{issue.id}",
        )

        stage = issue.pipeline_stage or issue.state or "open"
        plan_note = (
            " Plan will be submitted for your approval before implementation starts."
            if getattr(self._workspace.plan_approval, "enabled", False)
            else ""
        )
        return (
            f"Chat-track pipeline started for `{issue.id}` [{issue.kind}] "
            f'"{issue.title}" (current stage: {stage}).{plan_note}'
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _resolve_issue(self, identifier: str) -> EvolutionIssue | None:
        """Return the local EvolutionIssue, importing from GitHub when needed.

        Args:
            identifier (str): Local issue id string OR bare GitHub number (digits only).

        Returns:
            EvolutionIssue | None: Resolved issue, or ``None`` on failure.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(EvolutionChatBridge._resolve_issue)
            True
        """
        # Try local look-up first (works for both local ids and if the issue
        # was previously imported).
        local = get_issue(self._layout, identifier)
        if local is not None:
            return local

        # If identifier looks like a GitHub number, try to import it.
        if _is_github_number(identifier):
            return await self._import_github(int(identifier))

        # Unknown id.
        return None

    async def _import_github(self, number: int) -> EvolutionIssue | None:
        """Import one GitHub issue by number, if GitHub integration is configured.

        Args:
            number (int): GitHub issue number.

        Returns:
            EvolutionIssue | None: Imported issue, or ``None`` when GitHub is not
                configured or the import fails.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(EvolutionChatBridge._import_github)
            True
        """
        repo = _repo_slug(self._workspace)
        if not repo:
            logger.info(
                "evolution_chat_bridge: no github repo configured — cannot import issue #{}",
                number,
            )
            return None

        try:
            from sevn.evolution.github_sync import import_github_issue
            from sevn.integrations.github_skill.hooks import resolve_github_skill_hooks

            hooks = resolve_github_skill_hooks(self._workspace)
            return await import_github_issue(
                self._layout,
                hooks,
                repo=repo,
                number=number,
                ws=self._workspace,
            )
        except Exception:
            logger.exception(
                "evolution_chat_bridge: failed to import GitHub issue #{}",
                number,
            )
            return None

    async def _run_pipeline_safe(self, *, issue_id: str, session_id: str) -> None:
        """Run the chat-executor pipeline, swallowing PipelineBlockedError.

        ``PipelineBlockedError`` is the expected terminal state when PlanGate is
        enabled — the pipeline stops at ``awaiting_approval`` and the FL-2 resume
        wiring picks it up after the operator approves.

        Args:
            issue_id (str): Evolution issue id.
            session_id (str): Gateway session id.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(EvolutionChatBridge._run_pipeline_safe)
            True
        """
        try:
            await run_pipeline(
                self._conn,
                self._workspace,
                self._layout,
                issue_id,
                executor="chat",
                session_key=session_id,
                fanout=self._fanout,
            )
        except PipelineBlockedError as exc:
            # Expected when plan_approval is enabled; operator will approve via
            # PlanGate callback and FL-2 resume wiring will call run_pipeline again
            # with stage="implement".
            logger.info(
                "evolution_chat_bridge: issue {} blocked for approval: {}",
                issue_id,
                exc,
            )
        except Exception:
            logger.exception(
                "evolution_chat_bridge: pipeline error for issue {}",
                issue_id,
            )


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _repo_slug(workspace: WorkspaceConfig) -> str:
    """Extract the ``owner/repo`` slug from workspace config.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.

    Returns:
        str: ``owner/repo`` slug, or empty string when not configured.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _repo_slug(WorkspaceConfig.minimal())
        ''
    """
    my_sevn = getattr(workspace, "my_sevn", None)
    if my_sevn is None:
        return ""
    # my_sevn.repo_url = "https://github.com/owner/repo" or "owner/repo"
    repo_url = getattr(my_sevn, "repo_url", "") or ""
    if not repo_url:
        return ""
    # Strip protocol prefix if present.
    if "github.com/" in repo_url:
        parts = repo_url.split("github.com/", 1)
        slug = parts[1].rstrip("/")
        return slug  # noqa: RET504
    # Already in "owner/repo" form.
    if "/" in repo_url:
        return repo_url.rstrip("/")
    return ""


__all__ = ["EvolutionChatBridge"]
