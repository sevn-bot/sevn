#!/usr/bin/env python3
"""Bundled ``google-workspace`` skill — Hermes-style Google API CLI.

Module: sevn.data.bundled_skills.core.google-workspace.scripts.google_api
Depends: argparse, os, sevn.lcm.script_cli, sevn.skills.google_workspace_api

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import os

from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok
from sevn.skills.google_workspace_api import (
    calendar_create,
    calendar_delete,
    calendar_list,
    contacts_list,
    drive_get,
    drive_search,
    gmail_get,
    gmail_labels,
    gmail_modify,
    gmail_reply,
    gmail_search,
    gmail_send,
)

_DRY_RUN_ENV = "SEVN_GOOGLE_DRY_RUN"


def _csv_list(value: str | None) -> list[str] | None:
    """Split a comma-delimited string into a list."""

    if value is None:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def _error_code(exc: Exception) -> str:
    """Map common runtime exceptions to stable script codes."""

    if isinstance(exc, FileNotFoundError):
        return "NOT_AUTHENTICATED"
    if isinstance(exc, ImportError):
        return "DEPENDENCIES_MISSING"
    if isinstance(exc, ValueError):
        return "VALIDATION_ERROR"
    return "GOOGLE_WORKSPACE_API_FAILED"


def _enable_dry_run() -> None:
    """Enable env-based dry-run mode for shared helpers."""

    os.environ[_DRY_RUN_ENV] = "1"


def _build_parser() -> argparse.ArgumentParser:
    """Build the Hermes-style Google Workspace parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="service", required=True)

    gmail = sub.add_parser("gmail")
    gmail_sub = gmail.add_subparsers(dest="action", required=True)
    p = gmail_sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--max", type=int, default=10)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(handler=lambda ws, a: gmail_search(ws, a.query, max_results=a.max))
    p = gmail_sub.add_parser("get")
    p.add_argument("message_id")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(handler=lambda ws, a: gmail_get(ws, a.message_id))
    p = gmail_sub.add_parser("send")
    p.add_argument("--to", required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--body", required=True)
    p.add_argument("--html", action="store_true")
    p.add_argument("--from", dest="from_header")
    p.add_argument("--cc")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(
        handler=lambda ws, a: gmail_send(
            ws,
            a.to,
            a.subject,
            a.body,
            html=a.html,
            from_header=a.from_header,
            cc=a.cc,
        ),
    )
    p = gmail_sub.add_parser("reply")
    p.add_argument("message_id")
    p.add_argument("--body", required=True)
    p.add_argument("--from", dest="from_header")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(handler=lambda ws, a: gmail_reply(ws, a.message_id, a.body, from_header=a.from_header))
    p = gmail_sub.add_parser("labels")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(handler=lambda ws, a: gmail_labels(ws))
    p = gmail_sub.add_parser("modify")
    p.add_argument("message_id")
    p.add_argument("--add-labels")
    p.add_argument("--remove-labels")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(
        handler=lambda ws, a: gmail_modify(
            ws,
            a.message_id,
            add_labels=_csv_list(a.add_labels),
            remove_labels=_csv_list(a.remove_labels),
        ),
    )

    calendar = sub.add_parser("calendar")
    calendar_sub = calendar.add_subparsers(dest="action", required=True)
    p = calendar_sub.add_parser("list")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(handler=lambda ws, a: calendar_list(ws, start=a.start, end=a.end))
    p = calendar_sub.add_parser("create")
    p.add_argument("--summary", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--location")
    p.add_argument("--attendees")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(
        handler=lambda ws, a: calendar_create(
            ws,
            a.summary,
            a.start,
            a.end,
            location=a.location,
            attendees=_csv_list(a.attendees),
        ),
    )
    p = calendar_sub.add_parser("delete")
    p.add_argument("event_id")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(handler=lambda ws, a: calendar_delete(ws, a.event_id))

    drive = sub.add_parser("drive")
    drive_sub = drive.add_subparsers(dest="action", required=True)
    p = drive_sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--max", type=int, default=10)
    p.add_argument("--raw-query", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(
        handler=lambda ws, a: drive_search(ws, a.query, max_results=a.max, raw_query=a.raw_query),
    )
    p = drive_sub.add_parser("get")
    p.add_argument("file_id")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(handler=lambda ws, a: drive_get(ws, a.file_id))

    contacts = sub.add_parser("contacts")
    contacts_sub = contacts.add_subparsers(dest="action", required=True)
    p = contacts_sub.add_parser("list")
    p.add_argument("--max", type=int, default=20)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(handler=lambda ws, a: contacts_list(ws, max_results=a.max))

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the Hermes-style Google Workspace CLI."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "dry_run", False):
        _enable_dry_run()
    workspace = str(workspace_from_env())
    handler = getattr(args, "handler", None)
    if handler is None:
        write_error(code="VALIDATION_ERROR", error="no command handler configured")
        return 1
    try:
        write_ok(handler(workspace, args))
        return 0
    except Exception as exc:
        write_error(code=_error_code(exc), error=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
