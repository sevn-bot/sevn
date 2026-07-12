#!/usr/bin/env python3
"""Bundled ``scheduling`` skill — edit cron job.

Module: sevn.data.bundled_skills.core.scheduling.scripts.cron_edit
Depends: argparse, sevn.lcm.script_cli, sevn.triggers.cron

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import open_workspace_db, write_error, write_ok
from sevn.triggers.cron import cron_job_to_dict, edit_cron_job


def main() -> int:
    """Run cron edit CLI.

    Returns:
        int: ``0`` on success; ``1`` on validation failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--cron-expr", default=None)
    parser.add_argument("--timezone", default=None)
    parser.add_argument("--payload-template", default=None)
    parser.add_argument("--delivery-mode", default=None)
    parser.add_argument("--routing-mode", default=None)
    parser.add_argument("--permission-template-ref", default=None)
    parser.add_argument("--overlap-policy", default=None)
    parser.add_argument("--result-channel-json", default=None)
    parser.add_argument("--allow-tier-cd", action="store_true")
    parser.add_argument("--no-allow-tier-cd", action="store_true")
    parser.add_argument("--enabled", action="store_true")
    parser.add_argument("--disabled", action="store_true")
    parser.add_argument("--recompute-schedule", action="store_true")
    args = parser.parse_args()
    enabled: bool | None = None
    if args.enabled:
        enabled = True
    elif args.disabled:
        enabled = False
    allow_tier_cd: bool | None = None
    if args.allow_tier_cd:
        allow_tier_cd = True
    elif args.no_allow_tier_cd:
        allow_tier_cd = False
    conn = open_workspace_db()
    try:
        job = edit_cron_job(
            conn,
            job_id=args.job_id,
            cron_expr=args.cron_expr,
            timezone=args.timezone,
            payload_template=args.payload_template,
            routing_mode=args.routing_mode,  # type: ignore[arg-type]
            delivery_mode=args.delivery_mode,  # type: ignore[arg-type]
            permission_template_ref=args.permission_template_ref,
            allow_tier_cd=allow_tier_cd,
            overlap_policy=args.overlap_policy,
            result_channel_json=args.result_channel_json,
            enabled=enabled,
            recompute_schedule=args.recompute_schedule,
        )
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1
    finally:
        conn.close()
    write_ok({"job": cron_job_to_dict(job)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
