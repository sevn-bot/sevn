"""Sub-agents (L1/L2) subtree models for ``sevn.json``.

Module: sevn.config.sections.subagents
Depends: pydantic, sevn.config.defaults

Exports:
    SubAgentRoleLimits — ``subagents.agents.<role>`` per-role limit override (D2).
    SpecialistConfig — ``subagents.specialists.<name>`` specialist entry (D8).
    SubAgentsWorkspaceConfig — ``subagents`` subtree (D2).
    resolve_limits — pure precedence resolver: ``max_override`` ceiling → per-role → defaults (D2).
"""

from __future__ import annotations

from typing import Literal, cast, get_args

from pydantic import BaseModel, ConfigDict, Field

from sevn.config.defaults import (
    DEFAULT_SUBAGENT_SPECIALIST_MAX_CONCURRENT,
    DEFAULT_SUBAGENTS_ENABLED,
    DEFAULT_SUBAGENTS_MAX_LEVEL1,
    DEFAULT_SUBAGENTS_MAX_LEVEL2,
)

Role = Literal["triager", "tier_b", "tier_c", "tier_d"]
"""Level-1 sub-agent role — one of the existing tracked tier roles (D1)."""

_ROLES: frozenset[str] = frozenset(get_args(Role))


class SubAgentRoleLimits(BaseModel):
    """``subagents.agents.<role>`` — per-role level-1/level-2 concurrency override (D2)."""

    model_config = ConfigDict(extra="allow")

    max_level1: int | None = Field(default=None, ge=0)
    max_level2: int | None = Field(default=None, ge=0)


class SpecialistConfig(BaseModel):
    """``subagents.specialists.<name>`` — level-2 specialist entry (D8).

    First entry documented (not defaulted — specialists default to an empty
    dict): ``media_generator`` → ``provider: "minimax"``, ``model: "minimax-3"``,
    ``assigned_to: ["tier_b"]``, ``requestable_by: ["triager", "tier_b"]``,
    ``max_concurrent: 2``.
    """

    model_config = ConfigDict(extra="allow")

    model: str
    provider: str
    assigned_to: list[Role] = Field(default_factory=list)
    requestable_by: list[Role] = Field(default_factory=list)
    max_concurrent: int = Field(default=DEFAULT_SUBAGENT_SPECIALIST_MAX_CONCURRENT, ge=1)
    skill: str | None = None
    system_prompt_ref: str | None = None


class SubAgentsWorkspaceConfig(BaseModel):
    """Typed ``subagents`` subtree (`specs/36-sub-agents.md` D2)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = DEFAULT_SUBAGENTS_ENABLED
    max_level1_default: int = Field(default=DEFAULT_SUBAGENTS_MAX_LEVEL1, ge=0)
    max_level2_default: int = Field(default=DEFAULT_SUBAGENTS_MAX_LEVEL2, ge=0)
    max_override: int | None = Field(default=None, ge=0)
    timeout_s: float | None = Field(default=None, ge=0.0)
    agents: dict[Role, SubAgentRoleLimits] = Field(default_factory=dict)
    specialists: dict[str, SpecialistConfig] = Field(default_factory=dict)


def resolve_limits(cfg: SubAgentsWorkspaceConfig | None, role: str) -> tuple[int, int]:
    """Resolve effective ``(max_level1, max_level2)`` for a role (D2 precedence).

    Precedence: ``max_override`` (ceiling over every limit) → ``agents.<role>.*``
    (per-role override) → ``max_level1_default`` / ``max_level2_default``.

    Args:
        cfg (SubAgentsWorkspaceConfig | None): Parsed ``subagents`` subtree, or
            ``None`` to fall back to built-in defaults everywhere.
        role (str): Level-1 role name (``triager``, ``tier_b``, ``tier_c``, ``tier_d``).

    Returns:
        tuple[int, int]: ``(max_level1, max_level2)`` effective caps.

    Raises:
        ValueError: When ``role`` is not one of the four level-1 roles.

    Examples:
        >>> resolve_limits(None, "tier_b")
        (5, 3)
        >>> cfg = SubAgentsWorkspaceConfig(
        ...     agents={"tier_b": SubAgentRoleLimits(max_level1=2, max_level2=1)},
        ... )
        >>> resolve_limits(cfg, "tier_b")
        (2, 1)
        >>> resolve_limits(cfg, "tier_c")
        (5, 3)
        >>> ceiling = SubAgentsWorkspaceConfig(
        ...     max_override=1,
        ...     agents={"tier_b": SubAgentRoleLimits(max_level1=2, max_level2=1)},
        ... )
        >>> resolve_limits(ceiling, "tier_b")
        (1, 1)
        >>> resolve_limits(None, "bogus")
        Traceback (most recent call last):
            ...
        ValueError: unknown subagents role: 'bogus'
    """
    if role not in _ROLES:
        msg = f"unknown subagents role: {role!r}"
        raise ValueError(msg)
    role_ = cast("Role", role)

    if cfg is None:
        return DEFAULT_SUBAGENTS_MAX_LEVEL1, DEFAULT_SUBAGENTS_MAX_LEVEL2

    max_level1 = cfg.max_level1_default
    max_level2 = cfg.max_level2_default
    role_limits = cfg.agents.get(role_)
    if role_limits is not None:
        if role_limits.max_level1 is not None:
            max_level1 = role_limits.max_level1
        if role_limits.max_level2 is not None:
            max_level2 = role_limits.max_level2

    if cfg.max_override is not None:
        max_level1 = min(max_level1, cfg.max_override)
        max_level2 = min(max_level2, cfg.max_override)

    return max_level1, max_level2
