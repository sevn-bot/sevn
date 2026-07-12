"""Shared evolution pipeline helpers (`specs/35-bot-evolution.md` §4).

Module: sevn.evolution.pipeline_common
Depends: sevn.evolution.events, sevn.evolution.issues, sevn.evolution.pipelines

Exports:
    PipelineBlockedError — stage cannot proceed (e.g. missing HITL).
    set_issue_stage — persist state + pipeline_stage and append a log line.
    publish_transition — optional WS/Telegram fan-out for one transition.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sevn.evolution.events import EvolutionIssueEventPayload, maybe_publish_issue_event
from sevn.evolution.issues import EvolutionIssue, save_issue, utc_now_iso
from sevn.evolution.pipelines import append_pipeline_log

if TYPE_CHECKING:
    from sevn.evolution.events import EvolutionIssueEventFanoutFn
    from sevn.workspace.layout import WorkspaceLayout


class PipelineBlockedError(RuntimeError):
    """Raised when a pipeline stage cannot proceed (e.g. missing HITL approval)."""


async def publish_transition(
    fanout: EvolutionIssueEventFanoutFn | None,
    *,
    issue: EvolutionIssue,
    line: str | None = None,
) -> None:
    """Publish one pipeline transition event when fan-out is configured.

    Args:
        fanout (EvolutionIssueEventFanoutFn | None): Optional gateway hook.
        issue (EvolutionIssue): Updated issue row.
        line (str | None): Optional human-readable log line.

    Returns:
        None: Always.

    Examples:
        >>> import asyncio
        >>> from sevn.evolution.issues import EvolutionIssue
        >>> issue = EvolutionIssue(
        ...     id="i",
        ...     kind="feature",
        ...     title="t",
        ...     body="",
        ...     state="open",
        ...     created_at="t",
        ...     updated_at="t",
        ...     source="test",
        ... )
        >>> asyncio.run(publish_transition(None, issue=issue))
    """
    payload: EvolutionIssueEventPayload = {
        "issue_id": issue.id,
        "event": "transition",
        "state": issue.state,
        "pipeline_stage": issue.pipeline_stage,
        "approval_id": issue.approval_id,
    }
    # Include pr_url so the fanout can emit a PR-ready operator notice (FL-5.3).
    if issue.pr_url:
        payload["pr_url"] = issue.pr_url
    if line:
        payload["line"] = line
        await maybe_publish_issue_event(
            fanout,
            payload={
                "issue_id": issue.id,
                "event": "log_line",
                "line": line,
            },
        )
    await maybe_publish_issue_event(fanout, payload=payload)


def set_issue_stage(
    layout: WorkspaceLayout,
    issue: EvolutionIssue,
    *,
    state: str,
    pipeline_stage: str | None = None,
    log_line: str | None = None,
) -> EvolutionIssue:
    """Update issue state/stage and optionally append a pipeline log line.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue (EvolutionIssue): Issue row to mutate.
        state (str): New ``state`` value.
        pipeline_stage (str | None): Explicit stage id (defaults to ``state``).
        log_line (str | None): Optional log line.

    Returns:
        EvolutionIssue: Persisted issue.

    Examples:
        >>> set_issue_stage.__name__
        'set_issue_stage'
    """
    issue.state = state  # type: ignore[assignment]
    issue.pipeline_stage = pipeline_stage if pipeline_stage is not None else state
    issue.updated_at = utc_now_iso()
    if log_line:
        append_pipeline_log(layout, issue_id=issue.id, line=log_line)
    return save_issue(layout, issue)


__all__ = [
    "PipelineBlockedError",
    "publish_transition",
    "set_issue_stage",
]
