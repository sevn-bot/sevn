"""Construct pydantic-ai ``Tool`` rows for tier-B from ``ToolSet`` (`specs/14-executor-tier-b.md` §2.2).

Pattern §3.3: catalogue tools stay **stub-registered** with empty JSON parameters until
``load_tool`` succeeds, then ``prepare_tools`` restores full schemas from the live
``ToolExecutor`` snapshot.

Module: sevn.agent.adapters.tier_b_tools
Depends: pydantic, pydantic_ai, sevn.tools.*

Exports:
    prepare_lazy_tool_definitions — agent-level ``ToolsPrepareFunc`` helper.
    build_pydantic_tools_for_triage — materialize ``Tool`` list for ``Agent``.
    build_pydantic_tools_for_registry — full-registry ``Tool`` list for auto-grant dispatch.
    eager_hydrate_tool_names — names to pre-seed into ``BTierDeps.loaded_tools``.
    tool_definition_to_args_model — build a ``BaseModel`` from a tool's JSON Schema.
    meta_tool_name_frozenset — extract ``load_tool`` / ``load_skill`` from a registration.
    minimal_stub_json_schema — minimal JSON schema for file/search tool stubs (W5).
    bound_file_search_tools — intersection of triager picks with file/search bound set (W3).
    should_block_shell_improvisation — whether ``terminal_run`` / ``sandbox_exec`` is blocked (D3).

Examples:
    >>> from sevn.tools.registry import ToolSet
    >>> ToolSet(1, (), (), {})
    ToolSet(registry_version=1, native=(), mcp=(), skill_descriptions={}, skill_inventory={})
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sevn.agent.adapters.tier_b_capabilities import WebEgressDomainPolicy

from pydantic import BaseModel, ConfigDict, ValidationError, create_model
from pydantic_ai import RunContext, Tool
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.tools import ToolDefinition as PAToolDefinition

from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
from sevn.agent.adapters.tool_part_filter import RECOVERY_WIDEN_FAILURE_THRESHOLD
from sevn.agent.executors.b_types import BTierDeps, EscalationRequest
from sevn.agent.grounding import (
    GROUNDING_TOOL_NAMES,
    steer_for_direct_tool_call,
    steer_for_fallback_tool,
    steer_for_meta_tool_call,
)
from sevn.agent.tracing.sink import checkpoint_snapshot
from sevn.config.defaults import (
    TIER_B_TOOL_CALL_BUDGET,
    TIER_B_TOOL_FAILURE_HARD_CAP,
    TIER_B_TOOL_MAX_RETRIES,
)
from sevn.logging.structured import debug_event
from sevn.prompts.fallbacks import TIER_B_REPEATED_WRONG_CALL_TEMPLATE
from sevn.tools.base import ToolCall, ToolDefinition, ToolExecutor, enveloped_failure
from sevn.tools.codes import ToolResultCode
from sevn.tools.meta_loaders import META_TOOL_NAMES

_ALWAYS_INVOKABLE_SKILL_RUNNERS: frozenset[str] = frozenset(
    {"run_skill_script", "run_skill_runnable"},
)

_ALWAYS_INVOKABLE_FILE_OPS: frozenset[str] = frozenset({"read", "edit", "write"})

_ALWAYS_INVOKABLE_TIER_B: frozenset[str] = frozenset({"log_query", "list_registry"})

# Read-only exploration tools where an identical (name + args) call within one turn
# returns the same result — re-fetching wastes a round and inflates context/tokens.
# A repeat is short-circuited with a steer to reuse the prior result (D-wander-loop).
_DEDUP_GUARD_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "read",
        "list_dir",
        "glob",
        "search_in_file",
        "find_file",
        "log_query",
        "read_transcript",
        "history",
        "memory_search",
        "list_registry",
    },
)

# Names that are never lazy-loaded: already always-on or meta tools.
# Excluded from the eager-hydration count and never seeded into ``loaded_tools``
# (they bypass the stub gate via other branches in ``prepare_lazy_tool_definitions``).
_NEVER_LAZY_NAMES: frozenset[str] = (
    _ALWAYS_INVOKABLE_SKILL_RUNNERS
    | _ALWAYS_INVOKABLE_FILE_OPS
    | _ALWAYS_INVOKABLE_TIER_B
    | frozenset({"load_tool", "load_skill", "request_escalation"})
)

EAGER_HYDRATE_MAX_TOOLS: int = 7
"""When the Triager narrows to **≤ N** non-always-on tools, emit their full JSON schemas
immediately (no ``load_tool`` ritual).  Above N (including the ``full_index`` retry's
~40 tools) the lazy stub pattern stays in force.  Locked to 7 by L1 (2026-06-03)."""

FILE_TOOL_MINIMAL_STUB_KEYS: dict[str, tuple[str, ...]] = {
    "list_dir": ("path",),
    "glob": ("pattern", "path"),
    "search_in_file": ("pattern", "path"),
    "find_file": ("name", "path"),
    "read": ("path",),
}
"""Essential parameter keys emitted on lazy stub schemas for file/search tools (W5 / 1c)."""

FILE_SEARCH_BOUND_TOOLS: frozenset[str] = frozenset(
    {"search_in_file", "read", "glob", "list_dir", "find_file"},
)
"""Registry tools whose triager binding blocks ``terminal_run`` / ``sandbox_exec`` (W3 / D3)."""

_SHELL_IMPROVISATION_TOOLS: frozenset[str] = frozenset({"terminal_run", "sandbox_exec"})

_SHELL_BYPASS_STEER = (
    "Triager bound file/search tools — use `search_in_file` / `read`, not shell grep."
)

_STUB_VALIDATION_AUTO_GRANT_STEER = (
    "Schema loaded — retry `{tool}` with {{param: …}} per loaded schema."
)


def bound_file_search_tools(triager_bound_tools: frozenset[str]) -> frozenset[str]:
    """Return triager-bound file/search tool names that block shell improvisation (W3 / D3).

    Args:
        triager_bound_tools (frozenset[str]): ``TriageResult.tools`` bound for this turn.

    Returns:
        frozenset[str]: Subset of ``triager_bound_tools`` in ``FILE_SEARCH_BOUND_TOOLS``.

    Examples:
        >>> bound_file_search_tools(frozenset({"search_in_file", "load_tool"}))
        frozenset({'search_in_file'})
        >>> bound_file_search_tools(frozenset({"terminal_run", "process"}))
        frozenset()
    """
    return triager_bound_tools & FILE_SEARCH_BOUND_TOOLS


def should_block_shell_improvisation(
    tool_name: str,
    triager_bound_tools: frozenset[str],
) -> bool:
    """Return whether a shell tool call must be rejected when file/search tools are bound (D3).

    Args:
        tool_name (str): Registry tool the model requested.
        triager_bound_tools (frozenset[str]): Triager-bound tool names for this turn.

    Returns:
        bool: ``True`` when ``tool_name`` is ``terminal_run`` or ``sandbox_exec`` and the
        triager bound at least one ``FILE_SEARCH_BOUND_TOOLS`` name.

    Examples:
        >>> should_block_shell_improvisation("terminal_run", frozenset({"search_in_file"}))
        True
        >>> should_block_shell_improvisation("terminal_run", frozenset({"terminal_run"}))
        False
        >>> should_block_shell_improvisation("search_in_file", frozenset({"search_in_file"}))
        False
    """
    if tool_name not in _SHELL_IMPROVISATION_TOOLS:
        return False
    return bool(bound_file_search_tools(triager_bound_tools))


def eager_hydrate_tool_names(
    registration: PydanticToolRegistration,
    *,
    threshold: int = EAGER_HYDRATE_MAX_TOOLS,
) -> frozenset[str]:
    """Return tool names to pre-seed into ``BTierDeps.loaded_tools`` for eager hydration.

    When the Triager's narrowed set contains **≤ threshold** non-always-on tools those
    tools' full JSON schemas are exposed from the first model round — no ``load_tool``
    call is needed.  Above the threshold (e.g. the ``full_index`` retry's ~40 tools) an
    empty frozenset is returned so the lazy stub pattern remains in force.

    Args:
        registration (PydanticToolRegistration): Narrowed Triager-chosen tool/skill names.
        threshold (int): Maximum number of non-always-on tools that triggers eager hydration.
            Defaults to ``EAGER_HYDRATE_MAX_TOOLS`` (7).

    Returns:
        frozenset[str]: Names to pre-seed into ``BTierDeps.loaded_tools``.  Empty when the
        set is larger than ``threshold``.

    Examples:
        >>> from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
        >>> reg_serp = PydanticToolRegistration(
        ...     tool_names=("load_tool", "serp"),
        ...     tool_descriptions={"load_tool": "load", "serp": "search"},
        ...     skill_names=(),
        ...     skill_descriptions={},
        ... )
        >>> eager_hydrate_tool_names(reg_serp) == frozenset({"serp"})
        True
        >>> reg_core = PydanticToolRegistration(
        ...     tool_names=("load_tool", "read", "write", "log_query"),
        ...     tool_descriptions={},
        ...     skill_names=(),
        ...     skill_descriptions={},
        ... )
        >>> eager_hydrate_tool_names(reg_core) == frozenset()
        True
        >>> reg_big = PydanticToolRegistration(
        ...     tool_names=tuple(f"tool_{i}" for i in range(8)),
        ...     tool_descriptions={},
        ...     skill_names=(),
        ...     skill_descriptions={},
        ... )
        >>> eager_hydrate_tool_names(reg_big) == frozenset()
        True
    """
    candidates = frozenset(registration.tool_names) - _NEVER_LAZY_NAMES
    if len(candidates) <= threshold:
        return candidates
    return frozenset()


def _json_type_to_py(fragment: dict[str, Any]) -> Any:
    """Map a JSON Schema ``type`` keyword to a coarse Python annotation.

    Args:
        fragment (dict[str, Any]): JSON Schema fragment for one property.

    Returns:
        Any: Python type (``str``, ``int``, ...) or ``Any`` when unknown.

    Examples:
        >>> _json_type_to_py({"type": "string"})
        <class 'str'>
        >>> _json_type_to_py({})
        typing.Any
    """
    t = fragment.get("type")
    if t == "string":
        return str
    if t in ("integer",):
        return int
    if t == "number":
        return float
    if t == "boolean":
        return bool
    if t == "array":
        return list[Any]
    if t == "object":
        return dict[str, Any]
    return Any


def tool_definition_to_args_model(defn: ToolDefinition) -> type[BaseModel]:
    """Build a ``BaseModel`` approximating ``defn.parameters`` (flat / common JSON Schema only).

    Args:
        defn (ToolDefinition): Registry definition with a JSON-Schema ``parameters`` dict.

    Returns:
        type[BaseModel]: Generated pydantic model class enforcing field presence / extras.

    Examples:
        >>> from sevn.tools.base import ToolDefinition
        >>> d = ToolDefinition(
        ...     name="x",
        ...     category="meta",
        ...     description="",
        ...     parameters={"type": "object", "properties": {}},
        ... )
        >>> issubclass(tool_definition_to_args_model(d), BaseModel)
        True
    """

    schema = defn.parameters
    props = schema.get("properties")
    if not isinstance(props, dict):
        props = {}
    required = frozenset(schema.get("required") or [])
    fields_kv: dict[str, Any] = {}
    for key, spec in props.items():
        ann: Any = _json_type_to_py(spec) if isinstance(spec, dict) else Any
        if key in required:
            fields_kv[key] = (ann, ...)
        else:
            fields_kv[key] = (ann | None, None)
    safe_name = "".join(ch if ch.isalnum() else "_" for ch in defn.name) + "_args"
    if not fields_kv:
        return create_model(
            safe_name or "EmptyToolArgs",
            __config__=ConfigDict(extra="forbid"),
        )

    return create_model(
        safe_name,
        __config__=ConfigDict(extra="forbid"),
        **fields_kv,
    )


def minimal_stub_json_schema(defn: ToolDefinition) -> dict[str, Any]:
    """Build a minimal lazy stub JSON schema with essential parameter keys only (W5 / 1c).

    File/search tools expose hint keys such as ``path`` / ``pattern``; other catalogue
    tools fall back to required keys from the full registry schema.

    Args:
        defn (ToolDefinition): Registry definition backing the lazy stub.

    Returns:
        dict[str, Any]: JSON Schema object suitable for wire exposure and stub validation.

    Examples:
        >>> from sevn.tools.base import ToolDefinition
        >>> d = ToolDefinition(
        ...     name="list_dir",
        ...     category="file_ops",
        ...     description="list",
        ...     parameters={
        ...         "type": "object",
        ...         "properties": {"path": {"type": "string"}},
        ...         "required": [],
        ...     },
        ... )
        >>> "path" in minimal_stub_json_schema(d).get("properties", {})
        True
    """
    full = defn.parameters
    props = full.get("properties")
    if not isinstance(props, dict):
        props = {}
    required_full = frozenset(full.get("required") or [])
    keys = FILE_TOOL_MINIMAL_STUB_KEYS.get(defn.name, tuple(required_full))
    stub_props: dict[str, Any] = {}
    stub_required: list[str] = []
    for key in keys:
        spec = props.get(key)
        if not isinstance(spec, dict):
            continue
        entry: dict[str, Any] = {"type": spec.get("type", "string")}
        desc = spec.get("description")
        if isinstance(desc, str) and desc:
            entry["description"] = desc
        stub_props[key] = entry
        if key in required_full:
            stub_required.append(key)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": stub_props,
        "additionalProperties": False,
    }
    if stub_required:
        schema["required"] = stub_required
    return schema


def _minimal_stub_args_model(defn: ToolDefinition) -> type[BaseModel]:
    """Return a pydantic args model matching :func:`minimal_stub_json_schema`.

    Args:
        defn (ToolDefinition): Registry definition backing the lazy stub.

    Returns:
        type[BaseModel]: Generated pydantic model for stub-time validation.

    Examples:
        >>> from sevn.tools.base import ToolDefinition
        >>> d = ToolDefinition(
        ...     name="glob",
        ...     category="file_ops",
        ...     description="glob",
        ...     parameters={
        ...         "type": "object",
        ...         "properties": {
        ...             "pattern": {"type": "string"},
        ...             "path": {"type": "string"},
        ...         },
        ...         "required": ["pattern"],
        ...     },
        ... )
        >>> issubclass(_minimal_stub_args_model(d), BaseModel)
        True
    """
    stub_defn = replace(defn, parameters=minimal_stub_json_schema(defn))
    return tool_definition_to_args_model(stub_defn)


def _tool_uses_lazy_stub(deps: BTierDeps, tool_name: str) -> bool:
    """Return whether ``tool_name`` is still on the lazy stub validation path.

    Args:
        deps (BTierDeps): Per-run dependency bag.
        tool_name (str): Registry tool name.

    Returns:
        bool: ``True`` when the tool is catalogue-bound and not yet in ``loaded_tools``.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.context import ToolContext
        >>> from sevn.tools.permissions import AllowAllPermissionPolicy
        >>> deps = BTierDeps(
        ...     tool_executor=ToolExecutor(),
        ...     tool_context_template=ToolContext(
        ...         session_id="s",
        ...         workspace_path=Path("/tmp"),
        ...         workspace_id="w",
        ...         registry_version=1,
        ...         trace=None,
        ...         permissions=AllowAllPermissionPolicy(),
        ...     ),
        ...     workspace_path=Path("/tmp"),
        ...     registry_version=1,
        ... )
        >>> _tool_uses_lazy_stub(deps, "glob")
        True
    """
    if tool_name in deps.meta_tool_names:
        return False
    if tool_name in _ALWAYS_INVOKABLE_SKILL_RUNNERS:
        return False
    if tool_name in _ALWAYS_INVOKABLE_FILE_OPS:
        return False
    if tool_name in _ALWAYS_INVOKABLE_TIER_B:
        return False
    return tool_name not in deps.loaded_tools


def _is_registry_catalog_tool(deps: BTierDeps, tool_name: str) -> bool:
    """Return whether ``tool_name`` exists on this turn's registry catalog.

    Args:
        deps (BTierDeps): Per-run dependency bag.
        tool_name (str): Candidate registry tool name.

    Returns:
        bool: ``True`` when the name is in ``tool_allowlist.registry_names`` or the executor.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.agent.adapters.tool_part_filter import MutableToolAllowlist
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.context import ToolContext
        >>> from sevn.tools.permissions import AllowAllPermissionPolicy
        >>> allow = MutableToolAllowlist(
        ...     base=frozenset({"read"}),
        ...     registry_names=frozenset({"read", "glob"}),
        ... )
        >>> deps = BTierDeps(
        ...     tool_executor=ToolExecutor(),
        ...     tool_context_template=ToolContext(
        ...         session_id="s",
        ...         workspace_path=Path("/tmp"),
        ...         workspace_id="w",
        ...         registry_version=1,
        ...         trace=None,
        ...         permissions=AllowAllPermissionPolicy(),
        ...     ),
        ...     workspace_path=Path("/tmp"),
        ...     registry_version=1,
        ...     tool_allowlist=allow,
        ... )
        >>> _is_registry_catalog_tool(deps, "glob")
        True
    """
    allowlist = deps.tool_allowlist
    if allowlist is not None and allowlist.registry_names:
        return tool_name in allowlist.registry_names
    return any(defn.name == tool_name for defn in deps.tool_executor.definitions())


def _stub_validation_auto_grant(ctx: RunContext[BTierDeps], tool_name: str) -> str:
    """Auto-grant a catalogue tool after stub-schema validation failure (W5 / 1b).

    Args:
        ctx (RunContext[BTierDeps]): Pydantic AI run context.
        tool_name (str): Registry tool that failed stub validation.

    Returns:
        str: Failure envelope steering the model to retry with the hydrated schema.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_stub_validation_auto_grant)
        True
    """
    deps = ctx.deps
    deps.loaded_tools.add(tool_name)
    from sevn.agent.adapters.tier_b_hooks import apply_load_tool_grant

    apply_load_tool_grant(deps, tool_name)
    debug_event("tier_b.stub_validation_auto_grant", name=tool_name)
    steer_text = _STUB_VALIDATION_AUTO_GRANT_STEER.format(tool=tool_name)
    steer = deps.steer_buffer
    if steer is not None:
        steer.inject_pending(steer_text)
    return enveloped_failure(steer_text, code=ToolResultCode.VALIDATION_ERROR)


def _executor_catalog(deps: BTierDeps) -> dict[str, ToolDefinition]:
    """Return enabled registry definitions keyed by tool name.

    Args:
        deps (BTierDeps): Per-run dependency bag.

    Returns:
        dict[str, ToolDefinition]: Catalog snapshot from ``deps.tool_executor``.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.context import ToolContext
        >>> from sevn.tools.permissions import AllowAllPermissionPolicy
        >>> deps = BTierDeps(
        ...     tool_executor=ToolExecutor(),
        ...     tool_context_template=ToolContext(
        ...         session_id="s",
        ...         workspace_path=Path("/tmp"),
        ...         workspace_id="w",
        ...         registry_version=1,
        ...         trace=None,
        ...         permissions=AllowAllPermissionPolicy(),
        ...     ),
        ...     workspace_path=Path("/tmp"),
        ...     registry_version=1,
        ... )
        >>> _executor_catalog(deps)
        {}
    """
    return {d.name: d for d in deps.tool_executor.definitions() if d.enabled}


def _lazy_stub_parameters_json_schema(
    deps: BTierDeps,
    name: str,
) -> dict[str, Any]:
    """Resolve wire/stub JSON schema for an unloaded catalogue tool.

    Args:
        deps (BTierDeps): Per-run dependency bag.
        name (str): Registry tool name.

    Returns:
        dict[str, Any]: Minimal stub schema when known; otherwise empty object schema.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.tools.base import FunctionTool, ToolDefinition, ToolExecutor
        >>> from sevn.tools.context import ToolContext
        >>> from sevn.tools.permissions import AllowAllPermissionPolicy
        >>> exe = ToolExecutor()
        >>> exe.register(
        ...     FunctionTool(
        ...         ToolDefinition(
        ...             name="list_dir",
        ...             category="file_ops",
        ...             description="list",
        ...             parameters={
        ...                 "type": "object",
        ...                 "properties": {"path": {"type": "string"}},
        ...                 "required": [],
        ...             },
        ...         ),
        ...         lambda _ctx: "{}",
        ...     )
        ... )
        >>> deps = BTierDeps(
        ...     tool_executor=exe,
        ...     tool_context_template=ToolContext(
        ...         session_id="s",
        ...         workspace_path=Path("/tmp"),
        ...         workspace_id="w",
        ...         registry_version=1,
        ...         trace=None,
        ...         permissions=AllowAllPermissionPolicy(),
        ...     ),
        ...     workspace_path=Path("/tmp"),
        ...     registry_version=1,
        ... )
        >>> "path" in _lazy_stub_parameters_json_schema(deps, "list_dir").get("properties", {})
        True
    """
    defn = _executor_catalog(deps).get(name)
    if defn is not None and name in FILE_TOOL_MINIMAL_STUB_KEYS:
        return minimal_stub_json_schema(defn)
    return {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


def _after_dispatch_update_loaded(
    deps: BTierDeps,
    tool_name: str,
    payload: dict[str, Any],
    raw_envelope: str,
) -> None:
    """Mark ``loaded_tools`` / ``loaded_skills`` after a successful meta tool dispatch.

    Args:
        deps (BTierDeps): Per-run dependency bag tracking lazy-load state.
        tool_name (str): Dispatched tool name (``load_tool`` / ``load_skill`` are watched).
        payload (dict[str, Any]): Arguments passed to the meta tool (``name`` field used).
        raw_envelope (str): Raw envelope string returned by the executor.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.context import ToolContext
        >>> from sevn.tools.permissions import AllowAllPermissionPolicy
        >>> exe = ToolExecutor()
        >>> ctx = ToolContext(
        ...     session_id="s",
        ...     workspace_path=Path("/tmp"),
        ...     workspace_id="w",
        ...     registry_version=1,
        ...     trace=None,
        ...     permissions=AllowAllPermissionPolicy(),
        ... )
        >>> deps = BTierDeps(tool_executor=exe, tool_context_template=ctx, workspace_path=Path("/tmp"), registry_version=1)
        >>> _after_dispatch_update_loaded(deps, "other", {}, "{}")
        >>> deps.loaded_tools
        set()
    """
    if tool_name != "load_tool" and tool_name != "load_skill":
        return
    try:
        blob = json.loads(raw_envelope)
    except json.JSONDecodeError:
        return
    if not blob.get("ok"):
        return
    target = str(payload.get("name", "")).strip()
    if not target:
        return
    if tool_name == "load_tool":
        deps.loaded_tools.add(target)
        from sevn.agent.adapters.tier_b_hooks import apply_load_tool_grant

        apply_load_tool_grant(deps, target)
    else:
        deps.loaded_skills.add(target)
        deps.successful_skills_called.add(target)


async def _dispatch_tool(
    ctx: RunContext[BTierDeps],
    definition: ToolDefinition,
    payload: dict[str, Any],
) -> str:
    """Dispatch a tier-B tool call after guarding against unloaded names.

    Args:
        ctx (RunContext[BTierDeps]): Pydantic AI run context carrying tier-B deps.
        definition (ToolDefinition): Registry definition for the requested tool.
        payload (dict[str, Any]): Validated keyword arguments.

    Returns:
        str: Raw envelope string from the executor (or a validation-error envelope).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_dispatch_tool)
        True
    """
    deps = ctx.deps
    if should_block_shell_improvisation(definition.name, deps.triager_bound_tools):
        if deps.steer_buffer is not None:
            deps.steer_buffer.inject_pending(_SHELL_BYPASS_STEER)
        debug_event(
            "tier_b.shell_improvisation_blocked",
            tool=definition.name,
            triager_bound=sorted(deps.triager_bound_tools),
        )
        return enveloped_failure(_SHELL_BYPASS_STEER, code=ToolResultCode.VALIDATION_ERROR)
    if definition.name in _DEDUP_GUARD_TOOL_NAMES and deps.seen_successful_call(
        definition.name,
        payload,
    ):
        debug_event("tier_b.duplicate_tool_call_skipped", tool=definition.name)
        return enveloped_failure(
            f"Duplicate call to {definition.name!r} with identical arguments — "
            "this exact call already succeeded this turn. Reuse the previous result; "
            "do not re-fetch. Answer now or call a different tool.",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    repeat_n = deps.note_tool_call(definition.name, payload)
    if (
        definition.name not in deps.meta_tool_names
        and sum(deps.tool_call_counts.values()) > TIER_B_TOOL_CALL_BUDGET
    ):
        debug_event(
            "tier_b.tool_call_budget_exhausted",
            tool=definition.name,
            total=sum(deps.tool_call_counts.values()),
            budget=TIER_B_TOOL_CALL_BUDGET,
        )
        return enveloped_failure(
            f"Tool-call budget ({TIER_B_TOOL_CALL_BUDGET}) reached this turn. Stop "
            "calling tools and write your final answer from the evidence already "
            "gathered, or request escalation if blocked.",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    if definition.name in GROUNDING_TOOL_NAMES:
        deps.grounding_tools_called.add(definition.name)
    if (
        definition.name not in deps.meta_tool_names
        and definition.name not in _ALWAYS_INVOKABLE_SKILL_RUNNERS
        and definition.name not in _ALWAYS_INVOKABLE_FILE_OPS
        and definition.name not in _ALWAYS_INVOKABLE_TIER_B
        and definition.name not in deps.loaded_tools
    ):
        allow = deps.tool_allowlist.effective if deps.tool_allowlist is not None else frozenset()
        if definition.name in allow:
            deps.loaded_tools.add(definition.name)
        else:
            return enveloped_failure(
                f"Tool {definition.name!r} is not provisioned this turn "
                f"(TOOL_NOT_PROVISIONED). Call load_tool or use an available tool.",
                code=ToolResultCode.TOOL_NOT_PROVISIONED,
            )
    tool_ctx = deps.effective_tool_context()
    outcome = "exception"
    raw: str | None = None
    try:
        await checkpoint_snapshot(
            tool_ctx.trace,
            session_id=tool_ctx.session_id,
            turn_id=tool_ctx.turn_id,
            tier="B",
            kind="tool.before",
            excerpt=f"name={definition.name}",
            state={"name": definition.name, "arguments": dict(payload)},
        )
        raw = await deps.tool_executor.dispatch(
            tool_ctx,
            ToolCall(name=definition.name, arguments=payload),
            timeout_seconds="default",
        )
        try:
            blob = json.loads(raw)
        except json.JSONDecodeError:
            outcome = "parse_error"
        else:
            outcome = "ok" if blob.get("ok") else "error"
            if outcome == "ok":
                deps.successful_tools_called.add(definition.name)
                if definition.name in _DEDUP_GUARD_TOOL_NAMES:
                    deps.successful_call_sigs.add(
                        BTierDeps.call_signature(definition.name, payload),
                    )
                if definition.name == "run_skill_script":
                    skill = str(
                        payload.get("skill") or payload.get("skill_name") or "",
                    ).strip()
                    if skill:
                        deps.successful_skills_called.add(skill)
                elif definition.name == "run_skill_runnable":
                    skill = str(payload.get("skill") or "").strip()
                    if skill:
                        deps.successful_skills_called.add(skill)
                elif definition.name == "run_code":
                    code = str(payload.get("code") or "")
                    for name in deps.triager_bound_tools:
                        if name in {
                            "run_code",
                            "load_tool",
                            "load_skill",
                            "list_registry",
                            "request_escalation",
                        }:
                            continue
                        if re.search(rf"\b{re.escape(name)}\b", code):
                            deps.codemode_bound_tools_called.add(name)
            if outcome == "error":
                err = blob.get("error") or blob.get("message") or "ok=false"
                if isinstance(err, dict):
                    err = err.get("message") or str(err)
                deps.note_tool_failure(definition.name, str(err))
                if (
                    deps.tool_allowlist is not None
                    and deps.tool_failure_by_name.get(definition.name, 0)
                    >= RECOVERY_WIDEN_FAILURE_THRESHOLD
                ):
                    deps.tool_allowlist.widen_diagnostics()
                failures_for_tool = deps.tool_failure_by_name.get(definition.name, 0)
                if (
                    definition.name not in deps.meta_tool_names
                    and failures_for_tool >= TIER_B_TOOL_FAILURE_HARD_CAP
                ):
                    # Same tool has failed too many times this turn (varying args slip past
                    # the identical-call escalation). Stop the loop with a terminal steer so
                    # the model answers from evidence or switches approach instead of
                    # grinding to the round/timeout budget.
                    debug_event(
                        "tier_b.tool_failure_cap_reached",
                        tool=definition.name,
                        failures=failures_for_tool,
                        cap=TIER_B_TOOL_FAILURE_HARD_CAP,
                    )
                    return enveloped_failure(
                        f"{definition.name!r} has failed {failures_for_tool} times this turn — "
                        "stop calling it. Use a different tool or approach, or write your final "
                        "answer from the evidence already gathered (state plainly if you could "
                        "not complete the request). Do not retry this tool again.",
                        code=ToolResultCode.VALIDATION_ERROR,
                    )
                code = blob.get("code")
                if (
                    code == ToolResultCode.SKILL_IS_ACTUALLY_TOOL
                    and repeat_n == 1
                    and definition.name in _ALWAYS_INVOKABLE_SKILL_RUNNERS
                ):
                    tool_hint = blob.get("did_you_mean_tool")
                    if not isinstance(tool_hint, str) or not tool_hint.strip():
                        tool_hint = payload.get("skill") or payload.get("script")
                    if isinstance(tool_hint, str) and tool_hint.strip():
                        steer = deps.steer_buffer
                        if steer is not None:
                            steer.inject_pending(
                                steer_for_direct_tool_call(tool_hint.strip()),
                            )
                if (
                    definition.name == "load_tool"
                    and code == ToolResultCode.UNKNOWN_TOOL
                    and repeat_n == 1
                ):
                    requested = payload.get("name")
                    if isinstance(requested, str):
                        meta_name = requested.strip()
                        if meta_name in META_TOOL_NAMES:
                            steer = deps.steer_buffer
                            if steer is not None:
                                steer.inject_pending(
                                    steer_for_meta_tool_call(meta_name),
                                )
                data_blob = blob.get("data")
                fallback_hint = (
                    data_blob.get("fallback_tool") if isinstance(data_blob, dict) else None
                )
                if (
                    isinstance(fallback_hint, str)
                    and fallback_hint.strip()
                    and fallback_hint.strip() != definition.name
                    and repeat_n == 1
                    and fallback_hint.strip() in _executor_catalog(deps)
                ):
                    fallback_name = fallback_hint.strip()
                    deps.loaded_tools.add(fallback_name)
                    steer = deps.steer_buffer
                    if steer is not None:
                        steer.inject_pending(
                            steer_for_fallback_tool(definition.name, fallback_name),
                        )
                    debug_event(
                        "tier_b.fallback_tool_granted",
                        tool=definition.name,
                        fallback=fallback_name,
                    )
                fast_threshold = 2 if code == ToolResultCode.SKILL_IS_ACTUALLY_TOOL else 3
                if repeat_n >= fast_threshold:
                    deps.escalation = EscalationRequest(
                        reason="repeated_wrong_tool_call",
                        target_tier="C",
                        user_visible_message=TIER_B_REPEATED_WRONG_CALL_TEMPLATE.format(
                            tier="C",
                        ),
                    )
                    msg = f"repeated wrong tool call ({definition.name}, attempt={repeat_n})"
                    raise UsageLimitExceeded(msg)
        return raw
    finally:
        from sevn.agent.tracing.attrs import trace_tool_result_value

        after_state: dict[str, object] = {
            "name": definition.name,
            "outcome": outcome,
        }
        if raw is not None:
            after_state["result"] = trace_tool_result_value(raw)
        await checkpoint_snapshot(
            tool_ctx.trace,
            session_id=tool_ctx.session_id,
            turn_id=tool_ctx.turn_id,
            tier="B",
            kind="tool.after",
            excerpt=f"name={definition.name} outcome={outcome}",
            state=after_state,
        )


def _make_registry_tool(defn: ToolDefinition, *, code_mode: bool = False) -> Tool[BTierDeps]:
    """Wrap a registry definition as a pydantic-ai ``Tool`` bound to ``BTierDeps``.

    Args:
        defn (ToolDefinition): Registry definition exposing the tool to tier B.
        code_mode (bool): When ``True``, tag metadata so ``CodeMode`` sandboxes this tool (W8).

    Returns:
        Tool[BTierDeps]: Tool with validated args model and async dispatch.

    Examples:
        >>> import inspect
        >>> "defn" in inspect.signature(_make_registry_tool).parameters
        True
    """
    args_model = tool_definition_to_args_model(defn)
    stub_args_model = _minimal_stub_args_model(defn)
    name = defn.name

    async def _runner(ctx: RunContext[BTierDeps], **data: Any) -> str:
        use_stub = _tool_uses_lazy_stub(ctx.deps, name)
        validate_model = stub_args_model if use_stub else args_model
        try:
            payload = validate_model.model_validate(data).model_dump(exclude_none=True)
        except ValidationError:
            if use_stub and _is_registry_catalog_tool(ctx.deps, name):
                return _stub_validation_auto_grant(ctx, name)
            raise
        raw = await _dispatch_tool(ctx, defn, payload)
        _after_dispatch_update_loaded(ctx.deps, name, payload, raw)
        return raw

    _runner.__name__ = name
    tool = Tool.from_schema(
        _runner,
        name=name,
        description=defn.description,
        json_schema=args_model.model_json_schema(),
        takes_ctx=True,
    )
    if defn.requires_human:
        tool.requires_approval = True
    tool.max_retries = TIER_B_TOOL_MAX_RETRIES
    if code_mode:
        tool.metadata = {"code_mode": True}
    return tool


def build_pydantic_tools_for_triage(
    executor: ToolExecutor,
    registration: PydanticToolRegistration,
    *,
    extra_tools: list[Tool[BTierDeps]] | None = None,
) -> list[Tool[BTierDeps]]:
    """Hydrate pydantic ``Tool`` callables for narrowed tier-B names.

    Args:
        executor (ToolExecutor): Active registry whose definitions back the tools.
        registration (PydanticToolRegistration): Narrowed Triager-chosen names.
        extra_tools (list[Tool[BTierDeps]] | None): Optional tools appended after registry tools.

    Returns:
        list[Tool[BTierDeps]]: Tools to bind into ``Agent.tools``.

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
        >>> exe = ToolExecutor()
        >>> reg = PydanticToolRegistration((), {}, (), {})
        >>> build_pydantic_tools_for_triage(exe, reg)
        []
    """

    catalog = {d.name: d for d in executor.definitions()}
    tools: list[Tool[BTierDeps]] = []
    for tool_name in registration.tool_names:
        if tool_name == "request_escalation":
            continue
        defn = catalog.get(tool_name)
        if defn is None:
            continue
        tools.append(_make_registry_tool(defn))
    if extra_tools:
        tools.extend(extra_tools)
    return tools


def build_pydantic_tools_for_registry(
    executor: ToolExecutor,
    registration: PydanticToolRegistration,
    *,
    extra_tools: list[Tool[BTierDeps]] | None = None,
    codemode_eligible: frozenset[str] | None = None,
    exclude_tool_names: frozenset[str] | None = None,
    codemode_web_policy: WebEgressDomainPolicy | None = None,
) -> list[Tool[BTierDeps]]:
    """Hydrate pydantic ``Tool`` rows for the full enabled registry (P3 auto-grant dispatch).

    Triager-bound names are listed first (stable ordering); remaining enabled registry tools
    follow so auto-granted recovered calls can dispatch without re-building the agent.
    Wire exposure is still narrowed by :class:`MutableToolAllowlist` in tier-B model.

    Args:
        executor (ToolExecutor): Active registry whose definitions back the tools.
        registration (PydanticToolRegistration): Triager-chosen names (ordering anchor).
        extra_tools (list[Tool[BTierDeps]] | None): Optional tools appended after registry tools.
        codemode_eligible (frozenset[str] | None): When set, triager-scoped names tagged
            ``code_mode=True`` for ``CodeMode`` (W8). Auto-grant rows are never tagged.
        exclude_tool_names (frozenset[str] | None): Registry names omitted because a
            capability (e.g. W7 ``WebFetch``) already exposes the same tool name.
        codemode_web_policy (object | None): When set with ``codemode_eligible``, build
            triager-scoped web tools via :func:`~sevn.agent.adapters.tier_b_capabilities.make_codemode_web_registry_tool`.

    Returns:
        list[Tool[BTierDeps]]: Full-registry tools to bind into ``Agent.tools``.

    Examples:
        >>> from sevn.tools.base import FunctionTool, ToolDefinition, ToolExecutor
        >>> from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
        >>> exe = ToolExecutor()
        >>> for name in ("read", "glob"):
        ...     exe.register(
        ...         FunctionTool(
        ...             ToolDefinition(
        ...                 name=name,
        ...                 category="file",
        ...                 description=name,
        ...                 parameters={"type": "object", "properties": {}},
        ...             ),
        ...             lambda _ctx: "{}",
        ...         )
        ...     )
        >>> reg = PydanticToolRegistration(("read",), {"read": "r"}, (), {})
        >>> names = [t.name for t in build_pydantic_tools_for_registry(exe, reg)]
        >>> names == ["read", "glob"]
        True
    """
    catalog = {d.name: d for d in executor.definitions() if d.enabled}
    tools: list[Tool[BTierDeps]] = []
    seen: set[str] = set()
    skip = exclude_tool_names or frozenset()
    for tool_name in registration.tool_names:
        if tool_name == "request_escalation" or tool_name in seen or tool_name in skip:
            continue
        defn = catalog.get(tool_name)
        if defn is None:
            continue
        tag = codemode_eligible is not None and tool_name in codemode_eligible
        if tag and codemode_web_policy is not None:
            from sevn.agent.adapters.tier_b_capabilities import (
                CODEMODE_LOCAL_WEB_TOOL_NAMES,
                make_codemode_web_registry_tool,
            )

            if tool_name in CODEMODE_LOCAL_WEB_TOOL_NAMES:
                tools.append(make_codemode_web_registry_tool(defn, policy=codemode_web_policy))
                seen.add(tool_name)
                continue
        tools.append(_make_registry_tool(defn, code_mode=tag))
        seen.add(tool_name)
    for tool_name in sorted(catalog):
        if tool_name in seen or tool_name == "request_escalation" or tool_name in skip:
            continue
        tools.append(_make_registry_tool(catalog[tool_name], code_mode=False))
        seen.add(tool_name)
    if extra_tools:
        tools.extend(extra_tools)
    return tools


async def prepare_lazy_tool_definitions(
    ctx: RunContext[BTierDeps],
    defs: list[PAToolDefinition],
) -> list[PAToolDefinition] | None:
    """Strip tool JSON schemas until ``load_tool`` marks a name hot (§3.3 stub pattern).

    Tools in the always-on sets (meta, skill runners, core file ops, ``request_escalation``)
    keep their full schemas.  All other catalogue tools get an empty parameter schema and an
    explicit ``[SCHEMA NOT YET LOADED]`` description banner that tells the model:

    * the tool IS real and IS enabled;
    * call ``load_tool`` with exactly this name once to hydrate the full schema;
    * then call the tool normally — do not invent or guess names.

    The banner deliberately avoids the old terse "Call load_tool before invoking" phrasing,
    which weaker models (e.g. MiniMax-M2.7) misread as "tool not available / internal."

    Args:
        ctx (RunContext[BTierDeps]): Pydantic AI run context (used to read loaded state).
        defs (list[PAToolDefinition]): Candidate tool definitions for this round.

    Returns:
        list[PAToolDefinition] | None: Possibly-rewritten definitions with stub schemas.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(prepare_lazy_tool_definitions)
        True
    """

    out: list[PAToolDefinition] = []
    for td in defs:
        name = td.name
        if (
            name in ctx.deps.meta_tool_names
            or name == "request_escalation"
            or name in _ALWAYS_INVOKABLE_SKILL_RUNNERS
            or name in _ALWAYS_INVOKABLE_FILE_OPS
            or name in _ALWAYS_INVOKABLE_TIER_B
        ):
            out.append(td)
            continue
        if name in ctx.deps.loaded_tools:
            out.append(td)
            continue
        stub_schema = _lazy_stub_parameters_json_schema(ctx.deps, name)
        out.append(
            replace(
                td,
                parameters_json_schema=stub_schema,
                description=(
                    (td.description or "")
                    + "\n\n[SCHEMA NOT YET LOADED] This tool IS real and IS enabled."
                    " Its parameter schema is not shown here to save context."
                    " To use it: (1) call load_tool with name='"
                    + td.name
                    + "' ONCE — this hydrates the full schema; (2) then call '"
                    + td.name
                    + "' normally with the correct parameters."
                    " Do NOT invent or guess tool names — only names shown in this tool list are valid."
                    " Do NOT try to load_tool on 'load_tool', 'load_skill', or 'request_escalation'"
                    " — those are always available and need no hydration."
                ),
            ),
        )
    return out


def meta_tool_name_frozenset(registration: PydanticToolRegistration) -> frozenset[str]:
    """Return meta tool names (load_tool/load_skill) present on this turn.

    Args:
        registration (PydanticToolRegistration): Narrowed tier-B registration.

    Returns:
        frozenset[str]: Subset of ``tool_names`` covering ``load_tool`` / ``load_skill``.

    Examples:
        >>> from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
        >>> reg = PydanticToolRegistration(("load_tool", "alpha"), {}, (), {})
        >>> meta_tool_name_frozenset(reg) == frozenset({"load_tool"})
        True
    """

    return frozenset(n for n in registration.tool_names if n in ("load_tool", "load_skill"))


__all__ = [
    "EAGER_HYDRATE_MAX_TOOLS",
    "FILE_SEARCH_BOUND_TOOLS",
    "bound_file_search_tools",
    "build_pydantic_tools_for_registry",
    "build_pydantic_tools_for_triage",
    "eager_hydrate_tool_names",
    "meta_tool_name_frozenset",
    "minimal_stub_json_schema",
    "prepare_lazy_tool_definitions",
    "should_block_shell_improvisation",
    "tool_definition_to_args_model",
]
