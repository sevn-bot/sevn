#!/usr/bin/env python3
"""Bundled ``email-management`` skill — send plain-text email via SMTP.

Module: sevn.data.bundled_skills.core.email-management.scripts.send
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
    load_accounts,
    resolve_account,
    resolve_password,
    send_smtp_message,
)


def main(argv: list[str] | None = None) -> int:
    """Send a plain-text email for one configured account.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` on validation or SMTP failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True, help="Configured account id.")
    parser.add_argument("--to", required=True, help="Recipient email address.")
    parser.add_argument("--subject", required=True, help="Message subject.")
    parser.add_argument("--body", required=True, help="Plain-text body.")
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
        if account.backend == "gmail_api":
            msg = "email-management: send.py requires imap backend with SMTP host"
            raise ValueError(msg)
        password = resolve_password(account)
        result = send_smtp_message(
            account,
            password,
            to_addr=args.to,
            subject=args.subject,
            body=args.body,
            dry_run=dry_run_requested(cli_flag=args.dry_run),
        )
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1
    except Exception as exc:
        write_error(code="SMTP_FAILED", error=str(exc))
        return 1

    write_ok(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
