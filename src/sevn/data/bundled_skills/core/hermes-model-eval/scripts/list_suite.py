#!/usr/bin/env python3
"""Bundled ``hermes-model-eval`` skill — list fixed suite cases.

Module: sevn.data.bundled_skills.core.hermes-model-eval.scripts.list_suite
Depends: sevn.model_eval.config, sevn.model_eval.suite

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

from _common import emit_json, ensure_repo_root_on_path  # noqa: E402

ensure_repo_root_on_path()

from sevn.model_eval.config import D21_DECISION
from sevn.model_eval.suite import scenario_classes


def main() -> int:
    """Print scenario classes and case ids.

    Returns:
        int: Exit code ``0``.

    Examples:
        >>> main() == 0
        True
    """
    emit_json(
        {
            "ok": True,
            "d21_decision": D21_DECISION,
            "scenarios": {name: list(case_ids) for name, case_ids in scenario_classes().items()},
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
