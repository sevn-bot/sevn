"""Budget regime + per-model budget metadata (PRD 05).

Module: sevn.agent.providers.budget
Depends: pydantic

Exports:
    BudgetRegime — subscription vs per-token vs local.
    ModelBudget — formal pairing attached to routed ``model_id``.

Examples:
    >>> b = ModelBudget(model_id="anthropic/claude-3-5-haiku", regime=BudgetRegime.PER_TOKEN)
    >>> b.regime == BudgetRegime.PER_TOKEN
    True
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class BudgetRegime(StrEnum):
    """How the operator pays for calls on this model (PRD 05 §5.3)."""

    SUBSCRIPTION = "SUBSCRIPTION"
    PER_TOKEN = "PER_TOKEN"  # nosec B105
    FREE_LOCAL = "FREE_LOCAL"


class ModelBudget(BaseModel):
    """Budget metadata carried with a resolved ``model_id`` (PRD 05 §5.4)."""

    model_config = ConfigDict(extra="ignore")

    model_id: str = Field(..., description="Catalog id, e.g. anthropic/claude-sonnet-4-6")
    regime: BudgetRegime
    subscription_window_id: str | None = None
    notes: str | None = None
