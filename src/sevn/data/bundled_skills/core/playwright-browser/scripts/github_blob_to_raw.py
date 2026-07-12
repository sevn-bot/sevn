#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — Bundled ``playwright-browser`` skill script..

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.github_blob_to_raw
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

import re
import sys
from urllib.parse import unquote, urlparse


def blob_url_to_raw(url: str) -> str | None:
    u = (url or "").strip()
    if not u:
        return None
    p = urlparse(u)
    if p.netloc.lower() != "github.com":
        return None
    path = unquote(p.path or "")
    # /owner/repo/blob/ref/rest/of/path
    m = re.match(r"^/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$", path)
    if not m:
        return None
    owner, repo, ref, rest = m.groups()
    rest = rest.strip("/")
    if not rest:
        return None
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{rest}"


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: github_blob_to_raw.py <github_blob_url>", file=sys.stderr)
        from _output import emit_error

        emit_error("VALIDATION", "Usage: github_blob_to_raw.py <github_blob_url>")
        sys.exit(2)
    raw = blob_url_to_raw(sys.argv[1])
    if not raw:
        from _output import emit_error

        emit_error("CONVERSION_FAILED", "could not convert blob URL")
        return 1
    from _output import emit_ok

    emit_ok({"raw_url": raw})
    return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard
    def _run() -> int:
        return main()

    return _run()


if __name__ == "__main__":
    raise SystemExit(_entry())
