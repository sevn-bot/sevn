"""Tier-B CodeMode helpers (`specs/14-executor-tier-b.md` W8; D8/D9).

Triager-scoped Monty sandbox via ``pydantic-ai-harness`` — host tools re-enter
``ToolExecutor.dispatch``; no third-party imports inside the sandbox.

When CodeMode is enabled, W7 ``WebSearch`` / ``WebFetch`` capabilities are omitted and
triager-scoped web registry tools (``serp``, ``get_page_content``, …) are tagged
``code_mode=True`` instead (always-local under CodeMode).

Module: sevn.agent.adapters.tier_b_codemode
Depends: pydantic_ai_harness, sevn.config.model_resolution

Exports:
    is_codemode_eligible_tool — whether a tool name may enter CodeMode metadata.
    compute_codemode_eligible_names — triager-scoped tool names for ``code_mode`` metadata.
    build_codemode_capability — ``CodeMode(tools={'code_mode': True}, max_retries=3)``.

Examples:
    >>> compute_codemode_eligible_names(
    ...     triager_tools=frozenset({"glob", "read", "load_tool"}),
    ...     triager_skills=frozenset(),
    ... ) == frozenset({"glob", "read"})
    True
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sevn.config.defaults import DEFAULT_CODEMODE_MAX_RETRIES

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pydantic_ai.capabilities.abstract import AbstractCapability

    from sevn.agent.executors.b_types import BTierDeps

CODEMODE_NATIVE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "request_escalation",
        "load_tool",
        "load_skill",
        "list_registry",
        "delete",
    }
)
"""Tools that remain native pydantic-ai calls when CodeMode is enabled (D9)."""

CODEMODE_SKILL_RUNNER_NAMES: frozenset[str] = frozenset(
    {"run_skill_script", "run_skill_runnable"},
)
"""Skill runners exposed to the sandbox only when ``triage.skills[]`` is non-empty (D9)."""

CODEMODE_MAX_RETRIES: int = DEFAULT_CODEMODE_MAX_RETRIES


def is_codemode_eligible_tool(
    tool_name: str,
    *,
    triager_tools: frozenset[str],
    triager_skills: frozenset[str],
) -> bool:
    """Return whether *tool_name* may be tagged ``code_mode=True`` for this turn.

    Args:
        tool_name (str): Registry or meta tool name.
        triager_tools (frozenset[str]): Names the Triager listed in ``triage.tools[]``.
        triager_skills (frozenset[str]): Names the Triager listed in ``triage.skills[]``.

    Returns:
        bool: ``True`` when the tool may run inside ``run_code`` for this turn.

    Examples:
        >>> is_codemode_eligible_tool(
        ...     "glob",
        ...     triager_tools=frozenset({"glob", "read"}),
        ...     triager_skills=frozenset(),
        ... )
        True
        >>> is_codemode_eligible_tool(
        ...     "load_tool",
        ...     triager_tools=frozenset({"glob", "load_tool"}),
        ...     triager_skills=frozenset(),
        ... )
        False
        >>> is_codemode_eligible_tool(
        ...     "run_skill_script",
        ...     triager_tools=frozenset({"read"}),
        ...     triager_skills=frozenset({"pdf"}),
        ... )
        True
    """
    if tool_name in CODEMODE_NATIVE_TOOL_NAMES:
        return False
    if tool_name in CODEMODE_SKILL_RUNNER_NAMES:
        return bool(triager_skills)
    return tool_name in triager_tools


def compute_codemode_eligible_names(
    *,
    triager_tools: frozenset[str],
    triager_skills: frozenset[str],
) -> frozenset[str]:
    """Compute registry tool names to tag with ``code_mode`` metadata for one turn.

    Args:
        triager_tools (frozenset[str]): ``triage.tools[]`` for the turn.
        triager_skills (frozenset[str]): ``triage.skills[]`` for the turn.

    Returns:
        frozenset[str]: Names eligible for ``CodeMode(tools={'code_mode': True})``.

    Examples:
        >>> sorted(
        ...     compute_codemode_eligible_names(
        ...         triager_tools=frozenset({"glob", "read", "delete"}),
        ...         triager_skills=frozenset(),
        ...     )
        ... )
        ['glob', 'read']
    """
    eligible: set[str] = set()
    candidates = set(triager_tools) | CODEMODE_SKILL_RUNNER_NAMES
    for name in candidates:
        if is_codemode_eligible_tool(
            name,
            triager_tools=triager_tools,
            triager_skills=triager_skills,
        ):
            eligible.add(name)
    return frozenset(eligible)


def build_codemode_capability(
    limits: Mapping[str, float | int] | None = None,
    *,
    max_retries: int | None = None,
) -> AbstractCapability[BTierDeps]:
    """Build the tier-B ``CodeMode`` capability (W8.2).

    Installs a Monty ``ResourceLimits`` shim first so a runaway ``run_code`` snippet aborts
    inside the sandbox instead of blocking the event loop (see :mod:`sevn.agent.adapters.
    _monty_limits`). ``limits`` defaults to :func:`default_codemode_limits`.

    Args:
        limits (Mapping[str, float | int] | None): Monty ``ResourceLimits`` mapping; ``None``
            uses the defaults.
        max_retries (int | None): ``run_code`` retry budget; ``None`` uses
            :data:`DEFAULT_CODEMODE_MAX_RETRIES`.

    Returns:
        AbstractCapability[BTierDeps]: ``CodeMode`` selecting metadata-tagged tools only.

    Examples:
        >>> cap = build_codemode_capability()
        >>> cap.__class__.__name__
        'CodeMode'
    """
    from pydantic_ai_harness import CodeMode

    from sevn.agent.adapters._monty_limits import install_monty_resource_limits

    install_monty_resource_limits(limits)
    effective_retries = DEFAULT_CODEMODE_MAX_RETRIES if max_retries is None else max_retries
    return cast(
        "AbstractCapability[BTierDeps]",
        CodeMode(tools={"code_mode": True}, max_retries=effective_retries),
    )


__all__ = [
    "CODEMODE_MAX_RETRIES",
    "CODEMODE_NATIVE_TOOL_NAMES",
    "CODEMODE_SKILL_RUNNER_NAMES",
    "build_codemode_capability",
    "compute_codemode_eligible_names",
    "is_codemode_eligible_tool",
]
