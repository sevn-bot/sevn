#!/usr/bin/env python3
"""Bundled ``facebook-use`` skill — logged-in browser session status.

Module: sevn.data.bundled_skills.core.facebook-use.scripts.session_status
Depends: argparse, sevn.lcm.script_cli, sevn.skills.browser_session, sevn.skills.social_browser

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import os

from sevn.lcm.script_cli import workspace_from_env, write_ok
from sevn.skills.browser_session import session_status_payload
from sevn.skills.social_browser import FACEBOOK_USE_SKILL_ID, SKILL_EGRESS


def main(argv: list[str] | None = None) -> int:
    """Report session-bound browser profile and CDP status for Facebook workflows.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Alias for plan-only output.")
    _ = parser.parse_args(argv)

    workspace = workspace_from_env()
    session_id = os.environ.get("SEVN_SESSION_ID", "").strip() or "default"
    payload = session_status_payload(
        content_root=workspace,
        session_id=session_id,
        cfg=None,
        skill_name=FACEBOOK_USE_SKILL_ID,
    )
    payload = {
        **payload,
        "skill_id": FACEBOOK_USE_SKILL_ID,
        "egress_domains": list(SKILL_EGRESS[FACEBOOK_USE_SKILL_ID]),
        "session_model": "logged_in_browser_profile_or_cdp_attach",
        "lifecycle_scripts": {
            "session_status": "playwright-browser/scripts/session_status.py",
            "close_browser": "playwright-browser/scripts/close_browser.py",
            "restart_browser": "playwright-browser/scripts/restart_browser.py",
        },
    }
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
