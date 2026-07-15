#!/usr/bin/env python3
"""Report TwexAPI readiness and CDP browser reachability for social_media_manager."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import content_root_from_env, dry_run_requested  # noqa: E402

from sevn.integrations.twexapi.config import (  # noqa: E402
    TWEXAPI_ENV_KEYS,
    TWEXAPI_SECRET_ALIAS,
    load_twexapi_settings,
)
from sevn.lcm.script_cli import write_error, write_ok  # noqa: E402
from sevn.skills.browser_session import cdp_reachable, default_cdp_url  # noqa: E402


async def _status() -> dict[str, object]:
    """Build session status payload.

    Returns:
        dict[str, object]: TwexAPI + CDP readiness fields.
    """
    root = content_root_from_env()
    settings, _cfg = load_twexapi_settings(root)
    env_present = any(os.environ.get(name, "").strip() for name in TWEXAPI_ENV_KEYS)
    cdp_url = default_cdp_url()
    return {
        "specialist": "social_media_manager",
        "twexapi": {
            "docs": settings.docs_url,
            "base_url": settings.base_url,
            "enabled": settings.enabled,
            "api_key_ref_configured": bool(settings.api_key_ref),
            "env_key_present": env_present,
            "secret_alias": TWEXAPI_SECRET_ALIAS,
        },
        "browser": {
            "engine": "cdp",
            "cdp_url": cdp_url,
            "cdp_reachable": await asyncio.to_thread(cdp_reachable, cdp_url) if cdp_url else False,
            "tool": "browser",
        },
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry.

    Args:
        argv (list[str] | None): Optional argv override.

    Returns:
        int: Process exit code.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if dry_run_requested(args):
        write_ok({"dry_run": True, "script": "session_status"})
        return 0
    try:
        payload = asyncio.run(_status())
    except (OSError, RuntimeError, ValueError) as exc:
        write_error(str(exc))
        return 1
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
