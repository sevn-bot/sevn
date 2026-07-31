"""Hermes model eval config resolution (#91, W32).

Module: sevn.model_eval.config
Depends: os, sevn.config.defaults, sevn.config.model_resolution

Exports:
    HermesEvalModelSpec — one configured comparison model alias.
    hermes_eval_live_enabled — ``SEVN_HERMES_MODEL_EVAL=1`` gate.
    hermes_model_eval_enabled — workspace ``skills.hermes_model_eval.enabled``.
    resolve_hermes_eval_models — configured model aliases for comparison.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sevn.config.defaults import (
    DEFAULT_HERMES_MODEL_EVAL_ENABLED,
    DEFAULT_USE_MAIN_MODEL_FOR_ALL,
)
from sevn.config.model_resolution import ModelSlot, resolve_model_slot

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

D21_DECISION: str = (
    "W32 D21 gate (2026-07-31): scripts/spy_hermes.py and make spy-hermes-* are absent; "
    "Hermes 4 model eval builds on tests/fixtures/golden_llm/ only — no upstream spy_hermes tooling."
)

HERMES_EVAL_LIVE_ENV = "SEVN_HERMES_MODEL_EVAL"


@dataclass(frozen=True, slots=True)
class HermesEvalModelSpec:
    """One provider-agnostic model alias in the comparison matrix."""

    label: str
    model_id: str


def hermes_eval_live_enabled() -> bool:
    """Return whether live cross-model eval runs are allowed.

    Returns:
        bool: True when ``SEVN_HERMES_MODEL_EVAL=1``.

    Examples:
        >>> hermes_eval_live_enabled() in (True, False)
        True
    """
    return os.environ.get(HERMES_EVAL_LIVE_ENV) == "1"


def _hermes_eval_blob(workspace: WorkspaceConfig) -> dict[str, Any]:
    """Return raw ``skills.hermes_model_eval`` blob from workspace config.

    Args:
        workspace (WorkspaceConfig): Bound workspace config.

    Returns:
        dict[str, Any]: Skill config blob (possibly empty).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _hermes_eval_blob(WorkspaceConfig.minimal())
        {}
    """
    skills = getattr(workspace, "skills", None)
    raw = getattr(skills, "raw", None) if skills is not None else None
    if not isinstance(raw, dict):
        return {}
    blob = raw.get("hermes_model_eval")
    return blob if isinstance(blob, dict) else {}


def hermes_model_eval_enabled(workspace: WorkspaceConfig) -> bool:
    """Read ``skills.hermes_model_eval.enabled`` (default off, D9).

    Args:
        workspace (WorkspaceConfig): Bound workspace config.

    Returns:
        bool: Whether the advisory eval skill is enabled.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> hermes_model_eval_enabled(WorkspaceConfig.minimal())
        False
    """
    blob = _hermes_eval_blob(workspace)
    enabled = blob.get("enabled")
    if isinstance(enabled, bool):
        return enabled
    return DEFAULT_HERMES_MODEL_EVAL_ENABLED


def resolve_hermes_eval_models(workspace: WorkspaceConfig) -> tuple[HermesEvalModelSpec, ...]:
    """Resolve configured comparison models; fall back to tier-B default.

    Hermes aliases are provider-agnostic catalog ids — no hard-coded vendor
    assumptions (D10). Results are advisory and do not change routing defaults (D9).

    Args:
        workspace (WorkspaceConfig): Bound workspace config.

    Returns:
        tuple[HermesEvalModelSpec, ...]: At least one model spec.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> specs = resolve_hermes_eval_models(WorkspaceConfig.minimal())
        >>> len(specs) >= 1
        True
    """
    blob = _hermes_eval_blob(workspace)
    models_raw = blob.get("models")
    specs: list[HermesEvalModelSpec] = []
    if isinstance(models_raw, list):
        for row in models_raw:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "").strip()
            model_id = str(row.get("model_id") or "").strip()
            if label and model_id:
                specs.append(HermesEvalModelSpec(label=label, model_id=model_id))
    if specs:
        return tuple(specs)
    default_id = resolve_model_slot(workspace, ModelSlot.tier_b)
    _ = DEFAULT_USE_MAIN_MODEL_FOR_ALL  # documented routing context; eval does not mutate it
    return (HermesEvalModelSpec(label="tier_b_default", model_id=default_id),)


__all__ = [
    "D21_DECISION",
    "HERMES_EVAL_LIVE_ENV",
    "HermesEvalModelSpec",
    "hermes_eval_live_enabled",
    "hermes_model_eval_enabled",
    "resolve_hermes_eval_models",
]
