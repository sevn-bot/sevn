#!/usr/bin/env python3
"""Call an allowlisted TwexAPI op with optional JSON payloads."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import dry_run_requested, run_social_media_task  # noqa: E402


def _parse_json_flag(raw: str | None, *, label: str) -> dict[str, Any]:
    """Parse an optional JSON object flag.

    Args:
        raw (str | None): JSON text.
        label (str): Flag name for errors.

    Returns:
        dict[str, Any]: Parsed object or empty dict.

    Raises:
        SystemExit: When JSON is invalid or not an object.
    """
    if raw is None or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"invalid --{label} JSON: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if not isinstance(value, dict):
        print(f"--{label} must be a JSON object", file=sys.stderr)
        raise SystemExit(2)
    return {str(k): v for k, v in value.items()}


def main(argv: list[str] | None = None) -> int:
    """CLI entry.

    Args:
        argv (list[str] | None): Optional argv override.

    Returns:
        int: Process exit code.
    """
    parser = argparse.ArgumentParser(description="TwexAPI allowlisted op call")
    parser.add_argument("op", help="Allowlisted op id (search, users, timeline_page, …)")
    parser.add_argument("--body", default=None, help="JSON object body")
    parser.add_argument("--params", default=None, help="JSON object query params")
    parser.add_argument("--path-params", default=None, help="JSON object path params")
    parser.add_argument("--dry-run", "-n", action="store_true")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    task = {
        "medium": "twexapi",
        "op": args.op,
        "body": _parse_json_flag(args.body, label="body"),
        "params": _parse_json_flag(args.params, label="params"),
        "path_params": {
            str(k): str(v)
            for k, v in _parse_json_flag(args.path_params, label="path-params").items()
        },
    }
    return run_social_media_task(task, dry_run=args.dry_run or dry_run_requested([]))


if __name__ == "__main__":
    raise SystemExit(main())
