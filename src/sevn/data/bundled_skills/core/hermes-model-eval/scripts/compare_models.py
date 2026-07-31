#!/usr/bin/env python3
"""Bundled ``hermes-model-eval`` skill — live cross-model comparison.

Module: sevn.data.bundled_skills.core.hermes-model-eval.scripts.compare_models
Depends: argparse, sevn.model_eval.compare, sevn.model_eval.config, sevn.model_eval.suite

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from _common import emit_json, load_workspace_config  # noqa: E402

from sevn.model_eval.compare import run_live_model_comparison
from sevn.model_eval.config import hermes_eval_live_enabled, hermes_model_eval_enabled
from sevn.model_eval.suite import hermes_eval_suite_case_ids


def main(argv: list[str] | None = None) -> int:
    """Run live model comparison when ``SEVN_HERMES_MODEL_EVAL=1``.

    Args:
        argv (list[str] | None): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case-id",
        action="append",
        dest="case_ids",
        default=[],
        help="Restrict to specific golden case ids (repeatable).",
    )
    args = parser.parse_args(argv)
    workspace = load_workspace_config()
    if not hermes_model_eval_enabled(workspace):
        emit_json(
            {
                "ok": False,
                "error": "skills.hermes_model_eval.enabled is false (D9 default-off)",
            },
        )
        return 1
    if not hermes_eval_live_enabled():
        emit_json(
            {
                "ok": False,
                "error": "Set SEVN_HERMES_MODEL_EVAL=1 for live cross-model comparison",
            },
        )
        return 1
    case_ids = tuple(args.case_ids) if args.case_ids else hermes_eval_suite_case_ids()
    try:
        report = run_live_model_comparison(workspace, case_ids=case_ids)
    except (RuntimeError, ValueError) as exc:
        emit_json({"ok": False, "error": str(exc)})
        return 1
    payload = report.to_dict()
    payload["ok"] = True
    emit_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
