#!/usr/bin/env python3
"""Bundled ``email-management`` skill — fetch recent messages.

Module: sevn.data.bundled_skills.core.email-management.scripts.fetch_recent
Depends: argparse, sevn.config.loader, sevn.lcm.script_cli, sevn.skills.email_management

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.config.loader import SevnJsonNotFoundError, load_workspace
from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok
from sevn.skills.email_management import (
    dry_run_requested,
    fetch_recent_messages,
    gmail_api_plan,
    load_accounts,
    resolve_account,
    resolve_password,
    summaries_to_dicts,
)


def main(argv: list[str] | None = None) -> int:
    """Fetch recent message summaries from an IMAP folder or Gmail label.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` on validation or IMAP failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True, help="Configured account id.")
    parser.add_argument("--folder", default="INBOX", help="IMAP folder or Gmail label.")
    parser.add_argument("--limit", type=int, default=10, help="Max messages to return.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    workspace = workspace_from_env()
    try:
        cfg, _layout = load_workspace(sevn_json=workspace / "sevn.json")
    except SevnJsonNotFoundError:
        cfg = None

    try:
        accounts = load_accounts(cfg)
        account = resolve_account(accounts, args.account)
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1

    if account.backend == "gmail_api" or dry_run_requested(cli_flag=args.dry_run):
        write_ok(
            gmail_api_plan(
                account,
                operation="fetch_recent",
                folder=args.folder,
                limit=args.limit,
            ),
        )
        return 0

    try:
        password = resolve_password(account)
        rows = fetch_recent_messages(
            account,
            password,
            folder=args.folder,
            limit=max(args.limit, 0),
        )
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1
    except Exception as exc:
        write_error(code="IMAP_FAILED", error=str(exc))
        return 1

    write_ok(
        {
            "mode": "live",
            "account_id": account.id,
            "folder": args.folder,
            "messages": summaries_to_dicts(rows),
            "count": len(rows),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
