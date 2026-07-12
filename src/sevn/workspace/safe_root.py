"""Guard against seeding operator workspace into the sevn package checkout.

Module: sevn.workspace.safe_root
Depends: pathlib

Exports:
    UnsafeWorkspaceRootError — raised when ``content_root`` is the repo checkout.
    is_sevn_package_checkout — detect dev-tree layout.
    reject_package_checkout_content_root — fail fast before seed or workspace writes.
"""

from __future__ import annotations

from pathlib import Path


class UnsafeWorkspaceRootError(ValueError):
    """``content_root`` resolves to the sevn source checkout, not an operator home."""


def is_sevn_package_checkout(path: Path) -> bool:
    """True when ``path`` looks like the sevn.bot repository root.

    Args:
        path (Path): Candidate workspace ``content_root``.

    Returns:
        bool: Whether ``pyproject.toml`` and ``src/sevn`` exist under ``path``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     is_sevn_package_checkout(root)
        False
    """
    root = Path(path).expanduser().resolve()
    return (root / "pyproject.toml").is_file() and (root / "src" / "sevn").is_dir()


def reject_package_checkout_content_root(content_root: Path) -> None:
    """Raise when ``content_root`` would write into the package checkout.

    Args:
        content_root (Path): Resolved workspace content root.

    Raises:
        UnsafeWorkspaceRootError: When ``content_root`` is a package checkout.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> reject_package_checkout_content_root(Path(tempfile.mkdtemp()))
    """
    if is_sevn_package_checkout(content_root):
        resolved = Path(content_root).expanduser().resolve()
        msg = (
            f"refusing workspace writes into sevn package checkout ({resolved}); "
            "use ~/.sevn/workspace/sevn.json (or another directory outside the repo)"
        )
        raise UnsafeWorkspaceRootError(msg)


__all__ = [
    "UnsafeWorkspaceRootError",
    "is_sevn_package_checkout",
    "reject_package_checkout_content_root",
]
