#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — Bundled ``playwright-browser`` skill script..

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.cdp_probe
Depends: sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

import sys
from pathlib import Path

_bootstrap_dir = Path(__file__).resolve().parent / "_lib"
if str(_bootstrap_dir) not in sys.path:
    sys.path.insert(0, str(_bootstrap_dir))
import _bootstrap  # noqa: F401

import json
import os
import sys
import urllib.error
import urllib.request

from _pw_session import cdp_reachable


def main() -> int:
    from _output import emit_error, emit_ok

    url = __import__("os").environ.get("SEVN_CDP_URL", "http://127.0.0.1:9222").rstrip("/")
    if len(sys.argv) > 1 and sys.argv[1].strip():
        url = sys.argv[1].strip().rstrip("/")
    ok = cdp_reachable(url)
    payload: dict[str, object] = {"cdp_url": url, "reachable": ok}
    if ok:
        try:
            ver = f"{url}/json/version"
            with urllib.request.urlopen(ver, timeout=3) as r:
                data = json.loads(r.read().decode("utf-8", errors="replace"))
            payload["browser"] = data.get("Browser", data)
        except Exception as exc:  # noqa: BLE001
            payload["version_error"] = str(exc)
    if ok:
        emit_ok(payload)
        return 0
    emit_error("CDP_UNREACHABLE", f"CDP endpoint not reachable: {url}")
    return 1


def _entry() -> int:
    from _output import main_guard

    @main_guard
    def _run() -> int:
        return main()

    return _run()


if __name__ == "__main__":
    raise SystemExit(_entry())
