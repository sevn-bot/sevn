#!/usr/bin/env python3
"""Bundled ``facebook-use`` skill — search snapshot.

Module: sevn.data.bundled_skills.core.facebook-use.scripts.search
Depends: argparse, asyncio, sevn.lcm.script_cli, sevn.skills.social_browser

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import asyncio

from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok
from sevn.skills.social_browser import (
    FACEBOOK_USE_SKILL_ID,
    dry_run_requested,
    facebook_search_url,
    fetch_page_snapshot,
)


def main(argv: list[str] | None = None) -> int:
    """Return a visible-text snapshot of a Facebook search results page.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` on validation or runtime failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Search terms.")
    parser.add_argument("--max-chars", type=int, default=8000, help="Truncate extracted text.")
    parser.add_argument("--dry-run", action="store_true", help="Plan-only JSON (no browser).")
    args = parser.parse_args(argv)

    if not args.query.strip():
        write_error(code="VALIDATION_ERROR", error="--query is required")
        return 1

    workspace = workspace_from_env()
    url = facebook_search_url(args.query)
    dry = dry_run_requested(cli_flag=args.dry_run)
    try:
        payload = asyncio.run(
            fetch_page_snapshot(
                skill_id=FACEBOOK_USE_SKILL_ID,
                url=url,
                workspace=workspace,
                cfg=None,
                max_chars=args.max_chars,
                dry_run=dry,
            ),
        )
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1
    except RuntimeError as exc:
        message = str(exc)
        code = "DEPENDENCY_MISSING" if "playwright" in message.lower() else "BROWSER_FAILED"
        write_error(code=code, error=message)
        return 1

    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
