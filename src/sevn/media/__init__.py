"""Media download helpers for bundled skill scripts.

Module: sevn.media
Depends: sevn.media.yt_dlp_skill

Exports:
    EGRESS_DOWNLOAD_DOMAINS — host suffix allowlist for yt-dlp URLs.
    validate_media_url — reject URLs whose host is outside the allowlist.
    yt_dlp_available — whether ``yt-dlp`` is on PATH.
    build_metadata_argv — allowlisted argv for metadata-only extraction.
    build_download_argv — allowlisted argv for workspace downloads.
    run_yt_dlp — subprocess wrapper with capped stdout.
"""

from __future__ import annotations

from sevn.media.yt_dlp_skill import (
    EGRESS_DOWNLOAD_DOMAINS,
    build_download_argv,
    build_metadata_argv,
    resolve_path_under_workspace,
    run_yt_dlp,
    validate_media_url,
    yt_dlp_available,
)

__all__ = [
    "EGRESS_DOWNLOAD_DOMAINS",
    "build_download_argv",
    "build_metadata_argv",
    "resolve_path_under_workspace",
    "run_yt_dlp",
    "validate_media_url",
    "yt_dlp_available",
]
