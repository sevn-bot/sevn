#!/usr/bin/env python3
"""Bundled ``openwiki`` skill — non-interactive wiki generation via OpenWiki CLI.

Module: sevn.data.bundled_skills.core.openwiki.scripts.generate
Depends: argparse, os, sevn.code_understanding.openwiki_runner, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout (dry-run or live openwiki subprocess).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from sevn.code_understanding.openwiki_runner import (
    DEFAULT_OPENWIKI_TIMEOUT_SECONDS,
    build_openwiki_argv,
    content_root_from_env,
    looks_like_credentials_error,
    resolve_openwiki_root,
    run_openwiki_subprocess,
)
from sevn.lcm.script_cli import write_error, write_ok
from sevn.skills.openwiki_secrets import openwiki_credentials_hint

_DRY_RUN_ENV = "SEVN_OPENWIKI_DRY_RUN"


def _dry_run_requested(*, cli_flag: bool) -> bool:
    """Return True when dry-run mode is selected via CLI or environment.

    Args:
        cli_flag (bool): Whether ``--dry-run`` was passed on the CLI.

    Returns:
        bool: True when the script should print argv only (no subprocess).

    Examples:
        >>> _dry_run_requested(cli_flag=True)
        True
    """
    if cli_flag:
        return True
    return os.environ.get(_DRY_RUN_ENV, "").strip().lower() in {"1", "true", "yes"}


def main(argv: list[str] | None = None) -> int:
    """Generate or update OpenWiki documentation non-interactively.

    When ``--dry-run`` or ``SEVN_OPENWIKI_DRY_RUN=1`` is set, prints a success
    envelope with the argv plan only. Otherwise invokes ``openwiki`` when the npm
    CLI is installed; missing CLI returns ``DEPENDENCY_MISSING``.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` on validation or execution failure.

    Examples:
        >>> import io, contextlib
        >>> buf = io.StringIO()
        >>> with contextlib.redirect_stdout(buf):
        ...     rc = main(["--dry-run", "--mode", "init"])
        >>> rc
        0
        >>> '"mode":"dry_run"' in buf.getvalue()
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        required=True,
        choices=["init", "update", "chat"],
        help="OpenWiki run mode: init, update, or chat.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root; defaults to workspace source_code/ mirror when present.",
    )
    parser.add_argument("--message", default=None, help="Optional trailing user message.")
    parser.add_argument("--model-id", default=None, help="Optional OpenWiki model id override.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print argv plan only (also via SEVN_OPENWIKI_DRY_RUN=1).",
    )
    args = parser.parse_args(argv)

    workspace = content_root_from_env()
    root = Path(args.root).resolve() if args.root else resolve_openwiki_root(workspace)

    try:
        argv_plan = build_openwiki_argv(
            mode=args.mode,  # type: ignore[arg-type]
            message=args.message,
            model_id=args.model_id,
            print_mode=True,
        )
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1

    if _dry_run_requested(cli_flag=args.dry_run):
        write_ok(
            {
                "mode": "dry_run",
                "argv": argv_plan,
                "run_mode": args.mode,
                "root": str(root),
            },
        )
        return 0

    ok, detail, returncode = run_openwiki_subprocess(
        argv_plan,
        cwd=root,
        timeout=DEFAULT_OPENWIKI_TIMEOUT_SECONDS,
        env=os.environ.copy(),
    )
    if not ok:
        if returncode == 127:
            write_error(code="DEPENDENCY_MISSING", error=detail)
        elif looks_like_credentials_error(detail):
            write_error(
                code="CREDENTIALS_MISSING",
                error=f"{detail} — {openwiki_credentials_hint()}",
            )
        else:
            write_error(code="BUILD_FAILED", error=f"openwiki: {detail}")
        return 1

    write_ok(
        {
            "mode": "live",
            "argv": argv_plan,
            "run_mode": args.mode,
            "root": str(root),
            "returncode": returncode,
            "stdout": detail[:8192],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
