#!/usr/bin/env python3
"""Bundled ``proton-management`` skill — list calendar events."""

from __future__ import annotations

import argparse
import json

from sevn.lcm.script_cli import write_error, write_ok
from sevn.skills.proton_management import dry_run_requested, run_proton_cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="")
    parser.add_argument("--calendar", default="")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    cmd = ["calendar", "events", "list", "--output", "json"]
    if args.calendar:
        cmd.extend(["--calendar", args.calendar])
    if args.start:
        cmd.extend(["--start", args.start])
    if args.end:
        cmd.extend(["--end", args.end])
    if dry_run_requested(cli_flag=args.dry_run):
        write_ok({"mode": "dry_run", "command": cmd})
        return 0

    code, out, err = run_proton_cli(cmd, profile=args.profile)
    if code != 0:
        write_error(code="PROTON_CLI_FAILED", error=err.strip() or out.strip())
        return code
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        data = {"raw": out}
    write_ok({"calendar": data})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
