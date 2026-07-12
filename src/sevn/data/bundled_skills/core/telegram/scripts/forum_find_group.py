#!/usr/bin/env python3
"""Bundled ``telegram`` skill — resolve supergroup chat id by title.

Module: sevn.data.bundled_skills.core.telegram.scripts.forum_find_group
Depends: argparse, asyncio, sevn.channels.telegram_skill, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import asyncio

from sevn.channels.telegram_skill import find_group_by_name, resolve_telegram_skill_hooks
from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok


def main(argv: list[str] | None = None) -> int:
    """Find a supergroup chat id by display title.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="Group title substring to match.")
    args = parser.parse_args(argv)
    workspace = workspace_from_env()
    hooks = resolve_telegram_skill_hooks(workspace)
    try:
        payload = asyncio.run(find_group_by_name(hooks, name=args.name))
    except (RuntimeError, ValueError) as exc:
        write_error(code="TELEGRAM_FORUM_FIND_GROUP_FAILED", error=str(exc))
        return 1
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
