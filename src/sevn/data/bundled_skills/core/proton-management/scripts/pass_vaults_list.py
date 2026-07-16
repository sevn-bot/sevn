#!/usr/bin/env python3
"""Bundled ``proton-management`` skill — list Pass vaults."""

from __future__ import annotations

import argparse
import json

from sevn.lcm.script_cli import write_error, write_ok
from sevn.skills.proton_management import dry_run_requested, run_proton_cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="")
    parser.add_argument("--output", default="json", choices=["json", "text"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    cmd = ["pass", "vaults", "list", "--output", args.output]
    if dry_run_requested(cli_flag=args.dry_run):
        write_ok({"mode": "dry_run", "command": cmd, "profile": args.profile or "default"})
        return 0

    code, out, err = run_proton_cli(cmd, profile=args.profile)
    if code != 0:
        write_error(code="PROTON_CLI_FAILED", error=err.strip() or out.strip())
        return code

    if args.output == "json":
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            data = {"raw": out}
        write_ok({"vaults": data, "count": len(data) if isinstance(data, list) else None})
    else:
        write_ok({"text": out})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
