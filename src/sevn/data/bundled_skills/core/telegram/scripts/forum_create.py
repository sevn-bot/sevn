#!/usr/bin/env python3
"""Bundled ``telegram`` skill — create a forum topic.

Module: sevn.data.bundled_skills.core.telegram.scripts.forum_create
Depends: argparse, asyncio, sevn.channels.telegram_skill, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import asyncio

from sevn.channels.telegram_skill import create_forum_topic, resolve_telegram_skill_hooks
from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok


def main(argv: list[str] | None = None) -> int:
    """Create a forum topic via the Bot API hook.

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
    parser.add_argument("--chat-id", required=True, type=int, help="Supergroup chat id.")
    parser.add_argument("--name", required=True, help="Forum topic title.")
    parser.add_argument("--icon-color", type=int, default=None, help="Optional icon_color.")
    args = parser.parse_args(argv)
    workspace = workspace_from_env()
    hooks = resolve_telegram_skill_hooks(workspace)
    try:
        payload = asyncio.run(
            create_forum_topic(
                hooks,
                chat_id=args.chat_id,
                name=args.name,
                icon_color=args.icon_color,
            ),
        )
    except (RuntimeError, ValueError) as exc:
        write_error(code="TELEGRAM_FORUM_CREATE_FAILED", error=str(exc))
        return 1
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
