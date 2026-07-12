#!/usr/bin/env python3
"""Bundled ``browser-harness`` skill — run Python with helpers preloaded.

Module: sevn.data.bundled_skills.core.browser-harness.scripts.run
Depends: argparse, runpy, helpers, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

import helpers
from sevn.lcm.script_cli import write_error, write_ok


def main() -> int:
    """Execute a Python file with ``helpers`` injected into ``runpy`` globals.

    Returns:
        int: ``0`` on success.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("script", help="Python file under the workspace shadow")
    parser.add_argument("script_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    target = Path(args.script).resolve()
    if not target.is_file():
        write_error(code="VALIDATION", error=f"script not found: {target}")
        return 2
    argv = [str(target), *args.script_args]
    sys.argv = argv
    globals_dict = {
        "__name__": "__main__",
        "__file__": str(target),
        "helpers": helpers,
        "browser_cdp": helpers.browser_cdp,
    }
    try:
        runpy.run_path(str(target), init_globals=globals_dict, run_name="__main__")
    except Exception as exc:  # noqa: BLE001 — skill script boundary
        write_error(code="RUN_FAILED", error=str(exc))
        return 1
    write_ok({"script": str(target), "argv": argv[1:]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
