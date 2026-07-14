"""Gateway lifecycle event hooks.

Module: sevn.gateway.hooks.event_hooks
Depends: collections.abc

Exports:
    GatewayEvent — event name constants.
    GatewayEventPayload — event envelope.
    register_gateway_event_hook — append async listener.
    emit_gateway_event — dispatch event to registered hooks.
    clear_gateway_event_hooks — reset registry (tests).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

JsonDict = dict[str, Any]

GatewayEventHook = Callable[["GatewayEventPayload"], Awaitable[None]]

_HOOKS: list[tuple[int, str, GatewayEventHook]] = []


class GatewayEvent:
    """Stable gateway event names."""

    TURN_COMPLETE = "gateway.turn.complete"
    TURN_ERROR = "gateway.turn.error"
    CHANNEL_REGISTERED = "gateway.channel.registered"


@dataclass(frozen=True, slots=True)
class GatewayEventPayload:
    """Immutable event envelope passed to hooks."""

    event: str
    session_id: str | None
    channel: str | None
    attrs: JsonDict


def register_gateway_event_hook(
    name: str,
    hook: GatewayEventHook,
    *,
    priority: int = 0,
) -> None:
    """Register an async gateway event listener.

    Args:
        name (str): Stable hook id.
        hook (GatewayEventHook): Async callback.
        priority (int): Lower runs first.

    Examples:
        >>> async def _noop(_p: GatewayEventPayload) -> None:
        ...     return None
        >>> register_gateway_event_hook("test", _noop)
        >>> any(n == "test" for _, n, _ in _HOOKS)
        True
    """
    if any(existing == name for _, existing, _ in _HOOKS):
        msg = f"gateway event hook already registered: {name}"
        raise ValueError(msg)
    _HOOKS.append((priority, name, hook))


def clear_gateway_event_hooks() -> None:
    """Remove all hooks (test isolation).

    Examples:
        >>> clear_gateway_event_hooks()
        >>> _HOOKS
        []
    """
    _HOOKS.clear()


async def emit_gateway_event(payload: GatewayEventPayload) -> None:
    """Dispatch ``payload`` to hooks in priority order; errors are logged, not raised.

    Args:
        payload (GatewayEventPayload): Event to emit.

    Examples:
        >>> import asyncio
        >>> from sevn.gateway.hooks.event_hooks import GatewayEvent, GatewayEventPayload
        >>> asyncio.run(emit_gateway_event(GatewayEventPayload(
        ...     event=GatewayEvent.TURN_COMPLETE, session_id="s", channel="telegram", attrs={}
        ... )))
    """
    for _, name, hook in sorted(_HOOKS, key=lambda row: row[0]):
        try:
            await hook(payload)
        except Exception as exc:
            from loguru import logger

            logger.warning("gateway event hook {} failed: {}", name, exc)
