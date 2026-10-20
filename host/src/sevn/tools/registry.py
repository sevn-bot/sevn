"""``register_toolset`` so later plans add tools without editing core (D19)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sevn.domain.bots import BotRecord


@dataclass(frozen=True, slots=True)
class TurnDeps:
    """Identifiers a toolset factory closes over for one turn."""

    bot_id: str = ""
    agent_id: str = ""
    turn_id: str = ""
    approved: bool = False


type ToolsetFactory = Callable[[TurnDeps], object]
type ToolsetCondition = Callable[[BotRecord], bool]


@dataclass(frozen=True, slots=True)
class RegisteredToolset:
    """One registered toolset and the bot predicate that includes it."""

    name: str
    factory: ToolsetFactory
    eager: set[str]
    condition: ToolsetCondition
    deferred: set[str]


def always(_bot: BotRecord) -> bool:
    """Include the toolset for every bot."""
    return True


_toolsets: dict[str, RegisteredToolset] = {}


def register_toolset(
    name: str,
    factory: ToolsetFactory,
    eager: set[str],
    condition: ToolsetCondition = always,
    *,
    deferred: set[str] | None = None,
) -> None:
    """Register ``factory``. A second registration of ``name`` replaces the first."""
    _toolsets[name] = RegisteredToolset(
        name=name,
        factory=factory,
        eager=set(eager),
        condition=condition,
        deferred=set() if deferred is None else set(deferred),
    )


def unregister_toolset(name: str) -> None:
    """Remove one toolset. Missing names are ignored."""
    _toolsets.pop(name, None)


def toolsets_for(bot: BotRecord) -> list[RegisteredToolset]:
    """Toolsets whose condition accepts ``bot``, in registration order."""
    return [item for item in _toolsets.values() if item.condition(bot)]
