"""Level-1/level-2 sub-agent orchestration (D1-D16, `specs/36-sub-agents.md`).

Module: sevn.agent.subagents
Depends: sevn.agent.subagents.models, sevn.agent.subagents.registry,
    sevn.agent.subagents.supervisor, sevn.agent.subagents.storage

Exports:
    SubAgentStatus, ACTIVE_STATUSES, SubAgentRun, SubAgentLimitExceeded,
    generate_short_id — domain model (D1/D3/D5).
    SubAgentRegistry, RegistrySnapshot, PersistHook — the async-safe registry (D3/D10).
    SubAgentSupervisor, SubAgentSpec, SubAgentHandle, SubAgentBody,
    AnnounceBackHook — spawn/kill/completion semantics (D4/D5/D9/D11).
    ResolvedSpecialist, resolve_specialist, resolve_specialist_executor,
    resolve_specialist_transport, specialist_spawn_allowed — specialist
    resolution + ``assigned_to``/``requestable_by`` gating (D8, W3.2).

This package deliberately never imports ``sevn.gateway`` — the gateway wires
itself to the supervisor via the ``announce_back``/``persist`` constructor
hooks (see `agent-notes.md` composition point in ``sevn.gateway.boot``),
keeping the domain layer testable in isolation.

Examples:
    >>> from sevn.agent.subagents import SubAgentRegistry, SubAgentSupervisor
    >>> isinstance(SubAgentSupervisor(SubAgentRegistry()), SubAgentSupervisor)
    True
"""

from __future__ import annotations

from sevn.agent.subagents.models import (
    ACTIVE_STATUSES,
    SubAgentLimitExceeded,
    SubAgentRun,
    SubAgentStatus,
    generate_short_id,
)
from sevn.agent.subagents.registry import PersistHook, RegistrySnapshot, SubAgentRegistry
from sevn.agent.subagents.specialists import (
    ResolvedSpecialist,
    resolve_specialist,
    resolve_specialist_executor,
    resolve_specialist_transport,
    specialist_spawn_allowed,
)
from sevn.agent.subagents.supervisor import (
    AnnounceBackHook,
    SubAgentBody,
    SubAgentHandle,
    SubAgentSpec,
    SubAgentSupervisor,
)

__all__ = [
    "ACTIVE_STATUSES",
    "AnnounceBackHook",
    "PersistHook",
    "RegistrySnapshot",
    "ResolvedSpecialist",
    "SubAgentBody",
    "SubAgentHandle",
    "SubAgentLimitExceeded",
    "SubAgentRegistry",
    "SubAgentRun",
    "SubAgentSpec",
    "SubAgentStatus",
    "SubAgentSupervisor",
    "generate_short_id",
    "resolve_specialist",
    "resolve_specialist_executor",
    "resolve_specialist_transport",
    "specialist_spawn_allowed",
]
