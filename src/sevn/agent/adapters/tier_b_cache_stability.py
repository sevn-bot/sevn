"""Tier-B prompt-cache collapse monitor — harness WarnOnCacheBusts factory (D9/W7).

Observational capability for Anthropic prompt-cache concerns: warns when a previously
established cache prefix collapses between model requests. Default-off so tier-B behavior
and capability inventory stay unchanged until explicitly enabled.

Module: sevn.agent.adapters.tier_b_cache_stability
Depends: pydantic_ai_harness.warn_on_cache_busts

Exports:
    build_cache_stability_monitor_capability — factory returning ``WarnOnCacheBusts``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_ai_harness.warn_on_cache_busts import WarnOnCacheBusts

if TYPE_CHECKING:
    from pydantic_ai.capabilities.abstract import AbstractCapability


def build_cache_stability_monitor_capability() -> AbstractCapability[Any]:
    """Build the harness cache-stability monitor for tier-B (D9).

    Returns:
        AbstractCapability: ``WarnOnCacheBusts`` with harness defaults (observational only).

    Examples:
        >>> cap = build_cache_stability_monitor_capability()
        >>> cap.__class__.__name__
        'WarnOnCacheBusts'
    """
    return WarnOnCacheBusts()


__all__ = ["build_cache_stability_monitor_capability"]
