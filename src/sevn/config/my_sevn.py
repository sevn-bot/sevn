"""``my_sevn`` config helpers (`specs/35-bot-evolution.md`).

Module: sevn.config.my_sevn
Depends: sevn.config.workspace_config

Exports:
    effective_my_sevn — resolve typed ``my_sevn`` block with defaults.
    effective_my_sevn_executors — resolve typed ``my_sevn.executors`` with defaults.
    effective_my_sevn_issues — resolve typed ``my_sevn.issues`` with defaults.
    effective_my_sevn_pipelines — resolve typed ``my_sevn.pipelines`` with defaults.
    effective_my_sevn_sync — resolve typed ``my_sevn.sync`` with defaults.
    default_github_repo_slug — ``owner/repo`` from ``my_sevn.repo_url`` (no ``git remote``).
    resolve_github_repo_slug — explicit arg or ``my_sevn.repo_url`` (shared by gh scripts).
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


def default_github_repo_slug(ws: WorkspaceConfig) -> str:
    """Return ``owner/repo`` from ``my_sevn.repo_url`` without shelling out to git.

    Tools and gh-issue scripts must use this (or the equivalent config field)
    instead of ``git remote`` against the read-only ``source_code/`` mirror.

    Accepts HTTPS (``https://github.com/owner/repo``), SCP
    (``git@host:owner/repo.git``), and bare ``owner/repo`` forms.

    Args:
        ws (WorkspaceConfig): Parsed workspace root model.

    Returns:
        str: GitHub slug such as ``sevn-bot/sevn``.

    Raises:
        ValueError: When ``my_sevn.repo_url`` cannot be parsed as ``owner/repo``.

    Examples:
        >>> default_github_repo_slug(WorkspaceConfig.minimal())
        'sevn-bot/sevn'
        >>> from sevn.config.sections.evolution import MySevnWorkspaceConfig
        >>> ws = WorkspaceConfig.minimal()
        >>> ws.my_sevn = MySevnWorkspaceConfig(repo_url="git@github.com:acme/app.git")
        >>> default_github_repo_slug(ws)
        'acme/app'
    """
    raw = (effective_my_sevn(ws).repo_url or "").strip()
    if not raw:
        msg = "my_sevn.repo_url is empty"
        raise ValueError(msg)
    # Keep this helper free of integrations/tools imports (lint-imports contracts).
    lowered = raw.lower()
    # SCP-style: git@host:owner/repo(.git) — colon separates host from path.
    if "@" in raw and "://" not in raw and ":" in raw.split("@", 1)[-1]:
        tail = raw.rsplit(":", 1)[-1]
    elif "github.com/" in lowered:
        tail = raw[lowered.index("github.com/") + len("github.com/") :]
    else:
        tail = raw
    parts = [p for p in tail.split("/") if p]
    if len(parts) < 2:
        msg = f"cannot parse owner/repo from my_sevn.repo_url: {raw!r}"
        raise ValueError(msg)
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    return f"{owner}/{repo}"


def resolve_github_repo_slug(
    explicit: str | None = None,
    *,
    workspace: Path | None = None,
    ws: WorkspaceConfig | None = None,
) -> str:
    """Return ``owner/repo`` from an explicit arg or ``my_sevn.repo_url``.

    Shared by gh-issues scripts so each does not duplicate slug resolution.

    Args:
        explicit (str | None, optional): Explicit ``owner/repo`` when provided.
        workspace (Path | None, optional): Workspace root (loads ``sevn.json``).
        ws (WorkspaceConfig | None, optional): Pre-loaded config (skips disk load).

    Returns:
        str: GitHub ``owner/repo`` slug.

    Raises:
        ValueError: When neither explicit nor config yields a parseable slug.

    Examples:
        >>> resolve_github_repo_slug("acme/app")
        'acme/app'
        >>> resolve_github_repo_slug(ws=WorkspaceConfig.minimal())
        'sevn-bot/sevn'
    """
    if explicit and explicit.strip():
        return explicit.strip()
    if ws is not None:
        return default_github_repo_slug(ws)
    if workspace is not None:
        from sevn.config.loader import load_workspace

        cfg, _layout = load_workspace(sevn_json=workspace / "sevn.json")
        return default_github_repo_slug(cfg)
    from sevn.lcm.script_cli import workspace_from_env

    root = workspace_from_env()
    from sevn.config.loader import load_workspace

    cfg, _layout = load_workspace(sevn_json=root / "sevn.json")
    return default_github_repo_slug(cfg)


__all__ = [
    "default_github_repo_slug",
    "effective_my_sevn",
    "effective_my_sevn_executors",
    "effective_my_sevn_issues",
    "effective_my_sevn_pipelines",
    "effective_my_sevn_sync",
    "persist_my_sevn_repo_path",
    "resolve_github_repo_slug",
    "resolve_my_sevn_repo_path",
]
