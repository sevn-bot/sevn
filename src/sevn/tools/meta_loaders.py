"""Load meta tools attaching lazy bodies (`specs/11-tools-registry.md` §2.4).

Registers ``load_tool`` and ``load_skill`` using definition snapshots captured **before**
meta registration so callables stay free of circular dispatch.

Module: sevn.tools.meta_loaders
Depends: sevn.tools.base, sevn.tools.codes, sevn.tools.context

Exports:
    Classes:
        ListRegistryImplementation — emits enabled tool/skill name lists (W4.5).
        LoadToolImplementation — emits §2.4 payload shape.
        LoadSkillImplementation — emits compact skill manifests.
    Functions:
        attach_meta_loaders — mutates ``ToolExecutor`` to add both meta tools.

Examples:
    >>> LOAD_TOOL_PARAMETERS["type"]
    'object'
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

from sevn.tools.base import Tool, ToolDefinition, ToolExecutor, enveloped_failure, enveloped_success

if TYPE_CHECKING:
    from sevn.skills.manager import SkillsManager
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.readiness import readiness_for_tool, readiness_notes_for_tools

LOAD_TOOL_PARAMETERS: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
}


def _resolve_long_description(
    workspace_path: Path | None,
    relative: str,
) -> str | None:
    """Resolve a tool's long-description text from workspace overlay or packaged template.

    Args:
        workspace_path (Path | None): Workspace content root for the active turn.
        relative (str): Workspace-relative path declared on the tool (e.g. ``tools/log_query.md``).

    Returns:
        str | None: File contents if found in either location; ``None`` when neither
        the workspace overlay nor the packaged template exists. Path-traversal attempts
        (``..`` segments or absolute paths) return ``None`` without touching disk.

    Examples:
        >>> text = _resolve_long_description(None, "tools/log_query.md")
        >>> text is not None and "log_query" in text
        True
    """
    rel = (relative or "").strip()
    if not rel:
        return None
    # Reject absolute paths and parent-segment traversal before resolution.
    if rel.startswith(("/", "\\")) or ".." in Path(rel).parts:
        logger.warning("load_tool.long_description.refuse_traversal relative={}", rel)
        return None
    if workspace_path is not None:
        overlay = workspace_path / rel
        try:
            overlay.relative_to(workspace_path)
        except ValueError:
            logger.warning("load_tool.long_description.escape relative={}", rel)
            return None
        if overlay.is_file():
            try:
                return overlay.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning(
                    "load_tool.long_description.read_failed path={} error={}",
                    overlay,
                    type(exc).__name__,
                )
                # fall through to packaged fallback
    # Packaged template fallback under ``sevn.data.workspace_templates``.
    try:
        ref = resources.files("sevn.data.workspace_templates").joinpath(rel)
        if ref.is_file():
            return ref.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        logger.warning(
            "load_tool.long_description.template_read_failed relative={} error={}",
            rel,
            type(exc).__name__,
        )
    return None


LOAD_SKILL_PARAMETERS: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "full": {
            "type": "boolean",
            "default": False,
            "description": (
                "When true, inline the entire SKILL.md body (may spill). "
                "Default menu mode returns a short intro plus skill_md_path."
            ),
        },
    },
    "required": ["name"],
}

LIST_REGISTRY_PARAMETERS: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


class LoadToolImplementation(Tool):
    """Return schema payloads for lazily-loaded tools (§2.4)."""

    def __init__(
        self,
        catalog: dict[str, ToolDefinition],
        mcp_tool_names: AbstractSet[str],
    ) -> None:
        """Bind merged native + MCP ``ToolDefinition`` rows.

                Args:
        catalog (dict[str, ToolDefinition]): Canonical name → definition (**pre-meta** snapshot).
        mcp_tool_names (AbstractSet[str]): Names originating from MCP ``tools/list`` for this
            session (used to label ``capabilities[].id`` and overview text).

                Returns:
                    None

                Raises:
                    (none)

                Examples:
                    >>> isinstance(LoadToolImplementation({}, frozenset()), LoadToolImplementation)
                    True
        """

        self._catalog = dict(catalog)
        self._mcp_tool_names = frozenset(mcp_tool_names)
        self._definition = ToolDefinition(
            name="load_tool",
            category="meta",
            description="Load JSON schema + capability rows for another tool.",
            parameters=LOAD_TOOL_PARAMETERS,
            requires_human=False,
            abortable=True,
            sandbox_mode="none",
        )

    def definition(self) -> ToolDefinition:
        """Return meta-loader metadata.

        Returns:
            ToolDefinition: Pre-built ``load_tool`` descriptor.

        Examples:
            >>> LoadToolImplementation({}, frozenset()).definition().name
            'load_tool'
        """
        return self._definition

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> str:
        """Serialize ``schema`` / ``capabilities`` or surface ``UNKNOWN_TOOL``.

        Args:
            ctx (ToolContext): Runtime envelope (unused; retained for ABI parity).
            kwargs (Any): Tool arguments; ``name`` selects the catalog entry.

        Returns:
            str: §3.1 JSON envelope — success carries ``schema`` /
                ``capabilities`` rows; failure uses ``UNKNOWN_TOOL``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LoadToolImplementation({}, frozenset()).execute)
            True
        """
        name = str(kwargs.get("name", ""))
        if name in META_TOOL_NAMES:
            return enveloped_failure(
                f"{name!r} is a meta tool — call it directly; "
                "`load_tool` only hydrates native/MCP tools.",
                code=ToolResultCode.UNKNOWN_TOOL,
            )
        definition = self._catalog.get(name)
        if definition is None or not definition.enabled:
            return enveloped_failure(
                f"No enabled tool named {name!r}",
                code=ToolResultCode.UNKNOWN_TOOL,
            )
        is_mcp = definition.name in self._mcp_tool_names
        capabilities = [
            {
                "id": definition.name,
                "summary": definition.description,
                "parameters_overview": (
                    "MCP tools/list name matches `id`; see `schema.parameters`."
                    if is_mcp
                    else "See `schema.parameters` for the authoritative JSON Schema."
                ),
            },
        ]
        payload: dict[str, Any] = {
            "schema": definition.to_dict(),
            "category_instructions": None,
            "capabilities": capabilities,
        }
        if definition.long_description_file:
            long_text = _resolve_long_description(
                ctx.workspace_path,
                definition.long_description_file,
            )
            if long_text is not None:
                payload["long_description"] = long_text
        readiness = readiness_for_tool(name)
        if readiness is not None:
            fallback = str(readiness.get("fallback_tool") or "").strip()
            if fallback and readiness.get("status") != "ready":
                fallback_row = readiness_for_tool(fallback)
                if fallback_row is not None and fallback_row.get("status") == "ready":
                    readiness["action"] = (
                        f"Not ready ({readiness.get('status')}) until configured — "
                        f"prefer calling `{fallback}` directly."
                    )
            payload["readiness"] = readiness
        return enveloped_success(payload)


class LoadSkillImplementation(Tool):
    """Expose bundled skill summaries without front-loading ``SKILL.md`` bodies."""

    def __init__(self, manifests: dict[str, str]) -> None:
        """Bind ``skill_name → one_line_summary`` rows.

                Args:
        manifests (dict[str, str]): Human-readable one-line summaries keyed by skill name.

                Returns:
                    None

                Raises:
                    (none)

                Examples:
                    >>> isinstance(LoadSkillImplementation({}), LoadSkillImplementation)
                    True
        """

        self._manifests = dict(manifests)
        self._definition = ToolDefinition(
            name="load_skill",
            category="meta",
            description="Load a skill menu (default) or full skill manifest when full=true.",
            parameters=LOAD_SKILL_PARAMETERS,
            requires_human=False,
            abortable=True,
            sandbox_mode="none",
        )

    def definition(self) -> ToolDefinition:
        """Return meta-loader metadata.

        Returns:
            ToolDefinition: Pre-built ``load_skill`` descriptor.

        Examples:
            >>> LoadSkillImplementation({}).definition().name
            'load_skill'
        """
        return self._definition

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> str:
        """Return manifest-menu payload when no ``SkillsManager`` is session-scoped.

        Production registries with a live skills scan use
        :class:`sevn.tools.skills_register.SkillsBackedLoadSkillTool` instead.
        This fallback serves tests and registries built without workspace roots.

        Args:
            ctx (ToolContext): Runtime envelope (unused; retained for ABI parity).
            kwargs (Any): Tool arguments; ``name`` selects the skill manifest.

        Returns:
            str: §3.1 JSON envelope — success carries a skill-menu ``schema``
                plus a single ``capabilities`` entry; failure uses
                ``SKILL_NOT_FOUND``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LoadSkillImplementation({}).execute)
            True
        """
        _ = ctx
        name = str(kwargs.get("name", ""))
        summary = self._manifests.get(name)
        if summary is None:
            return enveloped_failure(
                f"Skill {name!r} unavailable", code=ToolResultCode.SKILL_NOT_FOUND
            )
        schema_stub = {
            "name": name,
            "description": summary,
            "kind": "skill_menu",
        }
        caps = [
            {
                "id": f"{name}.menu",
                "summary": summary,
                "parameters_overview": "Use `run_skill_script` / `run_skill_runnable` after choosing a step.",
            },
        ]
        return enveloped_success(
            {"schema": schema_stub, "category_instructions": None, "capabilities": caps},
        )


META_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {"load_tool", "load_skill", "list_registry", "request_escalation"},
)
"""Meta tools hidden from ``list_registry`` and from the tier-B full tool catalog.

