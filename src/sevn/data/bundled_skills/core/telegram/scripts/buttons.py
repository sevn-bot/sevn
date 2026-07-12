#!/usr/bin/env python3
"""Bundled ``telegram`` skill — custom inline button store.

Module: sevn.data.bundled_skills.core.telegram.scripts.buttons
Depends: argparse, sevn.channels.telegram_skill, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.channels.telegram_skill import (
    add_custom_button,
    build_custom_inline_keyboard,
    clear_custom_buttons,
    list_custom_buttons,
    remove_custom_button,
)
from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok


def main(argv: list[str] | None = None) -> int:
    """Manage workspace custom Telegram inline buttons.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` on validation failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        required=True,
        choices=("list", "add", "remove", "clear", "keyboard"),
        help="list|add|remove|clear|keyboard",
    )
    parser.add_argument("--name", help="Button label for add/remove.")
    parser.add_argument("--command", help="Slash command or payload for add.")
    args = parser.parse_args(argv)
    workspace = workspace_from_env()

    if args.action == "list":
        rows = list_custom_buttons(workspace)
        write_ok({"buttons": rows, "count": len(rows)})
        return 0
    if args.action == "keyboard":
        keyboard = build_custom_inline_keyboard(workspace)
        write_ok(keyboard)
        return 0
    if args.action == "clear":
        removed = clear_custom_buttons(workspace)
        write_ok({"removed": removed})
        return 0
    if args.action == "add":
        if not args.name or not args.command:
            write_error(code="VALIDATION_ERROR", error="--name and --command are required for add")
            return 1
        added = add_custom_button(workspace, name=args.name, command=args.command)
        if not added:
            write_error(code="CONFLICT", error=f"button already exists: {args.name}")
            return 1
        write_ok({"added": True, "name": args.name.strip(), "command": args.command.strip()})
        return 0
    if args.action == "remove":
        if not args.name:
            write_error(code="VALIDATION_ERROR", error="--name is required for remove")
            return 1
        removed = remove_custom_button(workspace, name=args.name)
        if not removed:
            write_error(code="NOT_FOUND", error=f"button not found: {args.name}")
            return 1
        write_ok({"removed": True, "name": args.name.strip()})
        return 0
    write_error(code="VALIDATION_ERROR", error=f"unknown action: {args.action}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
