"""OpenWiki CLI subprocess helpers for the bundled ``openwiki`` skill.

Module: sevn.code_understanding.openwiki_runner
Depends: json, os, pathlib, shutil, subprocess

Exports:
    content_root_from_env — operator content root (``SEVN_CONTENT_ROOT`` over shadow workspace).
    resolve_openwiki_root — prefer ``source_code/`` mirror under workspace.
    build_openwiki_argv — allowlisted ``openwiki`` argv for headless runs.
    openwiki_missing_message — install hint when CLI is absent.
    run_openwiki_subprocess — execute ``openwiki`` when present on PATH.
    openwiki_status — read wiki presence and last-update metadata.
    looks_like_credentials_error — heuristically detect auth failures in stderr.

Examples:
    >>> from pathlib import Path
    >>> from sevn.code_understanding.openwiki_runner import build_openwiki_argv
    >>> build_openwiki_argv(mode="init", message=None, model_id=None)
    ['openwiki', '--init', '-p']
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404 — fixed-argv openwiki CLI invocation, no shell
from pathlib import Path
from typing import Literal

OpenWikiMode = Literal["init", "update", "chat"]

OPENWIKI_DIR_NAME = "openwiki"
OPENWIKI_UPDATE_METADATA_REL = Path(OPENWIKI_DIR_NAME) / ".last-update.json"
DEFAULT_OPENWIKI_TIMEOUT_SECONDS = 3600.0
_SOURCE_CODE_REL = Path("source_code")

_CREDENTIAL_ERROR_MARKERS: tuple[str, ...] = (
    "api key",
    "api_key",
    "authentication",
    "unauthorized",
    "401",
    "403",
    "invalid api key",
    "missing credentials",
    "credential",
)


def content_root_from_env() -> Path:
    """Return operator content root, preferring ``SEVN_CONTENT_ROOT`` over shadow workspace.

    The skill runner sets ``SEVN_WORKSPACE`` to a temporary shadow tree and
    ``SEVN_CONTENT_ROOT`` to the durable operator workspace. OpenWiki output must
    land under the content root (typically ``source_code/openwiki/``).

    Returns:
        Path: Resolved content root, or ``SEVN_WORKSPACE``, or ``.`` when unset.

    Examples:
        >>> content_root_from_env().is_absolute()
        True
    """
    content_raw = os.environ.get("SEVN_CONTENT_ROOT", "").strip()
    if content_raw:
        return Path(content_raw).expanduser().resolve()
    workspace_raw = os.environ.get("SEVN_WORKSPACE", "").strip()
    if workspace_raw:
        return Path(workspace_raw).expanduser().resolve()
    return Path(".").resolve()


def resolve_openwiki_root(workspace: Path) -> Path:
    """Return the repository root OpenWiki should run against.

    Prefers ``<workspace>/source_code/`` when that mirror directory exists,
    otherwise returns the resolved workspace root.

    Args:
        workspace (Path): Operator workspace content root.

    Returns:
        Path: Absolute path to use as OpenWiki subprocess cwd.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path as _P
        >>> ws = _P(tempfile.mkdtemp())
        >>> resolve_openwiki_root(ws) == ws.resolve()
        True
    """
    root = workspace.resolve()
    mirror = root / _SOURCE_CODE_REL
    if mirror.is_dir():
        return mirror
    return root


def build_openwiki_argv(
    *,
    mode: OpenWikiMode,
    message: str | None,
    model_id: str | None,
    print_mode: bool = True,
) -> list[str]:
    """Build allowlisted argv for a non-interactive OpenWiki CLI invocation.

    Args:
        mode (OpenWikiMode): ``init``, ``update``, or ``chat``.
        message (str | None): Optional trailing user message.
        model_id (str | None): Optional ``--model-id`` override.
        print_mode (bool, optional): When true, append ``-p`` for one-shot output.

    Returns:
        list[str]: Process argv starting with ``openwiki``.

    Raises:
        ValueError: When ``mode`` is invalid or ``model_id`` is blank.

    Examples:
        >>> build_openwiki_argv(mode="update", message="refresh docs", model_id=None)
        ['openwiki', '--update', '-p', 'refresh docs']
        >>> build_openwiki_argv(mode="chat", message="hello", model_id="gpt-5.5")
        ['openwiki', '-p', '--model-id', 'gpt-5.5', 'hello']
    """
    if mode not in {"init", "update", "chat"}:
        msg = f"invalid openwiki mode: {mode!r}"
        raise ValueError(msg)
    argv: list[str] = ["openwiki"]
    if mode == "init":
        argv.append("--init")
    elif mode == "update":
        argv.append("--update")
    if print_mode:
        argv.append("-p")
    if model_id is not None:
        trimmed = model_id.strip()
        if not trimmed:
            msg = "model_id must be non-empty when provided"
            raise ValueError(msg)
        argv.extend(["--model-id", trimmed])
    if message is not None:
        trimmed = message.strip()
        if trimmed:
            argv.append(trimmed)
    return argv


def openwiki_missing_message() -> str:
    """Return the standard error when ``openwiki`` is missing from PATH.

    Returns:
        str: Install hint naming the npm global package.

    Examples:
        >>> "openwiki" in openwiki_missing_message()
        True
    """
    return (
        "openwiki: `openwiki` not found on PATH (run `sevn openwiki install`; requires Node >= 20)"
    )


def looks_like_credentials_error(detail: str) -> bool:
    """Heuristically detect missing or invalid LLM credentials in CLI output.

    Args:
        detail (str): Combined stderr/stdout text from a failed subprocess.

    Returns:
        bool: True when output suggests an auth/credential problem.

    Examples:
        >>> looks_like_credentials_error("Missing API key for provider")
        True
        >>> looks_like_credentials_error("file not found")
        False
    """
    lowered = detail.lower()
    return any(marker in lowered for marker in _CREDENTIAL_ERROR_MARKERS)


def run_openwiki_subprocess(
    argv: list[str],
    *,
    cwd: Path,
    timeout: float = DEFAULT_OPENWIKI_TIMEOUT_SECONDS,
    env: dict[str, str] | None = None,
) -> tuple[bool, str, int]:
    """Execute ``openwiki`` when the CLI is present on PATH.

    Args:
        argv (list[str]): Allowlisted argv from :func:`build_openwiki_argv`.
        cwd (Path): Working directory for the subprocess (repo root).
        timeout (float, optional): Wall-clock seconds before termination.
        env (dict[str, str] | None, optional): Explicit subprocess environment.
            When omitted, inherits the current process environment.

    Returns:
        tuple[bool, str, int]: ``(ok, detail, returncode)`` where ``detail`` is stdout
            on success or stderr/stdout text on failure. Return code ``127`` means missing CLI.

    Examples:
        >>> run_openwiki_subprocess.__name__
        'run_openwiki_subprocess'
    """
    if shutil.which("openwiki") is None:
        return False, openwiki_missing_message(), 127
    completed = subprocess.run(  # nosec B603 — argv is a fixed CLI list, no shell
        argv,
        cwd=cwd,
        env=env,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    code = completed.returncode or 0
    stdout = completed.stdout.decode("utf-8", errors="replace").strip()
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    if code != 0:
        detail = stderr or stdout
        if not detail:
            detail = f"openwiki exited {code}"
        return False, detail, code
    return True, stdout, code


def openwiki_status(root: Path) -> dict[str, object]:
    """Report whether an OpenWiki tree exists under ``root`` and read last-update metadata.

    Args:
        root (Path): Repository root (typically ``source_code/`` mirror).

    Returns:
        dict[str, object]: ``wiki_dir``, ``exists``, optional ``last_update`` parsed JSON,
            and ``page_count`` when markdown pages are present.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path as _P
        >>> repo = _P(tempfile.mkdtemp())
        >>> st = openwiki_status(repo)
        >>> st["exists"]
        False
    """
    wiki_dir = root.resolve() / OPENWIKI_DIR_NAME
    exists = wiki_dir.is_dir()
    out: dict[str, object] = {
        "root": str(root.resolve()),
        "wiki_dir": str(wiki_dir),
        "exists": exists,
    }
    meta_path = root.resolve() / OPENWIKI_UPDATE_METADATA_REL
    if meta_path.is_file():
        try:
            parsed = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            out["last_update"] = parsed
    if exists:
        pages = sorted(wiki_dir.rglob("*.md"))
        out["page_count"] = len(pages)
    return out
