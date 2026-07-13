"""Brand copy loaders for README generation.

Module: sevn.docs.readme.brand
Depends: pathlib, tomllib

Exports:
    load_root_intro_lines — read intro verse lines for the root README.
    load_root_value_prop — read value proposition paragraph for the root README.

Examples:
    >>> from pathlib import Path
    >>> from sevn.docs.readme.brand import load_root_intro_lines
    >>> lines = load_root_intro_lines(Path("."))
    >>> isinstance(lines, list) and all(isinstance(line, str) for line in lines)
    True
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT_INTRO_PATH = Path("docs/brand/root-intro.toml")

_DEFAULT_ROOT_INTRO_LINES: tuple[str, ...] = (
    "I'm Sevn. I'm more than a bot,",
    "or an Assistant, AI or not.",
    "I'm Sevn, I can be what you want,",
    "Agentic, attentive, shaped to your intent.",
    "I'm not perfect, I know, but I'm working on it,",
    "I will get better every day, as we keep turning it.",
    "Mostly Python, but also a harness,",
    "a model or many, to serve you or somebody.",
    "Tools when you need hands, quiet when you don't,",
    "Your gateway, your rules — I run where you chose.",
)


def load_root_intro_lines(repo_root: Path, *, path: Path | None = None) -> list[str]:
    """Load root README intro verse lines from ``docs/brand/root-intro.toml``.

        Args:
    repo_root (Path): Repository root.
    path (Path | None): Override intro TOML path (relative to ``repo_root``).

        Returns:
            list[str]: Non-empty intro lines in display order.

        Examples:
            >>> from pathlib import Path as _P
            >>> lines = load_root_intro_lines(_P("."))
            >>> lines[0].startswith("I'm Sevn")
            True
    """
    intro_path = repo_root.resolve() / (path or ROOT_INTRO_PATH)
    if not intro_path.is_file():
        return list(_DEFAULT_ROOT_INTRO_LINES)
    data = tomllib.loads(intro_path.read_text(encoding="utf-8"))
    raw = data.get("lines", ())
    lines = [str(line).strip() for line in raw if str(line).strip()]
    return lines or list(_DEFAULT_ROOT_INTRO_LINES)


def load_root_value_prop(repo_root: Path, *, path: Path | None = None) -> str | None:
    """Load root README value proposition from ``docs/brand/root-intro.toml``.

        Args:
    repo_root (Path): Repository root.
    path (Path | None): Override intro TOML path (relative to ``repo_root``).

        Returns:
            str | None: Value prop text when set; otherwise ``None``.

        Examples:
            >>> from pathlib import Path as _P
            >>> load_root_value_prop(_P(".")) is None or isinstance(load_root_value_prop(_P(".")), str)
            True
    """
    intro_path = repo_root.resolve() / (path or ROOT_INTRO_PATH)
    if not intro_path.is_file():
        return None
    data = tomllib.loads(intro_path.read_text(encoding="utf-8"))
    raw = data.get("value_prop")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None
