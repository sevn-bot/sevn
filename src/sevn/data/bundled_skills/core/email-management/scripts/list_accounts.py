#!/usr/bin/env python3
"""Bundled ``email-management`` skill — list configured accounts.

Module: sevn.data.bundled_skills.core.email-management.scripts.list_accounts
Depends: argparse, sevn.config.loader, sevn.lcm.script_cli, sevn.skills.email_management

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.config.loader import SevnJsonNotFoundError, load_workspace
from sevn.lcm.script_cli import workspace_from_env, write_ok
from sevn.skills.email_management import (
    account_public_dict,
    dry_run_requested,
    load_accounts,
)


def main(argv: list[str] | None = None) -> int:
    """List configured mailbox accounts without secret material.

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
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    workspace = workspace_from_env()
    try:
        cfg, _layout = load_workspace(sevn_json=workspace / "sevn.json")
    except SevnJsonNotFoundError:
        cfg = None

    accounts = load_accounts(cfg)
    payload: dict[str, object] = {
        "accounts": [account_public_dict(a) for a in accounts],
        "count": len(accounts),
    }
    if dry_run_requested(cli_flag=args.dry_run):
        payload["mode"] = "dry_run"
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
