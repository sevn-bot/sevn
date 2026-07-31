"""Redact browser credential paths from logs and tool outputs.

Module: sevn.browser.redaction
Depends: json, pathlib, re

Exports:
    redact_browser_credential_paths — scrub profile/cookie paths from plain text.
    redact_browser_tool_payload — scrub paths from browser tool JSON envelopes.
    assert_no_plaintext_browser_credentials — scan workspace for leaked secrets.

Examples:
    >>> redact_browser_credential_paths("cookies from /tmp/.sevn/browser-profiles/x/Default/Cookies")
    '<redacted-browser-path>'
"""

from __future__ import annotations

import json
import re
from pathlib import Path  # noqa: TC003 — runtime use in assert_no_plaintext_browser_credentials
from typing import Any

_REDACTED: str = "<redacted-browser-path>"
_USER_DATA_DIR_RE: re.Pattern[str] = re.compile(
    r"(--user-data-dir=)([^\s\"']+)",
)
_BROWSER_PROFILES_RE: re.Pattern[str] = re.compile(
    r"[^\s\"']*[/\\]\.sevn[/\\]browser-profiles[/\\][^\s\"']*",
)
_BROWSER_EPHEMERAL_RE: re.Pattern[str] = re.compile(
    r"[^\s\"']*[/\\]\.sevn[/\\]browser-ephemeral[/\\][^\s\"']*",
)
_CREDENTIAL_FILE_RE: re.Pattern[str] = re.compile(
    r"[^\s\"']*[/\\]Default[/\\](Cookies|Login Data|Web Data)[^\s\"']*",
    re.IGNORECASE,
)
_PLAINTEXT_SCAN_SUFFIXES: frozenset[str] = frozenset({".json", ".txt", ".md", ".env"})


def redact_browser_credential_paths(text: str) -> str:
    """Scrub browser profile and credential-store paths from ``text``.

    Args:
        text (str): Raw log line or message.

    Returns:
        str: Text with sensitive filesystem paths replaced.

    Examples:
        >>> redact_browser_credential_paths("--user-data-dir=/home/x/.sevn/browser-profiles/s")
        '--user-data-dir=<redacted-browser-path>'
    """
    if not text:
        return text
    out = _USER_DATA_DIR_RE.sub(rf"\1{_REDACTED}", text)
    out = _BROWSER_PROFILES_RE.sub(_REDACTED, out)
    out = _BROWSER_EPHEMERAL_RE.sub(_REDACTED, out)
    return _CREDENTIAL_FILE_RE.sub(_REDACTED, out)


def redact_browser_tool_payload(
    envelope: str | dict[str, Any],
    *,
    profile_dir: Path | None = None,
) -> dict[str, Any]:
    """Scrub browser credential paths from a tool JSON envelope.

    Args:
        envelope (str | dict[str, Any]): Tool result envelope (JSON string or dict).
        profile_dir (Path | None): Optional resolved profile dir to scrub explicitly.

    Returns:
        dict[str, Any]: Parsed envelope with redacted path strings.

    Examples:
        >>> redact_browser_tool_payload({"ok": True, "data": {"path": "/x/Default/Cookies"}})
        {'ok': True, 'data': {'path': '<redacted-browser-path>'}}
    """
    if isinstance(envelope, str):
        data: dict[str, Any] = json.loads(envelope)
    else:
        data = envelope
    blob = json.dumps(data)
    if profile_dir is not None:
        profile_text = str(profile_dir)
        blob = blob.replace(profile_text, _REDACTED)
        default_dir = str(profile_dir / "Default")
        blob = blob.replace(default_dir, _REDACTED)
    blob = redact_browser_credential_paths(blob)
    parsed = json.loads(blob)
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def assert_no_plaintext_browser_credentials(root: Path, *, sample_secret: str) -> None:
    """Assert ``sample_secret`` does not appear in plaintext workspace files.

    Scans ``root`` recursively for ``.json``, ``.txt``, ``.md``, and ``.env``
    files — a guard that login credentials never land on disk in plaintext.

    Args:
        root (Path): Workspace content root to scan.
        sample_secret (str): Secret substring that must not appear.

    Returns:
        None

    Raises:
        AssertionError: When ``sample_secret`` appears in a scanned file.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> assert_no_plaintext_browser_credentials(Path(tempfile.mkdtemp()), sample_secret="hunter2")
    """
    needle = (sample_secret or "").strip()
    if not needle:
        return
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in _PLAINTEXT_SCAN_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if needle in text:
            msg = f"plaintext browser credential material found in {path}"
            raise AssertionError(msg)


__all__ = [
    "assert_no_plaintext_browser_credentials",
    "redact_browser_credential_paths",
    "redact_browser_tool_payload",
]
