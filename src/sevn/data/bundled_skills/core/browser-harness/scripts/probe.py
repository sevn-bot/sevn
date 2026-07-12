#!/usr/bin/env python3
"""Bundled ``browser-harness`` skill — CDP HTTP probe.

Module: sevn.data.bundled_skills.core.browser-harness.scripts.probe
Depends: argparse, helpers, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

import helpers
from sevn.lcm.script_cli import write_error, write_ok


def main() -> int:
    """Probe CDP HTTP endpoints.

    Returns:
        int: ``0`` when reachable, ``1`` otherwise.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("cdp_url", nargs="?", default="")
    args = parser.parse_args()
    if args.cdp_url.strip():
        import os

        os.environ["SEVN_CDP_URL"] = args.cdp_url.strip().rstrip("/")
    base = helpers.default_cdp_url()
    try:
        version = helpers.cdp_http_object("/json/version")
        listing = helpers.cdp_http_json("/json/list")
        pages = [row for row in listing if isinstance(row, dict) and row.get("type") == "page"]
        write_ok(
            {
                "cdp_url": base,
                "reachable": True,
                "browser": version.get("Browser"),
                "webSocketDebuggerUrl": version.get("webSocketDebuggerUrl"),
                "page_targets": len(pages),
            }
        )
        return 0
    except RuntimeError as exc:
        write_error(code="CDP_UNREACHABLE", error=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
