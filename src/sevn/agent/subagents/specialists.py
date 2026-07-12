"""Resolve specialist level-2 configs to executor settings and enforce gating (D8/W3.4).

Module: sevn.agent.subagents.specialists
Depends: sevn.config.defaults, sevn.config.sections.subagents

Exports:
    ResolvedSpecialist — provider/model/transport bundle for a specialist L2 spawn.
    resolve_specialist — look up ``subagents.specialists.<name>`` by name.
    resolve_specialist_transport — provider/model → transport (reuses MiniMax defaults).
    resolve_specialist_executor — ``SpecialistConfig`` → :class:`ResolvedSpecialist`.
    specialist_spawn_allowed — ``assigned_to`` / ``requestable_by`` + triager-grant gate (D8).
    merge_specialist_grants — merge triager grants with skill→specialist bindings (W8.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sevn.config.defaults import DEFAULT_MINIMAX_TRANSPORT

if TYPE_CHECKING:
    from sevn.config.sections.subagents import Role, SpecialistConfig, SubAgentsWorkspaceConfig

__all__ = [
    "ResolvedSpecialist",
    "merge_specialist_grants",
    "resolve_specialist",
    "resolve_specialist_executor",
    "resolve_specialist_transport",
    "specialist_spawn_allowed",
]


@dataclass(frozen=True, slots=True)
class ResolvedSpecialist:
    """Executor settings resolved from one ``subagents.specialists.<name>`` entry (D8).

    Args:
        name (str): Specialist id (e.g. ``media_generator``).
        model (str): Configured model id, verbatim from :class:`SpecialistConfig`.
        provider (str): Configured provider key (e.g. ``minimax``).
        transport_name (str): Resolved wire transport (``chat_completions``, ``anthropic``, …).
        max_concurrent (int): Concurrency cap enforced by the supervisor (D8).
        system_prompt_ref (str | None): Optional system-prompt reference.
    """

    name: str
    model: str
    provider: str
    transport_name: str
    max_concurrent: int
    system_prompt_ref: str | None = None


def resolve_specialist(
    cfg: SubAgentsWorkspaceConfig | None,
    name: str,
) -> SpecialistConfig | None:
    """Look up one specialist entry by name.

    Args:
        cfg (SubAgentsWorkspaceConfig | None): Parsed ``subagents`` subtree, or ``None``.
        name (str): Specialist id.

    Returns:
        SpecialistConfig | None: The entry, or ``None`` when unconfigured.

    Examples:
        >>> resolve_specialist(None, "media_generator") is None
        True
    """
    if cfg is None:
        return None
    return cfg.specialists.get(name)


def resolve_specialist_transport(
    providers_obj: dict[str, Any],
    specialist: SpecialistConfig,
) -> str:
    """Resolve the wire transport for one specialist entry (D8).

    Precedence mirrors :func:`sevn.config.model_resolution.resolve_transport_for_model_id`,
    keyed by the specialist's own explicit ``provider`` (rather than a ``minimax/``-prefixed
    catalog id, since :class:`SpecialistConfig` already carries the provider separately):

    1. Per-model override — ``providers.models.<specialist.model>.transport``.
    2. Provider-level override — ``providers.<specialist.provider>.transport``.
    3. MiniMax's documented default (``chat_completions``) when ``provider == "minimax"``.
    4. Generic ``chat_completions`` fallback.

    Args:
        providers_obj (dict[str, Any]): Merged ``providers`` block (see
            :func:`sevn.config.sections.providers.providers_section_dict`).
        specialist (SpecialistConfig): Specialist entry under resolution.

    Returns:
        str: Lowercased transport name.

    Examples:
        >>> from sevn.config.sections.subagents import SpecialistConfig
        >>> spec = SpecialistConfig(model="minimax-3", provider="minimax")
        >>> resolve_specialist_transport({}, spec)
        'chat_completions'
        >>> resolve_specialist_transport({"minimax": {"transport": "anthropic"}}, spec)
        'anthropic'
        >>> resolve_specialist_transport(
        ...     {"models": {"minimax-3": {"transport": "responses"}}}, spec
        ... )
        'responses'
    """
    models = providers_obj.get("models")
    if isinstance(models, dict):
        raw = models.get(specialist.model)
        if isinstance(raw, dict):
            transport = raw.get("transport")
            if isinstance(transport, str) and transport.strip():
                return transport.strip().lower()
    provider_entry = providers_obj.get(specialist.provider)
    if isinstance(provider_entry, dict):
        transport = provider_entry.get("transport")
        if isinstance(transport, str) and transport.strip():
            return transport.strip().lower()
    if specialist.provider.strip().lower() == "minimax":
        return str(DEFAULT_MINIMAX_TRANSPORT)
    return "chat_completions"


def resolve_specialist_executor(
    name: str,
    specialist: SpecialistConfig,
    *,
    providers_obj: dict[str, Any] | None = None,
) -> ResolvedSpecialist:
    """Bundle one specialist entry's executor settings (D8).

    Args:
        name (str): Specialist id.
        specialist (SpecialistConfig): Parsed entry.
        providers_obj (dict[str, Any] | None): Merged ``providers`` block for transport
            resolution; ``None`` uses built-in defaults only.

    Returns:
        ResolvedSpecialist: Provider/model/transport bundle.

    Examples:
        >>> from sevn.config.sections.subagents import SpecialistConfig
        >>> spec = SpecialistConfig(model="minimax-3", provider="minimax")
        >>> resolved = resolve_specialist_executor("media_generator", spec)
        >>> (resolved.provider, resolved.transport_name)
        ('minimax', 'chat_completions')
    """
    transport = resolve_specialist_transport(providers_obj or {}, specialist)
    return ResolvedSpecialist(
        name=name,
        model=specialist.model,
        provider=specialist.provider,
        transport_name=transport,
        max_concurrent=specialist.max_concurrent,
        system_prompt_ref=specialist.system_prompt_ref,
    )


def specialist_spawn_allowed(
    specialist: SpecialistConfig,
    *,
    role: Role,
    granted_by_triager: bool = False,
) -> bool:
    """Whether ``role`` may spawn this specialist as a level-2 run (D8/W3.4).

    Allowed when any of:

    1. ``role`` is in ``specialist.assigned_to`` — the specialist is a default
       part of that role's toolkit.
    2. ``role`` is in ``specialist.requestable_by`` — the specialist explicitly
       opts in to being requested by this role directly.
    3. ``granted_by_triager`` is ``True`` and ``"triager"`` is in
       ``specialist.requestable_by`` — the triager attached a same-turn grant
       (``specialist_grants``, W3.4) and the specialist opts in to
       triager-brokered grants for roles outside 1/2.

    Args:
        specialist (SpecialistConfig): Specialist entry under gating.
        role (Role): Requesting level-1 role.
        granted_by_triager (bool): Whether the triager attached a same-turn
            ``specialist_grants`` entry naming this specialist.

    Returns:
        bool: ``True`` when the spawn is permitted.

    Examples:
        >>> from sevn.config.sections.subagents import SpecialistConfig
        >>> spec = SpecialistConfig(
        ...     model="minimax-3", provider="minimax",
        ...     assigned_to=["tier_b"], requestable_by=["triager", "tier_b"],
        ... )
        >>> specialist_spawn_allowed(spec, role="tier_b")
        True
        >>> specialist_spawn_allowed(spec, role="tier_c")
        False
        >>> specialist_spawn_allowed(spec, role="tier_c", granted_by_triager=True)
        True
    """
    if role in specialist.assigned_to:
        return True
    if role in specialist.requestable_by:
        return True
    return granted_by_triager and "triager" in specialist.requestable_by


def merge_specialist_grants(
    explicit: list[str] | tuple[str, ...],
    skills: list[str] | tuple[str, ...],
    cfg: SubAgentsWorkspaceConfig | None,
) -> frozenset[str]:
    """Merge triager grants with skill→specialist bindings (W8.3 / D8 ``skill`` field).

    When a triage-selected skill name matches ``subagents.specialists.<id>.skill``,
    that specialist id is auto-granted for the tier-B dispatch.

    Args:
        explicit (list[str] | tuple[str, ...]): Triager ``specialist_grants`` list.
        skills (list[str] | tuple[str, ...]): Triager ``skills`` list.
        cfg (SubAgentsWorkspaceConfig | None): Parsed ``subagents`` subtree.

    Returns:
        frozenset[str]: Effective specialist grant ids for this turn.

    Examples:
        >>> from sevn.config.sections.subagents import SpecialistConfig, SubAgentsWorkspaceConfig
        >>> cfg = SubAgentsWorkspaceConfig(
        ...     specialists={
        ...         "media_generator": SpecialistConfig(
        ...             model="minimax-3",
        ...             provider="minimax",
        ...             skill="media_generation",
        ...         ),
        ...     },
        ... )
        >>> merge_specialist_grants([], ["media_generation"], cfg)
        frozenset({'media_generator'})
    """
    names = {name.strip() for name in explicit if name.strip()}
    if cfg is None:
        return frozenset(names)
    skill_set = {skill.strip() for skill in skills if skill.strip()}
    for specialist_id, spec in cfg.specialists.items():
        bound = (spec.skill or "").strip()
        if bound and bound in skill_set:
            names.add(specialist_id)
    return frozenset(names)
