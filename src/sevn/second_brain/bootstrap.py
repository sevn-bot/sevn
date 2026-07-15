"""Idempotent Second Brain scope layout bootstrap (`specs/27-second-brain.md` §3.2).

Module: sevn.second_brain.bootstrap
Depends: importlib.resources, pathlib, sevn.config.workspace_config, sevn.data.second_brain

Exports:
    detect_layout — infer ``legacy`` | ``para`` | ``None`` from an on-disk vault tree.
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
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sevn.config.workspace_config import SecondBrainWorkspaceConfig, WorkspaceConfig

_DEFAULT_PARA_FOLDER_NAMES: tuple[str, ...] = (
    "00_Inbox",
    "10_Projects",
    "20_Areas",
    "30_Resources",
    "40_Archive",
    "90_Templates",
)

_BUNDLED_PARA_FOLDER_MAP: tuple[tuple[str, str], ...] = (
    ("00_Inbox", "inbox"),
    ("10_Projects", "projects"),
    ("20_Areas", "areas"),
    ("30_Resources", "resources"),
    ("40_Archive", "archive"),
    ("90_Templates", "templates"),
)


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


def _ensure_dir(path: Path) -> bool:
    """Create *path* as a directory when absent.

    Args:
        path (Path): Target directory.

    Returns:
        bool: ``True`` when the directory was created.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     p = Path(td) / "nested" / "dir"
        ...     _ensure_dir(p)
        True
    """
    if path.is_dir():
        return False
    path.mkdir(parents=True, exist_ok=True)
    return True


def _rel_posix(path: Path, scope_root: Path) -> str:
    """Return *path* relative to *scope_root* as a POSIX string.

    Args:
        path (Path): Absolute or resolved path under *scope_root*.
        scope_root (Path): Vault scope root.

    Returns:
        str: Workspace-relative POSIX path.

    Examples:
        >>> from pathlib import Path
        >>> root = Path("/vault")
        >>> _rel_posix(Path("/vault/wiki/index.md"), root)
        'wiki/index.md'
    """
    return path.resolve().relative_to(scope_root.resolve()).as_posix()


def _copy_resource_file(
    src: Traversable,
    dest: Path,
    *,
    scope_root: Path,
) -> str | None:
    """Copy a packaged resource file when the destination is missing.

    Args:
        src (resources.abc.Traversable): Packaged source file.
        dest (Path): Destination path under *scope_root*.
        scope_root (Path): Vault scope root for relative-path reporting.

    Returns:
        str | None: Created relative path, or ``None`` when skipped.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from importlib import resources
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     template = resources.files("sevn.data.second_brain").joinpath("default_MODEL.md")
        ...     rel = _copy_resource_file(template, root / "MODEL.md", scope_root=root)
        ...     rel == "MODEL.md"
        True
    """
    if dest.is_file():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return _rel_posix(dest, scope_root)


def _copy_resource_tree_create_missing(
    src_root: Traversable,
    dest_root: Path,
    *,
    scope_root: Path,
    rel_prefix: str = "",
) -> list[str]:
    """Recursively copy packaged files, skipping paths that already exist.

    Args:
        src_root (resources.abc.Traversable): Packaged source directory.
        dest_root (Path): Destination directory under *scope_root*.
        scope_root (Path): Vault scope root for relative-path reporting.
        rel_prefix (str): Relative prefix for nested traversal.

    Returns:
        list[str]: Created relative paths (POSIX).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from importlib import resources
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     bundled = resources.files("sevn.data.second_brain.para").joinpath("90_Templates")
        ...     created = _copy_resource_tree_create_missing(
        ...         bundled, root / "90_Templates", scope_root=root
        ...     )
        ...     isinstance(created, list)
        True
    """
    created: list[str] = []
    for entry in sorted(src_root.iterdir(), key=lambda item: item.name):
        rel = f"{rel_prefix}/{entry.name}" if rel_prefix else entry.name
        if entry.is_dir():
            created.extend(
                _copy_resource_tree_create_missing(
                    entry,
                    dest_root / entry.name,
                    scope_root=scope_root,
                    rel_prefix=rel,
                ),
            )
            continue
        dest = dest_root / entry.name
        rel_created = _copy_resource_file(entry, dest, scope_root=scope_root)
        if rel_created is not None:
            created.append(rel_created)
    return created


def detect_layout(vault_root: Path) -> Literal["legacy", "para"] | None:
    """Infer vault layout from on-disk folder markers (D7).

    Returns ``para`` when the vault contains at least two default PARA role
    folders, or an ``.obsidian/`` directory plus at least one PARA folder.
    Returns ``legacy`` when both ``wiki/`` and ``raw/`` exist. Otherwise
    returns ``None``.

    Args:
        vault_root (Path): Resolved vault directory.

    Returns:
        Literal["legacy", "para"] | None: Detected layout, if any.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "wiki").mkdir()
        ...     _ = (root / "raw").mkdir()
        ...     detect_layout(root)
        'legacy'
    """
    root = vault_root.expanduser().resolve()
    para_hits = sum(1 for name in _DEFAULT_PARA_FOLDER_NAMES if (root / name).is_dir())
    if para_hits >= 2:
        return "para"
    if (root / ".obsidian").is_dir() and para_hits >= 1:
        return "para"
    if (root / "wiki").is_dir() and (root / "raw").is_dir():
        return "legacy"
    return None


def _ensure_legacy_layout(
    scope_root: Path,
    *,
    copy_model: bool,
) -> list[str]:
    """Bootstrap the legacy ``wiki/raw/outputs`` layout (verbatim pre-PARA behaviour).

    Args:
        scope_root (Path): Resolved scope directory.
        copy_model (bool): Copy bundled ``default_MODEL.md`` when missing.

    Returns:
        list[str]: Created relative paths under *scope_root*.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     created = _ensure_legacy_layout(root, copy_model=False)
        ...     "wiki/index.md" in created
        True
    """
    root = scope_root.expanduser().resolve()
    created: list[str] = []

    for rel in ("raw", "wiki", "wiki/ingests", "outputs"):
        target = root / rel
        if _ensure_dir(target):
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


def _load_bundled_para_text(rel_path: str, *, fallback: str) -> str:
    """Read a packaged PARA scaffold text file, falling back when absent.

    Args:
        rel_path (str): Path relative to ``sevn.data.second_brain.para``.
        fallback (str): Body used when the packaged file is missing.

    Returns:
        str: File body.

    Examples:
        >>> text = _load_bundled_para_text("index.md", fallback="# Index\\n")
        >>> text.startswith("#")
        True
    """
    bundled = resources.files("sevn.data.second_brain.para")
    target = bundled.joinpath(rel_path)
    if target.is_file():
        return target.read_text(encoding="utf-8")
    return fallback


def _ensure_para_layout(
    scope_root: Path,
    cfg: SecondBrainWorkspaceConfig,
    *,
    copy_model: bool,
) -> list[str]:
    """Bootstrap a PARA Obsidian vault layout non-destructively (D6).

    Creates role directories, root ``index.md``/``log.md``, and copies bundled
    PARA scaffold files only where missing. Never overwrites existing notes or
    an existing ``.obsidian/`` directory.

    Args:
        scope_root (Path): Resolved vault scope root.
        cfg (SecondBrainWorkspaceConfig): Second Brain config (``layout="para"``).
        copy_model (bool): Copy ``para_MODEL.md`` to ``MODEL.md`` when missing.

    Returns:
        list[str]: Created relative paths under *scope_root*.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     cfg = SecondBrainWorkspaceConfig(layout="para")
        ...     created = _ensure_para_layout(root, cfg, copy_model=False)
        ...     "00_Inbox" in created
        True
    """
    root = scope_root.expanduser().resolve()
    para = cfg.para
    created: list[str] = []

    role_dirs = (
        para.inbox,
        para.projects,
        para.areas,
        para.resources,
        f"{para.resources}/{para.sources_subdir}",
        f"{para.resources}/{para.outputs_subdir}",
        para.archive,
        para.templates,
    )
    for rel in role_dirs:
        target = root / rel
        if _ensure_dir(target):
            created.append(rel)

    index_body = _load_bundled_para_text("index.md", fallback="# Index\n")
    log_body = _load_bundled_para_text("log.md", fallback="# Log\n")
    if _stub(root / para.index_note, index_body):
        created.append(para.index_note)
    if _stub(root / para.log_note, log_body):
        created.append(para.log_note)

    bundled = resources.files("sevn.data.second_brain.para")
    for bundled_name, attr in _BUNDLED_PARA_FOLDER_MAP:
        readme = bundled.joinpath(bundled_name, "README.md")
        if not readme.is_file():
            continue
        dest_name = getattr(para, attr)
        dest = root / dest_name / "README.md"
        rel_created = _copy_resource_file(readme, dest, scope_root=root)
        if rel_created is not None:
            created.append(rel_created)

    templates_src = bundled.joinpath("90_Templates")
    if templates_src.is_dir():
        templates_dest = root / para.templates
        created.extend(
            _copy_resource_tree_create_missing(
                templates_src,
                templates_dest,
                scope_root=root,
            ),
        )

    obsidian_dest = root / ".obsidian"
    if not obsidian_dest.exists():
        obsidian_src = bundled.joinpath(".obsidian")
        if obsidian_src.is_dir():
            created.extend(
                _copy_resource_tree_create_missing(
                    obsidian_src,
                    obsidian_dest,
                    scope_root=root,
                ),
            )

    model_path = root / "MODEL.md"
    if copy_model:
        model_src = bundled.joinpath("para_MODEL.md")
        rel_created = _copy_resource_file(model_src, model_path, scope_root=root)
        if rel_created is not None:
            created.append(rel_created)

    return created


def _normalize_sb_cfg(
    cfg: SecondBrainWorkspaceConfig | WorkspaceConfig | None,
) -> SecondBrainWorkspaceConfig | None:
    """Return the Second Brain slice from *cfg* when present.

    Args:
        cfg (SecondBrainWorkspaceConfig | WorkspaceConfig | None): Caller config.

    Returns:
        SecondBrainWorkspaceConfig | None: Normalised slice, or ``None``.

    Examples:
        >>> _normalize_sb_cfg(None) is None
        True
    """
    if cfg is None:
        return None
    if hasattr(cfg, "layout") and hasattr(cfg, "para"):
        return cfg  # type: ignore[return-value]
    sb = getattr(cfg, "second_brain", None)
    return sb if sb is not None else None


def ensure_second_brain_scope_layout(
    scope_root: Path,
    *,
    cfg: SecondBrainWorkspaceConfig | WorkspaceConfig | None = None,
    copy_model: bool = True,
) -> list[str]:
    """Ensure standard Second Brain folders and stub files exist under *scope_root*.

    Legacy layout (default) creates ``raw/``, ``wiki/``, ``outputs/``, and stub
    index/log notes under ``wiki/``. PARA layout creates the configured role
    tree and copies bundled scaffold files only where missing.

    Never overwrites existing notes, ``MODEL.md``, or an existing ``.obsidian/``.

    Args:
        scope_root (Path): Resolved scope directory (legacy or custom vault root).
        cfg (SecondBrainWorkspaceConfig | None): Layout config; ``None`` → legacy.
        copy_model (bool): When ``True``, copy bundled MODEL template when missing.

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
    sb_cfg = _normalize_sb_cfg(cfg)
    if sb_cfg is not None and sb_cfg.layout == "para":
        return _ensure_para_layout(scope_root, sb_cfg, copy_model=copy_model)
    return _ensure_legacy_layout(scope_root, copy_model=copy_model)


__all__ = ["detect_layout", "ensure_second_brain_scope_layout"]
