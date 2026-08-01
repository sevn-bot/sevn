#!/usr/bin/env python3
"""Bundled ``hermes-model-eval`` skill — tokenless replay comparison report.

Module: sevn.data.bundled_skills.core.hermes-model-eval.scripts.replay_report
Depends: argparse, sevn.model_eval.replay, sevn.model_eval.suite

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from _common import emit_json, ensure_repo_root_on_path  # noqa: E402

ensure_repo_root_on_path()

from sevn.model_eval.replay import run_replay_comparison_report
from sevn.model_eval.suite import hermes_eval_suite_case_ids


def main(argv: list[str] | None = None) -> int:
    """Run tokenless golden_llm replay and emit a comparison report.

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
    case_ids = tuple(args.case_ids) if args.case_ids else hermes_eval_suite_case_ids()
    try:
        report = run_replay_comparison_report(case_ids=case_ids)
    except (AssertionError, ValueError) as exc:
        emit_json({"ok": False, "error": str(exc)})
        return 1
    payload = report.to_dict()
    payload["ok"] = True
    emit_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
