"""Installable shell hooks so successful secret-setting ``sevn`` commands leave no history trace.

Module: sevn.cli.shell_history_hooks
Depends: pathlib, typer, sevn.cli.shell_history

Exports:
    shell_history_hook_installed — whether the current hook version is present.
    install_shell_history_hook — idempotent install into bash/zsh rc.
    uninstall_shell_history_hook — idempotent removal from bash/zsh rc.
    ensure_shell_history_hook — install or upgrade when needed (for sync/onboarding).
    emit_shell_history_session_hint — stderr note when the hook is missing.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer

from sevn.cli.shell_history import SENSITIVE_CLI_HISTORY_MARKERS

SHELL_HISTORY_HOOK_VERSION: str = "4"
_HOOK_BEGIN_PREFIX: str = "# >>> sevn managed shell-history hook"
SHELL_HISTORY_HOOK_BEGIN: str = f"{_HOOK_BEGIN_PREFIX} v{SHELL_HISTORY_HOOK_VERSION} >>>"
SHELL_HISTORY_HOOK_END: str = "# <<< sevn managed shell-history hook <<<"


def _shell_case_alternation(markers: tuple[str, ...]) -> str:
    """Build a shell ``case`` alternation matching any marker substring.

    Args:
        markers (tuple[str, ...]): Command substrings to match.

    Returns:
        str: Parenthesized alternation for ``case "$1" in … esac``.

    Examples:
        >>> "store-passphrase" in _shell_case_alternation(SENSITIVE_CLI_HISTORY_MARKERS)
        True
    """
    return "|".join(f'*"{marker}"*' for marker in markers)


_SECRET_CMD_CASE: str = _shell_case_alternation(SENSITIVE_CLI_HISTORY_MARKERS)

_ZSH_HOOK_BODY: str = f"""{SHELL_HISTORY_HOOK_BEGIN}
__sevn_is_secret_cmd() {{
  case "$1" in
    ({_SECRET_CMD_CASE})
      return 0
      ;;
  esac
  return 1
}}
__sevn_history_precmd() {{
  (( $? == 0 )) || return 0
  local _last
  _last="$(builtin fc -ln -1 2>/dev/null)" || return 0
  __sevn_is_secret_cmd "$_last" || return 0
  builtin fc -d -1 -1 2>/dev/null
  local _hist="${{HISTFILE:-$HOME/.zsh_history}}"
  if [[ -f "$_hist" ]]; then
    local _filelast
    _filelast="$(tail -1 "$_hist" 2>/dev/null)"
    case "$_filelast" in
      ({_SECRET_CMD_CASE})
        sed -i '' '$d' "$_hist" 2>/dev/null || sed -i '$d' "$_hist"
        ;;
    esac
  fi
}}
precmd_functions=(${{precmd_functions:#__sevn_history_precmd}} __sevn_history_precmd)
{SHELL_HISTORY_HOOK_END}
"""

_BASH_HOOK_BODY: str = f"""{SHELL_HISTORY_HOOK_BEGIN}
__sevn_is_secret_cmd() {{
  case "$1" in
    ({_SECRET_CMD_CASE})
      return 0
      ;;
  esac
  return 1
}}
__sevn_history_prompt() {{
  (( $? == 0 )) || return 0
  local _line _num _cmd
  _line="$(builtin history 1 2>/dev/null)" || return 0
  _num="${{_line%% *}}"
  _cmd="${{_line#* }}"
  __sevn_is_secret_cmd "$_cmd" || return 0
  builtin history -d "$_num" 2>/dev/null
}}
if [[ "${{PROMPT_COMMAND:-}}" != *"__sevn_history_prompt"* ]]; then
  PROMPT_COMMAND="__sevn_history_prompt${{PROMPT_COMMAND:+;$PROMPT_COMMAND}}"
fi
{SHELL_HISTORY_HOOK_END}
"""


def _rc_path_for_shell(shell: str) -> Path | None:
    """Return the rc file path for ``shell`` when supported.

    Args:
        shell (str): ``zsh`` or ``bash``.

    Returns:
        Path | None: ``~/.zshrc`` or ``~/.bashrc``, else ``None``.

    Examples:
        >>> _rc_path_for_shell("zsh") == Path.home() / ".zshrc"
        True
    """
    home = Path.home()
    if shell == "zsh":
        return home / ".zshrc"
    if shell == "bash":
        return home / ".bashrc"
    return None


def _hook_body_for_shell(shell: str) -> str | None:
    """Return the managed hook script body for ``shell``.

    Args:
        shell (str): ``zsh`` or ``bash``.

    Returns:
        str | None: Hook block text, or ``None`` when unsupported.

    Examples:
        >>> isinstance(_hook_body_for_shell("zsh"), str)
        True
    """
    if shell == "zsh":
        return _ZSH_HOOK_BODY
    if shell == "bash":
        return _BASH_HOOK_BODY
    return None


def _find_managed_block_span(text: str) -> tuple[int, int] | None:
    """Return ``(start, end)`` indices for the managed hook block in ``text``.

    Args:
        text (str): Shell rc file contents.

    Returns:
        tuple[int, int] | None: Span when present, else ``None``.

    Examples:
        >>> span = _find_managed_block_span(_ZSH_HOOK_BODY)
        >>> span is not None and span[0] == 0
        True
    """
    if SHELL_HISTORY_HOOK_END not in text:
        return None
    start = text.find(_HOOK_BEGIN_PREFIX)
    if start == -1:
        return None
    end = text.find(SHELL_HISTORY_HOOK_END, start)
    if end == -1:
        return None
    return start, end + len(SHELL_HISTORY_HOOK_END)


def _managed_block_present(text: str) -> bool:
    """Return whether ``text`` contains the managed shell-history hook block.

    Args:
        text (str): Shell rc file contents.

    Returns:
        bool: ``True`` when both begin and end markers are present.

    Examples:
        >>> _managed_block_present(SHELL_HISTORY_HOOK_BEGIN + "\\n" + SHELL_HISTORY_HOOK_END)
        True
    """
    return _find_managed_block_span(text) is not None


def _managed_block_is_current(text: str) -> bool:
    """Return whether the managed hook block matches the current hook version.

    Args:
        text (str): Shell rc file contents.

    Returns:
        bool: ``True`` when the installed block is current.

    Examples:
        >>> _managed_block_is_current(_ZSH_HOOK_BODY)
        True
    """
    span = _find_managed_block_span(text)
    if span is None:
        return False
    block = text[span[0] : span[1]]
    return f"v{SHELL_HISTORY_HOOK_VERSION}" in block


def shell_history_hook_installed(*, shell: str | None = None) -> bool:
    """Return whether the current shell-history hook version is installed.

    Args:
        shell (str | None): ``zsh`` or ``bash``; defaults to ``$SHELL`` basename.

    Returns:
        bool: ``True`` when the managed block is present and current.

    Examples:
        >>> isinstance(shell_history_hook_installed(shell="zsh"), bool)
        True
    """
    name = shell or Path(os.environ.get("SHELL", "")).name
    rc = _rc_path_for_shell(name)
    if rc is None or not rc.is_file():
        return False
    text = rc.read_text(encoding="utf-8", errors="replace")
    return _managed_block_present(text) and _managed_block_is_current(text)


def install_shell_history_hook(*, shell: str) -> Path:
    """Append the managed shell-history hook to the operator rc file (idempotent).

    Args:
        shell (str): ``zsh`` or ``bash``.

    Returns:
        Path: Rc file that was updated or already contained the hook.

    Raises:
        ValueError: When ``shell`` is unsupported.

    Examples:
        >>> import os, tempfile
        >>> td = tempfile.mkdtemp()
        >>> os.environ["HOME"] = td
        >>> rc = install_shell_history_hook(shell="zsh")
        >>> shell_history_hook_installed(shell="zsh")
        True
    """
    body = _hook_body_for_shell(shell)
    if body is None:
        msg = f"shell-history hook is supported for bash and zsh only (got {shell!r})"
        raise ValueError(msg)
    rc = _rc_path_for_shell(shell)
    assert rc is not None  # nosec B101
    if rc.is_file():
        original = rc.read_text(encoding="utf-8")
        if _managed_block_present(original) and _managed_block_is_current(original):
            return rc
        if _managed_block_present(original):
            uninstall_shell_history_hook(shell=shell)  # nosec B604
            original = rc.read_text(encoding="utf-8") if rc.is_file() else ""
        payload = original
        if payload and not payload.endswith("\n"):
            payload += "\n"
        payload += ("\n" if payload else "") + body + "\n"
    else:
        payload = body + "\n"
    rc.write_text(payload, encoding="utf-8")
    return rc


def uninstall_shell_history_hook(*, shell: str) -> bool:
    """Remove the managed shell-history hook from the operator rc file.

    Args:
        shell (str): ``zsh`` or ``bash``.

    Returns:
        bool: ``True`` when the rc file was modified.

    Examples:
        >>> import os, tempfile
        >>> td = tempfile.mkdtemp()
        >>> os.environ["HOME"] = td
        >>> _ = install_shell_history_hook(shell="bash")
        >>> uninstall_shell_history_hook(shell="bash")
        True
    """
    rc = _rc_path_for_shell(shell)
    if rc is None or not rc.is_file():
        return False
    original = rc.read_text(encoding="utf-8")
    span = _find_managed_block_span(original)
    if span is None:
        return False
    updated = (original[: span[0]] + original[span[1] :]).strip("\n")
    if updated:
        updated += "\n"
    rc.write_text(updated, encoding="utf-8")
    return True


def ensure_shell_history_hook(*, shell: str | None = None) -> str | None:
    """Install or upgrade the managed shell-history hook when needed.

    Args:
        shell (str | None): ``zsh`` or ``bash``; defaults to ``$SHELL`` basename.

    Returns:
        str | None: Human-readable summary when install/upgrade ran, else ``None``.

    Examples:
        >>> isinstance(ensure_shell_history_hook(shell="fish"), (str, type(None)))
        True
    """
    name = shell or Path(os.environ.get("SHELL", "")).name
    if name not in {"bash", "zsh"}:
        return None
    if shell_history_hook_installed(shell=name):  # nosec B604
        return None
    upgraded = False
    rc = _rc_path_for_shell(name)
    assert rc is not None  # nosec B101
    if rc.is_file() and _managed_block_present(rc.read_text(encoding="utf-8")):
        upgraded = True
    install_shell_history_hook(shell=name)  # nosec B604
    action = "upgraded" if upgraded else "installed"
    return f"{action} {name} shell-history hook (v{SHELL_HISTORY_HOOK_VERSION})"


def emit_shell_history_session_hint(*, json_out: bool = False) -> None:
    """Print a stderr hint when the interactive shell hook is not installed.

    Args:
        json_out (bool): When ``True``, suppress human-oriented stderr output.

    Examples:
        >>> emit_shell_history_session_hint(json_out=True)
    """
    if json_out or not sys.stderr.isatty():
        return
    shell = Path(os.environ.get("SHELL", "")).name
    if shell_history_hook_installed(shell=shell):  # nosec B604
        return
    typer.secho(
        "note: secret-setting sevn commands stay in shell history until the hook is installed. "
        "Run `sevn shell-history install` once, then restart the terminal or `source` your rc.",
        err=True,
    )


__all__ = [
    "emit_shell_history_session_hint",
    "ensure_shell_history_hook",
    "install_shell_history_hook",
    "shell_history_hook_installed",
    "uninstall_shell_history_hook",
]
