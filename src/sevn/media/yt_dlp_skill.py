"""Allowlisted yt-dlp subprocess helpers for the bundled ``yt-dlp`` skill.

Module: sevn.media.yt_dlp_skill
Depends: pathlib, shutil, subprocess, urllib.parse

Exports:
    host_allowed — suffix match against download egress allowlist.
    validate_media_url — parse URL and enforce host allowlist.
    resolve_path_under_workspace — workspace-relative path guard.
    yt_dlp_available — whether ``yt-dlp`` is on PATH.
    dry_run_requested — CLI/env dry-run selector.
    yt_dlp_missing_message — install hint when CLI absent.
    build_metadata_argv — allowlisted argv for ``--dump-json`` metadata.
    build_download_argv — allowlisted argv for workspace downloads.
    run_yt_dlp — subprocess wrapper with capped stdout.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

EGRESS_DOWNLOAD_DOMAINS: Final[tuple[str, ...]] = (
    "youtube.com",
    "youtu.be",
    "googlevideo.com",
    "ytimg.com",
    "youtubei.googleapis.com",
    "vimeo.com",
    "player.vimeo.com",
    "twitter.com",
    "x.com",
    "twimg.com",
    "video.twimg.com",
    "tiktok.com",
    "tiktokcdn.com",
    "tiktokv.com",
    "twitch.tv",
    "ttvnw.net",
    "jtvnw.net",
    "instagram.com",
    "cdninstagram.com",
    "facebook.com",
    "fbcdn.net",
    "soundcloud.com",
    "redd.it",
    "reddit.com",
    "v.redd.it",
    "dailymotion.com",
    "archive.org",
    "streamable.com",
    "rumble.com",
)

_ALLOWED_AUDIO_FORMATS: Final[frozenset[str]] = frozenset(
    {"mp3", "m4a", "aac", "wav", "flac", "opus"},
)

_YT_DLP_TIMEOUT_SECONDS = 3600.0
_DRY_RUN_ENV = "SEVN_YT_DLP_DRY_RUN"
_STDOUT_CAP = 8192


def host_allowed(host: str, *, allowlist: tuple[str, ...] = EGRESS_DOWNLOAD_DOMAINS) -> bool:
    """Return whether ``host`` matches an allowlisted download suffix.

    Args:
        host (str): Parsed URL hostname.
        allowlist (tuple[str, ...], optional): Host suffixes permitted for downloads.

    Returns:
        bool: ``True`` when the host equals or ends with ``.<suffix>`` for some suffix.

    Examples:
        >>> host_allowed("www.youtube.com")
        True
        >>> host_allowed("evil.example")
        False
    """
    normalized = host.lower().rstrip(".")
    if not normalized:
        return False
    for suffix in allowlist:
        candidate = suffix.lower()
        if normalized == candidate or normalized.endswith(f".{candidate}"):
            return True
    return False


def validate_media_url(raw_url: str) -> str:
    """Validate ``raw_url`` and return the stripped URL when the host is allowlisted.

    Args:
        raw_url (str): Media page URL supplied by the agent.

    Returns:
        str: Normalized URL string.

    Raises:
        ValueError: When the URL is malformed or the host is not allowlisted.

    Examples:
        >>> validate_media_url("https://www.youtube.com/watch?v=abc")
        'https://www.youtube.com/watch?v=abc'
    """
    url = raw_url.strip()
    if not url:
        msg = "yt-dlp: URL is required"
        raise ValueError(msg)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        msg = f"yt-dlp: URL must be http(s): {raw_url!r}"
        raise ValueError(msg)
    host = parsed.hostname or ""
    if not host_allowed(host):
        msg = f"yt-dlp: host {host!r} is not in the download egress allowlist"
        raise ValueError(msg)
    return url


def resolve_path_under_workspace(workspace: Path, raw: str) -> Path:
    """Resolve ``raw`` under ``workspace`` and reject escapes.

    Args:
        workspace (Path): Workspace content root.
        raw (str): Relative or absolute path under the workspace.

    Returns:
        Path: Resolved absolute path.

    Raises:
        ValueError: When the resolved path is outside ``workspace``.

    Examples:
        >>> import tempfile
        >>> ws = Path(tempfile.mkdtemp())
        >>> child = ws / "downloads"
        >>> resolve_path_under_workspace(ws, "downloads") == child.resolve()
        True
    """
    root = workspace.resolve()
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        msg = f"yt-dlp: path {raw!r} escapes workspace root"
        raise ValueError(msg)
    return resolved


def yt_dlp_available() -> bool:
    """Return whether the ``yt-dlp`` CLI is present on PATH.

    Returns:
        bool: ``True`` when ``shutil.which("yt-dlp")`` finds an executable.

    Examples:
        >>> isinstance(yt_dlp_available(), bool)
        True
    """
    return shutil.which("yt-dlp") is not None


def dry_run_requested(*, cli_flag: bool) -> bool:
    """Return True when dry-run mode is selected via CLI or environment.

    Args:
        cli_flag (bool): Whether ``--dry-run`` was passed on the CLI.

    Returns:
        bool: True when the script should print argv only (no subprocess).

    Examples:
        >>> dry_run_requested(cli_flag=True)
        True
    """
    if cli_flag:
        return True
    return os.environ.get(_DRY_RUN_ENV, "").strip().lower() in {"1", "true", "yes"}


def yt_dlp_missing_message() -> str:
    """Return the standard error when ``yt-dlp`` is missing from PATH.

    Returns:
        str: Install hint naming the optional extra.

    Examples:
        >>> "yt-dlp" in yt_dlp_missing_message()
        True
    """
    return (
        "yt-dlp: `yt-dlp` not found on PATH "
        "(install with `uv sync --extra yt-dlp` or `pip install yt-dlp`)"
    )


def build_metadata_argv(url: str) -> list[str]:
    """Build allowlisted argv for metadata-only extraction.

    Args:
        url (str): Validated media page URL.

    Returns:
        list[str]: Process argv starting with ``yt-dlp``.

    Examples:
        >>> build_metadata_argv("https://youtu.be/abc")[:3]
        ['yt-dlp', '--no-playlist', '--skip-download']
    """
    return [
        "yt-dlp",
        "--no-playlist",
        "--skip-download",
        "--dump-json",
        url,
    ]


def build_download_argv(
    url: str,
    out_dir: Path,
    *,
    audio_only: bool = False,
    audio_format: str | None = None,
    write_subs: bool = False,
) -> list[str]:
    """Build allowlisted argv for a workspace download.

    Args:
        url (str): Validated media page URL.
        out_dir (Path): Absolute workspace output directory.
        audio_only (bool, optional): Extract audio instead of video. Defaults to ``False``.
        audio_format (str | None, optional): Audio codec when ``audio_only`` is true.
        write_subs (bool, optional): Download subtitles when available. Defaults to ``False``.

    Returns:
        list[str]: Process argv starting with ``yt-dlp``.

    Raises:
        ValueError: When ``audio_format`` is outside the allowlist.

    Examples:
        >>> from pathlib import Path
        >>> argv = build_download_argv(
        ...     "https://www.youtube.com/watch?v=x",
        ...     Path("/tmp/out"),
        ...     audio_only=True,
        ...     audio_format="mp3",
        ... )
        >>> "-x" in argv and "--audio-format" in argv
        True
    """
    argv: list[str] = [
        "yt-dlp",
        "--no-playlist",
        "--restrict-filenames",
        "-o",
        str(out_dir / "%(title)s.%(ext)s"),
    ]
    if write_subs:
        argv.extend(["--write-subs", "--write-auto-subs"])
    if audio_only:
        argv.append("-x")
        fmt = (audio_format or "mp3").strip().lower()
        if fmt not in _ALLOWED_AUDIO_FORMATS:
            msg = f"yt-dlp: unsupported audio format {fmt!r}"
            raise ValueError(msg)
        argv.extend(["--audio-format", fmt])
    argv.append(url)
    return argv


def run_yt_dlp(argv: list[str], *, cwd: Path) -> tuple[bool, str, int, object | None]:
    """Execute ``yt-dlp`` with capped stdout/stderr.

    Args:
        argv (list[str]): Allowlisted process argv from :func:`build_metadata_argv` or
            :func:`build_download_argv`.
        cwd (Path): Working directory for the subprocess (workspace root).

    Returns:
        tuple[bool, str, int, object | None]: ``(ok, detail, returncode, parsed_json)`` where
            ``parsed_json`` is set for metadata runs that emit JSON on stdout.

    Examples:
        >>> run_yt_dlp.__name__
        'run_yt_dlp'
    """
    if not yt_dlp_available():
        return False, yt_dlp_missing_message(), 127, None
    completed = subprocess.run(  # nosec B603 — argv from allowlisted yt-dlp builder; no shell
        argv,
        cwd=str(cwd),
        capture_output=True,
        timeout=_YT_DLP_TIMEOUT_SECONDS,
        check=False,
    )
    code = completed.returncode or 0
    stdout = completed.stdout.decode("utf-8", errors="replace").strip()
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    if code != 0:
        detail = stderr or stdout or f"yt-dlp exited {code}"
        return False, detail, code, None
    parsed: object | None = None
    if "--dump-json" in argv and stdout:
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            parsed = None
    detail = stdout[:_STDOUT_CAP] if stdout else "ok"
    return True, detail, code, parsed