Shared source of truth so the executor's self-listing matches the ``list_registry``
tool output exactly (`specs/11-tools-registry.md` §2.3)."""


class ListRegistryImplementation(Tool):
    """Return enabled tool and skill names for tier-B self-listing (W4.5)."""

    _META_NAMES: Final[frozenset[str]] = META_TOOL_NAMES

    def __init__(
        self,
        catalog: dict[str, ToolDefinition],
        skill_descriptions: dict[str, str],
    ) -> None:
        """Bind pre-meta catalog rows and skill manifest summaries.

        Args:
            catalog (dict[str, ToolDefinition]): Native + MCP definitions (**pre-meta** snapshot).
            skill_descriptions (dict[str, str]): Skill id → one-line summary rows.

        Examples:
            >>> isinstance(ListRegistryImplementation({}, {}), ListRegistryImplementation)
            True
        """
        self._catalog = dict(catalog)
        self._skill_descriptions = dict(skill_descriptions)
        self._definition = ToolDefinition(
            name="list_registry",
            category="meta",
            description="List enabled registry tool names and bundled skill names for this session.",
            parameters=LIST_REGISTRY_PARAMETERS,
            requires_human=False,
            abortable=True,
            sandbox_mode="none",
        )

    def definition(self) -> ToolDefinition:
        """Return ``list_registry`` metadata.

        Returns:
            ToolDefinition: Pre-built descriptor.

        Examples:
            >>> ListRegistryImplementation({}, {}).definition().name
            'list_registry'
        """
        return self._definition

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> str:
        """Serialize sorted tool and skill name lists.

        Args:
            ctx (ToolContext): Runtime envelope (``registry_version`` echoed in payload).
            kwargs (Any): Unused; retained for ABI parity.

        Returns:
            str: §3.1 JSON envelope with ``tools`` and ``skills`` string lists.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ListRegistryImplementation({}, {}).execute)
            True
        """
        _ = kwargs
        tools = sorted(
            name
            for name, defn in self._catalog.items()
            if defn.enabled and name not in self._META_NAMES
        )
        skills = sorted(self._skill_descriptions)
        payload: dict[str, Any] = {
            "tools": tools,
            "skills": skills,
            "registry_version": ctx.registry_version,
            "meta_tools": sorted(self._META_NAMES),
        }
        notes = readiness_notes_for_tools(tools)
        if notes:
            payload["readiness_notes"] = notes
        gated: dict[str, dict[str, str]] = {}
        for gated_name in ("sandbox_exec", "integration_call"):
            if gated_name in tools:
                continue
            row = readiness_for_tool(gated_name)
            if row is not None:
                gated[gated_name] = {
                    "status": str(row.get("status") or "pending"),
                    "note": str(row.get("note") or ""),
                }
        if gated:
            payload["gated_tools"] = gated
        tool_status: dict[str, str] = {}
        for name in tools:
            row = readiness_for_tool(name)
            if row is not None and row.get("status"):
                tool_status[name] = str(row["status"])
        if tool_status:
            payload["tool_status"] = tool_status
        return enveloped_success(payload)


def attach_meta_loaders(
    executor: ToolExecutor,
    *,
    native_definitions: dict[str, ToolDefinition],
    mcp_definitions: dict[str, ToolDefinition],
    skill_descriptions: dict[str, str],
    mcp_tool_names: AbstractSet[str],
    skills_manager: SkillsManager | None = None,
) -> None:
    """Append ``load_tool`` / ``load_skill`` after the concrete catalog is known.

            Args:
    executor (ToolExecutor): Target registry (**mutated**).
    native_definitions (dict[str, ToolDefinition]): Native ``ToolDefinition`` rows.
    mcp_definitions (dict[str, ToolDefinition]): MCP rows keyed by dotted names.
    skill_descriptions (dict[str, str]): Skill summaries for manifest-menu ``load_skill`` fallback.
    mcp_tool_names (AbstractSet[str]): MCP ``tools/list`` names for the active session slice.
    skills_manager (SkillsManager | None): When set, registers
        :class:`sevn.tools.skills_register.SkillsBackedLoadSkillTool`; otherwise
        :class:`LoadSkillImplementation` manifest summaries for registries without workspace scan.

            Returns:
                None

            Raises:
                (none)

            Examples:
                >>> from sevn.tools.base import ToolExecutor
                >>> ex = ToolExecutor(default_timeout_seconds=None)
                >>> attach_meta_loaders(
                ...     ex,
                ...     native_definitions={},
                ...     mcp_definitions={},
                ...     skill_descriptions={},
                ...     mcp_tool_names=frozenset(),
                ... )
                >>> {d.name for d in ex.definitions()} >= {"load_tool", "load_skill"}
                True
    """

    catalog: dict[str, ToolDefinition] = dict(native_definitions)
    catalog.update(mcp_definitions)
    executor.register(ListRegistryImplementation(catalog, skill_descriptions))
    executor.register(LoadToolImplementation(catalog, mcp_tool_names))
    if skills_manager is not None:
        from sevn.tools.skills_register import SkillsBackedLoadSkillTool

        executor.register(SkillsBackedLoadSkillTool(skills_manager))
    else:
        executor.register(LoadSkillImplementation(skill_descriptions))


__all__ = [
    "LIST_REGISTRY_PARAMETERS",
    "LOAD_SKILL_PARAMETERS",
    "LOAD_TOOL_PARAMETERS",
    "ListRegistryImplementation",
    "LoadSkillImplementation",
    "LoadToolImplementation",
    "attach_meta_loaders",
]
