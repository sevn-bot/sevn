"""Agent tool for filing evolution issues (`specs/35-bot-evolution.md` EV-4).

Module: sevn.tools.evolution_issues
Depends: sevn.evolution.issues, sevn.tools.base, sevn.tools.context, sevn.tools.decorator

Exports:
    file_evolution_issue_tool — create a local bug/feature issue (optional GitHub mirror).
    register_evolution_issue_tools — register on a ``ToolExecutor``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from sevn.config.workspace_config import WorkspaceConfig
from sevn.evolution.issues import (
    create_issue,
    issue_to_api_dict,
    maybe_mirror_issue_to_github,
)
from sevn.tools.base import enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool, tool_from_decorated
from sevn.workspace.layout import WorkspaceLayout

if TYPE_CHECKING:
    from sevn.tools.base import ToolExecutor

_REGISTERED_WORKSPACE_CONFIG: WorkspaceConfig | None = None

_FILE_EVOLUTION_ISSUE_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": ["bug", "feature"],
            "description": "Issue kind — routes bug vs feature pipeline.",
        },
        "title": {"type": "string", "description": "Short issue title."},
        "body": {
            "type": "string",
            "description": "Optional markdown body (traces, repro steps).",
        },
    },
    "required": ["kind", "title"],
    "additionalProperties": False,
}


def _layout_from_tool_ctx(ctx: ToolContext, ws: WorkspaceConfig | None) -> WorkspaceLayout | None:
    """Resolve workspace layout from tool context.

    Args:
        ctx (ToolContext): Active tool invocation context.
        ws (WorkspaceConfig | None): Parsed workspace config when available.

    Returns:
        WorkspaceLayout | None: Layout or ``None`` when ``sevn.json`` is missing.

    Examples:
        >>> _layout_from_tool_ctx.__name__
        '_layout_from_tool_ctx'
    """
    if ws is None:
        return None
    sevn_json = ctx.workspace_path / "sevn.json"
    if not sevn_json.is_file():
        return None
    return WorkspaceLayout.from_config(sevn_json, ws)


@sevn_tool(
    name="file_evolution_issue",
    category="evolution",
    description="File a bug or feature evolution issue (local JSON; optional GitHub mirror).",
    parameters=_FILE_EVOLUTION_ISSUE_PARAMS,
    sandbox_mode="none",
)
async def file_evolution_issue_tool(
    ctx: ToolContext,
    *,
    kind: Literal["bug", "feature"],
    title: str,
    body: str = "",
) -> str:
    """Create one evolution issue under ``workspace/.sevn/issues/``.

    Args:
        ctx (ToolContext): Tool execution context.
        kind (Literal["bug", "feature"]): Issue kind.
        title (str): Short title.
        body (str, optional): Markdown body. Defaults to empty string.

    Returns:
        str: JSON tool envelope with created issue payload.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(file_evolution_issue_tool)
        True
    """
    title_clean = title.strip()
    if not title_clean:
        return enveloped_failure("title must be non-empty", code=ToolResultCode.VALIDATION_ERROR)
    ws = _REGISTERED_WORKSPACE_CONFIG
    layout = _layout_from_tool_ctx(ctx, ws)
    if layout is None or ws is None:
        return enveloped_failure(
            "workspace layout unavailable",
            code=ToolResultCode.MCP_UNAVAILABLE,
        )
    issue = create_issue(
        layout,
        kind=kind,
        title=title_clean,
        body=body,
        source="agent",
        ws=ws,
    )
    issue = await maybe_mirror_issue_to_github(layout, issue, ws)
    return enveloped_success({"issue": issue_to_api_dict(issue)})


_EVOLUTION_ISSUE_TOOLS = (file_evolution_issue_tool,)


def register_evolution_issue_tools(
    executor: ToolExecutor,
    workspace_config: WorkspaceConfig | None = None,
) -> None:
    """Register ``file_evolution_issue`` on the session tool executor.

    Args:
        executor (ToolExecutor): Registry under construction.
        workspace_config (WorkspaceConfig | None): Parsed workspace config for layout resolution.

    Returns:
        None

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.evolution_issues import register_evolution_issue_tools
        >>> exe = ToolExecutor()
        >>> register_evolution_issue_tools(exe)
        >>> "file_evolution_issue" in {d.name for d in exe.definitions()}
        True
    """
    global _REGISTERED_WORKSPACE_CONFIG
    _REGISTERED_WORKSPACE_CONFIG = workspace_config
    for tool_fn in _EVOLUTION_ISSUE_TOOLS:
        executor.register(tool_from_decorated(tool_fn))


__all__ = [
    "file_evolution_issue_tool",
    "register_evolution_issue_tools",
]
