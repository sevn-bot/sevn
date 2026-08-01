"""Stable ``mcp__server__tool`` qualified names for MCP registry rows (#90, W29.1).

Module: sevn.tools.mcp_naming
Depends: none

Exports:
    format_mcp_tool_name — build ``mcp__<server>__<tool>`` names.
    parse_mcp_qualified_name — split qualified names into server + upstream tool.
    upstream_mcp_tool_name — upstream MCP tool id from a registry name.
    mcp_server_id_from_tool_name — server id for dispatch (new + legacy dot form).
"""

from __future__ import annotations

MCP_QUALIFIED_PREFIX: str = "mcp__"
"""Prefix for MCP tools in the session registry (``specs/11-tools-registry.md`` §10.2 W29)."""


def format_mcp_tool_name(server_id: str, tool_name: str) -> str:
    """Return the stable qualified MCP tool name ``mcp__<server>__<tool>``.

    Args:
        server_id (str): Stable ``mcp_servers`` key.
        tool_name (str): Upstream MCP tool name (without server prefix).

    Returns:
        str: Qualified registry identifier.

    Examples:
        >>> format_mcp_tool_name("graphify", "query")
        'mcp__graphify__query'
    """
    return f"{MCP_QUALIFIED_PREFIX}{server_id}__{tool_name}"


def parse_mcp_qualified_name(qualified: str) -> tuple[str, str] | None:
    """Parse ``mcp__<server>__<tool>`` into server id and upstream tool name.

    Args:
        qualified (str): Registry tool name.

    Returns:
        tuple[str, str] | None: ``(server_id, tool_name)`` when the prefix matches.

    Examples:
        >>> parse_mcp_qualified_name("mcp__code_review_graph__get_minimal_context_tool")
        ('code_review_graph', 'get_minimal_context_tool')
        >>> parse_mcp_qualified_name("legacy.server.tool") is None
        True
    """
    if not qualified.startswith(MCP_QUALIFIED_PREFIX):
        return None
    rest = qualified[len(MCP_QUALIFIED_PREFIX) :]
    server_id, sep, tool_name = rest.partition("__")
    if not sep or not server_id or not tool_name:
        return None
    return server_id, tool_name


def upstream_mcp_tool_name(qualified: str) -> str:
    """Return the upstream MCP tool id from a registry-qualified name.

    Supports the W29 ``mcp__server__tool`` form and the legacy ``server.tool`` dot form.

    Args:
        qualified (str): Registry tool name.

    Returns:
        str: Upstream MCP tool name for ``tools/call``.

    Examples:
        >>> upstream_mcp_tool_name("mcp__demo__ping")
        'ping'
        >>> upstream_mcp_tool_name("demo.ping")
        'ping'
    """
    parsed = parse_mcp_qualified_name(qualified)
    if parsed is not None:
        return parsed[1]
    _head, sep, tail = qualified.partition(".")
    return tail if sep else qualified


def mcp_server_id_from_tool_name(tool_name: str) -> str:
    """Extract the MCP server id from a registry tool name.

    Args:
        tool_name (str): Registry tool name (``mcp__server__tool`` or legacy ``server.tool``).

    Returns:
        str: Server id substring.

    Examples:
        >>> mcp_server_id_from_tool_name("mcp__code_review_graph__get_minimal_context_tool")
        'code_review_graph'
        >>> mcp_server_id_from_tool_name("code_review_graph.get_minimal_context_tool")
        'code_review_graph'
    """
    parsed = parse_mcp_qualified_name(tool_name)
    if parsed is not None:
        return parsed[0]
    head, sep, _tail = tool_name.partition(".")
    return head if sep else tool_name


__all__ = [
    "MCP_QUALIFIED_PREFIX",
    "format_mcp_tool_name",
    "mcp_server_id_from_tool_name",
    "parse_mcp_qualified_name",
    "upstream_mcp_tool_name",
]
