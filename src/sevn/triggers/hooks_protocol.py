"""Minimal hook surface for trigger ingress (`specs/34-plugin-hooks.md` §4.7 stub).

Module: sevn.triggers.hooks_protocol
Depends: typing

Exports:
    TriggerPluginHookSurface — protocol implemented by future plugin-hook wiring.

Examples:
    >>> from sevn.triggers.hooks_protocol import TriggerPluginHookSurface
    >>> hasattr(TriggerPluginHookSurface, "trigger_before_receive")
    True
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TriggerPluginHookSurface(Protocol):
    """Optional augmentation around trigger receive / dispatch (normative in **34**)."""

    async def trigger_before_receive(
        self,
        *,
        transport: str,
        correlation_id: str,
        trigger_meta: dict[str, object],
    ) -> None:
        """Run after verify/validate, before dedupe decisions.

        Args:
            transport (str): Coarse transport label (``webhook``, ``api``, ``cron``).
            correlation_id (str): Trace id for this fire.
            trigger_meta (dict[str, object]): Provider metadata (delivery id, …).

        Examples:
            >>> # Implemented when plugin hooks register instances.
            >>> True
            True
        """
        ...

    async def trigger_after_dispatch(
        self,
        *,
        transport: str,
        correlation_id: str,
        trigger_meta: dict[str, object],
        status: str,
    ) -> None:
        """Run after a trigger arm finishes (success or fail_closed).

        Args:
            transport (str): Coarse transport label.
            correlation_id (str): Trace identifier.
            trigger_meta (dict[str, object]): Provider metadata.
            status (str): Outcome label for operators (``ok``, ``error``, …).

        Examples:
            >>> # Implemented when plugin hooks register instances.
            >>> True
            True
        """
        ...
