#!/usr/bin/env python3
"""Bundled ``yt-dlp`` skill — metadata-only JSON extraction.

Module: sevn.data.bundled_skills.core.yt-dlp.scripts.metadata
Depends: argparse, sevn.lcm.script_cli, sevn.media.yt_dlp_skill

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok
from sevn.media.yt_dlp_skill import (
    build_metadata_argv,
    dry_run_requested,
    run_yt_dlp,
    validate_media_url,
)


def main(argv: list[str] | None = None) -> int:
    """Export compact JSON metadata for an allowlisted media URL.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` on validation or execution failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Allowlisted media page URL.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print argv plan only (also via SEVN_YT_DLP_DRY_RUN=1).",
    )
    args = parser.parse_args(argv)

    workspace = workspace_from_env()
    try:
        url = validate_media_url(args.url)
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1

    argv_plan = build_metadata_argv(url)
    if dry_run_requested(cli_flag=args.dry_run):
        write_ok({"mode": "dry_run", "argv": argv_plan, "url": url})
        return 0

    ok, detail, returncode, parsed = run_yt_dlp(argv_plan, cwd=workspace)
    if not ok:
        code = "DEPENDENCY_MISSING" if returncode == 127 else "METADATA_FAILED"
        write_error(code=code, error=f"yt-dlp: {detail}")
        return 1

    metadata = parsed if isinstance(parsed, dict) else {"raw_stdout": detail}
    compact = {
        "id": metadata.get("id"),
        "title": metadata.get("title"),
        "uploader": metadata.get("uploader"),
        "duration": metadata.get("duration"),
        "view_count": metadata.get("view_count"),
        "upload_date": metadata.get("upload_date"),
        "webpage_url": metadata.get("webpage_url"),
        "description": (metadata.get("description") or "")[:2000],
    }
    write_ok(
        {
            "mode": "live",
            "argv": argv_plan,
            "url": url,
            "returncode": returncode,
            "metadata": compact,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
