#!/usr/bin/env python3
"""Report TwexAPI readiness and CDP browser reachability for social_media_manager."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import content_root_from_env, dry_run_requested  # noqa: E402

from sevn.integrations.social_media.readiness import build_social_media_readiness  # noqa: E402
from sevn.lcm.script_cli import write_error, write_ok  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """CLI entry.

    Args:
        argv (list[str] | None): Optional argv override.

    Returns:
        int: Process exit code.
    """
    args_list = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--site",
        help="Optional platform site key for a cheap login-state probe (x, facebook, …).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan-only output.")
    ns = parser.parse_args(args_list)

    if dry_run_requested(args_list) or ns.dry_run:
        write_ok({"dry_run": True, "script": "session_status"})
        return 0
    site = (ns.site or "").strip() or None
    try:
        payload = asyncio.run(
            build_social_media_readiness(content_root_from_env(), site=site),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        write_error(str(exc))
        return 1
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
