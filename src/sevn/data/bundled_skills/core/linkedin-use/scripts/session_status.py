#!/usr/bin/env python3
"""Bundled ``linkedin-use`` skill — session status."""

from __future__ import annotations

import argparse

from sevn.browser.recipes.linkedin import dry_run_requested
from sevn.browser.recipes.linkedin_scraper import LINKEDIN_EGRESS
from sevn.lcm.script_cli import write_ok
from sevn.skills.browser_session import default_cdp_url, session_status_payload
from sevn.skills.social_browser import cdp_reachable

from ._cli import content_root_from_env, session_id_from_env


def main(argv: list[str] | None = None) -> int:
    """Report LinkedIn browser session status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Plan-only JSON (no browser).")
    args = parser.parse_args(argv)

    workspace = content_root_from_env()
    session_id = session_id_from_env()
    cdp_url = default_cdp_url()
    payload = session_status_payload(
        content_root=workspace,
        session_id=session_id,
        cfg=None,
        skill_name="linkedin-use",
    )
    payload = {
        **payload,
        "skill_id": "linkedin-use",
        "egress_domains": list(LINKEDIN_EGRESS),
        "session_model": "logged_in_browser_profile_or_cdp_attach",
        "cdp_url": cdp_url,
        "cdp_reachable": cdp_reachable(cdp_url),
    }
    if dry_run_requested(cli_flag=args.dry_run):
        payload["mode"] = "dry_run"
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
