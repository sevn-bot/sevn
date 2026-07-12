"""Triager helpers for alphabetical tool/skill catalogs (`specs/11-tools-registry.md` §2).

Produces three lexical blocks (**native+MCP manifests**, explicit native vs MCP headings,
skills manifest). Lines target ~80 characters for concise Triager scaffolding.

Module: sevn.agent.triager.tool_index
Depends: sevn.tools.registry

Exports:
    build_tool_index_lines - render native, MCP, and skill blocks alphabetically.

Examples:
    >>> from sevn.agent.triager.tool_index import build_tool_index_lines
    >>> from sevn.tools.registry import ToolSet
    >>> lines = build_tool_index_lines(ToolSet(7, (), (), {}))
    >>> "::TOOLS (native)" in lines[0]
    True
"""

from __future__ import annotations

from sevn.tools.registry import ToolSet


def _render_row(name: str, description: str, *, max_width: int) -> str:
    """Format one ``name - description`` row truncated to ``max_width``.

    Args:
        name (str): Identifier to print at the start of the row.
        description (str): Free-form summary; newlines collapse to spaces.
        max_width (int): Soft truncation target for the full row.

    Returns:
        str: One-line ``name - description`` row, truncated with ``"..."``.

    Examples:
        >>> _render_row("foo", "bar", max_width=80)
        'foo - bar'
        >>> _render_row("foo", "abcdefghijklmnopqrstuv", max_width=20)
        'foo - abcdefghijk...'
    """
    flattened = description.replace("\n", " ").strip()
    overhead = len(name) + 5  # spacing + separators
    budget = max(16, max_width - overhead)
    if len(flattened) > budget:
        flattened = flattened[: budget - 3] + "..."
    return f"{name} - {flattened}".strip()


def build_tool_index_lines(tool_set: ToolSet, *, max_width: int = 500) -> list[str]:
    """Return ``[TOOLS native block, MCP block, SKILL block]`` with blank separators.

            Args:
    tool_set (ToolSet): Session snapshot exposing definitions + manifests.
    max_width (int): Soft truncation target per line (~500 chars by default — wide
        enough to keep a tool's full one-line description, including the discriminating
        tail, so the routing model can tell similar tools apart).

            Returns:
                list[str]: Lines safe for plaintext Triager scaffolding.

            Examples:
                >>> from sevn.tools.base import ToolDefinition
                >>> from sevn.tools.registry import ToolSet
                >>> native = (
                ...     ToolDefinition(
                ...         name="apple",
                ...         category="meta",
                ...         description="alpha tool",
                ...         parameters={"type": "object", "properties": {}},
                ...     ),
                ... )
                >>> mcp = (
                ...     ToolDefinition(
                ...         name="zed.server",
                ...         category="mcp",
                ...         description="remote",
                ...         parameters={"type": "object", "properties": {}},
                ...     ),
                ... )
                >>> ts = ToolSet(
                ...     1,
                ...     tuple(sorted(native, key=lambda item: item.name)),
                ...     tuple(sorted(mcp, key=lambda item: item.name)),
                ...     {"zebra": "skill summary"},
                ... )
                >>> "apple" in "\\n".join(build_tool_index_lines(ts))
                True
    """

    rendered: list[str] = []

    rendered.append("::TOOLS (native)")
    for definition in sorted(tool_set.native, key=lambda row: row.name):
        rendered.append(_render_row(definition.name, definition.description, max_width=max_width))
    rendered.append("")

    rendered.append("::TOOLS (MCP)")
    if tool_set.mcp:
        for definition in sorted(tool_set.mcp, key=lambda row: row.name):
            rendered.append(
                _render_row(definition.name, definition.description, max_width=max_width)
            )
    else:
        rendered.append("(none)")
    rendered.append("")

    rendered.append("::SKILLS (menus)")
    if tool_set.skill_descriptions:
        for skill_name in sorted(tool_set.skill_descriptions):
            summary = tool_set.skill_descriptions[skill_name]
            rendered.append(_render_row(skill_name, summary, max_width=max_width))
    else:
        rendered.append("(none)")
    return rendered


__all__ = ["build_tool_index_lines"]
