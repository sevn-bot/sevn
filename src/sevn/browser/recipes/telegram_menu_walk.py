"""CLI entry for the Telegram ``/config`` menu walker E2E harness.

Operators run via ``make telegram-menu-e2e`` (requires ``SEVN_TELEGRAM_MENU_E2E=1``).

Module: sevn.browser.recipes.telegram_menu_walk
Depends: argparse, asyncio, json, os, pathlib, sys,
    sevn.browser.recipes.telegram_menu

Exports:
    run_walk_cli — sync wrapper returning JSON text when ``json=True``.
    main — ``python -m sevn.browser.recipes.telegram_menu_walk`` entry.

Examples:
    >>> import inspect
    >>> inspect.isfunction(run_walk_cli)
    True
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from sevn.browser.recipes.base import RecipeError
from sevn.browser.recipes.telegram_menu import run_menu_walk


def _default_content_root() -> Path:
    """Return the default workspace content root for CLI runs.

    Returns:
        Path: ``SEVN_CONTENT_ROOT``, ``SEVN_WORKSPACE_ROOT``, or ``~/.sevn/workspace``.

    Examples:
        >>> _default_content_root().name
        'workspace'
    """
    env = os.environ.get("SEVN_CONTENT_ROOT") or os.environ.get("SEVN_WORKSPACE_ROOT")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".sevn" / "workspace"


def run_walk_cli(
    *,
    chat: str,
    safe: bool = True,
    as_json: bool = False,
    content_root: Path | None = None,
    profile_dir: Path | None = None,
    login_timeout: float = 300.0,
    out: Path | None = None,
    max_depth: int = 4,
) -> str:
    """Run the menu walk synchronously; return JSON text when ``as_json=True``.

    Args:
        chat (str): Bot @username or chat title.
        safe (bool): Safe mode (default ``True``).
        as_json (bool): When ``True``, return formatted JSON text.
        content_root (Path | None): Workspace root override.
        profile_dir (Path | None): Chrome profile directory.
        login_timeout (float): Login poll timeout in seconds.
        out (Path | None): Evidence output directory.
        max_depth (int): Max DFS depth forwarded to the walker.

    Returns:
        str: JSON report text.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(run_walk_cli)
        True
    """
    root = content_root or _default_content_root()
    report = asyncio.run(
        run_menu_walk(
            chat=chat,
            content_root=root,
            safe=safe,
            profile_dir=profile_dir,
            login_timeout=login_timeout,
            out=out,
            max_depth=max_depth,
        )
    )
    text = json.dumps(report, indent=2, sort_keys=True)
    if as_json:
        return text
    return text


def main(argv: list[str] | None = None) -> int:
    """CLI entry — exits non-zero on ``dead``/``error`` verdicts or coverage miss.

    Args:
        argv (list[str] | None): CLI args excluding program name.

    Returns:
        int: Process exit code (0 success, 1 failure).

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description="Walk the Telegram /config menu tree.")
    parser.add_argument("--chat", required=True, help="Bot @username or chat title")
    parser.add_argument(
        "--safe",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Safe mode: no toggle/cycle mutations (default: true)",
    )
    parser.add_argument("--mutate", action="store_true", help="Alias for --no-safe (D7)")
    parser.add_argument("--deny-extra", default="", help="Reserved: extra deny regex")
    parser.add_argument(
        "--login-timeout",
        type=float,
        default=300.0,
        help="Seconds to wait for Telegram Web login (default: 300)",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=Path(".sevn/browser-profiles/telegram-e2e"),
        help="Chrome profile directory",
    )
    parser.add_argument("--out", type=Path, default=None, help="Evidence output directory")
    parser.add_argument("--json", action="store_true", help="Print report JSON to stdout")
    parser.add_argument("--max-depth", type=int, default=4, help="Max menu DFS depth")
    parser.add_argument(
        "--content-root",
        type=Path,
        default=None,
        help="Workspace content root (default: SEVN_CONTENT_ROOT or ~/.sevn/workspace)",
    )
    args = parser.parse_args(argv)
    safe = args.safe and not args.mutate
    _ = args.deny_extra
    try:
        payload_text = run_walk_cli(
            chat=args.chat,
            safe=safe,
            as_json=True,
            content_root=args.content_root,
            profile_dir=args.profile_dir,
            login_timeout=args.login_timeout,
            out=args.out,
            max_depth=args.max_depth,
        )
    except RecipeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    report: dict[str, Any] = json.loads(payload_text)
    if args.json:
        sys.stdout.write(payload_text + "\n")
    summary = report.get("summary") or {}
    dead = int(summary.get("dead") or 0)
    error = int(summary.get("error") or 0)
    if dead or error:
        sys.stderr.write(f"walk failed: dead={dead} error={error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
