"""Evolution HITL approval queue (`specs/35-bot-evolution.md` §2.8).

Module: sevn.evolution.approvals
Depends: json, pathlib, uuid, sevn.evolution.issues, sevn.evolution.pipelines

Exports:
    EvolutionApproval — persisted approval record.
    approval_to_api_dict — Mission Control JSON shape.
    approvals_dir — resolve ``.sevn/evolution/approvals/``.
    create_approval — enqueue one approval row.
    ensure_issue_approval — create pending approval when issue awaits HITL.
    get_approval — load one approval by id.
    list_approvals — list approvals with optional pending-only filter.
    resolve_approval — approve, reject, or edit and unblock pipeline.
    save_approval — persist approval JSON.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path  # noqa: TC003 — runtime approval paths
from typing import TYPE_CHECKING, Any, Literal

from sevn.evolution.issues import EvolutionIssue, get_issue, save_issue, utc_now_iso
from sevn.evolution.pipelines import append_pipeline_log

if TYPE_CHECKING:
    from sevn.workspace.layout import WorkspaceLayout

ApprovalKind = Literal["feature_plan", "feature_tasks", "self_improve_plan"]
ApprovalStatus = Literal["pending", "approved", "rejected"]
ApprovalAction = Literal["approve", "reject", "edit"]


@dataclass
class EvolutionApproval:
    """One HITL approval under ``workspace/.sevn/evolution/approvals/<id>.json``."""

    id: str
    kind: ApprovalKind
    status: ApprovalStatus
    title: str
    body: str
    created_at: str
    updated_at: str
    issue_id: str | None = None
    job_id: str | None = None
    resolved_at: str | None = None
    edit_body: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON persistence.

        Returns:
            dict[str, Any]: JSON-safe mapping.

        Examples:
            >>> EvolutionApproval(
            ...     id="a",
            ...     kind="feature_plan",
            ...     status="pending",
            ...     title="Plan",
            ...     body="body",
            ...     created_at="t",
            ...     updated_at="t",
            ... ).to_dict()["kind"]
            'feature_plan'
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvolutionApproval:
        """Hydrate from persisted JSON.

        Args:
            data (dict[str, Any]): Approval JSON object.

        Returns:
            EvolutionApproval: Parsed record.

        Examples:
            >>> EvolutionApproval.from_dict(
            ...     {
            ...         "id": "a",
            ...         "kind": "feature_plan",
            ...         "status": "pending",
            ...         "title": "t",
            ...         "body": "b",
            ...         "created_at": "t",
            ...         "updated_at": "t",
            ...     },
            ... ).status
            'pending'
        """
        kind_raw = data.get("kind", "feature_plan")
        status_raw = data.get("status", "pending")
        return cls(
            id=str(data["id"]),
            kind=kind_raw
            if kind_raw in ("feature_plan", "feature_tasks", "self_improve_plan")
            else "feature_plan",
            status=status_raw if status_raw in ("pending", "approved", "rejected") else "pending",
            title=str(data.get("title", "")),
            body=str(data.get("body", "")),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            issue_id=data.get("issue_id"),
            job_id=data.get("job_id"),
            resolved_at=data.get("resolved_at"),
            edit_body=data.get("edit_body"),
        )


def approvals_dir(layout: WorkspaceLayout) -> Path:
    """Return ``<content_root>/.sevn/evolution/approvals``.

    Args:
        layout (WorkspaceLayout): Workspace layout.

    Returns:
        Path: Approvals directory.

    Examples:
        >>> approvals_dir.__name__
        'approvals_dir'
    """
    return layout.dot_sevn / "evolution" / "approvals"


def _approval_path(layout: WorkspaceLayout, approval_id: str) -> Path:
    """Return JSON path for one approval id.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        approval_id (str): Approval id.

    Returns:
        Path: File path.

    Examples:
        >>> _approval_path.__name__
        '_approval_path'
    """
    return approvals_dir(layout) / f"{approval_id.strip()}.json"


def save_approval(layout: WorkspaceLayout, approval: EvolutionApproval) -> EvolutionApproval:
    """Persist one approval record.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        approval (EvolutionApproval): Record to write.

    Returns:
        EvolutionApproval: Same record after write.

    Examples:
        >>> save_approval.__name__
        'save_approval'
    """
    root = approvals_dir(layout)
    root.mkdir(parents=True, exist_ok=True)
    path = _approval_path(layout, approval.id)
    path.write_text(json.dumps(approval.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return approval


def get_approval(layout: WorkspaceLayout, approval_id: str) -> EvolutionApproval | None:
    """Load one approval when present.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        approval_id (str): Approval id.

    Returns:
        EvolutionApproval | None: Record or ``None``.

    Examples:
        >>> get_approval.__name__
        'get_approval'
    """
    path = _approval_path(layout, approval_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    return EvolutionApproval.from_dict(data)


def list_approvals(
    layout: WorkspaceLayout,
    *,
    pending_only: bool = False,
    limit: int = 100,
) -> list[EvolutionApproval]:
    """List approvals sorted by ``updated_at`` descending.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        pending_only (bool): When true, return only ``pending`` rows.
        limit (int): Max rows.

    Returns:
        list[EvolutionApproval]: Newest first.

    Examples:
        >>> list_approvals.__name__
        'list_approvals'
    """
    root = approvals_dir(layout)
    if not root.is_dir():
        return []
    cap = max(1, min(int(limit), 500))
    rows: list[EvolutionApproval] = []
    for path in root.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            rows.append(EvolutionApproval.from_dict(data))
    if pending_only:
        rows = [row for row in rows if row.status == "pending"]
    rows.sort(key=lambda item: item.updated_at, reverse=True)
    return rows[:cap]


def approval_to_api_dict(approval: EvolutionApproval) -> dict[str, Any]:
    """Serialize one approval for Mission Control JSON.

    Args:
        approval (EvolutionApproval): Persisted record.

    Returns:
        dict[str, Any]: API payload.

    Examples:
        >>> approval_to_api_dict(
        ...     EvolutionApproval(
        ...         id="a",
        ...         kind="feature_plan",
        ...         status="pending",
        ...         title="t",
        ...         body="b",
        ...         created_at="t",
        ...         updated_at="t",
        ...         issue_id="i1",
        ...     ),
        ... )["issue_id"]
        'i1'
    """
    return approval.to_dict()


def create_approval(
    layout: WorkspaceLayout,
    *,
    kind: ApprovalKind,
    title: str,
    body: str,
    issue_id: str | None = None,
    job_id: str | None = None,
    approval_id: str | None = None,
) -> EvolutionApproval:
    """Create a pending approval row.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        kind (ApprovalKind): Approval category.
        title (str): Short title.
        body (str): Plan/tasks markdown body.
        issue_id (str | None): Linked evolution issue.
        job_id (str | None): Linked improve job.
        approval_id (str | None): Optional stable id.

    Returns:
        EvolutionApproval: Persisted pending approval.

    Examples:
        >>> create_approval.__name__
        'create_approval'
    """
    now = utc_now_iso()
    aid = approval_id or uuid.uuid4().hex[:12]
    approval = EvolutionApproval(
        id=aid,
        kind=kind,
        status="pending",
        title=title.strip(),
        body=body,
        created_at=now,
        updated_at=now,
        issue_id=issue_id,
        job_id=job_id,
    )
    if issue_id:
        issue = get_issue(layout, issue_id)
        if issue is not None:
            issue.approval_id = aid
            issue.updated_at = now
            save_issue(layout, issue)
    return save_approval(layout, approval)


def ensure_issue_approval(
    layout: WorkspaceLayout, issue: EvolutionIssue
) -> EvolutionApproval | None:
    """Ensure a pending approval exists when an issue is ``awaiting_approval``.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue (EvolutionIssue): Issue row.

    Returns:
        EvolutionApproval | None: Existing or created approval, or ``None`` when not applicable.

    Examples:
        >>> ensure_issue_approval.__name__
        'ensure_issue_approval'
    """
    if issue.state != "awaiting_approval":
        return None
    if issue.approval_id:
        existing = get_approval(layout, issue.approval_id)
        if existing is not None:
            return existing
    kind: ApprovalKind = "feature_plan" if issue.kind == "feature" else "feature_tasks"
    return create_approval(
        layout,
        kind=kind,
        title=f"{issue.kind.title()} approval: {issue.title}",
        body=issue.body or "(no plan body)",
        issue_id=issue.id,
    )


def _unblock_issue_after_approval(
    layout: WorkspaceLayout,
    issue: EvolutionIssue,
    *,
    action: ApprovalAction,
    edit_body: str | None = None,
) -> EvolutionIssue:
    """Apply pipeline state transition after an approval decision.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue (EvolutionIssue): Linked issue.
        action (ApprovalAction): Owner decision.
        edit_body (str | None): Optional edited plan body.

    Returns:
        EvolutionIssue: Updated issue row.

    Examples:
        >>> _unblock_issue_after_approval.__name__
        '_unblock_issue_after_approval'
    """
    if action == "reject":
        issue.state = "cancelled"
        issue.pipeline_stage = "cancelled"
        append_pipeline_log(
            layout, issue_id=issue.id, line="Approval rejected — pipeline cancelled."
        )
    else:
        issue.state = "implementing"
        issue.pipeline_stage = "implementing"
        if edit_body:
            issue.body = edit_body
        append_pipeline_log(
            layout, issue_id=issue.id, line=f"Approval {action} — pipeline unblocked."
        )
    issue.updated_at = utc_now_iso()
    return save_issue(layout, issue)


def resolve_approval(
    layout: WorkspaceLayout,
    approval_id: str,
    action: ApprovalAction,
    *,
    edit_body: str | None = None,
) -> tuple[EvolutionApproval | None, EvolutionIssue | None]:
    """Approve, reject, or edit one approval and unblock the linked pipeline when applicable.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        approval_id (str): Approval id.
        action (ApprovalAction): Owner decision.
        edit_body (str | None): Replacement body when ``action`` is ``edit``.

    Returns:
        tuple[EvolutionApproval | None, EvolutionIssue | None]: Updated approval and issue rows.

    Examples:
        >>> resolve_approval.__name__
        'resolve_approval'
    """
    approval = get_approval(layout, approval_id)
    if approval is None:
        return None, None
    if approval.status != "pending":
        issue = get_issue(layout, approval.issue_id) if approval.issue_id else None
        return approval, issue
    now = utc_now_iso()
    if action == "reject":
        approval.status = "rejected"
    else:
        approval.status = "approved"
        if action == "edit" and edit_body:
            approval.edit_body = edit_body
            approval.body = edit_body
    approval.resolved_at = now
    approval.updated_at = now
    save_approval(layout, approval)

    updated_issue: EvolutionIssue | None = None
    if approval.issue_id:
        loaded = get_issue(layout, approval.issue_id)
        if loaded is not None:
            updated_issue = _unblock_issue_after_approval(
                layout,
                loaded,
                action=action,
                edit_body=edit_body,
            )

    return approval, updated_issue


__all__ = [
    "ApprovalAction",
    "ApprovalKind",
    "ApprovalStatus",
    "EvolutionApproval",
    "approval_to_api_dict",
    "approvals_dir",
    "create_approval",
    "ensure_issue_approval",
    "get_approval",
    "list_approvals",
    "resolve_approval",
    "save_approval",
]
