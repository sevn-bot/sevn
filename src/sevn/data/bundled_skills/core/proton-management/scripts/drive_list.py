#!/usr/bin/env python3
"""Bundled ``proton-management`` skill — list Drive folder contents."""

from __future__ import annotations

import argparse
import json

from sevn.lcm.script_cli import write_error, write_ok
from sevn.skills.proton_management import dry_run_requested, run_proton_cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="")
    parser.add_argument("--path", default="/")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    cmd = ["drive", "items", "list", args.path, "--output", "json"]
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
    write_ok({"drive": data})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
