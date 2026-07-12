"""Shell history scrub helpers for sensitive CLI commands.

Module: sevn.cli.shell_history
Depends: os, pathlib, subprocess, sys, tempfile, atexit

Constants:
    ADD_GITHUB_TOKEN_HISTORY_MARKER — substring matched when scrubbing gh token commands.
    STORE_PASSPHRASE_HISTORY_MARKER — substring matched when scrubbing store-passphrase commands.
    SET_GATEWAY_TOKEN_HISTORY_MARKER — substring matched when scrubbing set-gateway-token commands.
    SECRETS_PUT_HISTORY_MARKER — substring matched when scrubbing secrets put commands.
    SENSITIVE_CLI_HISTORY_MARKERS — all secret-setting command markers for shell hooks.

Exports:
    resolve_shell_history_path — locate the active shell history file.
    scrub_shell_history — remove history lines matching markers or substrings.
    schedule_post_exit_history_scrub — scrub now and again after the shell records this command.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import re
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

ADD_GITHUB_TOKEN_HISTORY_MARKER: str = "sevn gh add-github-token"
STORE_PASSPHRASE_HISTORY_MARKER: str = "sevn secrets store-passphrase"
SECRETS_PUT_HISTORY_MARKER: str = "sevn secrets put"
SET_GATEWAY_TOKEN_HISTORY_MARKER: str = "sevn gateway set-gateway-token"
SENSITIVE_CLI_HISTORY_MARKERS: tuple[str, ...] = (
    ADD_GITHUB_TOKEN_HISTORY_MARKER,
    STORE_PASSPHRASE_HISTORY_MARKER,
    SECRETS_PUT_HISTORY_MARKER,
    SET_GATEWAY_TOKEN_HISTORY_MARKER,
)
_POST_EXIT_SCRUB_DELAYS_S: tuple[float, ...] = (0.35, 1.0, 3.0, 10.0)


def _parent_process_env_var(name: str) -> str | None:
    """Read one environment variable from the parent process when exported there.

    Args:
        name (str): Variable name (for example ``HISTFILE``).

    Returns:
        str | None: Value when discovered, else ``None``.

    Examples:
        >>> isinstance(_parent_process_env_var("HISTFILE"), (str, type(None)))
        True
    """
    ppid = os.getppid()
    if ppid <= 1:
        return None
    if sys.platform == "linux":
        environ_path = Path(f"/proc/{ppid}/environ")
        if not environ_path.is_file():
            return None
        try:
            payload = environ_path.read_bytes()
        except OSError:
            return None
        prefix = f"{name}=".encode()
        for entry in payload.split(b"\0"):
            if entry.startswith(prefix):
                return entry[len(prefix) :].decode("utf-8", errors="replace")
        return None
    try:
        output = subprocess.check_output(  # nosec
            ["ps", "eww", "-p", str(ppid)],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    match = re.search(rf"(?:^|\s){re.escape(name)}=([^\s]+)", output)
    if not match:
        return None
    return match.group(1)


def resolve_shell_history_path() -> Path | None:
    """Locate the active shell history file for the current user.

    Prefers ``$HISTFILE`` in this process, then the parent shell environment, then
    conventional defaults for ``$SHELL``.

    Returns:
        Path | None: History file path when known, else ``None``.

    Examples:
        >>> isinstance(resolve_shell_history_path(), (Path, type(None)))
        True
    """
    histfile = os.environ.get("HISTFILE", "").strip()
    if not histfile:
        histfile = (_parent_process_env_var("HISTFILE") or "").strip()
    if histfile:
        return Path(histfile).expanduser()
    shell = Path(os.environ.get("SHELL", "")).name
    home = Path.home()
    if shell == "zsh":
        return home / ".zsh_history"
    if shell in {"bash", "sh"}:
        return home / ".bash_history"
    return None


def _history_command_text(line: str) -> str:
    """Return the command portion of one history line (zsh extended or plain).

    Args:
        line (str): Raw history file line.

    Returns:
        str: Command text used for substring matching.

    Examples:
        >>> _history_command_text(": 1:0;sevn gh add-github-token --value x")
        'sevn gh add-github-token --value x'
        >>> _history_command_text("plain command")
        'plain command'
    """
    stripped = line.rstrip("\n")
    if stripped.startswith(": ") and ";" in stripped:
        return stripped.split(";", 1)[1]
    return stripped


def scrub_shell_history(
    *,
    containing: str | None = None,
    extra_substrings: tuple[str, ...] = (),
    histfile_path: Path | None = None,
) -> int:
    """Remove matching lines from the on-disk shell history file.

    Args:
        containing (str | None): Drop lines whose command text contains this substring.
        extra_substrings (tuple[str, ...]): Also drop lines containing any of these
            substrings anywhere in the raw line (for example a leaked token value).
        histfile_path (Path | None): Override the history file path (for shell hooks).

    Returns:
        int: Number of lines removed (``0`` when no file or no matches).

    Examples:
        >>> scrub_shell_history(containing="__no_such_marker__xyz__")
        0
    """
    if not containing and not extra_substrings:
        return 0
    path = histfile_path or resolve_shell_history_path()
    if path is None or not path.is_file():
        return 0
    try:
        original = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    if not original:
        return 0
    kept: list[str] = []
    removed = 0
    for line in original.splitlines(keepends=True):
        command = _history_command_text(line)
        drop = (containing and containing in command) or any(
            sub and sub in line for sub in extra_substrings
        )
        if drop:
            removed += 1
            continue
        kept.append(line)
    if removed == 0:
        return 0
    payload = "".join(kept)
    tmp_name: str | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
            text=True,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, path)
    except OSError:
        if tmp_name is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
        return 0
    return removed


def schedule_post_exit_history_scrub(
    *,
    containing: str,
    extra_substrings: tuple[str, ...] = (),
) -> None:
    """Scrub history now and again shortly after this process exits.

    Shells append the invoking command to history after the child exits; a short
    delayed re-scrub catches that final line.

    Args:
        containing (str): Command substring to remove from history.
        extra_substrings (tuple[str, ...]): Additional raw-line substrings to remove.

    Examples:
        >>> schedule_post_exit_history_scrub(containing="sevn gh add-github-token")
    """

    def _scrub() -> None:
        scrub_shell_history(containing=containing, extra_substrings=extra_substrings)

    atexit.register(_scrub)
    delays = ", ".join(str(delay) for delay in _POST_EXIT_SCRUB_DELAYS_S)
    script = (
        "import time\n"
        "from sevn.cli.shell_history import scrub_shell_history\n"
        f"for _delay in ({delays},):\n"
        "    time.sleep(_delay)\n"
        f"    scrub_shell_history(containing={containing!r}, "
        f"extra_substrings={extra_substrings!r})\n"
    )
    try:
        subprocess.Popen(  # nosec
            [sys.executable, "-c", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return
