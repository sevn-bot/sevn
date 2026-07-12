#!/usr/bin/env python3
"""Bundled ``linkedin-use`` skill — scrape staff."""

from __future__ import annotations

import argparse

from sevn.browser.recipes.base import RecipeError
from sevn.browser.recipes.linkedin import dry_run_requested, run_linkedin_op_sync
from sevn.lcm.script_cli import write_error, write_ok

from ._cli import content_root_from_env, session_id_from_env


def main(argv: list[str] | None = None) -> int:
    """Scrape LinkedIn staff for a company."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", required=True, help="Company universal name or search term.")
    parser.add_argument("--search-term", default="", help="Additional keyword filter.")
    parser.add_argument("--location", default="", help="Location filter.")
    parser.add_argument("--max-results", type=int, default=1000, help="Maximum profiles.")
    parser.add_argument("--extra-profile-data", action="store_true", help="Enrich profiles.")
    parser.add_argument("--dry-run", action="store_true", help="Plan-only JSON (no browser).")
    args = parser.parse_args(argv)

    dry = dry_run_requested(cli_flag=args.dry_run)
    try:
        payload = run_linkedin_op_sync(
            content_root=content_root_from_env(),
            session_id=session_id_from_env(),
            op="staff",
            dry_run=dry,
            company=args.company,
            search_term=args.search_term,
            location=args.location,
            max_results=args.max_results,
            extra_profile_data=args.extra_profile_data,
        )
    except RecipeError as exc:
        message = str(exc)
        code = "LOGIN_REQUIRED" if "LOGIN_REQUIRED" in message else "BROWSER_FAILED"
        if "RATE_LIMITED" in message:
            code = "RATE_LIMITED"
        elif "VOYAGER" in message.upper():
            code = "VOYAGER_QUERY_STALE"
        write_error(code=code, error=message)
        return 1

    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
