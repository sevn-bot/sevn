"""code-review-graph MCP stdio registration (`specs/28-code-understanding.md` §3.4, §4.5).

Exports:
    code_review_graph_mcp_enabled — explicit MCP opt-in gate.
    code_review_graph_mcp_server_id — stable ``mcp_servers`` key.
    read_only_tool_names — curated upstream tool ids for ``read_only`` preset.
    resolve_repo_root — resolve ``repo_root`` against workspace layout.
    validate_repo_root — path allowlist + ``.llmignore`` rejection.
    build_serve_argv — fixed ``serve`` argv (never model-supplied).
    resolve_command — ``argv[0]`` from extra or operator override.
    mcp_stdio_entry — ``{command, args}`` row for ``mcp_servers``.
    merge_code_review_graph_mcp_server — inject stdio row into a config document.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sevn.code_understanding.models import CodeReviewGraphSettings  # noqa: TC001
from sevn.config.defaults import (
    CODE_REVIEW_GRAPH_READ_ONLY_TOOLS,
    DEFAULT_CODE_REVIEW_GRAPH_COMMAND,
    DEFAULT_CODE_REVIEW_GRAPH_MCP_SERVER_ID,
    DEFAULT_CODE_REVIEW_GRAPH_TOOL_PRESET,
)
from sevn.config.workspace_config import WorkspaceConfig  # noqa: TC001
from sevn.tools.paths import ensure_path_not_under_llmignore

_ALLOWED_TOOL_PRESETS: frozenset[str] = frozenset({"read_only", "full"})


def code_review_graph_mcp_enabled(workspace: WorkspaceConfig) -> bool:
    """Return True when code-review-graph MCP opt-in is active.

    Requires ``code_understanding.code_review_graph.enabled`` and explicit
    ``code_understanding.code_review_graph.mcp.enabled``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace.

    Returns:
        bool: Whether gateway should register the stdio MCP server.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> code_review_graph_mcp_enabled(WorkspaceConfig.minimal()) is False
        True
    """
    cu = workspace.code_understanding
    if cu is None:
        return False
    crg = cu.code_review_graph
    if not crg.enabled:
        return False
    mcp = crg.mcp
    if not isinstance(mcp, dict):
        return False
    return bool(mcp.get("enabled"))


def code_review_graph_mcp_server_id() -> str:
    """Return the stable ``mcp_servers`` id for code-review-graph.

    Returns:
        str: Server id (``code_review_graph``).

    Examples:
        >>> code_review_graph_mcp_server_id()
        'code_review_graph'
    """
    return DEFAULT_CODE_REVIEW_GRAPH_MCP_SERVER_ID


def read_only_tool_names() -> list[str]:
    """Return the curated read-only MCP tool id list per spec §4.5.

    Returns:
        list[str]: Upstream tool names (copy).

    Examples:
        >>> "get_minimal_context_tool" in read_only_tool_names()
        True
        >>> "apply_refactor_tool" not in read_only_tool_names()
        True
    """
    return list(CODE_REVIEW_GRAPH_READ_ONLY_TOOLS)


def resolve_repo_root(
    settings: CodeReviewGraphSettings,
    content_root: Path,
) -> Path:
    """Resolve ``repo_root`` against the workspace content root.

    Args:
        settings (CodeReviewGraphSettings): Parsed ``code_review_graph`` subtree.
        content_root (Path): Workspace content root.

    Returns:
        Path: Absolute repo root (defaults to ``content_root`` when unset).

    Examples:
        >>> from pathlib import Path as _P
        >>> from sevn.code_understanding.models import CodeReviewGraphSettings
        >>> root = resolve_repo_root(CodeReviewGraphSettings(), _P("/w"))
        >>> root == _P("/w").resolve()
        True
    """
    root = content_root if settings.repo_root is None else (content_root / settings.repo_root)
    return root.expanduser().resolve()


def validate_repo_root(repo_root: Path, content_root: Path) -> Path:
    """Ensure ``repo_root`` is under the workspace allowlist and not ``.llmignore``.

    Args:
        repo_root (Path): Candidate absolute or relative repo root.
        content_root (Path): Workspace content root (allowlist anchor).

    Returns:
        Path: Resolved absolute path when allowed.

    Raises:
        ValueError: When the path escapes the workspace or falls under ``.llmignore/``.

    Examples:
        >>> from pathlib import Path as _P
        >>> ws = _P("/tmp/ws")
        >>> allowed = validate_repo_root(ws / "repo", ws)
        >>> allowed == (ws / "repo").resolve()
        True
    """
    resolved = repo_root.expanduser().resolve()
    workspace_abs = content_root.expanduser().resolve()
    try:
        resolved.relative_to(workspace_abs)
    except ValueError as exc:
        msg = (
            f"code_review_graph: repo_root {resolved!s} is outside workspace "
            f"allowlist ({workspace_abs!s})"
        )
        raise ValueError(msg) from exc
    try:
        return ensure_path_not_under_llmignore(resolved, workspace_abs)
    except PermissionError as exc:
        msg = f"code_review_graph: repo_root rejected — {exc}"
        raise ValueError(msg) from exc


def build_serve_argv(
    settings: CodeReviewGraphSettings,
    repo_root: Path,
) -> list[str]:
    """Build fixed ``code-review-graph serve`` argv from config (§4.5).

    Args:
        settings (CodeReviewGraphSettings): Parsed subtree (``tool_preset`` validated).
        repo_root (Path): Validated absolute repo root for ``--repo``.

    Returns:
        list[str]: Args after ``argv[0]`` (subcommand + flags only).

    Raises:
        ValueError: When ``tool_preset`` is not ``read_only`` or ``full``.

    Examples:
        >>> from pathlib import Path as _P
        >>> from sevn.code_understanding.models import CodeReviewGraphSettings
        >>> argv = build_serve_argv(CodeReviewGraphSettings(tool_preset="read_only"), _P("/r"))
        >>> argv[0:3]
        ['serve', '--repo', '/r']
        >>> '--tools' in argv
        True
    """
    preset = settings.tool_preset or DEFAULT_CODE_REVIEW_GRAPH_TOOL_PRESET
    if preset not in _ALLOWED_TOOL_PRESETS:
        allowed = sorted(_ALLOWED_TOOL_PRESETS)
        msg = f"code_review_graph: unsupported tool_preset {preset!r}; allowed: {allowed}"
        raise ValueError(msg)
    argv: list[str] = ["serve", "--repo", str(repo_root)]
    if preset == "read_only":
        tools_csv = ",".join(read_only_tool_names())
        argv.extend(["--tools", tools_csv])
    return argv


def resolve_command(settings: CodeReviewGraphSettings) -> str:
    """Return the executable for ``argv[0]`` (extra-shipped or operator override).

    Args:
        settings (CodeReviewGraphSettings): Parsed subtree.

    Returns:
        str: Command name or path.

    Examples:
        >>> from sevn.code_understanding.models import CodeReviewGraphSettings
        >>> resolve_command(CodeReviewGraphSettings()) == DEFAULT_CODE_REVIEW_GRAPH_COMMAND
        True
    """
    if settings.command:
        return settings.command.strip()
    return DEFAULT_CODE_REVIEW_GRAPH_COMMAND


def mcp_stdio_entry(
    workspace: WorkspaceConfig,
    content_root: Path,
) -> dict[str, str | list[str]] | None:
    """Build an ``mcp_servers`` stdio row when registration is active.

    Args:
        workspace (WorkspaceConfig): Parsed workspace.
        content_root (Path): Workspace content root for ``repo_root`` resolution.

    Returns:
        dict[str, str | list[str]] | None: ``{command, args}`` or ``None`` when gated off.

    Examples:
        >>> from pathlib import Path as _P
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> mcp_stdio_entry(WorkspaceConfig.minimal(), _P("/w")) is None
        True
    """
    if not code_review_graph_mcp_enabled(workspace):
        return None
    cu = workspace.code_understanding
    if cu is None:
        return None
    settings = cu.code_review_graph
    repo = validate_repo_root(resolve_repo_root(settings, content_root), content_root)
    return {
        "command": resolve_command(settings),
        "args": build_serve_argv(settings, repo),
    }


def merge_code_review_graph_mcp_server(
    config_doc: dict[str, Any],
    *,
    workspace: WorkspaceConfig,
    content_root: Path,
) -> None:
    """Inject code-review-graph stdio registration into ``config_doc`` (in-place).

    Args:
        config_doc (dict[str, Any]): Effective or preview config document.
        workspace (WorkspaceConfig): Parsed workspace.
        content_root (Path): Workspace content root.

    Returns:
        None

    Examples:
        >>> from pathlib import Path as _P
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> doc: dict[str, object] = {}
        >>> merge_code_review_graph_mcp_server(
        ...     doc, workspace=WorkspaceConfig.minimal(), content_root=_P("/w")
        ... )
        >>> doc.get("mcp_servers") is None
        True
    """
    entry = mcp_stdio_entry(workspace, content_root)
    if entry is None:
        return
    servers_raw = config_doc.get("mcp_servers")
    servers: dict[str, Any] = dict(servers_raw) if isinstance(servers_raw, dict) else {}
    servers[code_review_graph_mcp_server_id()] = entry
    config_doc["mcp_servers"] = servers


__all__ = [
    "build_serve_argv",
    "code_review_graph_mcp_enabled",
    "code_review_graph_mcp_server_id",
    "mcp_stdio_entry",
    "merge_code_review_graph_mcp_server",
    "read_only_tool_names",
    "resolve_command",
    "resolve_repo_root",
    "validate_repo_root",
]
