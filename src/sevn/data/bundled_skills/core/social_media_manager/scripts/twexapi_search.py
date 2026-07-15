#!/usr/bin/env python3
"""Advanced X/Twitter search via TwexAPI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import dry_run_requested, run_social_media_task  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """CLI entry.

    Args:
        argv (list[str] | None): Optional argv override.

    Returns:
        int: Process exit code.
    """
    parser = argparse.ArgumentParser(description="TwexAPI advanced search")
    parser.add_argument("query", help="Search query / term")
    parser.add_argument("--max-items", type=int, default=20)
    parser.add_argument("--dry-run", "-n", action="store_true")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    task = {
        "medium": "twexapi",
        "op": "search",
        "body": {"searchTerms": [args.query], "maxItems": args.max_items, "sortBy": "Latest"},
    }
    return run_social_media_task(task, dry_run=args.dry_run or dry_run_requested([]))


if __name__ == "__main__":
    raise SystemExit(main())
