#!/usr/bin/env python3
"""Bundled ``google-workspace`` skill — Google API command shim.

Module: sevn.data.bundled_skills.core.google-workspace.scripts.google_api
Depends: argparse, importlib, os, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import importlib
import os

from sevn.lcm.script_cli import write_error, write_ok

_DRY_RUN_ENV = "SEVN_GOOGLE_DRY_RUN"


def _dry_run_requested(*, cli_flag: bool) -> bool:
    """Return True when dry-run is selected via CLI or environment."""
    if cli_flag:
        return True
    return os.environ.get(_DRY_RUN_ENV, "").strip().lower() in {"1", "true", "yes"}


def _import_runtime_module() -> object | None:
    """Import ``sevn.skills.google_workspace`` when present."""
    try:
        return importlib.import_module("sevn.skills.google_workspace")
    except ModuleNotFoundError as exc:
        if exc.name == "sevn.skills.google_workspace":
            return None
        raise


def _argv_plan(args: argparse.Namespace) -> list[str]:
    """Return a compact argv plan for dry-run envelopes."""
    argv = [args.service, args.operation]
    if args.resource:
        argv.append(args.resource)
    return argv


def main(argv: list[str] | None = None) -> int:
    """Run a narrow Google Workspace CLI shim with dry-run planning."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "service",
        choices=["gmail", "calendar", "drive", "sheets", "docs", "contacts"],
    )
    parser.add_argument(
        "operation",
        help="Service operation (for example: search, get, create).",
    )
    parser.add_argument(
        "resource",
        nargs="?",
        default=None,
        help="Primary query/id/path argument.",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=10,
        help="Row cap for list/search operations.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Emit a plan envelope only.",
    )
    args, extra = parser.parse_known_args(argv)

    if _dry_run_requested(cli_flag=args.dry_run):
        write_ok(
            {
                "mode": "dry_run",
                "service": args.service,
                "operation": args.operation,
                "query": args.resource,
                "max_results": args.max,
                "extra_args": extra,
                "argv": _argv_plan(args) + extra,
            },
        )
        return 0

    if args.service == "gmail" and args.operation == "search" and args.resource:
        mod = _import_runtime_module()
        if mod is None or not hasattr(mod, "gmail_search"):
            write_error(
                code="DEPENDENCY_MISSING",
                error=(
                    "sevn.skills.google_workspace.gmail_search is unavailable; "
                    "use --dry-run or add the runtime module."
                ),
            )
            return 1
        search_fn = getattr(mod, "gmail_search")
        rows = search_fn(args.resource, max_results=args.max)
        write_ok(
            {
                "mode": "live",
                "service": "gmail",
                "operation": "search",
                "query": args.resource,
                "messages": rows,
                "count": len(rows),
            },
        )
        return 0

    write_error(
        code="NOT_IMPLEMENTED",
        error=(
            "Only gmail search live execution is scaffolded here; use --dry-run "
            "for other operations until the shared google_workspace runtime is wired."
        ),
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
