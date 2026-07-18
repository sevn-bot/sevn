#!/usr/bin/env python3
"""Bundled ``proton-management`` skill — CLI install and session status."""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import write_ok
from sevn.skills.proton_management import PROTON_MANAGEMENT_SKILL_ID, status_payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="default")
    args = parser.parse_args(argv)
    write_ok({"skill": PROTON_MANAGEMENT_SKILL_ID, **status_payload(profile=args.profile)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
