"""Request triage and routing types (`specs/10-schema-ontology.md` §2.1; `specs/13` façade).

Module: sevn.agent.triager
Depends: sevn.agent.providers.budget, sevn.agent.triager.models

Exports:
    BudgetRegime — re-export from provider budgets (`specs/10-schema-ontology.md` §3.4.1).
    COMPLEXITY_TIERS — tuple of all ``ComplexityTier`` members (§3.2).
    ComplexityTier — tier A-D enum.
    FollowupAnchor — discriminated union of per-channel anchors (§2.2).
    Intent — triage intent enum.
    MessageKind — message / command / blocked.
    SessionVisibility — type alias for visibility literals.
    SessionVisibilityLiteral — same, explicit name for annotations.
    TelegramFollowupAnchor — Telegram FOLLOWUP anchor (§2.2).
    TriageResult — structured Triager output model (ontology §2 lives in ``models.py`` — no duplicate).
    WebUIFollowupAnchor — Web UI FOLLOWUP anchor (§2.2).
    triage_turn — ``specs/13`` async entrypoint.
"""

from __future__ import annotations

from sevn.agent.providers.budget import BudgetRegime
from sevn.agent.triager.errors import TriagerUnavailable, TriagerUnknownToolAbort
from sevn.agent.triager.models import (
    COMPLEXITY_TIERS,
    ComplexityTier,
    FollowupAnchor,
    Intent,
    MessageKind,
    SessionVisibility,
    SessionVisibilityLiteral,
    TelegramFollowupAnchor,
    TriageResult,
    WebUIFollowupAnchor,
)
from sevn.agent.triager.run import triage_turn

__all__ = [
    "COMPLEXITY_TIERS",
    "BudgetRegime",
    "ComplexityTier",
    "FollowupAnchor",
    "Intent",
    "MessageKind",
    "SessionVisibility",
    "SessionVisibilityLiteral",
    "TelegramFollowupAnchor",
    "TriageResult",
    "TriagerUnavailable",
    "TriagerUnknownToolAbort",
    "WebUIFollowupAnchor",
    "triage_turn",
]
