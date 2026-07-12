"""``my_sevn`` config helpers (`specs/35-bot-evolution.md`).

Module: sevn.config.my_sevn
Depends: sevn.config.workspace_config

Exports:
    effective_my_sevn — resolve typed ``my_sevn`` block with defaults.
    effective_my_sevn_executors — resolve typed ``my_sevn.executors`` with defaults.
    effective_my_sevn_issues — resolve typed ``my_sevn.issues`` with defaults.
    effective_my_sevn_pipelines — resolve typed ``my_sevn.pipelines`` with defaults.
    effective_my_sevn_sync — resolve typed ``my_sevn.sync`` with defaults.
    resolve_my_sevn_repo_path — checkout path from ``my_sevn.repo_path`` in ``sevn.json``.
    persist_my_sevn_repo_path — record a resolved checkout into ``my_sevn.repo_path``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sevn.config.sevn_repo import is_sevn_repo
from sevn.config.workspace_config import (
    MySevnExecutorsWorkspaceConfig,
    MySevnIssuesWorkspaceConfig,
    MySevnPipelinesWorkspaceConfig,
    MySevnSyncWorkspaceConfig,
    MySevnWorkspaceConfig,
    WorkspaceConfig,
)

if TYPE_CHECKING:
    from pathlib import Path


def persist_my_sevn_repo_path(sevn_json_path: Path, repo_path: Path) -> bool:
    """Record ``repo_path`` as ``my_sevn.repo_path`` in ``sevn.json``.

    Used at boot to turn a one-time ``$HOME`` heuristic guess into an explicit,
    recorded choice so later boots skip the scan. Round-trips the JSON, preserving
    all other keys; a no-op (returns ``False``) when the value is already set or the
    file cannot be read/written. Never raises — boot treats failure as non-fatal.

    Args:
        sevn_json_path (Path): Path to the workspace ``sevn.json``.
        repo_path (Path): Checkout path to record.

    Returns:
        bool: ``True`` when the file was rewritten with the new value.

    Examples:
        >>> import json, tempfile
        >>> from pathlib import Path as _P
        >>> d = _P(tempfile.mkdtemp())
        >>> _ = (d / "sevn.json").write_text('{"schema_version": 1}', encoding="utf-8")
        >>> persist_my_sevn_repo_path(d / "sevn.json", _P("/srv/sevn.bot"))
        True
        >>> json.loads((d / "sevn.json").read_text())["my_sevn"]["repo_path"]
        '/srv/sevn.bot'
    """
    import json
    from pathlib import Path as _Path

    path = _Path(sevn_json_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    block = data.get("my_sevn")
    if not isinstance(block, dict):
        block = {}
    if block.get("repo_path") == str(repo_path):
        return False
    block["repo_path"] = str(repo_path)
    data["my_sevn"] = block
    try:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def resolve_my_sevn_repo_path(ws: WorkspaceConfig) -> Path | None:
    """Return the configured local checkout when ``my_sevn.repo_path`` is valid.

    Args:
        ws (WorkspaceConfig): Parsed workspace root.

    Returns:
        Path | None: Absolute sevn.bot checkout, or ``None`` when unset or invalid.

    Examples:
        >>> resolve_my_sevn_repo_path(WorkspaceConfig.minimal()) is None
        True
    """
    from pathlib import Path as _Path

    raw = (effective_my_sevn(ws).repo_path or "").strip()
    if not raw:
        return None
    root = _Path(raw).expanduser().resolve()
    if is_sevn_repo(root):
        return root
    return None


def effective_my_sevn_sync(ws: WorkspaceConfig) -> MySevnSyncWorkspaceConfig:
    """Return ``my_sevn.sync`` with defaults when the subtree is absent.

    Args:
        ws (WorkspaceConfig): Parsed workspace root model.

    Returns:
        MySevnSyncWorkspaceConfig: Effective sync cron settings.

    Examples:
        >>> effective_my_sevn_sync(WorkspaceConfig.minimal()).enabled
        True
    """
    if ws.my_sevn and ws.my_sevn.sync:
        return ws.my_sevn.sync
    return MySevnSyncWorkspaceConfig()


def effective_my_sevn_executors(ws: WorkspaceConfig) -> MySevnExecutorsWorkspaceConfig:
    """Return ``my_sevn.executors`` with product defaults when absent.

    Args:
        ws (WorkspaceConfig): Parsed workspace root model.

    Returns:
        MySevnExecutorsWorkspaceConfig: Effective routing for bug/feature implement.

    Examples:
        >>> effective_my_sevn_executors(WorkspaceConfig.minimal()).feature
        'cursor_cloud'
    """
    my = effective_my_sevn(ws)
    if my.executors:
        return my.executors
    return MySevnExecutorsWorkspaceConfig()


def effective_my_sevn_issues(ws: WorkspaceConfig) -> MySevnIssuesWorkspaceConfig:
    """Return ``my_sevn.issues`` with defaults when the subtree is absent.

    Args:
        ws (WorkspaceConfig): Parsed workspace root model.

    Returns:
        MySevnIssuesWorkspaceConfig: Effective GitHub ingest + registry options.

    Examples:
        >>> effective_my_sevn_issues(WorkspaceConfig.minimal()).webhook_import
        True
    """
    my = effective_my_sevn(ws)
    if my.issues:
        return my.issues
    return MySevnIssuesWorkspaceConfig()


def effective_my_sevn_pipelines(ws: WorkspaceConfig) -> MySevnPipelinesWorkspaceConfig:
    """Return ``my_sevn.pipelines`` with defaults when the subtree is absent.

    Args:
        ws (WorkspaceConfig): Parsed workspace root model.

    Returns:
        MySevnPipelinesWorkspaceConfig: Effective pipeline dry-run and budget options.

    Examples:
        >>> effective_my_sevn_pipelines(WorkspaceConfig.minimal()).ci_dry_run_default
        True
    """
    my = effective_my_sevn(ws)
    if my.pipelines:
        return my.pipelines
    return MySevnPipelinesWorkspaceConfig()


def effective_my_sevn(ws: WorkspaceConfig) -> MySevnWorkspaceConfig:
    """Return ``my_sevn`` with defaults when the subtree is absent.

    Args:
        ws (WorkspaceConfig): Parsed workspace root model.

    Returns:
        MySevnWorkspaceConfig: Effective repo binding.

    Examples:
        >>> effective_my_sevn(WorkspaceConfig.minimal()).repo_url.startswith("https://")
        True
    """
    if ws.my_sevn:
        return ws.my_sevn
    return MySevnWorkspaceConfig()


__all__ = [
    "effective_my_sevn",
    "effective_my_sevn_executors",
    "effective_my_sevn_issues",
    "effective_my_sevn_pipelines",
    "effective_my_sevn_sync",
    "persist_my_sevn_repo_path",
    "resolve_my_sevn_repo_path",
]
