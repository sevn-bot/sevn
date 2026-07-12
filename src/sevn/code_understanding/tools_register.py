"""Register code-understanding native tools (`specs/28-code-understanding.md` §2.2).

Tools are registered only when the corresponding ``code_understanding.*`` toggle
is **enabled**. Implementations return explicit JSON envelopes (never silent
no-ops) until Memgraph / subprocess / roam-code wiring lands.

Module: sevn.code_understanding.tools_register
Depends: sevn.config.workspace_config, sevn.tools.*

Exports:
    register_code_understanding_tools — append tools to a ``ToolExecutor``.
    legacy_native_code_graph_rag_enabled — read ``tools.legacy_native.code_graph_rag`` flag.
    legacy_native_roam_code_enabled — read ``tools.legacy_native.roam_code`` flag.
    code_graph_rag_read_export_tool — capped export reader stub (``@sevn_tool``).
    code_graph_rag_cli_tool — allowlisted ``cgr`` argv stub (``@sevn_tool``).
    roam_code_tool — roam-code adapter bridge (``@sevn_tool``).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sevn.code_understanding.cgr_adapter import build_cgr_argv, read_export_capped
from sevn.code_understanding.cgr_runner import read_export_file, run_cgr_subprocess
from sevn.code_understanding.roam_runner import run_roam_query_async
from sevn.tools.base import ToolExecutor, enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool, tool_from_decorated

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

_CGR_READ_EXPORT_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Filter or search hint for export slice."},
        "max_bytes": {"type": "integer", "minimum": 1, "default": 65536},
    },
    "required": [],
    "additionalProperties": False,
}

_CGR_CLI_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subcommand": {
            "type": "string",
            "enum": ["export", "stats", "doctor", "graph-loader"],
        },
    },
    "required": ["subcommand"],
    "additionalProperties": False,
}

_ROAM_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Repository root to query (resolved by caller)."},
        "query": {"type": ["string", "null"]},
    },
    "required": [],
    "additionalProperties": False,
}


def _index_root_for_ctx(ctx: ToolContext) -> Path:
    """Return preferred repo index root for code-understanding artefacts.

    Args:
        ctx (ToolContext): Tool execution context.

    Returns:
        Path: Workspace root (source lives at ``source_code/`` within it).

    Examples:
        >>> from pathlib import Path
        >>> from sevn.tools.permissions import AllowAllPermissionPolicy
        >>> c = ToolContext(
        ...     session_id="s",
        ...     workspace_path=Path("/tmp/ws"),
        ...     workspace_id="w",
        ...     registry_version=1,
        ...     trace=None,
        ...     permissions=AllowAllPermissionPolicy(),
        ... )
        >>> _index_root_for_ctx(c).as_posix().endswith("/tmp/ws")
        True
    """
    return ctx.workspace_path.resolve()


@sevn_tool(
    name="code_graph_rag_read_export",
    category="code_understanding",
    description="Read a capped slice of the current CGR export (Memgraph wiring pending).",
    parameters=_CGR_READ_EXPORT_PARAMS,
    sandbox_mode="none",
)
async def code_graph_rag_read_export_tool(
    ctx: ToolContext,
    query: str = "",
    max_bytes: int = 65536,
) -> str:
    """Return a failure envelope until export IO is implemented.

    Args:
        ctx (ToolContext): Tool execution context (unused; reserved for tracing).
        query (str, optional): Placeholder filter hint. Defaults to ``""``.
        max_bytes (int, optional): Cap for future export reads. Defaults to ``65536``.

    Returns:
        str: JSON tool envelope string.

    Examples:
        >>> import asyncio, json
        >>> from sevn.tools.context import ToolContext
        >>> from sevn.tools.permissions import AllowAllPermissionPolicy
        >>> from pathlib import Path
        >>> ctx = ToolContext(
        ...     session_id="s",
        ...     workspace_path=Path("/tmp"),
        ...     workspace_id="w",
        ...     registry_version=1,
        ...     trace=None,
        ...     permissions=AllowAllPermissionPolicy(),
        ... )
        >>> out = asyncio.run(code_graph_rag_read_export_tool(ctx))
        >>> json.loads(out)["ok"]
        False
    """

    export_path = _index_root_for_ctx(ctx) / ".index" / "code_graph_rag" / "export.json"
    if export_path.is_file():
        payload = read_export_file(export_path, max_bytes=max_bytes)
        return enveloped_success(
            {
                "bytes": len(payload),
                "query": query,
                "preview": payload[: min(len(payload), 4096)].decode("utf-8", errors="replace"),
            }
        )
    try:
        code, stdout, stderr = await run_cgr_subprocess("export")
    except FileNotFoundError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.MCP_UNAVAILABLE)
    if code != 0:
        return enveloped_failure(
            stderr.decode("utf-8", errors="replace") or f"cgr export exited {code}",
            code=ToolResultCode.MCP_UNAVAILABLE,
        )
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_bytes(stdout)
    payload = read_export_capped(stdout, max_bytes)
    return enveloped_success(
        {
            "bytes": len(payload),
            "query": query,
            "preview": payload[: min(len(payload), 4096)].decode("utf-8", errors="replace"),
        }
    )


@sevn_tool(
    name="code_graph_rag_cli",
    category="code_understanding",
    description="Invoke allowlisted cgr subcommands only (subprocess wiring pending).",
    parameters=_CGR_CLI_PARAMS,
    sandbox_mode="subprocess",
)
async def code_graph_rag_cli_tool(
    ctx: ToolContext,
    subcommand: Literal["export", "stats", "doctor", "graph-loader"],
) -> str:
    """Validate argv via :func:`build_cgr_argv` then refuse until subprocess ships.

    Args:
        ctx (ToolContext): Tool execution context (unused).
        subcommand (Literal[...]): Allowlisted ``cgr`` subcommand.

    Returns:
        str: JSON tool envelope string.

    Examples:
        >>> import asyncio, json
        >>> from sevn.tools.context import ToolContext
        >>> from sevn.tools.permissions import AllowAllPermissionPolicy
        >>> from pathlib import Path
        >>> ctx = ToolContext(
        ...     session_id="s",
        ...     workspace_path=Path("/tmp"),
        ...     workspace_id="w",
        ...     registry_version=1,
        ...     trace=None,
        ...     permissions=AllowAllPermissionPolicy(),
        ... )
        >>> out = asyncio.run(code_graph_rag_cli_tool(ctx, subcommand="export"))
        >>> json.loads(out)["ok"]
        False
    """

    _ = build_cgr_argv(subcommand)
    try:
        code, stdout, stderr = await run_cgr_subprocess(subcommand)
    except FileNotFoundError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.MCP_UNAVAILABLE)
    if code != 0:
        return enveloped_failure(
            stderr.decode("utf-8", errors="replace") or f"cgr {subcommand} exited {code}",
            code=ToolResultCode.MCP_UNAVAILABLE,
        )
    return enveloped_success(
        {
            "subcommand": subcommand,
            "stdout": stdout.decode("utf-8", errors="replace")[:8192],
        }
    )


@sevn_tool(
    name="roam_code",
    category="code_understanding",
    description="Lightweight path Q&A via roam-code (legacy native tool; prefer roam_code skill).",
    parameters=_ROAM_PARAMS,
    sandbox_mode="none",
)
async def roam_code_tool(
    ctx: ToolContext,
    path: str = "",
    query: str | None = None,
) -> str:
    """Delegate to :class:`RoamCodeAdapter` using ``ctx.workspace_path`` when path empty.

    Args:
        ctx (ToolContext): Supplies default workspace root when ``path`` is empty.
        path (str, optional): Override repository root. Defaults to ``""``.
        query (str | None, optional): Natural-language question.

    Returns:
        str: JSON success envelope with roam text in ``data.text``.

    Examples:
        >>> import asyncio, json
        >>> from pathlib import Path
        >>> from sevn.tools.context import ToolContext
        >>> from sevn.tools.permissions import AllowAllPermissionPolicy
        >>> ctx = ToolContext(
        ...     session_id="s",
        ...     workspace_path=Path("/tmp/ws"),
        ...     workspace_id="w",
        ...     registry_version=1,
        ...     trace=None,
        ...     permissions=AllowAllPermissionPolicy(),
        ... )
        >>> out = asyncio.run(roam_code_tool(ctx, query="how?"))
        >>> json.loads(out)["ok"]
        True
    """

    root = Path(path).expanduser() if path.strip() else Path(ctx.workspace_path)
    _ok, text = await run_roam_query_async(root.resolve(), query)
    return enveloped_success({"text": text})


def legacy_native_code_graph_rag_enabled(workspace_config: WorkspaceConfig | None) -> bool:
    """Return whether transitional native CGR tools should register.

    Native ``code_graph_rag_*`` tools are deprecated in favour of the bundled
    ``code_graph_rag`` skill. They register only when
    ``tools.legacy_native.code_graph_rag.enabled`` is true (default **false**).

    Args:
        workspace_config (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        bool: ``True`` when the legacy native CGR tool pair should register.

    Examples:
        >>> from sevn.config.workspace_config import parse_workspace_config
        >>> cfg = parse_workspace_config({"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}})
        >>> legacy_native_code_graph_rag_enabled(cfg)
        False
        >>> cfg2 = parse_workspace_config({
        ...     "schema_version": 1,
        ...     "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...     "tools": {"legacy_native": {"code_graph_rag": {"enabled": True}}},
        ... })
        >>> legacy_native_code_graph_rag_enabled(cfg2)
        True
    """
    if workspace_config is None or workspace_config.tools is None:
        return False
    legacy = workspace_config.tools.get("legacy_native")
    if not isinstance(legacy, dict):
        return False
    cgr = legacy.get("code_graph_rag")
    if not isinstance(cgr, dict):
        return False
    return bool(cgr.get("enabled", False))


def legacy_native_roam_code_enabled(workspace_config: WorkspaceConfig | None) -> bool:
    """Return whether transitional native ``roam_code`` should register.

    Native ``roam_code`` is deprecated in favour of the bundled ``roam_code`` skill.
    It registers only when ``tools.legacy_native.roam_code.enabled`` is true
    (default **false**).

    Args:
        workspace_config (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        bool: ``True`` when the legacy native roam tool should register.

    Examples:
        >>> from sevn.config.workspace_config import parse_workspace_config
        >>> cfg = parse_workspace_config({"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}})
        >>> legacy_native_roam_code_enabled(cfg)
        False
        >>> cfg2 = parse_workspace_config({
        ...     "schema_version": 1,
        ...     "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...     "tools": {"legacy_native": {"roam_code": {"enabled": True}}},
        ... })
        >>> legacy_native_roam_code_enabled(cfg2)
        True
    """
    if workspace_config is None or workspace_config.tools is None:
        return False
    legacy = workspace_config.tools.get("legacy_native")
    if not isinstance(legacy, dict):
        return False
    roam = legacy.get("roam_code")
    if not isinstance(roam, dict):
        return False
    return bool(roam.get("enabled", False))


def register_code_understanding_tools(
    executor: ToolExecutor,
    workspace_config: WorkspaceConfig | None,
) -> None:
    """Register native tools gated by ``code_understanding`` toggles.

    Args:
        executor (ToolExecutor): Registry to mutate.
        workspace_config (WorkspaceConfig | None): Parsed workspace; ``None`` skips all.

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.config.workspace_config import parse_workspace_config
        >>> ex = ToolExecutor(default_timeout_seconds=None)
        >>> register_code_understanding_tools(ex, None)
        >>> register_code_understanding_tools(
        ...     ex,
        ...     parse_workspace_config({
        ...         "schema_version": 1,
        ...         "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...         "code_understanding": {
        ...             "code_graph_rag": {"enabled": True},
        ...             "roam_code": {"enabled": False},
        ...         },
        ...         "tools": {"legacy_native": {"code_graph_rag": {"enabled": True}}},
        ...     }),
        ... )
        >>> names = {d.name for d in ex.definitions()}
        >>> "code_graph_rag_read_export" in names
        True
    """

    if workspace_config is None:
        return
    cu = workspace_config.code_understanding
    if cu is None:
        return
    if cu.code_graph_rag.enabled and legacy_native_code_graph_rag_enabled(workspace_config):
        executor.register(tool_from_decorated(code_graph_rag_read_export_tool))
        executor.register(tool_from_decorated(code_graph_rag_cli_tool))
    if cu.roam_code.enabled and legacy_native_roam_code_enabled(workspace_config):
        executor.register(tool_from_decorated(roam_code_tool))


__all__ = [
    "code_graph_rag_cli_tool",
    "code_graph_rag_read_export_tool",
    "legacy_native_code_graph_rag_enabled",
    "legacy_native_roam_code_enabled",
    "register_code_understanding_tools",
    "roam_code_tool",
]
