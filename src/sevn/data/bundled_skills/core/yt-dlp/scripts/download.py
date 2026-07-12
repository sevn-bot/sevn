#!/usr/bin/env python3
"""Bundled ``yt-dlp`` skill — allowlisted media download.

Module: sevn.data.bundled_skills.core.yt-dlp.scripts.download
Depends: argparse, sevn.lcm.script_cli, sevn.media.yt_dlp_skill

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok
from sevn.media.yt_dlp_skill import (
    build_download_argv,
    dry_run_requested,
    run_yt_dlp,
    validate_media_url,
)
from sevn.pdf import resolve_path_under_workspace


def main(argv: list[str] | None = None) -> int:
    """Download video or audio into a workspace directory via yt-dlp.

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
        "--out",
        default="downloads",
        help="Workspace-relative output directory (default: downloads under out/<session>/).",
    )
    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Extract audio instead of downloading video.",
    )
    parser.add_argument(
        "--audio-format",
        default="mp3",
        help="Audio codec when --audio-only is set (mp3, m4a, aac, wav, flac, opus).",
    )
    parser.add_argument(
        "--write-subs",
        action="store_true",
        help="Download subtitles when available.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print argv plan only (also via SEVN_YT_DLP_DRY_RUN=1).",
    )
    args = parser.parse_args(argv)

    workspace = workspace_from_env()
    try:
        url = validate_media_url(args.url)
        out_dir = resolve_path_under_workspace(workspace, args.out, artifact=True)
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1

    try:
        argv_plan = build_download_argv(
            url,
            out_dir,
            audio_only=args.audio_only,
            audio_format=args.audio_format,
            write_subs=args.write_subs,
        )
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1

    if dry_run_requested(cli_flag=args.dry_run):
        write_ok(
            {
                "mode": "dry_run",
                "argv": argv_plan,
                "url": url,
                "out_dir": str(out_dir.relative_to(workspace)),
            },
        )
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    ok, detail, returncode, _ = run_yt_dlp(argv_plan, cwd=workspace)
    if not ok:
        code = "DEPENDENCY_MISSING" if returncode == 127 else "DOWNLOAD_FAILED"
        write_error(code=code, error=f"yt-dlp: {detail}")
        return 1

    write_ok(
        {
            "mode": "live",
            "argv": argv_plan,
            "url": url,
            "out_dir": str(out_dir.relative_to(workspace)),
            "returncode": returncode,
            "stdout": detail,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
