"""Skills inventory loader (workspace-authoritative, repo starter as fallback).

Module: sevn.data.skills_index
Depends: pathlib, shutil (stdlib only).

The runtime canonical index lives at ``<workspace>/skills/INDEX.md``. The shipped
starter is packaged at ``sevn/data/skills/INDEX.md`` (wheel and git checkout).
Gateway boot and onboarding call :func:`ensure_workspace_index` to copy the
starter when the workspace file is missing. The workspace copy is authoritative
for user edits (see ``PROBLEMS.md`` §Priority 1.a).

The file is a markdown table with mandatory columns ``name`` and ``description``.
Additional columns (``tier_hint``, ``when_to_use``, …) are rendered for humans
but ignored by :func:`read_skills_index`, which returns ``{name: description}``.

Exports:
    SkillsStarterMissingError — raised when the packaged starter cannot be resolved.
    read_skills_index — return ``{name: description}`` for requested names (or all).
    ensure_workspace_index — copy the starter into a workspace on first boot.

Also exposes the module-level constant ``REPO_STARTER_INDEX`` (a ``Path``) that
points at the shipped starter; see its docstring below.

Examples:
    >>> isinstance(REPO_STARTER_INDEX.name, str)
    True
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Final

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Iterable


class SkillsStarterMissingError(FileNotFoundError):
    """Packaged ``skills/INDEX.md`` starter is missing from this install.

    Examples:
        >>> err = SkillsStarterMissingError("missing")
        >>> isinstance(err, FileNotFoundError)
        True
    """

    def __init__(self, resolved_path: Path) -> None:
        """Record the starter path the resolver attempted.

        Args:
            resolved_path (Path): Packaged or dev-checkout path that was missing.

        Examples:
            >>> SkillsStarterMissingError(Path("/tmp/skills/INDEX.md")).resolved_path.name
            'INDEX.md'
        """
        self.resolved_path = resolved_path
        super().__init__(
            "skills INDEX starter missing — verify wheel data_files includes "
            f"sevn/data/skills/INDEX.md (tried {resolved_path})",
        )


_PACKAGED_STARTER_INDEX: Final[Path] = Path(__file__).resolve().parent / "skills" / "INDEX.md"


def _resolve_repo_starter_index() -> Path:
    """Return the shipped starter ``INDEX.md`` for this install layout.

    Returns:
        Path: Packaged starter path (``sevn/data/skills/INDEX.md``).

    Examples:
        >>> p = _resolve_repo_starter_index()
        >>> p.name == "INDEX.md" and p.parent.name == "skills"
        True
    """
    return _PACKAGED_STARTER_INDEX


REPO_STARTER_INDEX: Final[Path] = _resolve_repo_starter_index()
"""Shipped starter index (packaged or repo-root fallback).

The runtime function searches the workspace first; this path is the copy source
for :func:`ensure_workspace_index` and the read fallback when no workspace copy
exists.

Examples:
    >>> REPO_STARTER_INDEX.parent.name
    'skills'
