#!/usr/bin/env python3
"""Filter last30days raw markdown by item date.

Single-shot helper for agents — avoids run_code/bash loops over workspace files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok

_ITEM_HEADER = re.compile(r"^\d+\.\s+\[(?P<source>[^\]]+)\]\s+(?P<title>.+)$")
_DATE_LINE = re.compile(r"^\s*-\s*(\d{4}-\d{2}-\d{2})\s*\|")
_URL_LINE = re.compile(r"^\s*-\s*URL:\s*(https?://\S+)")


def _resolve_raw_path(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    workspace = workspace_from_env()
    under_workspace = (workspace / raw_path).resolve()
    if under_workspace.is_file():
        return under_workspace
    msg = f"raw markdown not found: {raw_path}"
    raise FileNotFoundError(msg)


def parse_raw_items(text: str) -> list[dict[str, object]]:
    """Extract dated evidence rows from last30days ``--emit md`` output."""
    items: list[dict[str, object]] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        header = _ITEM_HEADER.match(lines[index].strip())
        if not header:
            index += 1
            continue
        title = header.group("title").strip()
        source = header.group("source").strip()
        date_str: str | None = None
        url: str | None = None
        signal: str | None = None
        cursor = index + 1
        while cursor < len(lines) and lines[cursor].startswith("   "):
            date_match = _DATE_LINE.match(lines[cursor])
            if date_match:
                date_str = date_match.group(1)
                signal = lines[cursor].strip().lstrip("- ").strip()
            url_match = _URL_LINE.match(lines[cursor])
            if url_match:
                url = url_match.group(1)
            cursor += 1
        if date_str:
            items.append(
                {
                    "title": title,
                    "source": source,
                    "date": date_str,
                    "url": url or "",
                    "signal": signal or "",
                },
            )
        index = cursor
    return items


def _cutoff_date(*, since_hours: int | None, since_date: str | None) -> datetime:
    if since_date:
        return datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=UTC)
    hours = since_hours if since_hours is not None else 24
    return datetime.now(UTC) - timedelta(hours=hours)


def filter_items(
    items: list[dict[str, object]],
    *,
    since_hours: int | None,
    since_date: str | None,
) -> list[dict[str, object]]:
    cutoff = _cutoff_date(since_hours=since_hours, since_date=since_date)
    filtered: list[dict[str, object]] = []
    for item in items:
        date_raw = str(item.get("date", ""))
        try:
            item_dt = datetime.strptime(date_raw, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            continue
        if item_dt >= cutoff.replace(hour=0, minute=0, second=0, microsecond=0):
            filtered.append(item)
    filtered.sort(key=lambda row: str(row.get("date", "")), reverse=True)
    return filtered


def main() -> int:
    parser = argparse.ArgumentParser(description="Filter last30days raw markdown by date")
    parser.add_argument("--path", required=True, help="Workspace-relative or absolute raw .md path")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--since-hours", type=int, default=24, help="Keep items within N hours (default 24)"
    )
    group.add_argument("--since-date", help="Keep items on/after YYYY-MM-DD")
    args = parser.parse_args()

    try:
        raw_path = _resolve_raw_path(args.path)
        text = raw_path.read_text(encoding="utf-8")
    except OSError as exc:
        write_error(code="IO_ERROR", error=str(exc))
        return 1

    items = parse_raw_items(text)
    if not items:
        write_error(
            code="NO_ITEMS",
            error=f"No dated evidence rows found in {raw_path.name}",
        )
        return 1

    since_hours = None if args.since_date else args.since_hours
    matched = filter_items(items, since_hours=since_hours, since_date=args.since_date)
    write_ok(
        {
            "path": str(raw_path),
            "total_items": len(items),
            "matched_items": len(matched),
            "since_hours": since_hours,
            "since_date": args.since_date,
            "items": matched,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
