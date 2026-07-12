#!/usr/bin/env python3
"""Bundled ``scheduling`` skill — add cron job.

Module: sevn.data.bundled_skills.core.scheduling.scripts.cron_add
Depends: argparse, sevn.lcm.script_cli, sevn.triggers.cron

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import json

from sevn.lcm.script_cli import open_workspace_db, workspace_from_env, write_error, write_ok
from sevn.triggers.cron import add_cron_job, cron_job_to_dict


def _resolve_default_result_channel_json(raw: str) -> str:
    """Fill an unset result channel with the operator's Telegram DM.

    A cron job created without an explicit ``--result-channel-json`` otherwise defaults to an
    empty ``{}`` object, which deserialises to the ``LOG`` sink: the scheduled run executes but
    its answer only lands in the gateway log (no ``channel`` sink), so the operator never sees it.
    When Telegram is configured, default delivery to the first ``channels.telegram.allowed_users``
    entry (the operator DM) via a ``TELEGRAM_TOPIC`` channel so daily jobs actually reach the user.

    Args:
        raw (str): The ``--result-channel-json`` value as passed on the CLI.

    Returns:
        str: The original value when a channel was supplied, else a resolved Telegram default,
            falling back to the original ``raw`` when no operator chat can be determined.

    Examples:
        >>> _resolve_default_result_channel_json('{"kind":"LOG"}')
        '{"kind":"LOG"}'
    """
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return raw
    if isinstance(parsed, dict) and parsed.get("kind"):
        return raw
    try:
        from sevn.config.loader import load_workspace

        ws = load_workspace(start_dir=workspace_from_env())[0]
        telegram = ws.channels.telegram if ws.channels else None
        allowed = list(telegram.allowed_users) if telegram and telegram.allowed_users else []
    except Exception:
        return raw
    if not allowed:
        return raw
    return json.dumps({"kind": "TELEGRAM_TOPIC", "telegram_topic_id": int(allowed[0])})


def main() -> int:
    """Run cron add CLI.

    Returns:
        int: ``0`` on success; ``1`` on validation failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--cron-expr", required=True)
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--payload-template", default=None)
    parser.add_argument("--delivery-mode", default="agent_pass")
    parser.add_argument("--routing-mode", default="fixed")
    parser.add_argument("--permission-template-ref", default="default")
    parser.add_argument("--overlap-policy", default="skip")
    parser.add_argument("--result-channel-json", default="{}")
    parser.add_argument("--allow-tier-cd", action="store_true")
    parser.add_argument("--disabled", action="store_true")
    args = parser.parse_args()
    result_channel_json = _resolve_default_result_channel_json(args.result_channel_json)
    conn = open_workspace_db()
    try:
        job = add_cron_job(
            conn,
            job_id=args.job_id,
            cron_expr=args.cron_expr,
            timezone=args.timezone,
            enabled=not args.disabled,
            routing_mode=args.routing_mode,  # type: ignore[arg-type]
            delivery_mode=args.delivery_mode,  # type: ignore[arg-type]
            permission_template_ref=args.permission_template_ref,
            allow_tier_cd=args.allow_tier_cd,
            overlap_policy=args.overlap_policy,
            result_channel_json=result_channel_json,
            payload_template=args.payload_template,
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
