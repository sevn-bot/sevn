"""Cross-model eval on the golden_llm harness (#91, W32).

Module: sevn.model_eval
Depends: sevn.model_eval.compare, sevn.model_eval.config, sevn.model_eval.replay, sevn.model_eval.suite

Exports:
    D21_DECISION — operator gate outcome (golden_llm only; no spy_hermes tooling).
    hermes_eval_live_enabled — opt-in live cross-model runs.
    hermes_eval_suite_case_ids — fixed advisory suite case ids.
    scenario_classes — scenario-class → case id mapping.
    run_replay_comparison_report — tokenless replay report.
    run_live_model_comparison — live multi-model comparison (keys required).
"""

from __future__ import annotations

from sevn.model_eval.config import D21_DECISION, hermes_eval_live_enabled
from sevn.model_eval.replay import run_replay_comparison_report
from sevn.model_eval.suite import hermes_eval_suite_case_ids, scenario_classes

__all__ = [
    "D21_DECISION",
    "hermes_eval_live_enabled",
    "hermes_eval_suite_case_ids",
    "run_live_model_comparison",
    "run_replay_comparison_report",
    "scenario_classes",
]


def __getattr__(name: str) -> object:
    """Lazy-load live comparison to avoid importing test fixtures at import time.

    Args:
        name (str): Attribute name requested by the importer.

    Returns:
        object: Lazy export (currently ``run_live_model_comparison`` only).

    Examples:
        >>> import sevn.model_eval as me
        >>> me.run_live_model_comparison.__name__
        'run_live_model_comparison'
    """
    if name == "run_live_model_comparison":
        from sevn.model_eval.compare import run_live_model_comparison

        return run_live_model_comparison
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
