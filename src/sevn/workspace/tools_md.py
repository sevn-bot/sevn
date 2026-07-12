"""Sync and read workspace ``TOOLS.md`` registry catalog (`specs/02-config-and-workspace.md`).

Module: sevn.workspace.tools_md
Depends: sevn.agent.triager.tool_index, sevn.onboarding.seed, sevn.tools.registry

Exports:
    render_registry_markdown — markdown catalog from a session ``ToolSet``.
    merge_tools_md_body — splice registry block into existing ``TOOLS.md`` body.
    read_tools_md_body — load workspace ``TOOLS.md`` when present.
    sync_tools_md — write catalog when content changes.
    sync_tools_md_for_config — build registry from ``sevn.json`` and sync.

Note:
    ``REGISTRY_BEGIN_MARKER`` and ``REGISTRY_END_MARKER`` delimit the auto-generated block.

Examples:
    >>> from pathlib import Path
    >>> from sevn.tools.base import ToolDefinition
    >>> from sevn.tools.registry import ToolSet
    >>> from sevn.workspace.tools_md import merge_tools_md_body, render_registry_markdown
    >>> native = (
    ...     ToolDefinition(
    ...         name="read",
    ...         category="file",
    ...         description="Read a workspace file.",
    ...         parameters={"type": "object", "properties": {}},
    ...     ),
    ... )
    >>> block = render_registry_markdown(ToolSet(1, native, (), {}))
    >>> "read" in block
    True
    >>> merged = merge_tools_md_body("# Tools\\n\\n", block)
    >>> "sevn:tools-registry:begin" in merged
    True
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sevn.agent.triager.tool_index import _render_row
from sevn.onboarding.seed import load_template, render_template
from sevn.tools.readiness import readiness_for_tool
from sevn.tools.registry import ToolSet, build_session_registry

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.tools.base import ToolDefinition
    from sevn.workspace.layout import WorkspaceLayout

REGISTRY_BEGIN_MARKER: str = "<!-- sevn:tools-registry:begin -->"
REGISTRY_END_MARKER: str = "<!-- sevn:tools-registry:end -->"
_TOOLS_MD_NAME: str = "TOOLS.md"
_PLACEHOLDER_REGISTRY: str = "*(Registry catalog is generated on first gateway run or onboarding.)*"


def _enabled_definitions(definitions: tuple[ToolDefinition, ...]) -> list[ToolDefinition]:
    """Return enabled tool definitions sorted by name.

    Args:
        definitions (tuple[ToolDefinition, ...]): Native or MCP ``ToolDefinition`` rows.

    Returns:
        list[ToolDefinition]: Enabled definitions sorted by ``name``.

    Examples:
        >>> from sevn.tools.base import ToolDefinition
        >>> row = ToolDefinition(
        ...     name="a",
        ...     category="meta",
        ...     description="x",
        ...     parameters={"type": "object", "properties": {}},
        ...     enabled=False,
        ... )
        >>> _enabled_definitions((row,))
        []
    """
    return sorted(
        (d for d in definitions if getattr(d, "enabled", True)),
        key=lambda row: row.name,
    )


def render_registry_markdown(tool_set: ToolSet, *, max_width: int = 120) -> str:
    """Render the auto-generated registry section for ``TOOLS.md``.

    Args:
        tool_set (ToolSet): Session registry snapshot (native, MCP, skills).
        max_width (int): Soft line width for ``name - description`` rows.

    Returns:
        str: Markdown body placed between registry HTML comment markers.

    Examples:
        >>> from sevn.tools.base import ToolDefinition
        >>> from sevn.tools.registry import ToolSet
        >>> native = (
        ...     ToolDefinition(
        ...         name="write",
        ...         category="file",
        ...         description="Write a workspace file.",
        ...         parameters={"type": "object", "properties": {}},
        ...     ),
        ... )
        >>> body = render_registry_markdown(ToolSet(2, native, (), {"lcm": "LCM menus."}))
        >>> "### Native tools" in body and "**write**" in body
        True
        >>> "**lcm**" in body
        True
    """
    lines: list[str] = [
        "Enabled tools, skills, and MCP surfaces for this workspace "
        f"(registry_version={tool_set.registry_version}). "
        "Use exact identifiers in triage `tools[]` / `skills[]`; "
        "tier-B loads full JSON schemas via `load_tool`.",
        "",
        "**Readiness tags** (when shown): `ready` = works in a standard deploy; "
        "`needs_key` / `needs_proxy` / `needs_dep` = operator setup required. "
        "Full matrix: `docs/runbooks/tool-skill-readiness.md` (repo checkout); "
        "`load_tool` also returns a `readiness` object at runtime.",
        "",
        "### Native tools",
    ]

    def _bullet(name: str, description: str) -> str:
        row = _render_row(name, description, max_width=max_width)
        _prefix, _sep, summary = row.partition(" - ")
        bullet = f"- **{name}** — {summary}"
        readiness = readiness_for_tool(name)
        if readiness is not None:
            status = str(readiness.get("status") or "")
            if status and status != "ready":
                bullet += f" *(`{status}`)*"
        return bullet

    native = _enabled_definitions(tool_set.native)
    if native:
        for definition in native:
            lines.append(_bullet(definition.name, definition.description))
    else:
        lines.append("- *(none)*")
    lines.extend(["", "### MCP tools"])
    mcp = _enabled_definitions(tool_set.mcp)
    if mcp:
        for definition in mcp:
            lines.append(_bullet(definition.name, definition.description))
    else:
        lines.append("- *(none)*")
    lines.extend(["", "### Skills (menus)"])
    if tool_set.skill_descriptions:
        for skill_name in sorted(tool_set.skill_descriptions):
            summary = tool_set.skill_descriptions[skill_name]
            lines.append(_bullet(skill_name, summary))
    else:
        lines.append("- *(none)*")
    return "\n".join(lines)


def _registry_section_inner(body: str) -> str | None:
    """Return markdown between registry HTML comment markers.

    Args:
        body (str): Full ``TOOLS.md`` text.

    Returns:
        str | None: Stripped inner catalog, or ``None`` when markers are absent.

    Examples:
        >>> inner = _registry_section_inner(
        ...     "<!-- sevn:tools-registry:begin -->\\ncat\\n<!-- sevn:tools-registry:end -->"
        ... )
        >>> inner
        'cat'
    """
    text = body.replace("\r\n", "\n")
    begin = text.find(REGISTRY_BEGIN_MARKER)
    end = text.find(REGISTRY_END_MARKER)
    if begin == -1 or end == -1 or end <= begin:
        return None
    inner_start = begin + len(REGISTRY_BEGIN_MARKER)
    return text[inner_start:end].strip()


def merge_tools_md_body(existing: str, registry_block: str) -> str:
    """Insert or replace the registry block inside ``TOOLS.md`` content.

    Args:
        existing (str): Current file body (may omit markers).
        registry_block (str): Markdown from :func:`render_registry_markdown`.

    Returns:
        str: Full ``TOOLS.md`` body with markers and ``registry_block`` between them.

    Examples:
        >>> body = merge_tools_md_body("# Tools\\n\\nnote\\n", "catalog")
        >>> body.count(REGISTRY_BEGIN_MARKER)
        1
        >>> "catalog" in body
        True
        >>> updated = merge_tools_md_body(body, "catalog-v2")
        >>> "catalog-v2" in updated and "catalog\\n" not in updated.split("catalog-v2")[1][:20]
        True
    """
    wrapped = "\n".join(  # noqa: FLY002
        [
            REGISTRY_BEGIN_MARKER,
            registry_block.strip(),
            REGISTRY_END_MARKER,
        ],
    )
    text = existing.replace("\r\n", "\n")
    begin = text.find(REGISTRY_BEGIN_MARKER)
    end = text.find(REGISTRY_END_MARKER)
    if begin != -1 and end != -1 and end > begin:
        after_end = end + len(REGISTRY_END_MARKER)
        tail = text[after_end:]
        if tail.startswith("\n"):
            tail = tail[1:]
        prefix = text[:begin].rstrip()
        return f"{prefix}\n\n{wrapped}\n\n{tail}".rstrip() + "\n"
    stripped = text.rstrip()
    if stripped:
        return f"{stripped}\n\n{wrapped}\n"
    return f"{wrapped}\n"


def _default_tools_md_template(agent_name: str = "Sevn") -> str:
    """Return packaged ``TOOLS.md`` template rendered for ``agent_name``.

    Args:
        agent_name (str): Bot display name for ``{{AGENT_NAME}}`` substitution.

    Returns:
        str: Template body including empty registry markers.

    Examples:
        >>> "Local notes" in _default_tools_md_template("Bot") or "What goes here" in _default_tools_md_template("Bot")
        True
    """
    return render_template(load_template(_TOOLS_MD_NAME), agent_name)


def read_tools_md_body(content_root: Path) -> str | None:
    """Read ``TOOLS.md`` from the workspace content root.

    Args:
        content_root (Path): Resolved workspace content root.

    Returns:
        str | None: Stripped file body, or ``None`` when missing or unreadable.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> read_tools_md_body(root) is None
        True
        >>> _ = (root / "TOOLS.md").write_text("hello", encoding="utf-8")
        >>> read_tools_md_body(root)
        'hello'
    """
    path = content_root / _TOOLS_MD_NAME
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def sync_tools_md(
    content_root: Path,
    tool_set: ToolSet,
    *,
    agent_name: str = "Sevn",
) -> bool:
    """Write ``TOOLS.md`` when the registry catalog section changes.

    Args:
        content_root (Path): Resolved workspace content root.
        tool_set (ToolSet): Live session registry snapshot.
        agent_name (str): Used when seeding the packaged template for a new file.

    Returns:
        bool: ``True`` when the file was created or updated.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> from sevn.tools.base import ToolDefinition
        >>> from sevn.tools.registry import ToolSet
        >>> native = (
        ...     ToolDefinition(
        ...         name="read",
        ...         category="file",
        ...         description="Read file.",
        ...         parameters={"type": "object", "properties": {}},
        ...     ),
        ... )
        >>> root = Path(tempfile.mkdtemp())
        >>> ts = ToolSet(1, native, (), {})
        >>> sync_tools_md(root, ts)
        True
        >>> sync_tools_md(root, ts)
        False
    """
    root = content_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / _TOOLS_MD_NAME
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = _default_tools_md_template(agent_name)
    else:
        existing = _default_tools_md_template(agent_name)
    registry_block = render_registry_markdown(tool_set)
    new_inner = registry_block.strip()
    prior_inner = _registry_section_inner(existing)
    if prior_inner is not None and prior_inner == new_inner:
        return False
    merged = merge_tools_md_body(existing, registry_block)
    path.write_text(merged.replace("\r\n", "\n"), encoding="utf-8")
    return True


def sync_tools_md_for_config(
    sevn_json_path: Path,
    workspace_config: WorkspaceConfig,
    *,
    layout: WorkspaceLayout | None = None,
    agent_name: str = "Sevn",
    include_bootstrap_tools: bool = False,
) -> bool:
    """Build the session registry from workspace config and sync ``TOOLS.md``.

    Args:
        sevn_json_path (Path): Path to ``sevn.json``.
        workspace_config (WorkspaceConfig): Parsed workspace document.
        layout (WorkspaceLayout | None): Optional pre-resolved layout.
        agent_name (str): Bot display name for new ``TOOLS.md`` files.
        include_bootstrap_tools (bool): Register bootstrap markdown tools when True.

    Returns:
        bool: ``True`` when ``TOOLS.md`` was written.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     sj = root / "sevn.json"
        ...     _ = sj.write_text('{"schema_version": 1, "workspace_root": "."}', encoding="utf-8")
        ...     cfg = WorkspaceConfig.minimal(workspace_root=".")
        ...     layout = WorkspaceLayout.from_config(sj, cfg)
        ...     sync_tools_md_for_config(sj, cfg, layout=layout)
        True
    """
    from sevn.workspace.layout import WorkspaceLayout as _Layout

    resolved = layout or _Layout.from_config(sevn_json_path, workspace_config)
    _exe, tool_set = build_session_registry(
        workspace_config=workspace_config,
        workspace_root=resolved.content_root,
        layout=resolved,
        include_bootstrap_tools=include_bootstrap_tools,
    )
    return sync_tools_md(resolved.content_root, tool_set, agent_name=agent_name)


__all__ = [
    "REGISTRY_BEGIN_MARKER",
    "REGISTRY_END_MARKER",
    "merge_tools_md_body",
    "read_tools_md_body",
    "render_registry_markdown",
    "sync_tools_md",
    "sync_tools_md_for_config",
]
