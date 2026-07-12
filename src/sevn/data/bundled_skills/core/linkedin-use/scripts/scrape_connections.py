#!/usr/bin/env python3
"""Bundled ``linkedin-use`` skill — scrape connections."""

from __future__ import annotations

import argparse

from sevn.browser.recipes.base import RecipeError
from sevn.browser.recipes.linkedin import dry_run_requested, run_linkedin_op_sync
from sevn.lcm.script_cli import write_error, write_ok

from ._cli import content_root_from_env, session_id_from_env


def main(argv: list[str] | None = None) -> int:
    """Scrape the logged-in account's LinkedIn connections."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-results", type=int, default=1000, help="Maximum profiles.")
    parser.add_argument("--extra-profile-data", action="store_true", help="Enrich profiles.")
    parser.add_argument("--dry-run", action="store_true", help="Plan-only JSON (no browser).")
    args = parser.parse_args(argv)

    try:
        payload = run_linkedin_op_sync(
            content_root=content_root_from_env(),
            session_id=session_id_from_env(),
            op="connections",
            dry_run=dry_run_requested(cli_flag=args.dry_run),
            max_results=args.max_results,
            extra_profile_data=args.extra_profile_data,
        )
    except RecipeError as exc:
        write_error(code="BROWSER_FAILED", error=str(exc))
        return 1

    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
