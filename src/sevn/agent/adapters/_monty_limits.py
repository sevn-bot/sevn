"""Inject Monty ``ResourceLimits`` into CodeMode sandbox sessions (D5/D6).

Module: sevn.agent.adapters._monty_limits
Depends: pydantic_monty, pydantic_ai_harness.code_mode

Harness 0.13+ drives Monty via ``Monty()`` / ``AsyncMonty()`` pool checkout rather than
``MontyRepl``. We patch ``checkout`` on both pool types so every CodeMode session receives
sevn's ``DEFAULT_CODEMODE_*`` caps when the caller omits ``limits``.

Install is idempotent and **fail-loud**: if the injection target disappears (upstream
execution-model drift), :func:`install_monty_resource_limits` raises :class:`MontyLimitInstallError`
instead of silently skipping — the regression this module exists to prevent (2026-06-22 freeze).

Upstream tracking (delete this patch when landed):
https://github.com/pydantic/pydantic-ai-harness/issues/501

Exports:
    MontyLimitInstallError — raised when limit injection cannot be installed.
    default_codemode_limits — ResourceLimits mapping from ``DEFAULT_CODEMODE_*``.
    install_monty_resource_limits — patch Monty/AsyncMonty checkout to default-inject limits.
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

_UPSTREAM_RESOURCE_LIMITS_ISSUE = "https://github.com/pydantic/pydantic-ai-harness/issues/501"

_lock = threading.Lock()
_installed = False
_active_limits: dict[str, float | int] = {}
_original_checkouts: dict[type[Any], Any] = {}


class MontyLimitInstallError(RuntimeError):
    """Raised when Monty ResourceLimits injection cannot be installed (D5)."""


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


def _limits_object(limits: Mapping[str, float | int]) -> Any:
    """Build a pydantic_monty ``ResourceLimits`` from a plain mapping.

    Args:
        limits (Mapping[str, float | int]): Limit fields to apply at checkout.

    Returns:
        Any: ``ResourceLimits`` instance for Monty checkout.

    Examples:
        >>> from sevn.agent.adapters._monty_limits import _limits_object
        >>> obj = _limits_object({"max_duration_secs": 1.0, "max_memory": 1, "max_allocations": 1})
        >>> obj["max_duration_secs"]
        1.0
    """
    from pydantic_monty import ResourceLimits

    return ResourceLimits(
        max_duration_secs=limits.get("max_duration_secs"),
        max_memory=int(limits["max_memory"]) if "max_memory" in limits else None,
        max_allocations=int(limits["max_allocations"]) if "max_allocations" in limits else None,  # type: ignore[typeddict-unknown-key]
    )


def _limited_checkout(original: Any, pool: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Call the real ``checkout`` with sevn default ``ResourceLimits`` when omitted.

    Args:
        original (Any): Unpatched ``Monty.checkout`` or ``AsyncMonty.checkout``.
        pool (Any): Monty pool instance.
        args (Any): Positional args forwarded to ``checkout``.
        kwargs (Any): Keyword args forwarded to ``checkout``; ``limits`` defaults when omitted.

    Returns:
        Any: Checked-out Monty session context manager.

    Examples:
        >>> True
        True
    """
    if kwargs.get("limits") is None:
        kwargs["limits"] = _limits_object(_active_limits)
    return original(pool, *args, **kwargs)


def _assert_injection_targets_present() -> tuple[type[Any], type[Any]]:
    """Verify Monty pool types exist for limit injection.

    Returns:
        tuple[type[Any], type[Any]]: ``(Monty, AsyncMonty)`` classes.

    Raises:
        MontyLimitInstallError: When either pool type is missing.

    Examples:
        >>> from pydantic_ai_harness.code_mode import _toolset as ts
        >>> hasattr(ts, "Monty")
        True
    """
    try:
        from pydantic_ai_harness.code_mode import _toolset as harness_toolset
    except Exception as exc:  # pragma: no cover - harness optional
        msg = f"CodeMode limit injection: harness code_mode._toolset import failed: {exc}"
        raise MontyLimitInstallError(msg) from exc

    monty_cls = getattr(harness_toolset, "Monty", None)
    if monty_cls is None:
        msg = (
            "CodeMode limit injection target missing: "
            "pydantic_ai_harness.code_mode._toolset.Monty — "
            f"file upstream {_UPSTREAM_RESOURCE_LIMITS_ISSUE}"
        )
        raise MontyLimitInstallError(msg)

    try:
        from pydantic_monty import AsyncMonty
    except Exception as exc:  # pragma: no cover
        msg = f"CodeMode limit injection: pydantic_monty.AsyncMonty import failed: {exc}"
        raise MontyLimitInstallError(msg) from exc

    return monty_cls, AsyncMonty


def install_monty_resource_limits(limits: Mapping[str, float | int] | None = None) -> None:
    """Patch Monty pool ``checkout`` so CodeMode sessions carry default resource limits.

    Idempotent: patches are applied once; subsequent calls only update the active limits
    mapping injected when ``limits=None`` at checkout.

    Args:
        limits (Mapping[str, float | int] | None): ``ResourceLimits`` mapping; defaults to
            :func:`default_codemode_limits` when ``None``.

    Raises:
        MontyLimitInstallError: When the harness Monty injection anchor is absent (D5).

    Examples:
        >>> install_monty_resource_limits({"max_duration_secs": 5})  # doctest: +SKIP
    """
    global _installed, _active_limits
    with _lock:
        _active_limits = dict(limits) if limits is not None else default_codemode_limits()
        if _installed:
            return

        monty_cls, async_monty_cls = _assert_injection_targets_present()

        for cls in (monty_cls, async_monty_cls):
            if cls not in _original_checkouts:
                original = cls.checkout
                _original_checkouts[cls] = original

                def _patched(pool: Any, /, *args: Any, _orig: Any = original, **kwargs: Any) -> Any:
                    return _limited_checkout(_orig, pool, *args, **kwargs)

                cls.checkout = _patched

        _installed = True


__all__ = [
    "MontyLimitInstallError",
    "default_codemode_limits",
    "install_monty_resource_limits",
]