"""


_ESCAPE_PIPE = "\x00PIPE\x00"


def _split_pipes(line: str) -> list[str]:
    """Split a markdown table row on unescaped ``|``.

    ``\\|`` is treated as a literal ``|`` in the resulting cell, not a separator.

    Args:
        line (str): One row of a markdown table.

    Returns:
        list[str]: Cells (including any leading/trailing empties from outer pipes).

    Examples:
        >>> _split_pipes("| a | b |")
        ['', ' a ', ' b ', '']
        >>> _split_pipes("| foo | a \\\\| b |")
        ['', ' foo ', ' a | b ', '']
    """
    masked = line.replace("\\|", _ESCAPE_PIPE)
    return [cell.replace(_ESCAPE_PIPE, "|") for cell in masked.split("|")]


def _parse_table(text: str) -> dict[str, str]:
    """Parse the markdown table into ``{name: description}``.

    Skips the header row (``| name | description |``) and the separator row
    (``|---|---|``). Additional columns past the second are ignored. ``\\|``
    inside a cell is preserved as a literal ``|``.

    Args:
        text (str): Full INDEX.md contents.

    Returns:
        dict[str, str]: Skill name → one-line description.

    Examples:
        >>> _parse_table("| name | description |\\n|---|---|\\n| a | b |\\n")
        {'a': 'b'}
        >>> _parse_table("| name | description | tier |\\n|---|---|---|\\n| a | b | B |")
        {'a': 'b'}
        >>> _parse_table("no table here")
        {}
    """
    rows: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = _split_pipes(line)
        # Outer pipes give leading/trailing empty cells; need ≥ 2 inner cells.
        inner = [c.strip() for c in cells[1:-1]] if len(cells) >= 4 else []
        if len(inner) < 2:
            continue
        first, second = inner[0], inner[1]
        # Skip header and separator rows.
        if first.lower() == "name" and second.lower().startswith("desc"):
            continue
        if set(first) <= {"-", ":"} and set(second) <= {"-", ":"}:
            continue
        if not first:
            continue
        rows[first] = second
    return rows


def _resolve_index_path(workspace_root: Path | None) -> Path:
    """Pick the authoritative INDEX path.

    Args:
        workspace_root (Path | None): Workspace content root; ``None`` falls
            back to the shipped starter directly.

    Returns:
        Path: Path to read; may not exist (caller handles missing).

    Examples:
        >>> _resolve_index_path(None) == REPO_STARTER_INDEX
        True
    """
    if workspace_root is None:
        return REPO_STARTER_INDEX
    ws_index = workspace_root / "skills" / "INDEX.md"
    if ws_index.is_file():
        return ws_index
    return REPO_STARTER_INDEX


def read_skills_index(
    names: Iterable[str] | None = None,
    *,
    workspace_root: Path | None = None,
) -> dict[str, str]:
    """Return ``{name: description}`` for the requested skills.

    Reads ``<workspace>/skills/INDEX.md`` when available; falls back to the
    shipped starter at ``sevn/data/skills/INDEX.md``. Unknown names in
    ``names`` are silently omitted from the result — the caller can diff
    ``set(names) - result.keys()`` to detect typos.

    Args:
        names (Iterable[str] | None): Subset of skill names to fetch. ``None``
            returns the full index (used by the tier-B failure fallback and
            by maintenance scripts).
        workspace_root (Path | None): Workspace content root. ``None`` reads
            the shipped starter directly (testing / CLI helpers).

    Returns:
        dict[str, str]: Skill name → one-line description.

    Examples:
        >>> idx = read_skills_index()
        >>> isinstance(idx, dict) and "graphify" in idx
        True
        >>> read_skills_index(names=["graphify"]) == {"graphify": idx["graphify"]}
        True
        >>> read_skills_index(names=["does-not-exist"])
        {}
    """
    path = _resolve_index_path(workspace_root)
    if not path.is_file():
        return {}
    table = _parse_table(path.read_text(encoding="utf-8"))
    if names is None:
        return table
    wanted = set(names)
    return {k: v for k, v in table.items() if k in wanted}


def ensure_workspace_index(workspace_root: Path) -> Path:
    """Copy the starter INDEX into a workspace if missing; return the path.

    Workspace is authoritative once it has an INDEX — this function never
    overwrites an existing workspace file. If the workspace lacks an INDEX
    but the starter is missing too (broken install), the workspace file is
    not created and the returned path will not exist.

    Args:
        workspace_root (Path): Workspace content root.

    Returns:
        Path: ``<workspace>/skills/INDEX.md`` (may or may not exist).

    Examples:
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as td:
        ...     ws = Path(td)
        ...     out = ensure_workspace_index(ws)
        ...     out.is_file() == REPO_STARTER_INDEX.is_file()
        True
    """
    target = workspace_root / "skills" / "INDEX.md"
    if target.is_file():
        return target
    starter = _resolve_repo_starter_index()
    if not starter.is_file():
        raise SkillsStarterMissingError(starter)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(starter, target)
    logger.info(
        "skills_index_seeded workspace={} from={}",
        workspace_root,
        starter,
    )
    return target


__all__ = [
    "REPO_STARTER_INDEX",
    "SkillsStarterMissingError",
    "ensure_workspace_index",
    "read_skills_index",
]
