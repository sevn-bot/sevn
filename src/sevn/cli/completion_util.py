"""Typer shell-completion install helpers (`specs/23-cli.md` §2.8).

Module: sevn.cli.completion_util
Depends: pathlib, typer.completion

Exports:
    completion_show_script — render installable completion script text.
    completion_install — idempotent install into the operator shell rc / config dir.
    completion_uninstall — idempotent removal of managed completion artefacts.
    normalize_shell — validate bash / zsh / fish shell names.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from typer.completion import get_completion_script, install  # type: ignore[attr-defined]

PROG_NAME = "sevn"
COMPLETE_VAR = "_SEVN_COMPLETE"
SUPPORTED_SHELLS = frozenset({"bash", "zsh", "fish"})
ShellName = Literal["bash", "zsh", "fish"]


def normalize_shell(shell: str) -> ShellName:
    """Return a supported shell name or raise ``ValueError``.

    Args:
        shell (str): Operator-supplied shell name (``bash``, ``zsh``, or ``fish``).

    Returns:
        ShellName: Normalized shell identifier.

    Raises:
        ValueError: When ``shell`` is not one of the supported shells.

    Examples:
        >>> normalize_shell("zsh")
        'zsh'
        >>> try:
        ...     normalize_shell("powershell")
        ... except ValueError:
        ...     pass
    """
    name = shell.strip().lower()
    if name not in SUPPORTED_SHELLS:
        msg = f"unsupported shell {shell!r}; choose one of: bash, zsh, fish"
        raise ValueError(msg)
    return name  # type: ignore[return-value]


def completion_show_script(*, shell: ShellName) -> str:
    """Return Typer completion script text for ``shell``.

    Args:
        shell (ShellName): Target shell.

    Returns:
        str: Script body suitable for stdout.

    Examples:
        >>> "complete" in completion_show_script(shell="bash")
        True
    """
    return get_completion_script(
        prog_name=PROG_NAME,
        complete_var=COMPLETE_VAR,
        shell=shell,  # nosec B604 — Typer kwarg, not subprocess shell=
    )


def completion_install(*, shell: ShellName) -> tuple[str, Path]:
    """Install Typer completion for ``shell`` (idempotent).

    Args:
        shell (ShellName): Target shell.

    Returns:
        tuple[str, Path]: Shell name and path to the installed script file.

    Examples:
        >>> import os
        >>> import tempfile
        >>> td = tempfile.mkdtemp()
        >>> os.environ["HOME"] = td
        >>> os.environ["_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION"] = "1"
        >>> completion_install(shell="bash")[0]
        'bash'
    """
    return install(  # nosec B604 — Typer kwarg, not subprocess shell=
        shell=shell,
        prog_name=PROG_NAME,
        complete_var=COMPLETE_VAR,
    )


def _strip_rc_lines(rc_path: Path, *, needles: tuple[str, ...]) -> bool:
    """Remove lines containing any needle from an rc file.

    Args:
        rc_path (Path): Shell rc file path.
        needles (tuple[str, ...]): Substrings that identify managed lines.

    Returns:
        bool: ``True`` when the file was modified.

    Examples:
        >>> import tempfile
        >>> td = Path(tempfile.mkdtemp())
        >>> rc = td / ".zshrc"
        >>> _ = rc.write_text("fpath+=~/.zfunc" + chr(10), encoding="utf-8")
        >>> _strip_rc_lines(rc, needles=("fpath+=~/.zfunc",))
        True
    """
    if not rc_path.is_file():
        return False
    original = rc_path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    filtered = [line for line in lines if not any(n in line for n in needles)]
    if filtered == lines:
        return False
    rc_path.write_text("".join(filtered), encoding="utf-8")
    return True


def completion_uninstall(*, shell: ShellName) -> tuple[str, Path]:
    """Remove managed completion artefacts for ``shell`` (idempotent).

    Args:
        shell (ShellName): Target shell.

    Returns:
        tuple[str, Path]: Shell name and primary artefact path Typer manages.

    Examples:
        >>> import os
        >>> import tempfile
        >>> td = tempfile.mkdtemp()
        >>> os.environ["HOME"] = td
        >>> _ = completion_install(shell="fish")
        >>> completion_uninstall(shell="fish")[0]
        'fish'
    """
    if shell == "bash":
        completion_path = Path.home() / ".bash_completions" / f"{PROG_NAME}.sh"
        source_needle = f"source '{completion_path}'"
        _strip_rc_lines(Path.home() / ".bashrc", needles=(source_needle,))
        if completion_path.is_file():
            completion_path.unlink()
        return shell, completion_path
    if shell == "zsh":
        completion_path = Path.home() / f".zfunc/_{PROG_NAME}"
        _strip_rc_lines(
            Path.home() / ".zshrc",
            needles=(
                "fpath+=~/.zfunc; autoload -Uz compinit; compinit",
                "zstyle ':completion:*' menu select",
            ),
        )
        if completion_path.is_file():
            completion_path.unlink()
        return shell, completion_path
    completion_path = Path.home() / f".config/fish/completions/{PROG_NAME}.fish"
    if completion_path.is_file():
        completion_path.unlink()
    return shell, completion_path
