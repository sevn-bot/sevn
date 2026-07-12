#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — Bundled ``playwright-browser`` skill script..

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.extract_page_text
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

import argparse
import asyncio
import sys
from typing import Any

from _pw_session import browser_session, wait_for_page_ready

# Ordered: prefer repo README / docs over generic chrome.
_GITHUB_SELECTORS = [
    "article.markdown-body",
    ".markdown-body",
    '[data-testid="markdown-body"]',
    "[data-tagsearch-path] .markdown-body",
    "#wiki-body .markdown-body",
    ".js-wiki-content",
    # Single file / blob (code or rendered markdown)
    ".react-code-text",
    ".react-code-text-contents",
    "div.react-code-text",
    ".blob-wrapper .highlight",
    ".blob-wrapper pre",
    "table.js-file-line-container",
    ".js-file-line-container",
    # Repo overview / file list + sidebar (still better than raw <body> noise)
    '[data-testid="repository-main-header"]',
    ".Layout-main",
    "#repo-content-pjax-container",
    '[data-selector="repos-split-pane-content"]',
]

_GENERIC_SELECTORS = [
    "article",
    '[role="main"]',
    "main",
    "#content",
    "#main",
    "body",
]


async def _first_usable_text(
    page: Any, selectors: list[str], *, min_len: int = 40
) -> tuple[str, str]:
    for sel in selectors:
        loc = page.locator(sel)
        try:
            n = await loc.count()
        except Exception:
            continue
        if n == 0:
            continue
        first = loc.first
        try:
            txt = await first.inner_text(timeout=12_000)
        except Exception:
            continue
        t = (txt or "").strip()
        if len(t) >= min_len:
            return t, sel
    try:
        t = (await page.locator("body").inner_text(timeout=15_000) or "").strip()
        return t, "body"
    except Exception:
        return "", "none"


async def main() -> int:
    ap = argparse.ArgumentParser(
        description="Extract visible text for summarization (GitHub-friendly).",
    )
    ap.add_argument(
        "--preset",
        choices=("auto", "github", "generic"),
        default="auto",
        help="github: GitHub DOM selectors first; generic: article/main/body; auto: github.com → github else generic",
    )
    ap.add_argument(
        "--max-chars",
        type=int,
        default=400_000,
        help="Truncate output (default 400k)",
    )
    ap.add_argument(
        "--min-len",
        type=int,
        default=40,
        help="Minimum chars to accept from a selector (skip tiny matches)",
    )
    args = ap.parse_args()

    async with browser_session() as page:
        await wait_for_page_ready(page)
        url = ""
        try:
            url = page.url or ""
        except Exception:
            pass

        preset = args.preset
        if preset == "auto":
            preset = "github" if "github.com" in url.lower() else "generic"

        if preset == "github":
            text, used = await _first_usable_text(
                page, _GITHUB_SELECTORS + _GENERIC_SELECTORS, min_len=args.min_len
            )
        else:
            text, used = await _first_usable_text(page, _GENERIC_SELECTORS, min_len=args.min_len)

        print(
            f"(extract_page_text: preset={preset} selector={used} chars={len(text)})\n",
            file=sys.stderr,
        )
        if len(text) > args.max_chars:
            print(f"(truncated to {args.max_chars} chars)\n", file=sys.stderr)
            text = text[: args.max_chars]
        from _output import emit_ok

        emit_ok(
            {
                "text": text,
                "chars": len(text),
                "selector": used,
                "preset": preset,
                "url": url,
            },
        )
        return 0


def _entry() -> int:
    from _output import main_guard
    from typing import cast

    @main_guard  # type: ignore[untyped-decorator]
    def _run() -> int:
        return asyncio.run(main())

    return cast("int", _run())


if __name__ == "__main__":
    raise SystemExit(_entry())
