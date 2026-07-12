#!/usr/bin/env python3
"""Bundled ``scheduling`` skill — one-shot reminder.

Module: sevn.data.bundled_skills.core.scheduling.scripts.reminder
Depends: argparse, sevn.lcm.script_cli, sevn.triggers.cron

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import open_workspace_db, write_error, write_ok
from sevn.triggers.cron import add_reminder, cron_job_to_dict


def main() -> int:
    """Run reminder CLI.

    Returns:
        int: ``0`` on success; ``1`` on validation failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--at", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--job-id", default=None)
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--delivery-mode", default="agent_pass")
    parser.add_argument("--permission-template-ref", default="default")
    parser.add_argument("--result-channel-json", default="{}")
    args = parser.parse_args()
    conn = open_workspace_db()
    try:
        job = add_reminder(
            conn,
            at=args.at,
            prompt=args.prompt,
            job_id=args.job_id,
            timezone=args.timezone,
            delivery_mode=args.delivery_mode,  # type: ignore[arg-type]
            permission_template_ref=args.permission_template_ref,
            result_channel_json=args.result_channel_json,
        )
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1
    finally:
        conn.close()
    write_ok({"job": cron_job_to_dict(job), "reminder": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
