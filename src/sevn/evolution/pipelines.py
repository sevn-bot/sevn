"""Evolution pipeline helpers — active runs, stages, kill (`specs/35-bot-evolution.md` §2.8).

Module: sevn.evolution.pipelines
Depends: json, pathlib, sevn.evolution.issues

Exports:
    PipelineStageRow — one stage stepper row.
    append_pipeline_log — append one log line and return it.
    get_pipeline_detail — stage stepper + log tail for one issue.
    issue_to_pipeline_dict — pipeline summary serialization.
    kill_pipeline — cancel an active pipeline run.
    list_active_pipelines — non-terminal issues as pipeline rows.
    pipeline_logs_path — resolve JSONL log path for an issue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — runtime log paths
from typing import TYPE_CHECKING, Any, Literal

from sevn.evolution.issues import EvolutionIssue, get_issue, list_issues, save_issue, utc_now_iso

if TYPE_CHECKING:
    from sevn.workspace.layout import WorkspaceLayout

StageStatus = Literal["done", "current", "pending", "skipped"]

BUG_PIPELINE_STAGES: tuple[str, ...] = ("open", "spec_kit", "implementing", "done")
FEATURE_PIPELINE_STAGES: tuple[str, ...] = (
    "open",
    "spec_kit",
    "awaiting_approval",
    "implementing",
    "done",
)

_TERMINAL_STATES = frozenset({"done", "cancelled"})


@dataclass(frozen=True)
class PipelineStageRow:
    """One stage in the pipeline stepper."""

    id: str
    label: str
    status: StageStatus


def _stages_for_kind(kind: str) -> tuple[str, ...]:
    """Return ordered stage ids for an issue kind.

    Args:
        kind (str): ``bug`` or ``feature``.

    Returns:
        tuple[str, ...]: Stage id sequence.

    Examples:
        >>> _stages_for_kind("feature")[2]
        'awaiting_approval'
    """
    if kind == "feature":
        return FEATURE_PIPELINE_STAGES
    return BUG_PIPELINE_STAGES


def _current_stage_index(issue: EvolutionIssue, stages: tuple[str, ...]) -> int:
    """Resolve the active stage index for stepper rendering.

    Args:
        issue (EvolutionIssue): Persisted issue row.
        stages (tuple[str, ...]): Ordered stage ids.

    Returns:
        int: Index of the current stage (clamped).

    Examples:
        >>> from sevn.evolution.issues import EvolutionIssue
        >>> issue = EvolutionIssue(
        ...     id="i",
        ...     kind="feature",
        ...     title="t",
        ...     body="",
        ...     state="awaiting_approval",
        ...     created_at="t",
        ...     updated_at="t",
        ...     source="test",
        ... )
        >>> _current_stage_index(issue, FEATURE_PIPELINE_STAGES)
        2
    """
    stage = (issue.pipeline_stage or issue.state or "open").strip()
    if stage in stages:
        return stages.index(stage)
    if issue.state in stages:
        return stages.index(issue.state)
    if issue.state == "cancelled":
        return max(0, len(stages) - 1)
    return 0


def _build_stage_rows(issue: EvolutionIssue) -> list[dict[str, str]]:
    """Build stepper rows for one issue.

    Args:
        issue (EvolutionIssue): Persisted issue.

    Returns:
        list[dict[str, str]]: Stage rows with ``id``, ``label``, ``status``.

    Examples:
        >>> from sevn.evolution.issues import EvolutionIssue
        >>> rows = _build_stage_rows(
        ...     EvolutionIssue(
        ...         id="i",
        ...         kind="bug",
        ...         title="t",
        ...         body="",
        ...         state="implementing",
        ...         created_at="t",
        ...         updated_at="t",
        ...         source="test",
        ...     ),
        ... )
        >>> rows[-1]["id"]
        'done'
    """
    stages = _stages_for_kind(issue.kind)
    current_idx = _current_stage_index(issue, stages)
    if issue.kind == "bug" and issue.state not in ("spec_kit",) and current_idx == 1:
        current_idx = 2 if issue.state == "implementing" else current_idx
    rows: list[dict[str, str]] = []
    for idx, stage_id in enumerate(stages):
        if issue.state == "done" or issue.state == "cancelled":
            status: StageStatus = "done" if idx <= current_idx else "pending"
        elif idx < current_idx:
            status = "done"
        elif idx == current_idx:
            status = "current"
        else:
            status = "pending"
        if issue.kind == "bug" and stage_id == "spec_kit" and issue.state == "implementing":
            status = "skipped"
        label = stage_id.replace("_", " ").title()
        rows.append({"id": stage_id, "label": label, "status": status})
    return rows


def pipeline_logs_path(layout: WorkspaceLayout, issue_id: str) -> Path:
    """Return JSONL log path for one issue pipeline.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.

    Returns:
        Path: ``.sevn/evolution/logs/<issue_id>.jsonl``.

    Examples:
        >>> pipeline_logs_path.__name__
        'pipeline_logs_path'
    """
    return layout.dot_sevn / "evolution" / "logs" / f"{issue_id.strip()}.jsonl"


def append_pipeline_log(
    layout: WorkspaceLayout,
    *,
    issue_id: str,
    line: str,
) -> dict[str, str]:
    """Append one pipeline log line to the issue JSONL file.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.
        line (str): Human-readable log line.

    Returns:
        dict[str, str]: Stored entry with ``ts`` and ``line``.

    Examples:
        >>> append_pipeline_log.__name__
        'append_pipeline_log'
    """
    path = pipeline_logs_path(layout, issue_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": utc_now_iso(), "line": line.strip()}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _read_log_tail(path: Path, *, limit: int = 100) -> list[dict[str, str]]:
    """Read the last ``limit`` JSONL log entries.

    Args:
        path (Path): JSONL file path.
        limit (int): Max entries.

    Returns:
        list[dict[str, str]]: Parsed entries newest-last.

    Examples:
        >>> _read_log_tail.__name__
        '_read_log_tail'
    """
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    tail = lines[-max(1, limit) :]
    out: list[dict[str, str]] = []
    for raw in tail:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            out.append(
                {
                    "ts": str(parsed.get("ts", "")),
                    "line": str(parsed.get("line", "")),
                },
            )
    return out


def issue_to_pipeline_dict(issue: EvolutionIssue) -> dict[str, Any]:
    """Serialize one issue as an active pipeline summary row.

    Args:
        issue (EvolutionIssue): Persisted issue.

    Returns:
        dict[str, Any]: Pipeline list payload.

    Examples:
        >>> from sevn.evolution.issues import EvolutionIssue
        >>> row = issue_to_pipeline_dict(
        ...     EvolutionIssue(
        ...         id="i",
        ...         kind="feature",
        ...         title="T",
        ...         body="",
        ...         state="spec_kit",
        ...         created_at="t",
        ...         updated_at="t",
        ...         source="test",
        ...     ),
        ... )
        >>> row["kind"]
        'feature'
    """
    return {
        "issue_id": issue.id,
        "kind": issue.kind,
        "title": issue.title,
        "state": issue.state,
        "pipeline_stage": issue.pipeline_stage or issue.state,
        "executor": issue.executor,
        "pr_url": issue.pr_url,
        "agent_url": issue.agent_url,
        "updated_at": issue.updated_at,
        "stages": _build_stage_rows(issue),
    }


def list_active_pipelines(layout: WorkspaceLayout, *, limit: int = 100) -> list[dict[str, Any]]:
    """List non-terminal evolution issues as active pipeline runs.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        limit (int): Max rows.

    Returns:
        list[dict[str, Any]]: Pipeline summaries newest-first.

    Examples:
        >>> list_active_pipelines.__name__
        'list_active_pipelines'
    """
    rows = [
        issue for issue in list_issues(layout, limit=limit) if issue.state not in _TERMINAL_STATES
    ]
    return [issue_to_pipeline_dict(issue) for issue in rows]


def get_pipeline_detail(layout: WorkspaceLayout, issue_id: str) -> dict[str, Any] | None:
    """Return pipeline detail including stage stepper and recent log lines.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.

    Returns:
        dict[str, Any] | None: Detail payload or ``None`` when missing.

    Examples:
        >>> get_pipeline_detail.__name__
        'get_pipeline_detail'
    """
    issue = get_issue(layout, issue_id)
    if issue is None:
        return None
    payload = issue_to_pipeline_dict(issue)
    payload["logs"] = _read_log_tail(pipeline_logs_path(layout, issue_id))
    payload["approval_id"] = issue.approval_id
    return payload


def kill_pipeline(layout: WorkspaceLayout, issue_id: str) -> EvolutionIssue | None:
    """Cancel an active pipeline by marking the issue ``cancelled``.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.

    Returns:
        EvolutionIssue | None: Updated issue or ``None`` when missing.

    Examples:
        >>> kill_pipeline.__name__
        'kill_pipeline'
    """
    issue = get_issue(layout, issue_id)
    if issue is None:
        return None
    if issue.state in _TERMINAL_STATES:
        return issue
    issue.state = "cancelled"
    issue.pipeline_stage = "cancelled"
    issue.updated_at = utc_now_iso()
    append_pipeline_log(layout, issue_id=issue.id, line="Pipeline killed from Mission Control.")
    return save_issue(layout, issue)


__all__ = [
    "BUG_PIPELINE_STAGES",
    "FEATURE_PIPELINE_STAGES",
    "PipelineStageRow",
    "append_pipeline_log",
    "get_pipeline_detail",
    "issue_to_pipeline_dict",
    "kill_pipeline",
    "list_active_pipelines",
    "pipeline_logs_path",
]
