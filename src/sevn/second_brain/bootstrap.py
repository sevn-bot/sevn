"""Idempotent Second Brain scope layout bootstrap (`specs/27-second-brain.md` §3.2).

Module: sevn.second_brain.bootstrap
Depends: importlib.resources, pathlib, sevn.data.second_brain

Exports:
    ensure_second_brain_scope_layout — create missing dirs and stub files under a scope root.

Examples:
    >>> import tempfile
    >>> from pathlib import Path
    >>> with tempfile.TemporaryDirectory() as td:
    ...     created = ensure_second_brain_scope_layout(Path(td), copy_model=False)
    ...     "wiki/index.md" in created
    True
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path


def _stub(path: Path, content: str) -> bool:
    """Write *content* to *path* when the file is missing.

    Args:
        path (Path): Target file path.
        content (str): Stub body.

    Returns:
        bool: ``True`` when the file was created.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     p = Path(td) / "x.md"
        ...     _stub(p, "# X\\n")
        True
    """
    if path.is_file():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def ensure_second_brain_scope_layout(
    scope_root: Path,
    *,
    copy_model: bool = True,
) -> list[str]:
    """Ensure standard Second Brain folders and stub files exist under *scope_root*.

    Never overwrites existing ``wiki/index.md``, ``wiki/log.md``, or ``MODEL.md``.

    Args:
        scope_root (Path): Resolved scope directory (legacy or custom vault root).
        copy_model (bool): When ``True``, copy bundled ``default_MODEL.md`` when missing.

    Returns:
        list[str]: Workspace-relative paths created (POSIX) under *scope_root*.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     created = ensure_second_brain_scope_layout(root, copy_model=False)
        ...     (root / "wiki" / "index.md").is_file()
        True
    """
    root = scope_root.expanduser().resolve()
    created: list[str] = []

    for rel in ("raw", "wiki", "wiki/ingests", "outputs"):
        target = root / rel
        if not target.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            created.append(rel)

    if _stub(root / "wiki" / "index.md", "# Index\n"):
        created.append("wiki/index.md")
    if _stub(root / "wiki" / "log.md", "# Log\n"):
        created.append("wiki/log.md")

    model_path = root / "MODEL.md"
    if copy_model and not model_path.is_file():
        template = resources.files("sevn.data.second_brain").joinpath("default_MODEL.md")
        model_path.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        created.append("MODEL.md")

    return created


__all__ = ["ensure_second_brain_scope_layout"]
