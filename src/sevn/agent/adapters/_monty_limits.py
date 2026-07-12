"""Inject Monty ``ResourceLimits`` into CodeMode's sandbox REPL.

Module: sevn.agent.adapters._monty_limits
Depends: pydantic_monty, pydantic_ai_harness.code_mode

``pydantic-ai-harness`` runs LLM-authored Python through Monty (``pydantic_monty``) driven
*synchronously* on the event loop (``CodeModeToolset._execution_loop`` uses ``feed_start`` /
``resume`` with no background threads). A CPU-bound or pathological ``run_code`` snippet (e.g.
catastrophic regex backtracking) therefore blocks the whole event loop, so the outer
``asyncio.wait_for`` tier-B executor timeout cannot fire and the gateway freezes until Monty
returns (an 8.5-minute freeze was observed 2026-06-22).

Monty's Rust sandbox enforces ``ResourceLimits`` (duration / memory / allocations) regardless
of the event loop, so capping execution there is the only reliable interrupt. The harness
creates ``MontyRepl()`` with no limits and exposes no knob, so we patch the ``MontyRepl``
symbol the harness imported (``pydantic_ai_harness.code_mode._toolset.MontyRepl``) to a factory
that default-injects limits. Install-once + idempotent; re-installing only updates the limits.

Exports:
    default_codemode_limits — ResourceLimits built from ``DEFAULT_CODEMODE_*``.
    install_monty_resource_limits — patch the harness ``MontyRepl`` to default-inject limits.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from sevn.config.defaults import (
    DEFAULT_CODEMODE_MAX_ALLOCATIONS,
    DEFAULT_CODEMODE_MAX_DURATION_S,
    DEFAULT_CODEMODE_MAX_MEMORY_BYTES,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_lock = threading.Lock()
_installed = False
_active_limits: dict[str, float | int] = {}


def default_codemode_limits() -> dict[str, float | int]:
    """Return the default Monty ``ResourceLimits`` mapping for CodeMode.

    Returns:
        dict[str, float | int]: ``{max_duration_secs, max_memory, max_allocations}``.

    Examples:
        >>> default_codemode_limits()["max_duration_secs"] > 0
        True
    """
    return {
        "max_duration_secs": DEFAULT_CODEMODE_MAX_DURATION_S,
        "max_memory": DEFAULT_CODEMODE_MAX_MEMORY_BYTES,
        "max_allocations": DEFAULT_CODEMODE_MAX_ALLOCATIONS,
    }


def install_monty_resource_limits(limits: Mapping[str, float | int] | None = None) -> None:
    """Patch the harness ``MontyRepl`` so CodeMode REPLs carry default resource limits.

    Idempotent: the patch is applied once; subsequent calls only update the active limits the
    factory injects. A no-op (logged, not raised) if the harness/sandbox isn't importable.

    Args:
        limits (Mapping[str, float | int] | None): ``ResourceLimits`` mapping; defaults to
            :func:`default_codemode_limits` when ``None``.

    Examples:
        >>> install_monty_resource_limits({"max_duration_secs": 5})  # doctest: +SKIP
    """
    global _installed, _active_limits
    with _lock:
        _active_limits = dict(limits) if limits is not None else default_codemode_limits()
        if _installed:
            return
        try:
            from pydantic_ai_harness.code_mode import _toolset as harness_toolset
        except Exception:  # pragma: no cover - harness optional / import shape drift
            return

        real_repl = harness_toolset.MontyRepl  # type: ignore[attr-defined]

        def _limited_monty_repl(*args: Any, **kwargs: Any) -> Any:
            """Construct a ``MontyRepl`` defaulting ``limits`` to the active CodeMode caps."""
            if kwargs.get("limits") is None:
                kwargs["limits"] = dict(_active_limits)
            return real_repl(*args, **kwargs)

        harness_toolset.MontyRepl = _limited_monty_repl  # type: ignore[attr-defined, assignment]
        _installed = True


__all__ = ["default_codemode_limits", "install_monty_resource_limits"]
