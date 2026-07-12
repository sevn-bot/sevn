#!/usr/bin/env python3
"""Bundled ``browser-harness`` skill — raw CDP passthrough CLI.

Module: sevn.data.bundled_skills.core.browser-harness.scripts.cdp
Depends: argparse, json, helpers, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

import helpers
from sevn.lcm.script_cli import write_error, write_ok


def main() -> int:
    """Invoke ``helpers.browser_cdp`` with CLI args.

    Returns:
        int: ``0`` on success, non-zero on validation or runtime failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("method", help="CDP method name")
    parser.add_argument("--params", default="{}", help="JSON object of CDP params")
    parser.add_argument("--session-id", default="", help="Optional CDP session id")
    args = parser.parse_args()
    try:
        params_obj: dict[str, Any] = json.loads(args.params)
    except json.JSONDecodeError as exc:
        write_error(code="VALIDATION", error=f"invalid --params JSON: {exc}")
        return 2
    if not isinstance(params_obj, dict):
        write_error(code="VALIDATION", error="--params must decode to a JSON object")
        return 2
    session_id = args.session_id.strip() or None
    try:
        result = helpers.browser_cdp(
            args.method.strip(),
            params_obj,
            session_id=session_id,
        )
    except RuntimeError as exc:
        if "websocket-client" in str(exc):
            write_error(code="DEPENDENCY_MISSING", error=str(exc))
            return 1
        write_error(code="CDP_FAILED", error=str(exc))
        return 1
    write_ok({"method": args.method.strip(), "result": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
