"""Confidence gates for jev and each fallback step (D4)."""

from __future__ import annotations

from sevn.config import DecisionThresholds, Settings

STEP_CONFIDENCE = 0.6


def jev_thresholds() -> DecisionThresholds:
    """Thresholds from ``decisions.thresholds`` in the host config."""
    return Settings.load().decisions.thresholds


def jev_accepts(*, intent: float, target: float | None, busy: float | None) -> bool:
    """True when every asked jev question meets its own threshold."""
    gates = jev_thresholds()
    if intent < gates.intent:
        return False
    if target is not None and target < gates.target:
        return False
    if busy is not None and busy < gates.busy:
        return False
    return True


def step_accepts(confidence: float) -> bool:
    """A fallback step below 0.6 yields to the next step."""
    return confidence >= STEP_CONFIDENCE
