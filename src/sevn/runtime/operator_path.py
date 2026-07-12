"""Augment subprocess PATH for operator tool locations (`specs/23-cli.md`).

Module: sevn.runtime.operator_path
Depends: os, pathlib

Exports:
    operator_path_prefixes — common bin dirs to prepend when present on disk.
    augment_operator_path — return env with operator bins prepended to PATH.
    augment_macos_dyld_library_path — add Homebrew lib dir to DYLD_FALLBACK_LIBRARY_PATH (macOS).

Gateway daemons (launchd/systemd) and ``terminal_run`` / ``process`` inherit a
minimal PATH. Prepend ``~/.local/bin`` (uv), Homebrew, and cargo so installs and
CLI tools resolve without absolute paths.
"""

from __future__ import annotations

import os
import platform as _platform
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

# Homebrew lib dirs (Apple Silicon, then Intel). WeasyPrint binds Pango/GObject/cairo via
# ``cffi.dlopen`` at import; dyld only searches these when DYLD_FALLBACK_LIBRARY_PATH lists
# them, so a plain ``brew install pango`` is not enough for a launchd/systemd gateway.
_HOMEBREW_LIB_DIRS: Final[tuple[str, ...]] = (
    "/opt/homebrew/lib",
    "/usr/local/lib",
)

# macOS default DYLD_FALLBACK_LIBRARY_PATH (when the var is unset). Re-appended so setting the
# var explicitly does not shadow system libraries.
_DYLD_DEFAULT_DIRS: Final[tuple[str, ...]] = (
    "/usr/local/lib",
    "/lib",
    "/usr/lib",
)

_DEFAULT_PREFIX_REL: Final[tuple[str, ...]] = (
    ".local/bin",
    ".cargo/bin",
    # Deno's official installer drops the binary here; without it the launchd/systemd gateway
    # (minimal PATH) can't find an installed Deno and downgrades the Pyodide sandbox to Docker.
    ".deno/bin",
)

# launchd/systemd units often pass a partial env without PATH; ``security`` and other
# system CLIs live under these dirs.
_DEFAULT_SYSTEM_PATH: Final[tuple[str, ...]] = (
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
)


def operator_path_prefixes(*, home: Path | None = None) -> tuple[Path, ...]:
    """Return candidate operator bin directories to prepend to PATH.

    Args:
        home (Path | None, optional): Operator home; defaults to ``Path.home()``.

    Returns:
        tuple[Path, ...]: Existing directories only, in prepend order.

    Examples:
        >>> isinstance(operator_path_prefixes(), tuple)
        True
    """
    root = home if home is not None else Path.home()
    candidates: list[Path] = [root / rel for rel in _DEFAULT_PREFIX_REL]
    candidates.extend(
        (
            Path("/opt/homebrew/bin"),
            Path("/usr/local/bin"),
            root / "Library" / "Application Support" / "uv" / "bin",
        ),
    )
    return tuple(p for p in candidates if p.is_dir())


def augment_operator_path(
    env: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> dict[str, str]:
    """Return a copy of ``env`` with operator bin dirs prepended to PATH.

    Args:
        env (Mapping[str, str] | None, optional): Base environment; defaults to
            ``os.environ``.
        home (Path | None, optional): Operator home for ``~/.local/bin`` etc.

    Returns:
        dict[str, str]: Environment mapping safe to pass to subprocess spawn.

    Examples:
        >>> merged = augment_operator_path({"PATH": "/usr/bin"})
        >>> "PATH" in merged
        True
    """
    merged = dict(os.environ if env is None else env)
    current = merged.get("PATH", "")
    parts = [part for part in current.split(os.pathsep) if part]
    known = set(parts)
    prepend: list[str] = []
    for prefix in operator_path_prefixes(home=home):
        entry = str(prefix)
        if entry not in known:
            prepend.append(entry)
            known.add(entry)
    append: list[str] = []
    for entry in _DEFAULT_SYSTEM_PATH:
        if entry not in known:
            append.append(entry)
            known.add(entry)
    if prepend or append:
        merged["PATH"] = os.pathsep.join([*prepend, *parts, *append])
    return merged


def augment_macos_dyld_library_path(
    env: Mapping[str, str] | None = None,
    *,
    system: str | None = None,
    home: Path | None = None,
    lib_dirs: Sequence[str] | None = None,
) -> dict[str, str]:
    """Return a copy of ``env`` with the Homebrew lib dir on ``DYLD_FALLBACK_LIBRARY_PATH``.

    No-op off macOS or when no Homebrew lib dir exists. WeasyPrint's native libraries
    (Pango/GObject/cairo) load only when dyld's fallback search path includes the Homebrew
    ``lib`` dir; dyld reads this variable at ``exec`` time, so it must be baked into the
    gateway's launch env rather than set at runtime.

    Args:
        env (Mapping[str, str] | None): Base environment; defaults to ``os.environ``.
        system (str | None): ``platform.system()`` override (tests).
        home (Path | None): Operator home for the ``$HOME/lib`` default entry.
        lib_dirs (Sequence[str] | None): Homebrew lib dir override (tests); existing dirs only
            otherwise.

    Returns:
        dict[str, str]: Environment mapping (unchanged off macOS / when no lib dir exists).

    Examples:
        >>> out = augment_macos_dyld_library_path(
        ...     {}, system="Darwin", home=Path("/Users/x"), lib_dirs=["/opt/homebrew/lib"]
        ... )
        >>> out["DYLD_FALLBACK_LIBRARY_PATH"].split(":")[0]
        '/opt/homebrew/lib'
        >>> augment_macos_dyld_library_path({}, system="Linux")
        {}
    """
    merged = dict(os.environ if env is None else env)
    sys_name = system if system is not None else _platform.system()
    if sys_name != "Darwin":
        return merged
    brew_dirs = (
        list(lib_dirs)
        if lib_dirs is not None
        else [d for d in _HOMEBREW_LIB_DIRS if Path(d).is_dir()]
    )
    if not brew_dirs:
        return merged
    current = merged.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    existing = [part for part in current.split(os.pathsep) if part]
    known = set(existing)
    prepend = [d for d in brew_dirs if d not in known]
    if not prepend:
        return merged
    home_lib = str((home if home is not None else Path.home()) / "lib")
    result = [*prepend, *existing]
    for default in (home_lib, *_DYLD_DEFAULT_DIRS):
        if default not in known and default not in result:
            result.append(default)
    merged["DYLD_FALLBACK_LIBRARY_PATH"] = os.pathsep.join(result)
    return merged
