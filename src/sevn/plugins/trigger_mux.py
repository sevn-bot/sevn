"""Multiplex trigger ingress/egress across loaded plugin hooks.

Module: sevn.plugins.trigger_mux
Depends: sevn.plugins.hook, sevn.triggers.hooks_protocol

Exports:
    TriggerPluginHooksMux — ``TriggerPluginHookSurface`` over ``PluginHookChain``.
    as_trigger_surface — normalize ``None`` chain to absent mux.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sevn.plugins.runner import PluginHookChain
    from sevn.triggers.hooks_protocol import TriggerPluginHookSurface


class TriggerPluginHooksMux:
    """Fan-out trigger callbacks to every registered :class:`~sevn.plugins.hook.PluginHook`."""

    def __init__(self, chain: PluginHookChain) -> None:
        """Capture the ordered hook list to forward trigger lifecycle events.

        Args:
            chain (PluginHookChain): Hooks loaded at gateway startup.

        Examples:
            >>> from sevn.plugins.runner import PluginHookChain
            >>> isinstance(TriggerPluginHooksMux(PluginHookChain(())), TriggerPluginHooksMux)
            True
        """
        self._chain = chain

    async def trigger_before_receive(
        self,
        *,
        transport: str,
        correlation_id: str,
        trigger_meta: dict[str, object],
    ) -> None:
        """Call each hook's ``trigger_before_receive`` in registration order.

        Args:
            transport (str): Transport label.
            correlation_id (str): Correlation id.
            trigger_meta (dict[str, object]): Metadata.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        for rh in self._chain.hooks:
            await rh.hook.trigger_before_receive(
                transport=transport,
                correlation_id=correlation_id,
                trigger_meta=trigger_meta,
            )

    async def trigger_after_dispatch(
        self,
        *,
        transport: str,
        correlation_id: str,
        trigger_meta: dict[str, object],
        status: str,
    ) -> None:
        """Call each hook's ``trigger_after_dispatch`` in registration order.

        Args:
            transport (str): Transport label.
            correlation_id (str): Correlation id.
            trigger_meta (dict[str, object]): Metadata.
            status (str): Outcome label.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        for rh in self._chain.hooks:
            await rh.hook.trigger_after_dispatch(
                transport=transport,
                correlation_id=correlation_id,
                trigger_meta=trigger_meta,
                status=status,
            )


def as_trigger_surface(chain: PluginHookChain | None) -> TriggerPluginHookSurface | None:
    """Return a multiplex surface when hooks exist.

    Args:
        chain (PluginHookChain | None): Loaded hooks, if any.

    Returns:
        TriggerPluginHookSurface | None: Multiplexer or ``None``.

    Examples:
        >>> as_trigger_surface(None) is None
        True
    """
    if chain is None or not chain.hooks:
        return None
    return TriggerPluginHooksMux(chain)


__all__ = ["TriggerPluginHooksMux", "as_trigger_surface"]
