"""Central home for agent prompt text and fallback strings.

Every prompt the gateway shows to a model, and every canned message it shows
to the user when a turn can't complete, lives under this package. Code that
*assembles* prompts (cache layering, transcript injection, etc.) stays in
``sevn.agent.triager.prompt`` / ``sevn.agent.persona``; only the *text content*
is centralised here.

Module: sevn.prompts
Depends: sevn.prompts.{triager,tier_b,fallbacks}

Exports:
    triager — triager system-prompt segments (`specs/13-rlm-triager.md`).
    tier_b — tier-B persona / repo-access / hallucination-guard / file-link blocks.
    fallbacks — user-visible canned messages on turn failure or escalation gaps.
"""

from __future__ import annotations

from sevn.prompts import fallbacks, tier_b, triager

__all__ = ["fallbacks", "tier_b", "triager"]
