"""Register skill tools backed by :class:`SkillsManager` (`specs/11-tools-registry.md` §2.4-§2.5).

Module: sevn.tools.skills_register
Depends: sevn.skills.manager, sevn.tools.base, sevn.tools.codes, sevn.tools.context

Exports:
    SkillsBackedLoadSkillTool — ``load_skill`` delegating to ``build_load_skill_payload``.
    register_skill_tools — wire skill runners and authoring tools to a manager.
    register_skill_tools_unconfigured — enabled rows when no manager is session-scoped.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from time import time_ns
from typing import TYPE_CHECKING, Any

from loguru import logger

from sevn.config.workspace_config import tool_as_skill_auto_route_enabled
from sevn.skills.errors import (
    QUARANTINE_SECURITY,
    SKILL_IS_ACTUALLY_TOOL,
    SkillExecutionError,
    failure_envelope,
    success_envelope,
)
from sevn.skills.index import resolve_skill_alias
from sevn.skills.security_scan import (
    DEFAULT_FAIL_SEVERITIES,
    MEDIUM_PLUS_SEVERITIES,
    emit_security_scan_trace,
    normalize_skill_path,
    scan_skill_path,
)
from sevn.tools.base import (
    FunctionTool,
    Tool,
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    enveloped_failure,
)
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.meta_loaders import LOAD_SKILL_PARAMETERS

if TYPE_CHECKING:
    from sevn.skills.manager import SkillsManager

_LOAD_SKILL_DEFINITION = ToolDefinition(
    name="load_skill",
    category="meta",
    description="Load full SKILL.md manifest, capabilities, and quarantine state.",
    parameters=LOAD_SKILL_PARAMETERS,
    requires_human=False,
    abortable=True,
    sandbox_mode="none",
)

_RUN_SKILL_SCRIPT_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "skill": {
            "type": "string",
            "description": "Canonical skill id from load_skill (e.g. social_media_manager).",
        },
        "script": {
            "type": "string",
            "description": "Manifest script path (e.g. scripts/capture.py).",
        },
        "argv": {
            # Accept a JSON/bare string too (CodeMode models pass argv='["x"]'); coerced in-tool.
            "type": ["array", "string"],
            "items": {"type": "string"},
            "description": (
                "Positional CLI arguments for the script as a list of strings. When load_skill "
                "lists args_overview with <placeholders> outside [...], pass those values here "
                '— e.g. argv=["https://example.com"] for capture.py. Pass a real list, never a '
                "JSON-wrapped string."
            ),
        },
    },
    "required": ["skill", "script"],
}

_RUN_SKILL_RUNNABLE_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "skill": {"type": "string"},
        "runnable": {"type": "string"},
        # Accept a JSON string too (CodeMode models pass payload='{...}'); coerced in-tool.
        "payload": {"type": ["object", "string"]},
    },
    "required": ["skill", "runnable"],
}

_SKILL_CREATE_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "version": {"type": "string"},
        "create_scripts_dir": {"type": "boolean"},
    },
    "required": ["name", "description"],
}

_SKILL_RUNNER_NAMES: frozenset[str] = frozenset(
    {
        "load_skill",
        "run_skill_script",
        "run_skill_runnable",
        "skill_create",
        "promote_generated_skill",
    }
)

_PROMOTE_GENERATED_SKILL_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "force": {
            "type": "boolean",
            "description": (
                "Owner override: promote despite SkillSpector HIGH/CRITICAL findings "
                "(requires human acknowledgement for promote_generated_skill)."
            ),
        },
    },
    "required": ["name"],
}


def _coerce_argv_arg(value: object) -> tuple[list[str] | None, str | None]:
    """Coerce a model-supplied ``argv`` that may arrive as a JSON/bare string under CodeMode.

    MiniMax-class tier-B models invoke ``run_skill_script`` through ``run_code`` (CodeMode),
    where the array kwarg often arrives as a string — ``argv='["owner/repo", "--title", "T"]'``
    or a single bare value ``argv="owner/repo"``. The shared JSON-schema validator rejects a
    string for an ``array`` param before the tool runs, so the call errors and is silently
    dropped in the sandbox — burning the ``run_code`` retry budget instead of running the skill.
    Parse a JSON array string back to a list, wrap a bare string as a single element, and
    stringify list items; return a readable error for anything else.

    Args:
        value (object): Raw ``argv`` value (``list``, ``tuple``, JSON/bare ``str``, or ``None``).

    Returns:
        tuple[list[str] | None, str | None]: ``(coerced, None)`` on success, ``(None, error)`` on
            failure. ``(None, None)`` when ``value`` is ``None`` (caller applies its default).

    Examples:
        >>> _coerce_argv_arg(["a", "b"])
        (['a', 'b'], None)
        >>> _coerce_argv_arg('["owner/repo", "--title", "T"]')
        (['owner/repo', '--title', 'T'], None)
        >>> _coerce_argv_arg("owner/repo")
        (['owner/repo'], None)
        >>> _coerce_argv_arg(None)
        (None, None)
        >>> _coerce_argv_arg(123)[0] is None
        True
    """
    if value is None:
        return None, None
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value], None
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except ValueError:
                return None, f"run_skill_script: 'argv' is not valid JSON (got {value!r})"
            if isinstance(parsed, list):
                return [str(item) for item in parsed], None
            return None, f"run_skill_script: 'argv' JSON must be an array (got {value!r})"
        return [text], None
    return None, f"run_skill_script: 'argv' must be a list of strings (got {value!r})"


def _coerce_payload_arg(value: object) -> tuple[dict[str, object] | None, str | None]:
    """Coerce a model-supplied ``payload`` that may arrive as a JSON string under CodeMode.

    Like :func:`_coerce_argv_arg`, CodeMode models pass the ``object`` kwarg as a JSON string —
    ``payload='{"url": "https://x"}'`` — which the schema validator rejects before dispatch, so
    the ``run_skill_runnable`` call vanishes in the sandbox. Parse a JSON object string back to a
    dict; return a readable error for anything else.

    Args:
        value (object): Raw ``payload`` value (``dict``, JSON ``str``, or ``None``).

    Returns:
        tuple[dict[str, object] | None, str | None]: ``(coerced, None)`` on success,
            ``(None, error)`` on failure. ``(None, None)`` when ``value`` is ``None``.

    Examples:
        >>> _coerce_payload_arg({"url": "https://x"})
        ({'url': 'https://x'}, None)
        >>> _coerce_payload_arg('{"url": "https://x"}')
        ({'url': 'https://x'}, None)
        >>> _coerce_payload_arg(None)
        (None, None)
        >>> _coerce_payload_arg("not json")[0] is None
        True
    """
    if value is None:
        return None, None
    if isinstance(value, dict):
        return value, None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None, f"run_skill_runnable: 'payload' is not valid JSON (got {value!r})"
        if isinstance(parsed, dict):
            return parsed, None
        return None, f"run_skill_runnable: 'payload' JSON must be an object (got {value!r})"
    return None, f"run_skill_runnable: 'payload' must be an object (got {value!r})"


def _run_skill_script_definition() -> ToolDefinition:
    """Build the ``run_skill_script`` catalog row.

    Returns:
        ToolDefinition: Enabled skill-runner descriptor.

    Examples:
        >>> _run_skill_script_definition().name
        'run_skill_script'
    """
    return ToolDefinition(
        name="run_skill_script",
        category="skills",
        description=(
            "Execute a declared skill script. Pass required positional values in argv as a "
            "list (see each script's args_overview from load_skill). Under CodeMode call it "
            'inside run_code: out = await run_skill_script(skill="gh-issues", '
            'script="scripts/issue_create.py", argv=["owner/repo", "--title", "T"]); never '
            "JSON-wrap argv."
        ),
        parameters=_RUN_SKILL_SCRIPT_PARAMS,
        abortable=False,
        # Skill scripts enforce their own per-skill ``max_wall_seconds`` inside
        # ``SkillsManager.run_script`` (subprocess killed on exceedance). Disable the generic
        # 30 s dispatch deadline so a legitimately long run (e.g. last30days ~45 s) is not
        # pre-empted with TOOL_TIMEOUT while its subprocess keeps running orphaned.
        dispatch_timeout_seconds=None,
    )


def _skill_create_definition() -> ToolDefinition:
    """Build the ``skill_create`` catalog row.

    Returns:
        ToolDefinition: Enabled skill-authoring descriptor.

    Examples:
        >>> _skill_create_definition().name
        'skill_create'
    """
    return ToolDefinition(
        name="skill_create",
        category="skills",
        description="Scaffold a quarantined skill under ``workspace/skills/generated/``.",
        parameters=_SKILL_CREATE_PARAMS,
        abortable=False,
    )


def _promote_generated_skill_definition() -> ToolDefinition:
    """Build the ``promote_generated_skill`` catalog row.

    Returns:
        ToolDefinition: Owner-gated promotion descriptor.

    Examples:
        >>> _promote_generated_skill_definition().requires_human
        True
    """
    return ToolDefinition(
        name="promote_generated_skill",
        category="skills",
        description="Move ``generated/<name>/`` to ``user/<name>/`` and clear quarantine.",
        parameters=_PROMOTE_GENERATED_SKILL_PARAMS,
        requires_human=True,
        abortable=False,
    )


def _run_skill_runnable_definition() -> ToolDefinition:
    """Build the ``run_skill_runnable`` catalog row.

    Returns:
        ToolDefinition: Enabled skill-runner descriptor.

    Examples:
        >>> _run_skill_runnable_definition().name
        'run_skill_runnable'
    """
    return ToolDefinition(
        name="run_skill_runnable",
        category="skills",
        description="Execute configured runnable payloads from manifests.",
        parameters=_RUN_SKILL_RUNNABLE_PARAMS,
        abortable=False,
        # See ``_run_skill_script_definition``: the skill runner owns the wall-clock budget.
        dispatch_timeout_seconds=None,
    )


def _has_skill(skills_manager: SkillsManager, name: str) -> bool:
    """Return whether ``name`` resolves to a registered skill id.

    Args:
        skills_manager (SkillsManager): Session-scoped skills registry.
        name (str): Skill id or transitional alias.

    Returns:
        bool: True when the resolved id is in the manager inventory.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.skills.manager import SkillsManager
        >>> mgr = SkillsManager.shared(Path("/tmp/ws"), (Path("/tmp/ws/skills"),))
        >>> isinstance(_has_skill(mgr, "missing"), bool)
        True
    """
    resolved = resolve_skill_alias(name)
    return resolved in skills_manager.inventory_for_triager()


def _is_registered_tool_name(ctx: ToolContext, name: str) -> bool:
    """Return whether ``name`` is a session tool, excluding skill-runner meta tools.

    Args:
        ctx (ToolContext): Dispatch context with ``known_tool_names`` snapshot.
        name (str): Candidate tool/skill id from ``run_skill_*``.

    Returns:
        bool: True when the name is a registered native/MCP tool.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.tools.context import ToolContext
        >>> ctx = ToolContext(
        ...     session_id="s",
        ...     workspace_path=Path("/tmp"),
        ...     workspace_id="w",
        ...     registry_version=1,
        ...     known_tool_names=frozenset({"serp"}),
        ... )
        >>> _is_registered_tool_name(ctx, "serp")
        True
    """
    if not ctx.known_tool_names or name in _SKILL_RUNNER_NAMES:
        return False
    return name in ctx.known_tool_names


def _skill_is_actually_tool_envelope(tool_name: str) -> dict[str, object]:
    """Build a §3.1 failure redirecting a tool name away from ``run_skill_*``.

    Args:
        tool_name (str): Registered tool id mistaken for a skill.

    Returns:
        dict[str, object]: ``ok=false`` envelope with ``SKILL_IS_ACTUALLY_TOOL``.

    Examples:
        >>> env = _skill_is_actually_tool_envelope("serp")
        >>> env["code"] == SKILL_IS_ACTUALLY_TOOL
        True
        >>> env["did_you_mean_tool"] == "serp"
        True
    """
    msg = (
        f"`{tool_name}` is a registered tool, not a skill — call `{tool_name}(...)` "
        "directly; do not use run_skill_script or run_skill_runnable."
    )
    payload = failure_envelope(
        SKILL_IS_ACTUALLY_TOOL,
        msg,
        data={"did_you_mean_tool": tool_name},
    )
    payload["did_you_mean_tool"] = tool_name
    return payload


def _tool_args_from_skill_invocation(
    *,
    payload: dict[str, object] | None,
    argv: Sequence[str] | None,
) -> dict[str, object]:
    """Map ``run_skill_*`` arguments to a direct tool kwargs dict for auto-route.

    Args:
        payload (dict[str, object] | None): Runnable payload from ``run_skill_runnable``.
        argv (Sequence[str] | None): Script argv from ``run_skill_script``.

    Returns:
        dict[str, object]: Best-effort kwargs for ``ToolCall.arguments``.

    Examples:
        >>> _tool_args_from_skill_invocation(payload={"query": "x"}, argv=None)["query"]
        'x'
        >>> _tool_args_from_skill_invocation(payload=None, argv=("hello",))["query"]
        'hello'
    """
    if isinstance(payload, dict) and payload:
        return dict(payload)
    if argv:
        if len(argv) == 1:
            return {"query": str(argv[0])}
        return {"argv": [str(a) for a in argv]}
    return {}


async def _unconfigured_skill_executor(ctx: ToolContext, **_kwargs: Any) -> str:
    """Fail closed when skill runners are registered without a live manager.

    Args:
        ctx (ToolContext): Runtime envelope (unused; retained for ABI parity).
        _kwargs (Any): Tool arguments (ignored).

    Returns:
        str: §3.1 JSON failure envelope coded ``INTERNAL_ERROR``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_unconfigured_skill_executor)
        True
    """
    _ = ctx
    return enveloped_failure(
        "SkillsManager not configured for this registry",
        code=ToolResultCode.INTERNAL_ERROR,
    )


class SkillsBackedLoadSkillTool(Tool):
    """Return §2.3 payloads from :meth:`SkillsManager.build_load_skill_payload`."""

    def __init__(self, skills_manager: SkillsManager) -> None:
        """Bind a session-scoped manager for lazy ``SKILL.md`` bodies.

        Args:
            skills_manager (SkillsManager): Session-scoped skills scan + payload builder.

        Returns:
            None

        Examples:
            >>> from pathlib import Path
            >>> from sevn.skills.manager import SkillsManager
            >>> mgr = SkillsManager.shared(Path("/tmp/ws"), (Path("/tmp/ws/skills"),))
            >>> isinstance(SkillsBackedLoadSkillTool(mgr), SkillsBackedLoadSkillTool)
            True
        """
        self._skills_manager = skills_manager

    def definition(self) -> ToolDefinition:
        """Return meta-loader metadata.

        Returns:
            ToolDefinition: Pre-built ``load_skill`` descriptor.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.skills.manager import SkillsManager
            >>> tool = SkillsBackedLoadSkillTool(
            ...     SkillsManager.shared(Path("/tmp/ws"), (Path("/tmp/ws/skills"),))
            ... )
            >>> tool.definition().name
            'load_skill'
        """
        return _LOAD_SKILL_DEFINITION

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> str:
        """Serialise ``build_load_skill_payload`` to a §3.1 JSON string.

        Args:
            ctx (ToolContext): Runtime envelope (unused; retained for ABI parity).
            kwargs (Any): Tool arguments; ``name`` selects the skill id.

        Returns:
            str: §3.1 JSON envelope with ``markdown``, ``capabilities``, and
                ``quarantine`` on success; skill failure codes on error.

        Examples:
            >>> import inspect
            >>> from pathlib import Path
            >>> from sevn.skills.manager import SkillsManager
            >>> tool = SkillsBackedLoadSkillTool(
            ...     SkillsManager.shared(Path("/tmp/ws"), (Path("/tmp/ws/skills"),))
            ... )
            >>> inspect.iscoroutinefunction(tool.execute)
            True
        """
        _ = ctx
        name = str(kwargs.get("name", ""))
        full = bool(kwargs.get("full", False))
        result = await self._skills_manager.build_load_skill_payload(name, full=full)
        return json.dumps(result, separators=(",", ":"), ensure_ascii=False)


def register_skill_tools_unconfigured(executor: ToolExecutor) -> None:
    """Register enabled skill runner rows without a live :class:`SkillsManager`.

    Args:
        executor (ToolExecutor): Registry being constructed.

    Returns:
        None: Mutates ``executor`` in place.

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> ex = ToolExecutor(default_timeout_seconds=None)
        >>> register_skill_tools_unconfigured(ex)
        >>> ex.get("run_skill_script") is not None
        True
    """
    executor.register(FunctionTool(_run_skill_script_definition(), _unconfigured_skill_executor))
    executor.register(FunctionTool(_run_skill_runnable_definition(), _unconfigured_skill_executor))
    executor.register(FunctionTool(_skill_create_definition(), _unconfigured_skill_executor))
    executor.register(
        FunctionTool(_promote_generated_skill_definition(), _unconfigured_skill_executor)
    )


def register_skill_tools(executor: ToolExecutor, skills_manager: SkillsManager) -> None:
    """Register skill runners and authoring tools delegating to ``skills_manager``.

    Handlers close over ``skills_manager`` at registration time and serialise the manager's
    dict envelope to a JSON string at the tool boundary.

    Args:
        executor (ToolExecutor): Registry receiving the skill tools.
        skills_manager (SkillsManager): Session-scoped skills scan + subprocess runner.

    Returns:
        None: Mutates ``executor`` in place.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.skills.manager import SkillsManager
        >>> ex = ToolExecutor(default_timeout_seconds=None)
        >>> mgr = SkillsManager.shared(Path("/tmp/ws"), (Path("/tmp/ws/skills"),))
        >>> register_skill_tools(ex, mgr)
        >>> ex.get("skill_create") is not None
        True
    """

    async def _skill_create(
        ctx: ToolContext,
        *,
        name: str,
        description: str,
        version: str | None = None,
        create_scripts_dir: bool | None = None,
    ) -> str:
        _ = ctx
        try:
            result = skills_manager.scaffold_generated_skill(
                name,
                description,
                version=version if version is not None else "0.1.0",
                create_scripts_dir=(create_scripts_dir if create_scripts_dir is not None else True),
            )
        except SkillExecutionError as exc:
            result = failure_envelope(exc.code, str(exc))
        else:
            if (
                isinstance(result, dict)
                and result.get("ok") is True
                and len(skills_manager._skills_roots) == 1
            ):
                gen_path = skills_manager._skills_roots[0] / "generated" / name
                scan = scan_skill_path(gen_path, fail_severities=tuple(MEDIUM_PLUS_SEVERITIES))
                await emit_security_scan_trace(
                    ctx.trace,
                    session_id=ctx.session_id,
                    path=normalize_skill_path(gen_path),
                    result=scan,
                    turn_id=ctx.session_id,
                )
                medium_plus = [i for i in scan.issues if i.severity in MEDIUM_PLUS_SEVERITIES]
                payload = result.get("data")
                if medium_plus and isinstance(payload, dict):
                    note = (
                        f"SkillSpector: {len(medium_plus)} MEDIUM+ finding(s) in generated scaffold "
                        "— review before promote_generated_skill."
                    )
                    result = success_envelope(payload, message=note)
        return json.dumps(result, separators=(",", ":"), ensure_ascii=False)

    async def _promote_generated_skill(
        ctx: ToolContext, *, name: str, force: bool | None = None
    ) -> str:
        rv_before = skills_manager.registry_version
        if len(skills_manager._skills_roots) != 1:
            result = failure_envelope("SKILL_VALIDATION", "promote requires a single skills root")
            return json.dumps(result, separators=(",", ":"), ensure_ascii=False)
        gen_path = skills_manager._skills_roots[0] / "generated" / name
        scan = scan_skill_path(gen_path, fail_severities=DEFAULT_FAIL_SEVERITIES)
        await emit_security_scan_trace(
            ctx.trace,
            session_id=ctx.session_id,
            path=normalize_skill_path(gen_path),
            result=scan,
            turn_id=ctx.session_id,
        )
        high_plus = scan.issues_at_or_above(DEFAULT_FAIL_SEVERITIES)
        owner_force = bool(force)
        if high_plus and not owner_force:
            result = failure_envelope(
                QUARANTINE_SECURITY,
                (
                    f"SkillSpector blocked promote: {len(high_plus)} HIGH/CRITICAL finding(s) "
                    f"in generated/{name}/ — remediate or pass force=true with owner acknowledgement"
                ),
                data={
                    "skill_name": name,
                    "finding_count": len(high_plus),
                    "rule_ids": sorted({issue.rule_id for issue in high_plus}),
                },
            )
            return json.dumps(result, separators=(",", ":"), ensure_ascii=False)
        try:
            skills_manager.promote_generated_to_user(name)
        except SkillExecutionError as exc:
            result = failure_envelope(exc.code, str(exc))
        else:
            result = success_envelope(
                {
                    "skill_name": name,
                    "registry_version_before": rv_before,
                    "registry_version": skills_manager.registry_version,
                    "security_scan_findings": len(high_plus),
                },
            )
        return json.dumps(result, separators=(",", ":"), ensure_ascii=False)

    async def _maybe_route_tool_as_skill(
        ctx: ToolContext,
        *,
        skill: str,
        via: str,
        payload: dict[str, object] | None = None,
        argv: Sequence[str] | None = None,
    ) -> str | None:
        if _has_skill(skills_manager, skill) or not _is_registered_tool_name(ctx, skill):
            return None
        if tool_as_skill_auto_route_enabled(skills_manager._config):
            tool_args = _tool_args_from_skill_invocation(payload=payload, argv=argv)
            raw = await executor.dispatch(
                ctx,
                ToolCall(name=skill, arguments=tool_args),
            )
            try:
                blob = json.loads(raw)
            except json.JSONDecodeError:
                return raw
            if isinstance(blob, dict) and blob.get("ok") is True:
                note = (
                    f"Auto-routed from {via}: `{skill}` is a tool — call "
                    f"`{skill}(...)` directly next time."
                )
                prior = blob.get("message")
                blob["message"] = f"{prior}\n{note}" if prior else note
                return json.dumps(blob, separators=(",", ":"), ensure_ascii=False)
            return raw
        return json.dumps(
            _skill_is_actually_tool_envelope(skill),
            separators=(",", ":"),
            ensure_ascii=False,
        )

    async def _run_skill_script(
        ctx: ToolContext,
        *,
        skill: str,
        script: str,
        argv: Sequence[str] | None = None,
    ) -> str:
        # Coerce a string-typed argv the model sends under CodeMode (e.g. argv='["x"]')
        # before dispatch, so a JSON-string call runs instead of vanishing in the sandbox.
        coerced_argv, argv_err = _coerce_argv_arg(argv)
        if argv_err is not None:
            return enveloped_failure(argv_err, code=ToolResultCode.VALIDATION_ERROR)
        argv = coerced_argv
        routed = await _maybe_route_tool_as_skill(
            ctx, skill=skill, via="run_skill_script", argv=argv
        )
        if routed is not None:
            return routed
        start_ns = time_ns()
        logger.debug(
            "skill_call.start kind=script skill={} script={} argc={}",
            skill,
            script,
            len(argv) if argv else 0,
        )
        try:
            result = await skills_manager.run_script(
                skill,
                script,
                args=argv or (),
                session_id=ctx.session_id,
                artifact_output_prefix=ctx.artifact_output_prefix,
            )
        except Exception as exc:
            logger.debug(
                "skill_call.finish kind=script skill={} script={} status=error "
                "dur_ms={:.1f} error={}",
                skill,
                script,
                (time_ns() - start_ns) / 1_000_000,
                type(exc).__name__,
            )
            raise
        logger.debug(
            "skill_call.finish kind=script skill={} script={} status={} dur_ms={:.1f}",
            skill,
            script,
            "ok" if isinstance(result, dict) and result.get("ok", True) else "error",
            (time_ns() - start_ns) / 1_000_000,
        )
        return json.dumps(result, separators=(",", ":"), ensure_ascii=False)

    async def _run_skill_runnable(
        ctx: ToolContext,
        *,
        skill: str,
        runnable: str,
        payload: dict[str, object] | None = None,
    ) -> str:
        # Coerce a string-typed payload the model sends under CodeMode (e.g. payload='{...}')
        # before dispatch, so a JSON-string call runs instead of vanishing in the sandbox.
        coerced_payload, payload_err = _coerce_payload_arg(payload)
        if payload_err is not None:
            return enveloped_failure(payload_err, code=ToolResultCode.VALIDATION_ERROR)
        payload = coerced_payload
        # Guard: if the *runnable* argument names a registered native/MCP tool,
        # redirect immediately — even when *skill* is a legitimate skill name.
        # This catches ``run_skill_runnable(skill="browser-harness", runnable="serp")``
        # which the existing ``_maybe_route_tool_as_skill`` (keyed on ``skill``) misses
        # because "browser-harness" is a real skill (L3 locked decision 2026-06-04).
        if _is_registered_tool_name(ctx, runnable):
            return json.dumps(
                _skill_is_actually_tool_envelope(runnable),
                separators=(",", ":"),
                ensure_ascii=False,
            )
        routed = await _maybe_route_tool_as_skill(
            ctx,
            skill=skill,
            via="run_skill_runnable",
            payload=payload,
        )
        if routed is not None:
            return routed
        start_ns = time_ns()
        logger.debug(
            "skill_call.start kind=runnable skill={} runnable={} payload_keys={}",
            skill,
            runnable,
            sorted(payload.keys()) if isinstance(payload, dict) else None,
        )
        try:
            result = await skills_manager.run_runnable(skill, runnable, params=payload or {})
        except Exception as exc:
            logger.debug(
                "skill_call.finish kind=runnable skill={} runnable={} status=error "
                "dur_ms={:.1f} error={}",
                skill,
                runnable,
                (time_ns() - start_ns) / 1_000_000,
                type(exc).__name__,
            )
            raise
        logger.debug(
            "skill_call.finish kind=runnable skill={} runnable={} status={} dur_ms={:.1f}",
            skill,
            runnable,
            "ok" if isinstance(result, dict) and result.get("ok", True) else "error",
            (time_ns() - start_ns) / 1_000_000,
        )
        return json.dumps(result, separators=(",", ":"), ensure_ascii=False)

    executor.register(FunctionTool(_run_skill_script_definition(), _run_skill_script))
    executor.register(FunctionTool(_run_skill_runnable_definition(), _run_skill_runnable))
    executor.register(FunctionTool(_skill_create_definition(), _skill_create))
    executor.register(FunctionTool(_promote_generated_skill_definition(), _promote_generated_skill))


__all__ = [
    "SkillsBackedLoadSkillTool",
    "register_skill_tools",
    "register_skill_tools_unconfigured",
]
