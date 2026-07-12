"""Git worktree leases for evolution pipelines (`specs/35-bot-evolution.md` §2.6).

Module: sevn.evolution.worktree
Depends: json, pathlib, subprocess, sevn.cli.repo_sync, sevn.evolution.pipelines

Exports:
    WorktreeError — allocation or promotion failure.
    WorktreeLease — persisted lease metadata.
    CiSmokeResult — outcome of ``make ci`` in a worktree.
    code_worktrees_dir — resolve ``workspace/.sevn/code-worktrees/``.
    allocate_worktree — ``git worktree add`` under the workspace lease dir.
    load_worktree_lease — read ``meta.json`` for one issue id.
    release_worktree — mark lease released (does not delete checkout).
    promote_worktree — record promotion intent per ``my_sevn.promotion.mode``.
    run_ci_smoke — run ``make ci`` (or dry-run) inside a worktree checkout.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sevn.cli.repo_sync import RepoSyncError, resolve_sevn_repo_root
from sevn.config.my_sevn import effective_my_sevn
from sevn.evolution.pipelines import append_pipeline_log

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.workspace.layout import WorkspaceLayout

PromotionMode = Literal["pr", "merge"]


class WorktreeError(RuntimeError):
    """Worktree allocation, CI smoke, or promotion failure."""


@dataclass
class WorktreeLease:
    """Lease record persisted beside one issue worktree."""

    issue_id: str
    path: str
    base_sha: str
    executor: str
    leased_at: str
    released_at: str | None = None
    branch: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for ``meta.json``.

        Returns:
            dict[str, Any]: JSON-safe mapping.

        Examples:
            >>> WorktreeLease(
            ...     issue_id="i1",
            ...     path="/tmp/wt",
            ...     base_sha="abc",
            ...     executor="local",
            ...     leased_at="t",
            ... ).to_dict()["issue_id"]
            'i1'
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorktreeLease:
        """Hydrate from ``meta.json``.

        Args:
            data (dict[str, Any]): Parsed JSON object.

        Returns:
            WorktreeLease: Lease record.

        Examples:
            >>> WorktreeLease.from_dict(
            ...     {
            ...         "issue_id": "i1",
            ...         "path": "/tmp/wt",
            ...         "base_sha": "abc",
            ...         "executor": "local",
            ...         "leased_at": "t",
            ...     },
            ... ).issue_id
            'i1'
        """
        return cls(
            issue_id=str(data["issue_id"]),
            path=str(data["path"]),
            base_sha=str(data.get("base_sha", "")),
            executor=str(data.get("executor", "local")),
            leased_at=str(data.get("leased_at", "")),
            released_at=data.get("released_at"),
            branch=data.get("branch"),
        )


@dataclass(frozen=True)
class CiSmokeResult:
    """Outcome of :func:`run_ci_smoke`."""

    ok: bool
    exit_code: int | None
    stdout: str
    stderr: str
    dry_run: bool


def code_worktrees_dir(layout: WorkspaceLayout) -> Path:
    """Return ``<content_root>/.sevn/code-worktrees``.

    Args:
        layout (WorkspaceLayout): Workspace layout.

    Returns:
        Path: Worktrees root directory.

    Examples:
        >>> code_worktrees_dir.__name__
        'code_worktrees_dir'
    """
    return layout.dot_sevn / "code-worktrees"


def _lease_dir(layout: WorkspaceLayout, issue_id: str) -> Path:
    """Return lease directory for one issue id.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.

    Returns:
        Path: Lease directory path.

    Examples:
        >>> _lease_dir.__name__
        '_lease_dir'
    """
    return code_worktrees_dir(layout) / issue_id.strip()


def _meta_path(layout: WorkspaceLayout, issue_id: str) -> Path:
    """Return ``meta.json`` path for one lease.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.

    Returns:
        Path: Metadata file path.

    Examples:
        >>> _meta_path.__name__
        '_meta_path'
    """
    return _lease_dir(layout, issue_id) / "meta.json"


def _checkout_path(layout: WorkspaceLayout, issue_id: str) -> Path:
    """Return git worktree checkout path for one issue.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.

    Returns:
        Path: Checkout directory under the lease folder.

    Examples:
        >>> _checkout_path.__name__
        '_checkout_path'
    """
    return _lease_dir(layout, issue_id) / "checkout"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one git subprocess in ``cwd``.

    Args:
        cwd (Path): Repository or worktree root.
        args (str): Git subcommand and arguments (variadic).

    Returns:
        subprocess.CompletedProcess[str]: Completed process.

    Examples:
        >>> _git.__name__
        '_git'
    """
    git_bin = shutil.which("git") or "git"
    return subprocess.run(  # nosec B603 — fixed git argv; no shell
        [git_bin, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _git_rev_parse(repo_root: Path, ref: str = "HEAD") -> str:
    """Return one resolved object id.

    Args:
        repo_root (Path): Git repository root.
        ref (str): Ref to resolve.

    Returns:
        str: Full or short object id.

    Raises:
        WorktreeError: When git fails.

    Examples:
        >>> _git_rev_parse.__name__
        '_git_rev_parse'
    """
    proc = _git(repo_root, "rev-parse", ref)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "git rev-parse failed").strip()
        raise WorktreeError(msg)
    return proc.stdout.strip()


def load_worktree_lease(layout: WorkspaceLayout, issue_id: str) -> WorktreeLease | None:
    """Load lease metadata when present.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.

    Returns:
        WorktreeLease | None: Lease or ``None``.

    Examples:
        >>> load_worktree_lease.__name__
        'load_worktree_lease'
    """
    path = _meta_path(layout, issue_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    return WorktreeLease.from_dict(data)


def allocate_worktree(
    layout: WorkspaceLayout,
    issue_id: str,
    *,
    repo_root: Path | None = None,
    executor: str = "local",
    base_ref: str = "HEAD",
    owner_principal: str = "owner",
) -> WorktreeLease:
    """Allocate a git worktree under ``workspace/.sevn/code-worktrees/<issue-id>/``.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Evolution issue id (lease key).
        repo_root (Path | None): Optional explicit sevn.bot checkout (else
            :func:`resolve_sevn_repo_root`).
        executor (str): ``local`` or ``cursor_cloud`` label for metadata.
        base_ref (str): Git ref to branch from.
        owner_principal (str): Owner principal for audit logs.

    Returns:
        WorktreeLease: Persisted lease after ``git worktree add``.

    Raises:
        WorktreeError: When repo resolution fails or worktree already leased.

    Examples:
        >>> allocate_worktree.__name__
        'allocate_worktree'
    """
    _ = owner_principal
    existing = load_worktree_lease(layout, issue_id)
    if existing is not None and existing.released_at is None:
        checkout = Path(existing.path)
        if checkout.is_dir():
            return existing
        msg = f"worktree lease exists but checkout missing: {issue_id}"
        raise WorktreeError(msg)

    try:
        root = repo_root if repo_root is not None else resolve_sevn_repo_root()
    except RepoSyncError as exc:
        raise WorktreeError(str(exc)) from exc

    lease_dir = _lease_dir(layout, issue_id)
    checkout = _checkout_path(layout, issue_id)
    lease_dir.mkdir(parents=True, exist_ok=True)
    if checkout.exists():
        msg = f"checkout path already exists: {checkout}"
        raise WorktreeError(msg)

    base_sha = _git_rev_parse(root, base_ref)
    branch = f"evolution/{issue_id}"
    add_proc = _git(root, "worktree", "add", "-b", branch, str(checkout), base_ref)
    if add_proc.returncode != 0:
        msg = (add_proc.stderr or add_proc.stdout or "git worktree add failed").strip()
        raise WorktreeError(msg)

    from sevn.evolution.issues import utc_now_iso

    lease = WorktreeLease(
        issue_id=issue_id,
        path=str(checkout.resolve()),
        base_sha=base_sha,
        executor=executor,
        leased_at=utc_now_iso(),
        branch=branch,
    )
    _meta_path(layout, issue_id).write_text(
        json.dumps(lease.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    append_pipeline_log(
        layout,
        issue_id=issue_id,
        line=f"Worktree allocated at {lease.path} (base {base_sha[:8]}).",
    )
    return lease


def release_worktree(layout: WorkspaceLayout, issue_id: str) -> WorktreeLease | None:
    """Mark a lease released without deleting the checkout directory.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.

    Returns:
        WorktreeLease | None: Updated lease or ``None`` when missing.

    Examples:
        >>> release_worktree.__name__
        'release_worktree'
    """
    lease = load_worktree_lease(layout, issue_id)
    if lease is None:
        return None
    from sevn.evolution.issues import utc_now_iso

    lease.released_at = utc_now_iso()
    _meta_path(layout, issue_id).write_text(
        json.dumps(lease.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    append_pipeline_log(layout, issue_id=issue_id, line="Worktree lease released.")
    return lease


def _effective_promotion_mode(ws: WorkspaceConfig) -> PromotionMode:
    """Return promotion mode from config.

    Args:
        ws (WorkspaceConfig): Parsed workspace.

    Returns:
        PromotionMode: ``pr`` or ``merge``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _effective_promotion_mode(WorkspaceConfig.minimal())
        'pr'
    """
    my = effective_my_sevn(ws)
    mode = (my.promotion.mode if my.promotion else "pr").strip().lower()
    if mode == "merge":
        return "merge"
    return "pr"


def promote_worktree(
    layout: WorkspaceLayout,
    issue_id: str,
    ws: WorkspaceConfig,
    *,
    dry_run: bool = False,
) -> dict[str, str]:
    """Push worktree branch per ``my_sevn.promotion.mode`` (legacy sync path).

    This is the *synchronous* legacy entry-point used by pipeline callers that
    do not hold :class:`~sevn.integrations.github_skill.hooks.GithubSkillHooks`.
    For the full async path that pushes **and** opens a pull request, use
    :func:`sevn.evolution.promotion.promote_issue` directly.

    Mode semantics:

    - ``pr`` (default): push branch to origin; caller should follow up with
      :func:`~sevn.evolution.promotion.promote_issue` to open the PR.
    - ``merge``: print a manual note — automated merge is not supported.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.
        ws (WorkspaceConfig): Workspace config for promotion mode.
        dry_run (bool): When true, skip git push and return a plan message.

    Returns:
        dict[str, str]: Promotion summary with ``mode`` and ``detail``.

    Raises:
        WorktreeError: When lease or checkout is missing.

    Examples:
        >>> promote_worktree.__name__
        'promote_worktree'
    """
    lease = load_worktree_lease(layout, issue_id)
    if lease is None:
        msg = f"no worktree lease for issue {issue_id}"
        raise WorktreeError(msg)
    checkout = Path(lease.path)
    if not checkout.is_dir():
        msg = f"worktree checkout missing: {checkout}"
        raise WorktreeError(msg)

    mode = _effective_promotion_mode(ws)
    branch = lease.branch or f"evolution/{issue_id}"
    if dry_run:
        detail = f"dry-run: would promote branch {branch} via {mode}"
        append_pipeline_log(layout, issue_id=issue_id, line=detail)
        return {"mode": mode, "detail": detail}

    if mode == "merge":
        detail = f"merge promotion not automated; push branch {branch} manually"
        append_pipeline_log(layout, issue_id=issue_id, line=detail)
        return {"mode": mode, "detail": detail}

    push_proc = _git(checkout, "push", "-u", "origin", branch)
    if push_proc.returncode != 0:
        detail = (
            push_proc.stderr or push_proc.stdout or "git push failed"
        ).strip() + " — open PR manually from local branch"
        append_pipeline_log(layout, issue_id=issue_id, line=detail)
        return {"mode": mode, "detail": detail}

    detail = f"pushed {branch}; open PR via sevn.evolution.promotion.promote_issue"
    append_pipeline_log(layout, issue_id=issue_id, line=detail)
    return {"mode": mode, "detail": detail, "branch": branch}


def run_ci_smoke(
    worktree_path: Path,
    *,
    dry_run: bool = False,
    timeout_sec: int = 600,
) -> CiSmokeResult:
    """Run ``make ci`` inside a worktree checkout.

    Args:
        worktree_path (Path): Git worktree root.
        dry_run (bool): When true, skip subprocess and return success.
        timeout_sec (int): Subprocess timeout in seconds.

    Returns:
        CiSmokeResult: Structured smoke outcome.

    Examples:
        >>> run_ci_smoke.__name__
        'run_ci_smoke'
    """
    if dry_run:
        return CiSmokeResult(ok=True, exit_code=0, stdout="dry-run", stderr="", dry_run=True)
    if not worktree_path.is_dir():
        return CiSmokeResult(
            ok=False,
            exit_code=None,
            stdout="",
            stderr=f"worktree not found: {worktree_path}",
            dry_run=False,
        )
    try:
        make_bin = shutil.which("make") or "make"
        proc = subprocess.run(  # nosec B603 — fixed make argv; no shell
            [make_bin, "ci"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=max(30, timeout_sec),
            check=False,
        )
        ok = proc.returncode == 0
        return CiSmokeResult(
            ok=ok,
            exit_code=proc.returncode,
            stdout=(proc.stdout or "")[:4096],
            stderr=(proc.stderr or "")[:4096],
            dry_run=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CiSmokeResult(ok=False, exit_code=None, stdout="", stderr=str(exc), dry_run=False)


__all__ = [
    "CiSmokeResult",
    "WorktreeError",
    "WorktreeLease",
    "allocate_worktree",
    "code_worktrees_dir",
    "load_worktree_lease",
    "promote_worktree",
    "release_worktree",
    "run_ci_smoke",
]
