"""Concrete stdio MCP client implementing :class:`McpStdioClient` (`specs/11-tools-registry.md` §2.7, §10.2).

Opens a subprocess per ``call_tool`` invocation (spawn-per-call model).  Per-call spawning
keeps the implementation simple and correct; a persistent session-pool can be layered on
later without changing the :class:`McpStdioClient` Protocol contract.

Module: sevn.tools.mcp_stdio_client
Depends: sevn.tools.runtime_dispatch, sevn.tools.base, sevn.tools.context, mcp

Exports:
    SevnMcpStdioClient — concrete :class:`McpStdioClient` implementation over subprocess stdio.
    build_mcp_stdio_client — factory returning a client bound to ``mcp_servers`` rows.
    list_tools_from_server — discover ``ToolDefinition`` rows from a single MCP server.
    discover_mcp_tool_definitions — build ``extra_mcp`` tuples from all configured servers.

Examples:
    >>> from pathlib import Path
    >>> c = SevnMcpStdioClient(mcp_servers={})
    >>> c.mcp_server_ids
    []
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from loguru import logger
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from sevn.tools.base import ToolDefinition

if TYPE_CHECKING:
    from sevn.tools.context import ToolContext

_MCP_CALL_TIMEOUT_S: float = 30.0
"""Per-call stdio subprocess timeout (seconds)."""

_MCP_DISCOVER_TIMEOUT_S: float = 10.0
"""Timeout for ``list_tools`` discovery at boot (seconds)."""


class SevnMcpStdioClient:
    """Concrete :class:`~sevn.tools.runtime_dispatch.McpStdioClient` backed by subprocess stdio.

    Each :meth:`call_tool` invocation spawns a new subprocess, sends ``initialize`` +
    ``tools/call``, then terminates.  This is the simplest correct implementation; a
    persistent-session variant can replace it transparently (same Protocol interface).

    Args:
        mcp_servers (Mapping[str, Mapping[str, Any]]): Server id → ``{command, args}`` rows
            read from workspace config (``mcp_servers`` key or ``build_effective_mcp_servers``).
    """

    def __init__(self, mcp_servers: Mapping[str, Mapping[str, Any]]) -> None:
        """Bind to the declared server map.

        Args:
            mcp_servers (Mapping[str, Mapping[str, Any]]): server_id → ``{command, args}`` rows.

        Returns:
            None

        Examples:
            >>> c = SevnMcpStdioClient({"srv": {"command": "echo", "args": []}})
            >>> c.mcp_server_ids
            ['srv']
        """
        self._servers: dict[str, dict[str, Any]] = {k: dict(v) for k, v in mcp_servers.items()}

    @property
    def mcp_server_ids(self) -> list[str]:
        """Return declared server ids.

        Returns:
            list[str]: Stable server id list.

        Examples:
            >>> c = SevnMcpStdioClient({"a": {"command": "echo", "args": []}, "b": {"command": "cat", "args": []}})
            >>> sorted(c.mcp_server_ids)
            ['a', 'b']
        """
        return list(self._servers)

    def _server_params(self, server_id: str) -> tuple[str, list[str]] | None:
        """Return ``(command, args)`` for ``server_id``, or ``None`` when undeclared.

        Args:
            server_id (str): Stable server id from ``mcp_servers`` config.

        Returns:
            tuple[str, list[str]] | None: Command and argv tail, or ``None``.

        Examples:
            >>> c = SevnMcpStdioClient({"s": {"command": "mcp-server", "args": ["--flag"]}})
            >>> c._server_params("s")
            ('mcp-server', ['--flag'])
            >>> c._server_params("missing") is None
            True
        """
        row = self._servers.get(server_id)
        if row is None:
            return None
        command = str(row.get("command") or "").strip()
        if not command:
            return None
        args_raw = row.get("args")
        args: list[str] = [str(a) for a in args_raw] if isinstance(args_raw, list) else []
        return command, args

    async def call_tool(
        self,
        *,
        server_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        ctx: ToolContext,
    ) -> Mapping[str, Any]:
        """Spawn an MCP stdio subprocess and invoke ``tool_name``.

        Opens the subprocess, runs ``initialize`` + ``tools/call``, returns decoded payload.
        On transport failure or timeout the caller receives a typed error mapping; the
        :class:`~sevn.tools.runtime_dispatch.McpStdioTool` wrapper converts this to an
        ``MCP_UNAVAILABLE`` envelope.

        Args:
            server_id (str): Stable ``mcp_servers`` key.
            tool_name (str): Upstream MCP tool name (without server prefix).
            arguments (Mapping[str, Any]): JSON-safe arguments forwarded verbatim.
            ctx (ToolContext): Active runtime frame (used for timeout / cancellation).

        Returns:
            Mapping[str, Any]: Decoded result payload.  When ``isError`` is set by the
            server, the mapping includes ``{"error": <text>}``; callers should handle
            this like a typed error response rather than raising.

        Raises:
            RuntimeError: When ``server_id`` is not in ``mcp_servers``, or on unrecoverable
                transport failure (so :class:`McpStdioTool` wraps it in ``MCP_UNAVAILABLE``).

        Examples:
            >>> import asyncio, inspect
            >>> inspect.iscoroutinefunction(SevnMcpStdioClient.call_tool)
            True
        """
        _ = ctx
        params = self._server_params(server_id)
        if params is None:
            msg = f"MCP server '{server_id}' not declared in mcp_servers"
            raise RuntimeError(msg)
        command, args = params

        sp = StdioServerParameters(command=command, args=args)
        async with asyncio.timeout(_MCP_CALL_TIMEOUT_S):
            async with stdio_client(sp) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        name=tool_name,
                        arguments=dict(arguments),
                    )

        if result.isError:
            # Surface server-side errors as a plain mapping so McpStdioTool wraps them
            # into MCP_UNAVAILABLE rather than letting them propagate as exceptions.
            parts: list[str] = []
            for item in result.content:
                text = getattr(item, "text", None)
                if text:
                    parts.append(str(text))
            return {"error": " ".join(parts) or "MCP server reported isError=True"}

        # Flatten content list to a JSON-safe mapping.
        texts: list[str] = []
        blobs: list[dict[str, Any]] = []
        for item in result.content:
            text = getattr(item, "text", None)
            if text is not None:
                texts.append(str(text))
                continue
            # ImageContent / EmbeddedResource / AudioContent — serialize to dict
            try:
                blobs.append(json.loads(item.model_dump_json()))
            except Exception:
                blobs.append({"type": type(item).__name__})

        if texts and not blobs:
            # Common case: single text response — try to parse as JSON, else return as text.
            combined = "\n".join(texts)
            try:
                decoded = json.loads(combined)
                if isinstance(decoded, dict):
                    return decoded
            except (json.JSONDecodeError, ValueError):
                pass
            return {"text": combined}

        return {"texts": texts, "blobs": blobs}


async def list_tools_from_server(
    server_id: str,
    command: str,
    args: list[str],
    *,
    timeout_s: float = _MCP_DISCOVER_TIMEOUT_S,
) -> list[ToolDefinition]:
    """Discover ``ToolDefinition`` rows by calling ``tools/list`` on one MCP server.

    Args:
        server_id (str): Stable server id used to prefix tool names (``server_id.tool_name``).
        command (str): Executable for the MCP server subprocess.
        args (list[str]): argv tail.
        timeout_s (float): Discovery timeout.  Defaults to ``_MCP_DISCOVER_TIMEOUT_S``.

    Returns:
        list[ToolDefinition]: Prefixed descriptors; empty on transport error.

    Examples:
        >>> import asyncio, inspect
        >>> inspect.iscoroutinefunction(list_tools_from_server)
        True
    """
    try:
        sp = StdioServerParameters(command=command, args=args)
        async with asyncio.timeout(timeout_s):
            async with stdio_client(sp) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()

        out: list[ToolDefinition] = []
        for tool in tools_result.tools:
            qualified_name = f"{server_id}.{tool.name}"
            out.append(
                ToolDefinition(
                    name=qualified_name,
                    category="mcp",
                    description=tool.description or f"MCP tool from {server_id}",
                    parameters=dict(tool.inputSchema),
                    enabled=True,
                )
            )
        return out
    except Exception as exc:
        # Broad catch: MCP transport errors (McpError, ExceptionGroup wrapping McpError),
        # OS/timeout/type errors — all are soft failures at discovery time.  The server
        # will produce McpUnavailableTool placeholders at runtime instead of crashing boot.
        logger.warning(
            "mcp_stdio_discover: server_id=%s command=%s failed: %s",
            server_id,
            command,
            exc,
        )
        return []


async def discover_mcp_tool_definitions(
    mcp_servers: Mapping[str, Mapping[str, Any]],
    *,
    timeout_s: float = _MCP_DISCOVER_TIMEOUT_S,
) -> tuple[ToolDefinition, ...]:
    """Probe each declared MCP server and collect their tool descriptors.

    Unreachable servers are silently skipped — the caller can still pass the returned
    definitions as ``extra_mcp`` to ``build_session_registry``; a missing server will
    produce :class:`~sevn.tools.registry.McpUnavailableTool` placeholders at runtime
    since its ``server_id`` won't appear in ``RuntimeToolBindings.mcp_servers``.

    Args:
        mcp_servers (Mapping[str, Mapping[str, Any]]): Server id → ``{command, args}`` rows.
        timeout_s (float): Per-server discovery timeout.

    Returns:
        tuple[ToolDefinition, ...]: Flattened discovered tool definitions.

    Examples:
        >>> import asyncio
        >>> asyncio.run(discover_mcp_tool_definitions({}))
        ()
    """
    if not mcp_servers:
        return ()

    tasks: list[tuple[str, asyncio.Task[list[ToolDefinition]]]] = []
    async with asyncio.TaskGroup() as tg:
        for server_id, spec in mcp_servers.items():
            if not isinstance(spec, dict):
                continue
            command = str(spec.get("command") or "").strip()
            if not command:
                continue
            args_raw = spec.get("args")
            args: list[str] = [str(a) for a in args_raw] if isinstance(args_raw, list) else []
            task = tg.create_task(
                list_tools_from_server(server_id, command, args, timeout_s=timeout_s)
            )
            tasks.append((server_id, task))

    all_definitions: list[ToolDefinition] = []
    for _sid, task in tasks:
        all_definitions.extend(task.result())
    return tuple(all_definitions)


def build_mcp_stdio_client(
    mcp_servers: Mapping[str, Mapping[str, Any]],
) -> SevnMcpStdioClient | None:
    """Return a bound :class:`SevnMcpStdioClient` when servers are declared, else ``None``.

    The factory is the seam for :class:`~sevn.tools.runtime_dispatch.RuntimeToolBindings`
    that W3 folds into its single boot factory.  Pass the result directly as
    ``RuntimeToolBindings(mcp=build_mcp_stdio_client(servers), mcp_servers=servers)``.

    Args:
        mcp_servers (Mapping[str, Mapping[str, Any]]): Effective server map from
            :func:`~sevn.code_understanding.graphify_mcp.build_effective_mcp_servers` or
            equivalent.

    Returns:
        SevnMcpStdioClient | None: Live client, or ``None`` when no servers are declared.

    Examples:
        >>> build_mcp_stdio_client({}) is None
        True
        >>> c = build_mcp_stdio_client({"srv": {"command": "echo", "args": []}})
        >>> isinstance(c, SevnMcpStdioClient)
        True
    """
    if not mcp_servers:
        return None
    return SevnMcpStdioClient(mcp_servers)


__all__ = [
    "SevnMcpStdioClient",
    "build_mcp_stdio_client",
    "discover_mcp_tool_definitions",
    "list_tools_from_server",
]
